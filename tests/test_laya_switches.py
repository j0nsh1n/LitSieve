"""Laya as an optional switch: client fail-closed behaviour, the study-type gate,
and the topic-area route. No real model runs here; the sidecar's HTTP answers
are faked at requests.post."""
from __future__ import annotations

import pytest
import requests
from fastapi.testclient import TestClient
from test_search_http import _register, app_module  # noqa: F401  (fixture reuse)

from app.services import laya_client, study_type
from app.services.study_type import (
    LAYA_MIN_P,
    PATTERN_KEEP,
    attach_study_types,
    classify_study_type,
    refine_study_types_with_laya,
)

URL = "http://127.0.0.1:7880"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    laya_client._reset_for_tests()
    study_type._clear_laya_cache_for_tests()
    monkeypatch.delenv("LITSIEVE_LAYA_URL", raising=False)
    yield
    laya_client._reset_for_tests()
    study_type._clear_laya_cache_for_tests()


@pytest.fixture
def laya_on(monkeypatch):
    """Enable Laya and record every request; `answers` maps state -> (choice, p)."""
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    calls, answers = [], {}

    def fake_post(url, json, timeout):
        calls.append(json)
        out = []
        for s in json["states"]:
            pick, p = answers.get(s, (next(iter(json["options"])), 0.3))
            out.append({"choice": pick, "p": p, "probabilities": {pick: p}})
        return FakeResp({"results": out, "ms": 1.0})

    monkeypatch.setattr(laya_client.requests, "post", fake_post)
    return calls, answers


# --- client ------------------------------------------------------------------

def test_disabled_when_env_unset(monkeypatch):
    called = []
    monkeypatch.setattr(laya_client.requests, "post", lambda *a, **k: called.append(1))
    assert laya_client.choice("q", {"a": "A", "b": "B"}, ["text"]) is None
    assert called == []


def test_blank_url_counts_as_disabled(monkeypatch):
    monkeypatch.setenv("LITSIEVE_LAYA_URL", "  ")
    assert not laya_client.enabled()


@pytest.mark.parametrize("exc", [requests.ConnectionError("down"), requests.ReadTimeout("slow")])
def test_network_errors_return_none_and_cool_down(monkeypatch, exc):
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise exc

    monkeypatch.setattr(laya_client.requests, "post", boom)
    assert laya_client.choice("q", {"a": "A", "b": "B"}, ["t"]) is None
    assert laya_client.choice("q", {"a": "A", "b": "B"}, ["t"]) is None
    assert calls == [1], "second call should be skipped during the cooldown"


@pytest.mark.parametrize("payload", [
    ValueError("not json"),
    {"results": []},                                               # wrong length
    {"results": [{"choice": "zzz", "p": 0.9}]},                    # unknown option
    {"results": [{"choice": "a", "p": 1.7}]},                      # p out of range
    {"nope": 1},
])
def test_malformed_answers_return_none(monkeypatch, payload):
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    monkeypatch.setattr(laya_client.requests, "post", lambda *a, **k: FakeResp(payload))
    assert laya_client.choice("q", {"a": "A", "b": "B"}, ["t"]) is None


def test_timeout_is_short():
    connect, read = laya_client.TIMEOUT
    assert connect <= 0.5 and read <= 1.5


# --- study-type gate ---------------------------------------------------------

UNSURE = {"title": "Peer instruction in introductory physics",
          "abstract": "Peer instruction with clickers was implemented in two large lecture sections. "
                      "Normalized gains exceeded historical lecture baselines."}
SURE = {"title": "Growth mindset interventions: a meta-analysis",
        "abstract": "This meta-analysis synthesizes 48 school-based growth mindset interventions."}


def _text(a):
    return f"{a['title']}. {a['abstract']}"


def test_classify_study_type_stays_pure(laya_on):
    calls, _ = laya_on
    classify_study_type(UNSURE["title"], UNSURE["abstract"])
    assert calls == []


def test_confident_pattern_kept_without_asking(laya_on):
    calls, _ = laya_on
    arts = [dict(SURE)]
    attach_study_types(arts)
    assert arts[0]["study_type_confidence"] >= PATTERN_KEEP
    assert refine_study_types_with_laya(arts) == 0
    assert calls == [] and arts[0]["study_type_source"] == "pattern"


def test_unsure_pattern_replaced_when_laya_confident(laya_on):
    calls, answers = laya_on
    arts = [dict(UNSURE)]
    attach_study_types(arts)
    assert arts[0]["study_type"] == "unclear"
    answers[_text(UNSURE)] = ("observational", 0.97)
    assert refine_study_types_with_laya(arts) == 1
    a = arts[0]
    assert (a["study_type"], a["study_type_source"]) == ("observational", "laya")
    assert a["study_type_label"] == study_type.STUDY_TYPE_LABELS["observational"]
    assert a["study_type_matched"] is None and a["study_type_confidence_band"] == "high"


def test_laya_below_threshold_keeps_pattern_exactly(laya_on):
    _, answers = laya_on
    arts = [dict(UNSURE)]
    attach_study_types(arts)
    before = dict(arts[0])
    answers[_text(UNSURE)] = ("trial", LAYA_MIN_P - 0.01)
    assert refine_study_types_with_laya(arts) == 0
    assert arts[0] == before


def test_threshold_is_inclusive(laya_on):
    _, answers = laya_on
    arts = [dict(UNSURE)]
    attach_study_types(arts)
    answers[_text(UNSURE)] = ("trial", LAYA_MIN_P)
    assert refine_study_types_with_laya(arts) == 1


def test_laya_unavailable_keeps_pattern_exactly(monkeypatch):
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    monkeypatch.setattr(laya_client.requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    arts = [dict(UNSURE)]
    attach_study_types(arts)
    before = dict(arts[0])
    assert refine_study_types_with_laya(arts) == 0
    assert arts[0] == before


def test_one_call_per_search_and_only_unsure_papers(laya_on):
    calls, _ = laya_on
    unsure = [{"title": f"Classroom study number {i}", "abstract": UNSURE["abstract"] + f" Site {i}."} for i in range(20)]
    arts = [dict(SURE)] + unsure
    attach_study_types(arts)
    refine_study_types_with_laya(arts)
    assert len(calls) == 1
    assert len(calls[0]["states"]) == 20
    assert all("meta-analysis" not in s for s in calls[0]["states"])


def test_cache_skips_repeat_and_misses_on_changed_abstract(laya_on):
    calls, answers = laya_on
    answers[_text(UNSURE)] = ("observational", 0.95)
    for _ in range(2):
        arts = [dict(UNSURE)]
        attach_study_types(arts)
        refine_study_types_with_laya(arts)
        assert arts[0]["study_type"] == "observational"
    assert len(calls) == 1
    edited = dict(UNSURE, abstract=UNSURE["abstract"] + " Revised.")
    arts = [edited]
    attach_study_types(arts)
    refine_study_types_with_laya(arts)
    assert len(calls) == 2


def test_tags_never_reorder_results(laya_on):
    _, answers = laya_on
    arts = [{"article_id": str(i), "title": f"Paper {i} about classroom practice",
             "abstract": UNSURE["abstract"] + f" ({i})"} for i in range(6)]
    for a in arts[::2]:
        answers[_text(a)] = ("trial", 0.99)
    attach_study_types(arts)
    refine_study_types_with_laya(arts)
    assert [a["article_id"] for a in arts] == [str(i) for i in range(6)]


# --- topic-area route ----------------------------------------------------------

def test_topic_route_requires_auth(app_module):  # noqa: F811
    c = TestClient(app_module.app)
    assert c.post("/api/topic-area", json={"topic": "How do bees navigate?"}).status_code == 401


def test_topic_route_requires_csrf(app_module):  # noqa: F811
    c = TestClient(app_module.app)
    _register(c, "layacsrf")
    assert c.post("/api/topic-area", json={"topic": "How do bees navigate?"}).status_code == 403


def test_topic_route_disabled_shape(app_module):  # noqa: F811
    c = TestClient(app_module.app)
    h = _register(c, "layaoff")
    r = c.post("/api/topic-area", json={"topic": "How do bees navigate?"}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"available": False, "reason": "disabled", "topics": []}


def test_topic_route_unavailable_when_worker_down(app_module, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    monkeypatch.setattr(laya_client.requests, "post", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    c = TestClient(app_module.app)
    h = _register(c, "layadown")
    assert c.post("/api/topic-area", json={"topic": "How do bees navigate?"}, headers=h).json()["reason"] == "unavailable"


def _topic_answer(monkeypatch, probs):
    monkeypatch.setenv("LITSIEVE_LAYA_URL", URL)
    sent = []

    def fake_post(url, json, timeout):
        sent.append(json)
        best = max(probs, key=probs.get)
        return FakeResp({"results": [{"choice": best, "p": probs[best], "probabilities": probs}]})

    monkeypatch.setattr(laya_client.requests, "post", fake_post)
    return sent


def test_topic_route_best_and_close_second(app_module, monkeypatch):  # noqa: F811
    sent = _topic_answer(monkeypatch, {"biology": 0.6, "earth": 0.35, "health": 0.05})
    c = TestClient(app_module.app)
    h = _register(c, "layatwo")
    body = c.post("/api/topic-area", json={"topic": "Ocean acidification and coral reefs"}, headers=h).json()
    assert body["available"] is True
    assert [t["id"] for t in body["topics"]] == ["biology", "earth"]
    from app.content.source_catalog import TOPIC_META
    assert set(sent[0]["options"]) == set(TOPIC_META)


def test_topic_route_drops_far_second_and_unsure(app_module, monkeypatch):  # noqa: F811
    _topic_answer(monkeypatch, {"physics": 0.9, "math": 0.08})
    c = TestClient(app_module.app)
    h = _register(c, "layaone")
    assert [t["id"] for t in c.post("/api/topic-area", json={"topic": "Dark matter detection"}, headers=h).json()["topics"]] == ["physics"]
    _topic_answer(monkeypatch, {"physics": 0.3, "math": 0.28, "cs": 0.2})
    body = c.post("/api/topic-area", json={"topic": "Something vague here"}, headers=h).json()
    assert body == {"available": True, "reason": "unsure", "topics": []}


def test_topic_route_validates_length(app_module):  # noqa: F811
    c = TestClient(app_module.app)
    h = _register(c, "layalen")
    assert c.post("/api/topic-area", json={"topic": "x"}, headers=h).status_code == 422
