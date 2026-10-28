"""Offline unit tests for new public source fetchers (HTTP mocked)."""

import json
from pathlib import Path

import pytest

from app.fetchers.base import FetchError
from app.fetchers.biorxiv import BioRxivFetcher, MedRxivFetcher
from app.fetchers.hal import HALFetcher
from app.fetchers.openaire import OpenAIREFetcher, _node_text
from app.fetchers.plos import PLOSFetcher
from app.services.pipeline import FETCHERS

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def test_all_new_sources_registered():
    for src in ("biorxiv", "medrxiv", "openaire", "plos", "hal"):
        assert src in FETCHERS


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


class _JsonResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_biorxiv_searches_europepmc_for_that_servers_preprints(monkeypatch):
    f = BioRxivFetcher()
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params)
        return _JsonResp(_fixture("europepmc_ppr_biorxiv.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart disease", max_results=2)
    assert calls[0]["query"] == '(heart disease) AND SRC:PPR AND PUBLISHER:"bioRxiv"'
    assert [a["article_id"] for a in arts] == [
        "10.64898/2026.10.06.757136",
        "10.64898/2026.10.06.757199",
    ]
    assert {a["source"] for a in arts} == {"biorxiv"}
    assert {a["journal"] for a in arts} == {""}
    assert all(a["abstract"] and "<" not in a["abstract"] for a in arts)
    assert len(arts[0]["authors"]) == 14


def test_medrxiv_is_scoped_to_medrxiv(monkeypatch):
    f = MedRxivFetcher()
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params)
        return _JsonResp(_fixture("europepmc_ppr_medrxiv.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart disease", max_results=2)
    assert calls[0]["query"].endswith('PUBLISHER:"medRxiv"')
    assert {a["source"] for a in arts} == {"medrxiv"}
    assert {a["journal"] for a in arts} == {""}


def test_rxiv_skips_a_preprint_without_a_doi_and_reports_no_results(monkeypatch):
    f = BioRxivFetcher()
    payload = _fixture("europepmc_ppr_biorxiv.json")
    for record in payload["resultList"]["result"]:
        record.pop("doi", None)
    monkeypatch.setattr(f.http, "get", lambda *a, **k: _JsonResp(payload))
    with pytest.raises(FetchError) as exc:
        f.search_and_fetch("heart disease", max_results=2)
    assert exc.value.kind == "no_results"


def test_plos_parse(monkeypatch):
    f = PLOSFetcher()
    payload = {
        "response": {
            "docs": [{
                "id": "10.1371/journal.pone.0000001",
                "title": "Open science education study",
                "abstract": ["Students used open data to learn biology methods."],
                "author": ["Ada Lovelace"],
                "publication_date": "2020-01-15T00:00:00Z",
                "journal": "PLOS ONE",
            }]
        }
    }

    class FakeResp:
        def json(self):
            return payload

    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    arts = f.search_and_fetch("education", max_results=5)
    assert arts[0]["source"] == "plos"
    assert "open data" in arts[0]["abstract"].lower()


def test_hal_parse(monkeypatch):
    f = HALFetcher()
    payload = {
        "response": {
            "docs": [{
                "halId_s": "hal-123",
                "title_s": ["French education policy"],
                "abstract_s": ["A study of secondary schooling in France."],
                "authFullName_s": ["Camille Durand"],
                "producedDateY_i": 2019,
                "journalTitle_s": ["Education Review"],
            }]
        }
    }

    class FakeResp:
        def json(self):
            return payload

    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    arts = f.search_and_fetch("education", max_results=5)
    assert arts[0]["source"] == "hal"
    assert arts[0]["article_id"] == "hal-123"
    assert arts[0]["year"] == "2019"


def test_openaire_node_text_and_parse(monkeypatch):
    assert _node_text({"$": "Hello"}) == "Hello"
    f = OpenAIREFetcher()
    payload = {
        "response": {
            "results": {
                "result": {
                    "header": {"dri:objIdentifier": {"$": "obj1"}},
                    "metadata": {
                        "oaf:entity": {
                            "oaf:result": {
                                "title": [{"$": "Climate education in schools"}],
                                "description": {
                                    "$": "<p>We study climate education programs.</p>"
                                },
                                "creator": [{"$": "Alex Rivera"}],
                                "dateofacceptance": {"$": "2021-05-01"},
                                "journal": {"$": "Env Ed J"},
                                "pid": {
                                    "@classid": "doi",
                                    "$": "10.1234/example",
                                },
                            }
                        }
                    },
                }
            }
        }
    }

    class FakeResp:
        def json(self):
            return payload

    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    arts = f.search_and_fetch("climate", max_results=5)
    assert len(arts) == 1
    assert arts[0]["source"] == "openaire"
    assert arts[0]["article_id"] == "10.1234/example"
    assert "climate education" in arts[0]["title"].lower()


def test_openaire_timeout_preserves_completed_page(monkeypatch):
    f = OpenAIREFetcher()
    page = {
        "response": {
            "results": {
                "result": [
                    {
                        "header": {"dri:objIdentifier": {"$": f"obj{i}"}},
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "title": [{"$": f"Climate study {i}"}],
                                    "description": {"$": "A complete abstract."},
                                }
                            }
                        },
                    }
                    for i in range(25)
                ]
            }
        }
    }
    requests = 0

    class FakeResp:
        def json(self):
            return page

    def get(*args, **kwargs):
        nonlocal requests
        requests += 1
        if requests == 1:
            return FakeResp()
        raise FetchError("OpenAIRE request timed out", kind="timeout")

    monkeypatch.setattr(f.http, "get", get)

    try:
        f.search_and_fetch("climate", max_results=26)
    except FetchError as exc:
        assert exc.kind == "timeout"
        assert len(exc.articles) == 25
        assert [article["article_id"] for article in exc.articles] == [
            f"obj{i}" for i in range(25)
        ]
    else:
        raise AssertionError("OpenAIRE timeout should propagate")
