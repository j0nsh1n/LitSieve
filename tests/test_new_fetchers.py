"""Offline unit tests for new public source fetchers (HTTP mocked)."""

from unittest.mock import MagicMock

import pytest

from biorxiv_fetcher import BioRxivFetcher, MedRxivFetcher, _matches
from dblp_fetcher import DBLPFetcher
from plos_fetcher import PLOSFetcher
from hal_fetcher import HALFetcher
from openaire_fetcher import OpenAIREFetcher, _node_text
from pipeline import FETCHERS


def test_all_new_sources_registered():
    for src in ("biorxiv", "medrxiv", "dblp", "openaire", "plos", "hal"):
        assert src in FETCHERS


def test_biorxiv_token_match():
    assert _matches("stem cell", "Stem cell niches", "biology of stem cells")
    assert not _matches("stem cell zebra", "Stem cell niches", "biology of cells")


def test_biorxiv_parse_and_filter(monkeypatch):
    f = BioRxivFetcher()
    sample = {
        "title": "CRISPR editing in mice",
        "abstract": "We used CRISPR to edit genes in laboratory mice models.",
        "authors": "Doe, J.; Roe, A.",
        "doi": "10.1101/2024.01.01.123456",
        "date": "2024-06-01",
    }

    class FakeResp:
        def json(self):
            return {
                "messages": [{"status": "ok", "count": 1, "total": "1"}],
                "collection": [sample],
            }

    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    arts = f.search_and_fetch("CRISPR mice", max_results=10)
    assert len(arts) == 1
    assert arts[0]["source"] == "biorxiv"
    assert arts[0]["article_id"].startswith("10.1101/")


def test_medrxiv_source_name():
    assert MedRxivFetcher.SOURCE_NAME == "medrxiv"
    assert MedRxivFetcher.SERVER == "medrxiv"


def test_dblp_parse_without_abstract(monkeypatch):
    f = DBLPFetcher()
    payload = {
        "result": {
            "hits": {
                "hit": [{
                    "@id": "1",
                    "info": {
                        "key": "conf/test/Doe24",
                        "title": "Learning in Games.",
                        "year": "2024",
                        "venue": "ICML",
                        "authors": {"author": {"text": "Jane Doe"}},
                    },
                }],
            }
        }
    }

    class FakeResp:
        def json(self):
            return payload

    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    arts = f.search_and_fetch("learning", max_results=5)
    assert len(arts) == 1
    assert arts[0]["source"] == "dblp"
    assert "No abstract" in arts[0]["abstract"]
    assert arts[0]["authors"] == ["Jane Doe"]


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
