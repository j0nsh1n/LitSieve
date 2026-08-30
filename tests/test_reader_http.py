"""HTTP contract for Reader Mode routes (auth, CSRF, isolation, errors)."""

from __future__ import annotations

import os
import pathlib
import shutil

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.support_gate import _ALLOWED_POST

PAPER = {
    "article_id": "34567890",
    "source": "pubmed",
    "title": "Later school start times and adolescent sleep",
    "abstract": (
        "Methods: In this randomised controlled trial, n = 512 participants were "
        "assigned to a sleep treatment or usual care. Results: Sleep rose 43 minutes "
        "per night (95% CI 21 to 65); 34% reported better sleep (p < 0.01). "
        "Conclusions: The treatment was associated with longer sleep."
    ),
}

FAKE_BODY = {
    "article_id": "34567890",
    "source": "pubmed",
    "audience": "general_reader",
    "cached": False,
    "content": {
        "plain_summary": "Students slept longer.",
        "question_asked": "Does a later start help sleep?",
        "who_was_studied": "Teenagers at school.",
        "what_was_found": "Sleep rose by 43 minutes.",
        "what_it_does_not_show": (
            "The abstract alone cannot establish whether these findings apply to everyone."
        ),
        "stated_limitations": "Not reported in the abstract.",
        "glossary": [],
        "not_reported_fields": ["stated_limitations"],
    },
    "verification": {
        "status": "no_automatic_issues",
        "checks": [],
        "verifier_version": "v1",
    },
    "label": "AI explanation (from this abstract only — not medical advice)",
    "disclaimer": (
        "This is an educational reading aid, not medical, legal, or professional "
        "advice. Always check the original paper."
    ),
    "provider": "openai",
    "prompt_version": "reader_v1",
}


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setenv("DEBUG", "true")

    import importlib

    from app.storage.user_db import UserDatabase

    main = importlib.import_module("app.main")
    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    return main


def _register(client, username="readeruser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD,
              "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _uid(username="readeruser"):
    row = core.user_db.get_by_username(username)
    return row["id"]


def _seed_paper(username="readeruser", paper=None):
    uid = _uid(username)
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.insert_articles([paper or PAPER], dedupe=False)
    finally:
        core.release_pipeline(uid)


def test_reader_routes_require_auth(app_module):
    c = TestClient(app_module.app)
    r = c.post("/api/reader/explain", json={"article_id": "x", "source": "pubmed"})
    assert r.status_code in (401, 403)
    r2 = c.get("/api/reader/explanation", params={"article_id": "x", "source": "pubmed"})
    assert r2.status_code in (401, 403)


def test_reader_requires_csrf(app_module):
    c = TestClient(app_module.app)
    _register(c)
    _seed_paper()
    r = c.post(
        "/api/reader/explain",
        json={"article_id": PAPER["article_id"], "source": PAPER["source"]},
    )
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_reader_404_for_unknown_article(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c)
    monkeypatch.setattr("app.services.reader_mode.explain_article", lambda *a, **k: FAKE_BODY)
    r = c.post(
        "/api/reader/explain",
        json={"article_id": "missing", "source": "pubmed"},
        headers=headers,
    )
    assert r.status_code == 404


def test_reader_400_for_short_abstract(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_paper(paper={
        "article_id": "short1",
        "source": "pubmed",
        "title": "Tiny",
        "abstract": "Too short.",
    })
    r = c.post(
        "/api/reader/explain",
        json={"article_id": "short1", "source": "pubmed"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "too short" in r.json()["detail"].lower()


def test_reader_503_when_unconfigured(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_paper()
    monkeypatch.setattr("app.services.reader_mode.is_configured", lambda: False)
    r = c.post(
        "/api/reader/explain",
        json={"article_id": PAPER["article_id"], "source": PAPER["source"]},
        headers=headers,
    )
    assert r.status_code == 503


def test_user_cannot_read_another_users_explanation(app_module, monkeypatch):
    calls = {"n": 0}

    def fake_explain(db, article, audience, force_regenerate=False):
        calls["n"] += 1
        return dict(FAKE_BODY)

    monkeypatch.setattr("app.services.reader_mode.explain_article", fake_explain)

    c1 = TestClient(app_module.app)
    h1 = _register(c1, "alice")
    _seed_paper("alice")
    r = c1.post(
        "/api/reader/explain",
        json={"article_id": PAPER["article_id"], "source": PAPER["source"]},
        headers=h1,
    )
    assert r.status_code == 200, r.text

    c2 = TestClient(app_module.app)
    h2 = _register(c2, "bob")
    got = c2.get(
        "/api/reader/explanation",
        params={"article_id": PAPER["article_id"], "source": PAPER["source"]},
        headers=h2,
    )
    assert got.status_code == 404


def test_explanation_not_shared_across_libraries(app_module, monkeypatch):
    monkeypatch.setattr("app.services.reader_mode.explain_article", lambda *a, **k: dict(FAKE_BODY))
    c = TestClient(app_module.app)
    headers = _register(c, "libuser")
    _seed_paper("libuser")
    r = c.post(
        "/api/reader/explain",
        json={"article_id": PAPER["article_id"], "source": PAPER["source"]},
        headers=headers,
    )
    assert r.status_code == 200
    created = c.post("/api/libraries", json={"name": "Other shelf"}, headers=headers)
    assert created.status_code == 200, created.text
    other_id = created.json()["active_id"]
    switched = c.post("/api/libraries/switch", json={"library_id": other_id}, headers=headers)
    assert switched.status_code == 200, switched.text
    got = c.get(
        "/api/reader/explanation",
        params={"article_id": PAPER["article_id"], "source": PAPER["source"]},
        headers=headers,
    )
    assert got.status_code == 404


def test_support_view_cannot_generate():
    assert "/api/reader/explain" not in _ALLOWED_POST


def test_rate_limit_applies(app_module, monkeypatch):
    monkeypatch.setattr("app.services.reader_mode.explain_article", lambda *a, **k: dict(FAKE_BODY))
    c = TestClient(app_module.app)
    headers = _register(c, "ratelimituser")
    _seed_paper("ratelimituser")
    body = {"article_id": PAPER["article_id"], "source": PAPER["source"]}
    codes = [
        c.post("/api/reader/explain", json=body, headers=headers).status_code
        for _ in range(8)
    ]
    assert 429 in codes
    assert codes.count(200) >= 1
