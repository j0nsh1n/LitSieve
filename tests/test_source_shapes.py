"""Source fetchers against the live response shapes captured on 2026-10-15.

Fixtures in tests/fixtures/sources/ are trimmed live responses (audit 18.x).
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

import pytest

from app.fetchers.base import FetchError
from app.fetchers.clinicaltrials import ClinicalTrialsFetcher
from app.fetchers.doaj import DOAJFetcher
from app.fetchers.openaire import OpenAIREFetcher
from app.fetchers.openalex import OpenAlexFetcher
from app.fetchers.zenodo import ZenodoFetcher
from app.services.citations import SOURCE_URL, article_url

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "sources"

TAG = re.compile(r"</?[A-Za-z][^>]*>")
ENTITY = re.compile(r"&#?\w+;")


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class NotJsonResp:
    """A bot wall: HTTP 2xx whose body is a web page."""

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def assert_plain(text):
    assert text
    assert not TAG.search(text), text[:200]
    assert not ENTITY.search(text), text[:200]


# ---------------------------------------------------------------- DOAJ

def test_doaj_live_shape_has_plain_text_abstracts(monkeypatch):
    f = DOAJFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(load("doaj_articles.json")))
    arts = f.search_and_fetch("heart disease", max_results=3)
    assert len(arts) == 3
    for art in arts:
        assert_plain(art["abstract"])
        assert_plain(art["title"])
    assert arts[0]["journal"] == "Children"
    assert arts[0]["year"] == "2025"
    # A literal "p < 0.01" is text, not markup, and an escaped &lt; is decoded.
    assert "p < 0.01" in arts[1]["abstract"]
    assert "P < 0.001" in arts[2]["abstract"]


def test_doaj_double_escaped_entities_are_decoded():
    f = DOAJFetcher()
    art = f._parse_result(
        {
            "id": "x",
            "bibjson": {
                "title": "Rats &amp; mice",
                "abstract": "<p>Effect was small (P &amp;lt; 0.05).</p>",
            },
        }
    )
    assert art["title"] == "Rats & mice"
    assert art["abstract"] == "Effect was small (P < 0.05)."


def _numbered_doaj(total):
    return [
        {"id": f"d{i}", "bibjson": {"title": f"T{i}", "abstract": f"A{i}", "year": "2020"}}
        for i in range(total)
    ]


def test_doaj_paging_uses_constant_page_size_and_no_repeats(monkeypatch):
    f = DOAJFetcher()
    universe = _numbered_doaj(230)
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(dict(params))
        size, page = params["pageSize"], params["page"]
        return FakeResp({"results": universe[(page - 1) * size : page * size]})

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart", max_results=150)
    assert [c["pageSize"] for c in calls] == [100, 100]
    ids = [a["article_id"] for a in arts]
    assert len(ids) == 150
    assert len(set(ids)) == 150


def test_doaj_non_json_body_is_a_typed_network_error(monkeypatch):
    f = DOAJFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: NotJsonResp())
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=5)
    assert caught.value.kind == "network"


def test_doaj_unexpected_error_keeps_articles_and_is_not_silent(monkeypatch):
    f = DOAJFetcher()
    universe = _numbered_doaj(100)
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params["page"])
        if params["page"] == 1:
            return FakeResp({"results": universe})
        return FakeResp(["not", "a", "dict"])  # .get() fails on a list

    monkeypatch.setattr(f.http, "get", get)
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=500)
    assert caught.value.kind == "network"
    assert len(caught.value.articles) == 100


# ---------------------------------------------------------------- Zenodo

def test_zenodo_live_shape_has_plain_text_abstracts(monkeypatch):
    f = ZenodoFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(load("zenodo_records.json")))
    arts = f.search_and_fetch("heart disease", max_results=5)
    assert [a["article_id"] for a in arts] == ["14250931", "2634610"]
    for art in arts:
        assert_plain(art["abstract"])
    assert "0.2%–4% of pregnancies" in arts[0]["abstract"]
    assert arts[0]["journal"] == "International Journal of Pharmaceutical and Clinical Research"
    assert arts[1]["journal"] == ""


def test_zenodo_paging_uses_constant_page_size_and_no_repeats(monkeypatch):
    f = ZenodoFetcher()
    universe = [
        {"id": i, "metadata": {"title": f"T{i}", "description": f"A{i}"}} for i in range(60)
    ]
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(dict(params))
        size, page = params["size"], params["page"]
        return FakeResp({"hits": {"hits": universe[(page - 1) * size : page * size]}})

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart", max_results=30)
    assert [c["size"] for c in calls] == [25, 25]
    ids = [a["article_id"] for a in arts]
    assert len(ids) == 30
    assert len(set(ids)) == 30


def test_zenodo_unexpected_error_is_a_typed_network_error(monkeypatch):
    f = ZenodoFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(["nope"]))
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=5)
    assert caught.value.kind == "network"


# -------------------------------------------------------------- OpenAIRE

def _openaire_records():
    return load("openaire_publications.json")["response"]["results"]["result"]


def test_openaire_live_shape_ids_and_plain_text(monkeypatch):
    f = OpenAIREFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(load("openaire_publications.json")))
    arts = f.search_and_fetch("heart disease", max_results=3)
    # PMIDs arrive as JSON numbers; they must come out as strings.
    assert [a["article_id"] for a in arts] == ["40123605", "3837525", "10.1093/innovait/inm006"]
    assert all(isinstance(a["article_id"], str) for a in arts)
    for art in arts:
        assert_plain(art["abstract"])
        assert_plain(art["title"])
    assert arts[0]["year"] == ""


def test_openaire_prefers_doi_over_other_pids():
    f = OpenAIREFetcher()
    record = copy.deepcopy(_openaire_records()[0])
    result = record["metadata"]["oaf:entity"]["oaf:result"]
    result["pid"].append({"@classid": "doi", "$": "10.1000/abc"})
    assert f._parse(record)["article_id"] == "10.1000/abc"


def test_openaire_falls_back_to_object_identifier():
    f = OpenAIREFetcher()
    record = copy.deepcopy(_openaire_records()[0])
    del record["metadata"]["oaf:entity"]["oaf:result"]["pid"]
    record["header"] = {"dri:objIdentifier": {"$": "pmid________::5768f99c"}}
    assert f._parse(record)["article_id"] == "pmid________::5768f99c"


def test_openaire_paging_uses_constant_page_size_and_no_repeats(monkeypatch):
    f = OpenAIREFetcher()
    template = _openaire_records()[2]
    universe = []
    for i in range(60):
        rec = copy.deepcopy(template)
        rec["metadata"]["oaf:entity"]["oaf:result"]["pid"] = {"@classid": "doi", "$": f"10.1/{i}"}
        universe.append(rec)
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(dict(params))
        size, page = params["size"], params["page"]
        chunk = universe[(page - 1) * size : page * size]
        return FakeResp({"response": {"results": {"result": chunk}}})

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart", max_results=30)
    assert [c["size"] for c in calls] == [25, 25]
    ids = [a["article_id"] for a in arts]
    assert len(ids) == 30
    assert len(set(ids)) == 30


def test_openaire_non_json_body_is_a_typed_network_error(monkeypatch):
    f = OpenAIREFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: NotJsonResp())
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=5)
    assert caught.value.kind == "network"


OPENAIRE_LINKS = [
    ("10.1093/innovait/inm006", "https://doi.org/10.1093/innovait/inm006"),
    ("40123605", "https://pubmed.ncbi.nlm.nih.gov/40123605/"),
    ("https://example.org/paper", "https://example.org/paper"),
    (
        "pmid________::5768f99cd4375a4a",
        "https://explore.openaire.eu/search/result?id=" + quote("pmid________::5768f99cd4375a4a", safe=""),
    ),
]


@pytest.mark.parametrize("aid,expected", OPENAIRE_LINKS)
def test_openaire_links_python(aid, expected):
    assert SOURCE_URL["openaire"](aid) == expected
    assert article_url({"source": "openaire", "article_id": aid}) == expected


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_openaire_links_js_match_python():
    script = r"""
const fs = require('fs'), vm = require('vm');
const source = fs.readFileSync('static/js/common.js', 'utf8');
const start = source.indexOf('function getArticleUrl(');
const end = source.indexOf('// === Source display name');
const sandbox = {};
vm.runInNewContext(source.slice(start, end) + ';this.f = getArticleUrl;', sandbox);
const ids = JSON.parse(process.argv[1]);
console.log(JSON.stringify(ids.map((id) => sandbox.f(id, 'openaire'))));
"""
    ids = [aid for aid, _ in OPENAIRE_LINKS]
    out = subprocess.run(
        ["node", "-e", script, json.dumps(ids)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(out.stdout) == [expected for _, expected in OPENAIRE_LINKS]


# -------------------------------------------------------- ClinicalTrials

def test_clinicaltrials_journal_is_the_registry_not_the_sponsor(monkeypatch):
    f = ClinicalTrialsFetcher()
    page = load("clinicaltrials_studies.json")
    page.pop("nextPageToken", None)  # one page only
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(page))
    arts = f.search_and_fetch("heart disease", max_results=5)
    assert [a["article_id"] for a in arts] == ["NCT02791113", "NCT05933824"]
    assert {a["journal"] for a in arts} == {"ClinicalTrials.gov"}
    assert [a["year"] for a in arts] == ["2014", "2023"]


def test_clinicaltrials_keeps_every_official_and_empty_year():
    f = ClinicalTrialsFetcher()
    study = copy.deepcopy(load("clinicaltrials_studies.json")["studies"][0])
    proto = study["protocolSection"]
    proto["contactsLocationsModule"]["overallOfficials"] = [{"name": f"Dr {i}"} for i in range(8)]
    del proto["statusModule"]["startDateStruct"]
    art = f._parse_study(study)
    assert art["authors"] == [f"Dr {i}" for i in range(8)]
    assert art["year"] == ""


def test_clinicaltrials_non_json_body_is_a_typed_network_error(monkeypatch):
    f = ClinicalTrialsFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: NotJsonResp())
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=5)
    assert caught.value.kind == "network"


# -------------------------------------------------------------- OpenAlex

def _works():
    return load("openalex_works.json")["results"]


def test_openalex_live_shape(monkeypatch):
    f = OpenAlexFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: FakeResp(load("openalex_works.json")))
    arts = f.search_and_fetch("heart disease", max_results=5)
    by_id = {a["article_id"]: a for a in arts}
    assert by_id["W3122226502"]["journal"] == "Circulation"
    assert by_id["W3122226502"]["year"] == "2021"
    # W2340941041: every location is the PubMed repository, so the name it was
    # deposited under (the journal) is used instead of "PubMed".
    assert by_id["W2340941041"]["journal"].startswith("Heart disease and stroke")
    # W2592146705: no source at all -> empty, not "Unknown journal".
    assert by_id["W2592146705"]["journal"] == ""


def test_openalex_prefers_a_journal_location_over_a_repository_primary():
    f = OpenAlexFetcher()
    work = copy.deepcopy(_works()[1])  # W3122226502: Circulation is the primary
    circulation = work["primary_location"]
    work["primary_location"] = {"source": {"display_name": "PubMed", "type": "repository"}}
    work["locations"] = [
        {"source": {"display_name": "PubMed", "type": "repository"}},
        circulation,
        {"source": {"display_name": "Some Conference", "type": "conference"}},
    ]
    assert f._parse_work(work)["journal"] == "Circulation"


def test_openalex_year_is_empty_when_missing():
    f = OpenAlexFetcher()
    for missing in (None, "drop"):
        work = copy.deepcopy(_works()[1])
        if missing == "drop":
            del work["publication_year"]
        else:
            work["publication_year"] = None
        assert f._parse_work(work)["year"] == ""


def test_openalex_keeps_every_author():
    f = OpenAlexFetcher()
    work = copy.deepcopy(_works()[1])
    work["authorships"] = [{"author": {"display_name": f"Author {i}"}} for i in range(12)]
    assert len(f._parse_work(work)["authors"]) == 12


def test_openalex_api_key_and_mailto(monkeypatch):
    seen = []

    def run(email):
        f = OpenAlexFetcher(email=email)

        def get(url, params=None, **kwargs):
            seen.append(dict(params))
            return FakeResp({"results": []})

        monkeypatch.setattr(f.http, "get", get)
        f.search_and_fetch("heart", max_results=5)

    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    run(None)
    assert "api_key" not in seen[-1]
    assert "mailto" not in seen[-1]

    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")
    run("student@example.edu")
    assert seen[-1]["api_key"] == "secret-key"
    assert seen[-1]["mailto"] == "student@example.edu"


def test_openalex_paging_stops_on_a_short_page(monkeypatch):
    f = OpenAlexFetcher()
    works = [w for w in _works() if w["id"] != "https://openalex.org/W2592146705"]
    calls = []

    def get(url, params=None, **kwargs):
        calls.append(params["page"])
        return FakeResp({"results": works})  # 2 results, fewer than per_page

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("heart", max_results=100)
    assert calls == [1]
    assert len(arts) == 2


def test_openalex_non_json_body_is_a_typed_network_error(monkeypatch):
    f = OpenAlexFetcher()
    monkeypatch.setattr(f.http, "get", lambda *a, **k: NotJsonResp())
    with pytest.raises(FetchError) as caught:
        f.search_and_fetch("heart", max_results=5)
    assert caught.value.kind == "network"
