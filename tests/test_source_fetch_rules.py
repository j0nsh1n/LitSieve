"""Phase 18 source rules: typed errors, plain text, honest queries and budgets.

Fixtures in tests/fixtures/sources/ are trimmed live responses (2026-10-15).
"""

import json
import socket
import subprocess
import time
from pathlib import Path

import pytest

from app.fetchers import base
from app.fetchers.arxiv import ArXivFetcher
from app.fetchers.base import FetchError, HttpClient, clean_text, json_of, user_agent
from app.fetchers.europepmc import EuropePMCFetcher
from app.fetchers.nasa_ads import NASAADSFetcher
from app.fetchers.plos import PLOSFetcher
from app.fetchers.pubmed import PubMedFetcher
from app.fetchers.semanticscholar import SemanticScholarFetcher
from app.fetchers.terms import boolean_terms
from app.services import pipeline as pipeline_mod
from app.services.citations import SOURCE_URL
from app.services.pipeline import FETCHERS, LiteratureSearchPipeline

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeResp:
    def __init__(self, payload=None, text="", content=b""):
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


# ------------------------------------------------------------- shared helpers

def test_a_web_page_instead_of_data_is_a_typed_network_error():
    with pytest.raises(FetchError) as exc:
        json_of(FakeResp(text="<html>Making sure you're not a bot!</html>"))
    assert exc.value.kind == "network"
    assert "Expecting value" not in str(exc.value)
    assert "refusing automated requests" in str(exc.value)


def test_clean_text_decodes_entities_and_drops_only_tags():
    assert clean_text("<h4>Background</h4>Heart&nbsp;failure &ndash; HF") == "Background Heart failure – HF"
    assert clean_text("&lt;b&gt;Bold&lt;/b&gt; and &amp;lt;i&amp;gt;it&amp;lt;/i&amp;gt;") == "Bold and it"
    assert clean_text("p < 0.01 and q > 2") == "p < 0.01 and q > 2"
    assert clean_text(None) == ""


def test_no_fetcher_sends_a_placeholder_contact_address():
    assert user_agent("") == "LitSieve (educational)"
    assert user_agent("ada@school.org") == "LitSieve (educational; ada@school.org)"
    for name, cls in FETCHERS.items():
        fetcher = cls(email=None)
        http = getattr(fetcher, "http", None)
        if http is not None:
            assert "example.com" not in http.session.headers["User-Agent"], name


def test_blank_contact_email_reaches_the_fetchers_as_blank():
    import inspect

    sig = inspect.signature(LiteratureSearchPipeline.fetch_articles_parallel)
    assert sig.parameters["email"].default == ""
    assert "example.com" not in (ROOT / "app/routes/corpus.py").read_text()


def test_any_error_kind_keeps_the_pages_already_fetched():
    err = FetchError("HTTP 403", kind="http")
    with pytest.raises(FetchError) as exc:
        base.reraise_fetch_error(err, [{"article_id": "1"}])
    assert exc.value.articles == [{"article_id": "1"}]


def test_retry_after_longer_than_the_budget_fails_at_once():
    http = HttpClient(delay=0, budget_seconds=5)
    calls = []

    class Busy:
        status_code = 429
        headers = {"Retry-After": "120"}
        text = ""

    def request(*args, **kwargs):
        calls.append(1)
        return Busy()

    http.session.request = request
    started = time.monotonic()
    with pytest.raises(FetchError) as exc:
        http.get("https://example.test/busy")
    assert exc.value.kind == "rate_limited"
    assert "120 seconds" in str(exc.value)
    assert time.monotonic() - started < 1
    assert len(calls) == 1


def test_a_fetch_that_returns_after_the_budget_keeps_its_papers(tmp_path, monkeypatch):
    monkeypatch.setenv("LITSIEVE_FETCH_SOURCE_TIMEOUT", "0.03")
    article = {
        "article_id": "late-1", "source": "late", "title": "Late paper",
        "abstract": "Finished a moment after the budget.", "authors": [],
        "year": "2026", "journal": "Fixture",
    }

    class Late:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            time.sleep(0.06)
            return [article]

    monkeypatch.setitem(pipeline_mod.FETCHERS, "late", Late)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "late.db"))
    try:
        result = p.fetch_articles_parallel("q", ["late"])
        assert result["late"]["count"] == 1
        assert result["late"]["error"] is None
    finally:
        p.close()


def test_boolean_terms_put_and_between_words():
    assert boolean_terms("heart disease") == ["heart", "AND", "disease"]
    assert boolean_terms('"stem cell" OR mice') == ['"stem cell"', "OR", "mice"]
    assert boolean_terms("asthma NOT children") == ["asthma", "NOT", "children"]
    assert boolean_terms("asthma AND NOT children") == ["asthma", "AND", "NOT", "children"]
    assert boolean_terms("(diabetes) AND") == ["diabetes"]


# ------------------------------------------------------------------ Europe PMC

def test_europepmc_reads_the_core_journal_and_strips_html(monkeypatch):
    f = EuropePMCFetcher()
    payload = load("europepmc_core_abstract_html.json")
    payload.pop("nextCursorMark", None)
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(payload))
    arts = {a["article_id"]: a for a in f.search_and_fetch("heart disease", 5)}
    assert arts["42808454"]["journal"] == "Journal of the American Heart Association"
    assert arts["42680123"]["journal"] == "American journal of preventive medicine"
    for art in arts.values():
        assert "<" not in art["abstract"] and "&lt;" not in art["abstract"]
    # pubYear 2028 is the future issue; the paper came out in 2026.
    assert arts["42680123"]["year"] == "2026"


def test_europepmc_non_json_is_an_error_not_an_empty_result(monkeypatch):
    f = EuropePMCFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp())
    with pytest.raises(FetchError) as exc:
        f.search_and_fetch("heart disease", 5)
    assert exc.value.kind == "network"


EUROPEPMC_LINKS = [
    ("42808454", "https://europepmc.org/article/MED/42808454"),
    ("PPR1338733", "https://europepmc.org/article/PPR/PPR1338733"),
    ("PMC1234567", "https://europepmc.org/article/PMC/PMC1234567"),
]
PREPRINT_DOI = "10.64898/2026.10.06.757136"


def _js_links(source, ids):
    script = r"""
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync('static/js/common.js', 'utf8');
const start = source.indexOf('function getArticleUrl(');
const end = source.indexOf('// === Source display name');
const sandbox = {};
vm.runInNewContext(source.slice(start, end) + ';this.f = getArticleUrl;', sandbox);
const [src, ids] = JSON.parse(process.argv[1]);
console.log(JSON.stringify(ids.map((id) => sandbox.f(id, src))));
"""
    out = subprocess.run(
        ["node", "-e", script, json.dumps([source, ids])],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_europepmc_and_preprint_links_match_in_python_and_js():
    ids = [aid for aid, _ in EUROPEPMC_LINKS]
    expected = [url for _, url in EUROPEPMC_LINKS]
    assert [SOURCE_URL["europepmc"](aid) for aid in ids] == expected
    assert _js_links("europepmc", ids) == expected
    for src in ("biorxiv", "medrxiv"):
        assert SOURCE_URL[src](PREPRINT_DOI) == f"https://doi.org/{PREPRINT_DOI}"
        assert _js_links(src, [PREPRINT_DOI]) == [f"https://doi.org/{PREPRINT_DOI}"]


# ----------------------------------------------------------------------- arXiv

def test_arxiv_ands_the_words_and_reads_entries_from_one_request(monkeypatch):
    f = ArXivFetcher()
    assert f.http.delay >= 3.0
    xml = (FIXTURES / "arxiv_and_query.xml").read_text()
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params)
        return FakeResp(text=xml)

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("diabetes insulin", max_results=10)
    assert calls == [{"search_query": "all:diabetes AND all:insulin", "start": 0, "max_results": 10}]
    assert len(arts) == 2
    assert all(a["abstract"] and a["source"] == "arxiv" for a in arts)


def test_arxiv_not_becomes_andnot():
    assert ArXivFetcher.search_query("asthma NOT children") == "all:asthma ANDNOT all:children"
    assert ArXivFetcher.search_query("asthma AND NOT children") == "all:asthma ANDNOT all:children"


def test_arxiv_unreadable_reply_is_a_network_error(monkeypatch):
    f = ArXivFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(text="<html>busy"))
    with pytest.raises(FetchError) as exc:
        f.search_and_fetch("diabetes", max_results=5)
    assert exc.value.kind == "network"


# ------------------------------------------------------------------------ PLOS

def test_plos_scopes_every_word_to_title_or_abstract(monkeypatch):
    assert PLOSFetcher.solr_query("heart disease") == (
        "title:(heart AND disease) OR abstract:(heart AND disease)"
    )
    f = PLOSFetcher()
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params)
        return FakeResp(load("plos_search_parenthesised.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart disease", max_results=5)
    assert calls[0]["q"] == "title:(heart AND disease) OR abstract:(heart AND disease)"
    assert [a["article_id"] for a in arts] == [
        "10.1371/journal.pone.0066861",
        "10.1371/journal.pone.0321209",
    ]


# ---------------------------------------------------------------------- PubMed

def test_pubmed_sets_no_process_wide_socket_timeout():
    assert socket.getdefaulttimeout() is None


def test_pubmed_reads_a_medline_date_year_and_every_author(monkeypatch):
    f = PubMedFetcher()
    xml = (FIXTURES / "pubmed_efetch_medlinedate.xml").read_bytes()
    monkeypatch.setattr(f.http, "post", lambda *a, **k: FakeResp(content=xml))
    arts = {a["article_id"]: a for a in f.fetch_details(["10149012", "2246988"])}
    # 2246988 has <MedlineDate>1990 Dec 3-17</MedlineDate> and no <Year>.
    assert arts["2246988"]["year"] == "1990"
    assert arts["2246988"]["authors"]
    assert all(a["year"].isdigit() for a in arts.values())


def test_pubmed_network_failure_is_an_error_not_no_results(monkeypatch):
    f = PubMedFetcher()

    def down(*args, **kwargs):
        raise FetchError("Network error: connection refused", kind="network")

    monkeypatch.setattr(f.http, "get", down)
    with pytest.raises(FetchError) as exc:
        f.search_and_fetch("heart disease", 5)
    assert exc.value.kind == "network"


def test_pubmed_sends_the_ncbi_key_and_the_students_email_only(monkeypatch):
    monkeypatch.setenv("NCBI_API_KEY", "ncbi-test-key")
    f = PubMedFetcher(email="")
    params = f._params(term="x")
    assert params["api_key"] == "ncbi-test-key"
    assert "email" not in params
    assert PubMedFetcher(email="ada@school.org")._params()["email"] == "ada@school.org"


# ---------------------------------------------------- Semantic Scholar, ADS

def test_semantic_scholar_sends_its_key_when_the_host_has_one(monkeypatch):
    monkeypatch.setenv("S2_API_KEY", "s2-test-key")
    assert SemanticScholarFetcher().http.session.headers["x-api-key"] == "s2-test-key"
    monkeypatch.delenv("S2_API_KEY")
    assert "x-api-key" not in SemanticScholarFetcher().http.session.headers


def test_semantic_scholar_unexpected_failure_is_an_error_not_no_results(monkeypatch):
    f = SemanticScholarFetcher()

    def broken(*args, **kwargs):
        raise KeyError("paperId")

    monkeypatch.setattr(f.http, "get", broken)
    with pytest.raises(FetchError) as exc:
        f.search_and_fetch("heart disease", 5)
    assert exc.value.kind == "network"


def test_nasa_ads_without_a_token_says_so(monkeypatch):
    monkeypatch.delenv("NASA_ADS_TOKEN", raising=False)
    with pytest.raises(FetchError) as exc:
        NASAADSFetcher().search_and_fetch("exoplanet", 5)
    assert exc.value.kind == "unavailable"
    assert "token" in str(exc.value)
