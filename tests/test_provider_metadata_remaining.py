"""P1.3: remaining fetchers fill work metadata for new fetches."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from app.fetchers.arxiv import ARXIV_NS, ATOM_NS, ArXivFetcher
from app.fetchers.biorxiv import BioRxivFetcher, MedRxivFetcher
from app.fetchers.clinicaltrials import ClinicalTrialsFetcher
from app.fetchers.eric import ERICFetcher
from app.fetchers.europepmc import EuropePMCFetcher
from app.fetchers.hal import HALFetcher
from app.fetchers.nasa_ads import NASAADSFetcher
from app.fetchers.openaire import OpenAIREFetcher
from app.fetchers.plos import PLOSFetcher
from app.fetchers.pubmed import PubMedFetcher
from app.fetchers.semanticscholar import SemanticScholarFetcher
from app.fetchers.zenodo import ZenodoFetcher
from app.services.citations import collection_to_apa, collection_to_bibtex, collection_to_ris
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import dbconn
from app.storage.database import ARTICLE_COLUMNS, omit_null_metadata

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
LEGACY = ARTICLE_COLUMNS[:7]


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResp:
    def __init__(self, payload=None, text="", content=b""):
        self.payload = payload
        self.text = text
        self.content = content

    def json(self):
        return self.payload


def extra_row(db, article_id, source):
    return db.conn.execute(
        "SELECT provenance, locations, provider_record, raw_status "
        "FROM article_extra WHERE article_id = ? AND source = ?",
        (article_id, source),
    ).fetchone()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    return tmp_path / "articles.db"


def test_eric_fills_types_doi_and_keeps_the_search_query(monkeypatch):
    f = ERICFetcher()
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp(load("eric_journal.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("sleep", max_results=5)
    fields = seen[0]["fields"]
    assert seen[0]["search"] == "sleep"
    for name in ("publicationtype", "peerreviewed", "url", "isbn", "issn"):
        assert name in fields.split(",")
    article = arts[0]
    assert article["work_type"] == "journal-article"
    assert "Journal Articles" in article["provider_type"]
    assert "Reports - Evaluative" in article["provider_type"]
    assert article["doi"] == "10.3102/0013189x11402323"
    assert article["container_title"] == "Educational Researcher"
    assert article["journal"] == "Educational Researcher"
    assert article["host_name"] is None
    assert article["oa_status"] is None
    assert article["evidence_basis"] == "abstract"


def test_eric_report_without_url_leaves_doi_null():
    article = ERICFetcher()._parse_doc(load("eric_report.json")["response"]["docs"][0])
    assert article["work_type"] == "report"
    assert article["doi"] is None
    assert article["container_title"] is None
    assert article["journal"] == ""
    assert json.loads(article["biblio"])["publisher"] == "Abell Foundation"


def test_eric_non_journal_types_move_source_to_publisher():
    report = ERICFetcher()._parse_doc(load("eric_report.json")["response"]["docs"][0])
    assert report["container_title"] is None
    assert json.loads(report["biblio"])["publisher"] == "Abell Foundation"
    book = ERICFetcher()._parse_doc({
        "id": "ED1",
        "title": "A book",
        "description": "Abstract.",
        "source": "Harvard Education Press",
        "publicationtype": ["Books"],
        "isbn": "9780262014793",
    })
    assert book["work_type"] == "book"
    assert book["container_title"] is None
    assert book["journal"] == ""
    biblio = json.loads(book["biblio"])
    assert biblio["publisher"] == "Harvard Education Press"
    assert biblio["isbn"] == ["9780262014793"]
    journal = ERICFetcher()._parse_doc(load("eric_journal.json")["response"]["docs"][0])
    assert journal["container_title"] == "Educational Researcher"
    assert "publisher" not in json.loads(journal["biblio"] or "{}")


def test_pubmed_review_beats_journal_article_and_fills_doi(monkeypatch):
    f = PubMedFetcher()
    xml = (FIXTURES / "pubmed_review.xml").read_bytes()
    monkeypatch.setattr(f.http, "post", lambda *a, **k: FakeResp(content=xml))
    arts = f.fetch_details(["35946417"])
    article = arts[0]
    assert article["work_type"] == "review-article"
    assert article["provider_type"] == "pubmed:Review; Journal Article"
    assert article["doi"] == "10.5664/jcsm.10224"
    assert "Journal of clinical sleep medicine" in article["container_title"]
    assert article["host_name"] is None
    assert article["oa_status"] is None
    assert json.loads(article["biblio"])["volume"] == "18"


def test_pubmed_absent_doi_is_null(monkeypatch):
    f = PubMedFetcher()
    xml = (FIXTURES / "pubmed_efetch_medlinedate.xml").read_bytes()
    monkeypatch.setattr(f.http, "post", lambda *a, **k: FakeResp(content=xml))
    arts = {a["article_id"]: a for a in f.fetch_details(["10149012", "2246988"])}
    assert arts["10149012"]["doi"] is None
    assert arts["2246988"]["doi"] == "10.5694/j.1326-5377.1990.tb126316.x"
    assert arts["10149012"]["work_type"] == "journal-article"


def test_europepmc_open_pmc_and_closed_review():
    open_hit = EuropePMCFetcher()._parse_article(
        load("europepmc_oa_pmc.json")["resultList"]["result"][0]
    )
    assert open_hit["work_type"] == "journal-article"
    assert "research-article" in open_hit["provider_type"]
    assert open_hit["doi"] is None
    assert open_hit["oa_status"] == "green"
    assert "pdf" in open_hit["best_oa_url"]
    closed = EuropePMCFetcher()._parse_article(
        load("europepmc_review_closed.json")["resultList"]["result"][0]
    )
    assert closed["work_type"] == "review-article"
    assert closed["doi"] == "10.1016/j.smrv.2026.102379"
    assert closed["oa_status"] is None
    assert closed["best_oa_url"] is None
    assert closed["container_title"] == "Sleep medicine reviews"


def test_europepmc_search_query_is_unchanged(monkeypatch):
    f = EuropePMCFetcher()
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp({"resultList": {"result": []}})

    monkeypatch.setattr(f.http, "get", get)
    assert f.search_and_fetch("sleep", max_results=5) == []
    assert seen[0]["query"] == "sleep"
    assert seen[0]["resultType"] == "core"


def test_biorxiv_and_medrxiv_use_the_preprint_pdf(monkeypatch):
    bio = BioRxivFetcher()
    monkeypatch.setattr(
        bio.http, "get", lambda *a, **k: FakeResp(load("europepmc_ppr_biorxiv.json"))
    )
    article = bio.search_and_fetch("heart disease", max_results=1)[0]
    assert article["work_type"] == "preprint"
    assert article["host_name"] == "bioRxiv"
    assert article["journal"] == ""
    assert article["container_title"] is None
    assert article["oa_status"] == "green"
    assert article["best_oa_url"].endswith(".full.pdf")
    assert "biorxiv.org/content/" in article["best_oa_url"]

    med = MedRxivFetcher()
    monkeypatch.setattr(
        med.http, "get", lambda *a, **k: FakeResp(load("europepmc_ppr_medrxiv.json"))
    )
    med_art = med.search_and_fetch("heart disease", max_results=1)[0]
    assert med_art["host_name"] == "medRxiv"
    assert "medrxiv.org/content/" in med_art["best_oa_url"]


def test_semantic_scholar_parses_docs_fields_and_tolerates_absence(monkeypatch):
    f = SemanticScholarFetcher()
    filled = f._parse_paper(load("s2_paper.json"))
    assert filled["work_type"] == "review-article"
    assert filled["provider_type"] == "semanticscholar:Review; JournalArticle"
    assert filled["doi"] == "10.1016/j.sleh.2022.01.001"
    assert filled["container_title"] == "Sleep Health"
    assert filled["best_oa_url"] == "https://example.org/paper.pdf"
    empty = f._parse_paper({
        "paperId": "bare",
        "title": "Bare paper",
        "abstract": "No extra fields were confirmed live.",
    })
    assert empty["doi"] is None
    assert empty["work_type"] == "unknown"
    assert empty["provider_type"] is None
    assert empty["oa_status"] is None
    assert empty["best_oa_url"] is None
    assert empty["container_title"] is None
    seen = []

    def post(url, params=None, json=None, **kwargs):
        seen.append(dict(params))
        return FakeResp([load("s2_paper.json")])

    monkeypatch.setattr(f.http, "post", post)
    f.fetch_details(["abc123"])
    fields = seen[0]["fields"]
    for name in (
        "externalIds", "publicationTypes", "openAccessPdf", "journal", "publicationDate"
    ):
        assert name in fields.split(",")


def test_hal_file_is_open_and_notice_is_not(monkeypatch):
    f = HALFetcher()
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp(load("hal_file.json"))

    monkeypatch.setattr(f.http, "get", get)
    file_art = f.search_and_fetch("Roosevelt", max_results=1)[0]
    assert "docType_s" in seen[0]["fl"]
    assert "submitType_s" in seen[0]["fl"]
    assert "fileMain_s" in seen[0]["fl"]
    assert file_art["work_type"] == "journal-article"
    assert file_art["provider_type"] == "hal:ART"
    assert file_art["host_name"] == "HAL"
    assert file_art["oa_status"] == "green"
    assert file_art["best_oa_url"].endswith("/document")
    assert file_art["doi"] is None

    notice = HALFetcher()._parse(load("hal_notice.json")["response"]["docs"][0])
    assert notice["oa_status"] is None
    assert notice["best_oa_url"] is None
    assert notice["doi"] == "10.1111/1574-6968.12489"
    assert notice["host_name"] == "HAL"


def test_openaire_object_and_list_instance_shapes(monkeypatch):
    f = OpenAIREFetcher()
    obj = f._parse(load("openaire_instance_object.json")["response"]["results"]["result"][0])
    assert obj["work_type"] == "book-chapter"
    assert obj["provider_type"] == "openaire:Part of book or chapter of book"
    assert obj["doi"] == "10.4135/9781412952507.n459"
    assert obj["host_name"] is None
    assert obj["oa_status"] is None
    listed = f._parse(load("openaire_instance_lists.json")["response"]["results"]["result"][0])
    assert listed["work_type"] == "book-chapter"
    assert "Other literature type" in listed["provider_type"]
    assert "Part of book or chapter of book" in listed["provider_type"]
    assert listed["doi"] == "10.1093/acrefore/9780199329175.013.632"
    assert listed["host_name"] is None
    assert listed["oa_status"] is None
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp(load("openaire_instance_object.json"))

    monkeypatch.setattr(f.http, "get", get)
    f.search_and_fetch("New Deal", max_results=1)
    assert seen[0]["keywords"] == "New Deal"
    assert seen[0]["format"] == "json"


def test_zenodo_open_file_and_restricted_are_not_open():
    opened = ZenodoFetcher()._parse_record(load("zenodo_open.json")["hits"]["hits"][0])
    assert opened["work_type"] == "journal-article"
    assert opened["host_name"] == "Zenodo"
    assert opened["oa_status"] == "green"
    assert opened["best_oa_url"].startswith("https://zenodo.org/api/records/")
    assert opened["doi"] == "10.5281/zenodo.18364505"
    assert opened["container_title"] == (
        "Ennoia Advances in Social Science, Technology and Education"
    )
    restricted = ZenodoFetcher()._parse_record(
        load("zenodo_restricted.json")["hits"]["hits"][0]
    )
    assert restricted["oa_status"] is None
    assert restricted["best_oa_url"] is None
    assert restricted["host_name"] == "Zenodo"


def test_arxiv_preprint_pdf_and_optional_doi():
    root = ET.parse(FIXTURES / "arxiv_and_query.xml").getroot()
    ns = {"a": ATOM_NS, "ax": ARXIV_NS}
    entries = root.findall("a:entry", ns)
    first = ArXivFetcher()._parse_entry(entries[0], ns)
    assert first["work_type"] == "preprint"
    assert first["host_name"] == "arXiv"
    assert first["journal"] == ""
    assert first["container_title"] is None
    assert first["oa_status"] == "green"
    assert first["best_oa_url"] == "https://arxiv.org/pdf/2411.12812v1"
    assert first["doi"] is None
    second = ArXivFetcher()._parse_entry(entries[1], ns)
    assert second["doi"] == "10.1109/tmbmc.2025.3559470"
    assert second["best_oa_url"].endswith("/pdf/2502.03269v1")


def test_plos_is_gold_and_clinicaltrials_is_a_registry_record():
    plos = PLOSFetcher()._parse(load("plos_search_parenthesised.json")["response"]["docs"][0])
    assert plos["work_type"] == "journal-article"
    assert plos["oa_status"] == "gold"
    assert plos["doi"] == "10.1371/journal.pone.0066861"
    assert plos["container_title"] == "PLoS ONE"
    assert plos["best_oa_url"] == "https://doi.org/10.1371/journal.pone.0066861"

    trial = ClinicalTrialsFetcher()._parse_study(load("clinicaltrials_studies.json")["studies"][0])
    assert trial["work_type"] == "registry-record"
    assert trial["host_name"] == "ClinicalTrials.gov"
    assert trial["journal"] == "ClinicalTrials.gov"
    assert trial["container_title"] is None
    assert trial["doi"] is None


def test_nasa_ads_fills_doi_and_requests_doctype(monkeypatch):
    monkeypatch.setenv("NASA_ADS_TOKEN", "ads-test")
    f = NASAADSFetcher()
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp(load("nasa_ads_doc.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("sleep", max_results=5)
    fl = seen[0]["fl"]
    assert seen[0]["q"] == "sleep"
    assert "doi" in fl.split(",")
    assert "doctype" in fl.split(",")
    article = arts[0]
    assert article["work_type"] == "journal-article"
    assert article["doi"] == "10.3847/1538-4357/ab5c1a"
    assert article["host_name"] == "ADS"
    assert article["container_title"] == "The Astrophysical Journal"


def test_exports_and_search_omit_extra_and_match_legacy_bytes(db_path):
    article = ERICFetcher()._parse_doc(load("eric_journal.json")["response"]["docs"][0])
    legacy = {name: article[name] for name in LEGACY}
    pipe = LiteratureSearchPipeline(db_path=str(db_path))
    try:
        pipe.db.insert_articles([article], dedupe=False)
        filled = pipe.db.get_all_articles()[0]
        assert "_extra" not in filled
        export_rows = pipe.db.get_library_export_rows()
        assert all("_extra" not in row for row in export_rows)
        filled_ris = collection_to_ris(export_rows)
        assert "DO  - " in filled_ris
        assert "https://doi.org/" in filled_ris
        assert filled_ris != collection_to_ris([legacy])
        assert collection_to_bibtex(export_rows) != collection_to_bibtex([legacy])
        assert "doi.org" in collection_to_apa(export_rows)
        leak = dict(filled)
        leak["_extra"] = {"provider_record": {"secret": True}}
        assert "_extra" not in omit_null_metadata(leak)
        pipe.db.insert_embeddings(
            {(article["article_id"], article["source"]): np.array([1.0, 0.0], dtype=np.float32)},
            model_name="general",
        )
        results = pipe.search_similar(
            "sleep", top_k=5, query_embedding=np.array([1.0, 0.0], dtype=np.float32),
        )
        dumped = json.dumps(results)
        assert "_extra" not in dumped
        assert "provider_record" not in dumped
        assert extra_row(pipe.db, article["article_id"], article["source"]) is not None
    finally:
        pipe.db.close()


def test_duplicate_skip_does_not_write_extra(db_path):
    first = HALFetcher()._parse(load("hal_file.json")["response"]["docs"][0])
    second = PLOSFetcher()._parse(load("plos_search_parenthesised.json")["response"]["docs"][0])
    second["title"] = first["title"]
    db = __import__("app.storage.database", fromlist=["ArticleDatabase"]).ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        # Title-only identity now requires compatible author and container, so
        # these remain two rows (PLOS also carries a DOI the HAL file lacks).
        assert stats["inserted"] == 2
        assert stats["skipped_duplicates"] == 0
        assert extra_row(db, first["article_id"], first["source"]) is not None
        assert extra_row(db, second["article_id"], second["source"]) is not None
    finally:
        db.close()
