"""P1.2: OpenAlex, Crossref and DOAJ fill work metadata for new fetches."""

import copy
import json
import random
import string
import zlib
from pathlib import Path

import numpy as np
import pytest

from app.fetchers.crossref import CrossRefFetcher
from app.fetchers.doaj import DOAJFetcher
from app.fetchers.openalex import OpenAlexFetcher
from app.services.citations import collection_to_apa, collection_to_bibtex, collection_to_ris
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import dbconn
from app.storage.database import ARTICLE_COLUMNS, ArticleDatabase, omit_null_metadata

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sources"
LEGACY = ARTICLE_COLUMNS[:7]


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def parse_openalex(name):
    return OpenAlexFetcher()._parse_work(load(name)["results"][0])


def parse_crossref(name, abstract=None):
    item = copy.deepcopy(load(name)["message"]["items"][0])
    if abstract is not None:
        item["abstract"] = abstract
    return CrossRefFetcher()._parse_item(item)


def parse_doaj(name):
    return DOAJFetcher()._parse_result(load(name)["results"][0])


def extra_row(db, article_id, source, *, staging=False):
    table = "staging_article_extra" if staging else "article_extra"
    return db.conn.execute(
        f"SELECT provenance, locations, provider_record, raw_status "
        f"FROM {table} WHERE article_id = ? AND source = ?",
        (article_id, source),
    ).fetchone()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    return tmp_path / "articles.db"


def test_openalex_chapter_fills_parent_book_and_platform_host():
    article = parse_openalex("openalex_chapter_volume.json")
    assert article["article_id"] == "W4408664739"
    assert article["work_type"] == "book-chapter"
    assert article["provider_type"] == "openalex:book-chapter"
    assert article["doi"] == "10.3735/9781935306627.book-part-157"
    assert article["container_title"] == "Schlager Anthology of Black America"
    assert article["host_name"] == "Schlager Group eBooks"
    assert article["journal"] == ""
    assert article["oa_status"] == "closed"
    assert article["best_oa_url"] is None
    assert article["evidence_basis"] == "abstract"
    biblio = json.loads(article["biblio"])
    assert biblio["parent_book_id"] == "https://openalex.org/W4408368666"
    assert biblio["published_date"] == "2021-08-15"
    assert "volume" not in biblio
    assert article["_extra"]["provenance"]["container_title"] == "openalex"
    assert article["_extra"]["locations"] == []
    assert "abstract_inverted_index" not in article["_extra"]["provider_record"]


def test_openalex_article_fills_oa_biblio_and_keeps_journal():
    article = parse_openalex("openalex_article_oa.json")
    assert article["work_type"] == "journal-article"
    assert article["provider_type"] == "openalex:article"
    assert article["doi"] == "10.1016/j.sleh.2025.07.003"
    assert article["journal"] == "Sleep Health"
    assert article["container_title"] == "Sleep Health"
    assert article["host_name"] is None
    assert article["oa_status"] == "hybrid"
    assert article["best_oa_url"].endswith("/pdf")
    biblio = json.loads(article["biblio"])
    assert biblio["volume"] == "12"
    assert biblio["issue"] == "1"
    assert biblio["pages"] == "30-38"
    assert biblio["license"] == "cc-by-nc-nd"
    loc = article["_extra"]["locations"][0]
    assert loc["kind"] == "pdf"
    assert loc["via"] == "openalex"
    assert loc["version"] == "publishedVersion"


def test_openalex_search_filter_is_unchanged(monkeypatch):
    seen = []
    f = OpenAlexFetcher()

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp({"results": []})

    monkeypatch.setattr(f.http, "get", get)
    assert f.search_and_fetch("sleep", max_results=5) == []
    assert seen[0]["filter"] == "has_abstract:true,type:article"


def test_crossref_chapter_fills_container_isbn_and_selects_new_fields(monkeypatch):
    f = CrossRefFetcher()
    seen = []

    def get(url, params=None, **kwargs):
        seen.append(dict(params))
        return FakeResp(load("crossref_chapter.json"))

    monkeypatch.setattr(f.http, "get", get)
    arts = f.search_and_fetch("New Deal", max_results=5)
    select = seen[0]["select"]
    for field in ("type", "ISBN", "publisher", "editor", "link", "license", "volume", "issue", "page"):
        assert field in select.split(",")
    assert seen[0]["filter"] == "has-abstract:true"
    article = arts[0]
    assert article["work_type"] == "book-chapter"
    assert article["provider_type"] == "crossref:book-chapter"
    assert article["doi"] == "10.3735/9781935306627.book-part-166"
    assert article["container_title"] == "Schlager Anthology of Black America"
    assert article["journal"] == "Schlager Anthology of Black America"
    assert article["host_name"] is None
    assert article["oa_status"] is None
    assert article["best_oa_url"] is None
    biblio = json.loads(article["biblio"])
    assert biblio["publisher"] == "Schlager Group Inc."
    assert biblio["isbn"] == ["9781935306627"]
    assert biblio["published_date"] == "2021-08-15"
    assert article["_extra"]["locations"][0]["url"].startswith("https://library.schlagergroup.com/")


def test_crossref_book_and_edited_book_fill_type_and_editors():
    book = parse_crossref("crossref_book.json", abstract="Abstract.")
    assert book["work_type"] == "book"
    assert book["provider_type"] == "crossref:book"
    assert book["doi"] == "10.4324/9780203309506"
    assert book["container_title"] is None
    assert book["journal"] == ""
    assert json.loads(book["biblio"])["publisher"] == "Routledge"
    assert json.loads(book["biblio"])["isbn"] == ["9780203309506"]
    assert book["authors"] == ["Patricia Hill Collins"]

    edited = parse_crossref("crossref_edited_book.json", abstract="Abstract.")
    assert edited["work_type"] == "edited-book"
    assert edited["provider_type"] == "crossref:edited-book"
    assert json.loads(edited["biblio"])["editors"] == ["Rachel Jacoff"]
    assert edited["container_title"] is None


def test_doaj_fills_doi_gold_oa_and_publisher():
    article = parse_doaj("doaj_oa_article.json")
    assert article["work_type"] == "journal-article"
    assert article["provider_type"] == "doaj:journal-article"
    assert article["doi"] == "10.1016/j.sleepx.2025.100159"
    assert article["container_title"] == "Sleep Medicine: X"
    assert article["journal"] == "Sleep Medicine: X"
    assert article["oa_status"] == "gold"
    assert article["best_oa_url"].startswith("http://www.sciencedirect.com/")
    assert json.loads(article["biblio"])["publisher"] == "Elsevier"


def test_absent_fields_are_null_never_unknown_text():
    work = copy.deepcopy(load("openalex_article_closed.json")["results"][0])
    work["doi"] = None
    work["ids"] = {}
    work["open_access"] = {"oa_status": None}
    work["best_oa_location"] = None
    work["primary_location"] = {"source": {"type": "journal", "display_name": ""}}
    work["locations"] = []
    work["biblio"] = {}
    work["publication_date"] = None
    article = OpenAlexFetcher()._parse_work(work)
    assert article["doi"] is None
    assert article["container_title"] is None
    assert article["host_name"] is None
    assert article["oa_status"] is None
    assert article["best_oa_url"] is None
    assert article["biblio"] is None
    assert article["work_type"] == "journal-article"
    assert "unknown" not in (article["container_title"] or "")
    assert "unknown" not in (article["host_name"] or "")

    result = copy.deepcopy(load("doaj_oa_article.json")["results"][0])
    result["bibjson"]["identifier"] = [{"id": "2590-1427", "type": "eissn"}]
    result["bibjson"]["link"] = [{"type": "homepage", "url": "https://example.org"}]
    result["bibjson"]["journal"] = {"title": "", "publisher": ""}
    empty = DOAJFetcher()._parse_result(result)
    assert empty["doi"] is None
    assert empty["container_title"] is None
    assert empty["oa_status"] is None
    assert empty["best_oa_url"] is None
    assert empty["biblio"] is None
    assert empty["journal"] == ""


def test_extra_is_stored_and_too_large_record_is_null(db_path):
    article = parse_openalex("openalex_article_oa.json")
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([article], dedupe=False)
        assert stats["inserted"] == 1
        row = extra_row(db, article["article_id"], article["source"])
        assert json.loads(row[0])["doi"] == "openalex"
        assert json.loads(row[1])[0]["kind"] == "pdf"
        stored = json.loads(zlib.decompress(row[2]))
        assert stored["id"] == "https://openalex.org/W4412783059"
        assert "abstract_inverted_index" not in stored
        assert row[3] is None
        assert "_extra" not in db.get_article_by_id(article["article_id"], article["source"])

        huge = copy.deepcopy(article)
        huge["article_id"] = "W-too-large"
        rng = random.Random(9)
        huge["_extra"] = {
            "provenance": {"doi": "openalex"},
            "locations": [],
            "provider_record": {
                "payload": "".join(rng.choices(string.ascii_letters, k=12000)),
            },
        }
        assert len(zlib.compress(json.dumps(huge["_extra"]["provider_record"],
                                            ensure_ascii=False, separators=(",", ":")).encode())) > 4096
        db.insert_articles([huge], dedupe=False)
        blob, status = extra_row(db, "W-too-large", "openalex")[2:]
        assert blob is None
        assert status == "too_large"
        assert json.loads(extra_row(db, "W-too-large", "openalex")[0])["doi"] == "openalex"
    finally:
        db.close()


def test_duplicate_skip_does_not_write_extra(db_path):
    first = parse_doaj("doaj_oa_article.json")
    second = parse_crossref("crossref_chapter.json")
    second["title"] = first["title"]
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        assert extra_row(db, first["article_id"], first["source"]) is not None
        assert extra_row(db, second["article_id"], second["source"]) is None
    finally:
        db.close()


def test_staging_swap_keeps_metadata_and_extra(db_path):
    article = parse_openalex("openalex_chapter_volume.json")
    db = ArticleDatabase(str(db_path))
    try:
        db.ensure_staging_articles()
        assert db.insert_articles([article], dedupe=False, staging=True)["inserted"] == 1
        staged = extra_row(db, article["article_id"], article["source"], staging=True)
        assert staged is not None
        assert db.replace_from_staging() == 1
        stored = db.get_article_by_id(article["article_id"], article["source"])
        assert stored["work_type"] == "book-chapter"
        assert stored["container_title"] == "Schlager Anthology of Black America"
        assert stored["host_name"] == "Schlager Group eBooks"
        live = extra_row(db, article["article_id"], article["source"])
        assert live[0] == staged[0]
        assert json.loads(zlib.decompress(live[2]))["volume"]["display_name"] == (
            "Schlager Anthology of Black America"
        )
    finally:
        db.close()


def test_search_and_exports_omit_extra_and_match_legacy_bytes(db_path):
    article = parse_openalex("openalex_article_oa.json")
    legacy = {name: article[name] for name in LEGACY}
    pipe = LiteratureSearchPipeline(db_path=str(db_path))
    try:
        pipe.db.insert_articles([article], dedupe=False)
        filled = pipe.db.get_all_articles()[0]
        assert "_extra" not in filled
        assert filled["doi"] == article["doi"]
        export_rows = pipe.db.get_library_export_rows()
        assert all("_extra" not in row for row in export_rows)
        assert collection_to_ris(export_rows) == collection_to_ris([legacy])
        assert collection_to_bibtex(export_rows) == collection_to_bibtex([legacy])
        assert collection_to_apa(export_rows) == collection_to_apa([legacy])

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
        assert results
        assert all("_extra" not in row for row in results)
        dumped = json.dumps(results)
        assert "_extra" not in dumped
        assert "provider_record" not in dumped
    finally:
        pipe.db.close()


def test_legacy_rows_stay_null(db_path):
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([{
            "article_id": "legacy-1",
            "source": "pubmed",
            "title": "Old row",
            "abstract": "Abstract.",
            "year": "2019",
            "authors": ["A"],
            "journal": "Nature",
        }], dedupe=False)
        row = db.get_article_by_id("legacy-1", "pubmed")
        for name in ARTICLE_COLUMNS[7:]:
            assert row[name] is None
        assert extra_row(db, "legacy-1", "pubmed") is None
        stripped = omit_null_metadata(dict(row))
        assert all(name not in stripped for name in ARTICLE_COLUMNS[7:])
    finally:
        db.close()
