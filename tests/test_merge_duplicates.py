"""P1.5: merge duplicate works instead of skipping them."""

import json

import numpy as np
import pytest

from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import dbconn
from app.storage.database import ArticleDatabase

REDRESS = (
    "Only One Place of Redress: African Americans, Labor Regulations, "
    "and the Courts from Reconstruction to the New Deal"
)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    return tmp_path / "articles.db"


def _paper(**kwargs):
    row = {
        "article_id": "W1",
        "source": "openalex",
        "title": "Widgets and sleep in adults",
        "abstract": "An abstract that is long enough to store.",
        "year": "2020",
        "authors": ["Jane Doe"],
        "journal": "",
    }
    row.update(kwargs)
    return row


def _extra(db, article_id, source, *, staging=False):
    table = "staging_article_extra" if staging else "article_extra"
    return db.conn.execute(
        f"SELECT provenance, locations FROM {table} "
        "WHERE article_id = ? AND source = ?",
        (article_id, source),
    ).fetchone()


def test_norm_title_is_unicode_aware():
    assert ArticleDatabase._norm_title("Café") == ArticleDatabase._norm_title("Cafe")
    japanese = ArticleDatabase._norm_title("睡眠と健康の研究")
    assert japanese
    assert "睡眠" in japanese
    assert ArticleDatabase._norm_title("INTRODUCTION") == "introduction"


def test_openalex_then_crossref_same_doi_fills_empty_fields(db_path):
    openalex = _paper(
        doi="10.1016/example.merge",
        journal="Sleep Health",
        _extra={"provenance": {"doi": "openalex"}, "locations": []},
    )
    crossref = _paper(
        article_id="10.1016/example.merge",
        source="crossref",
        abstract="A different abstract that must not overwrite.",
        doi="10.1016/example.merge",
        work_type="journal-article",
        container_title="Sleep Health",
        _extra={
            "provenance": {"work_type": "crossref"},
            "locations": [{"url": "https://example.org/pdf", "kind": "pdf"}],
        },
    )
    db = ArticleDatabase(str(db_path))
    try:
        first = db.insert_articles([openalex], dedupe=True)
        second = db.insert_articles([crossref], dedupe=True)
        assert first["inserted"] == 1
        assert second["inserted"] == 0
        assert second["skipped_duplicates"] == 1
        assert second["merged"] == 1
        rows = db.get_all_articles()
        assert len(rows) == 1
        row = rows[0]
        assert (row["article_id"], row["source"]) == ("W1", "openalex")
        assert row["abstract"] == "An abstract that is long enough to store."
        assert row["work_type"] == "journal-article"
        assert row["container_title"] == "Sleep Health"
        provenance, locations = _extra(db, "W1", "openalex")
        parsed = json.loads(provenance)
        assert parsed["work_type"] == "crossref"
        assert parsed["container_title"] == "crossref"
        assert json.loads(locations)[0]["url"] == "https://example.org/pdf"
    finally:
        db.close()


def test_crossref_then_openalex_keeps_crossref_key(db_path):
    crossref = _paper(
        article_id="10.1016/example.merge",
        source="crossref",
        doi="10.1016/example.merge",
        work_type="journal-article",
        container_title="Sleep Health",
        journal="Sleep Health",
    )
    openalex = _paper(
        doi="10.1016/example.merge",
        oa_status="hybrid",
        best_oa_url="https://example.org/oa",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([crossref], dedupe=True)
        stats = db.insert_articles([openalex], dedupe=True)
        assert stats["skipped_duplicates"] == 1
        assert stats["merged"] == 1
        rows = db.get_all_articles()
        assert len(rows) == 1
        row = rows[0]
        assert (row["article_id"], row["source"]) == ("10.1016/example.merge", "crossref")
        assert row["work_type"] == "journal-article"
        assert row["oa_status"] == "hybrid"
        assert row["best_oa_url"] == "https://example.org/oa"
    finally:
        db.close()


def test_redress_triple_with_conflicting_dois_stays_three_rows(db_path):
    records = [
        _paper(
            article_id="W-redress-1",
            title=REDRESS,
            year="2002",
            authors=["David E. Bernstein"],
            doi="10.2307/25149301",
            container_title="Labour / Le Travail",
            journal="Labour / Le Travail",
        ),
        _paper(
            article_id="W-redress-2",
            title=REDRESS,
            year="2001",
            authors=["David E. Bernstein"],
            doi="10.2307/3185328",
            container_title="American Journal of Legal History",
            journal="American Journal of Legal History",
        ),
        _paper(
            article_id="W-redress-3",
            title=REDRESS,
            year="2002",
            authors=["David E. Bernstein"],
            doi="10.2307/2700866",
            container_title="Journal of American History",
            journal="Journal of American History",
        ),
    ]
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles(records, dedupe=True)
        assert stats["inserted"] == 3
        assert stats["skipped_duplicates"] == 0
        assert stats["merged"] == 0
        assert len(db.get_all_articles()) == 3
    finally:
        db.close()


def test_generic_introduction_chapters_do_not_title_match(db_path):
    first = _paper(
        article_id="chap-1",
        source="crossref",
        title="Introduction",
        year="2010",
        authors=["A Author"],
        container_title="Book One",
    )
    second = _paper(
        article_id="chap-2",
        source="openalex",
        title="Introduction",
        year="2010",
        authors=["A Author"],
        container_title="Book Two",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert stats["skipped_duplicates"] == 0
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_same_title_years_three_apart_are_two_rows(db_path):
    first = _paper(year="2010", doi=None)
    second = _paper(
        article_id="pmid-2",
        source="pubmed",
        year="2013",
        doi=None,
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_same_title_year_plus_minus_one_same_author_merges(db_path):
    first = _paper(year="2010", authors=["Jane Doe"], doi=None)
    second = _paper(
        article_id="pmid-2",
        source="pubmed",
        year="2011",
        authors=["Doe, Jane"],
        doi=None,
        work_type="journal-article",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        assert stats["merged"] == 1
        rows = db.get_all_articles()
        assert len(rows) == 1
        assert rows[0]["work_type"] == "journal-article"
        assert (rows[0]["article_id"], rows[0]["source"]) == ("W1", "openalex")
    finally:
        db.close()


def test_nonempty_fields_are_kept_and_conflicts_recorded(db_path):
    first = _paper(
        doi="10.1016/example.conflict",
        work_type="journal-article",
        oa_status="closed",
    )
    second = _paper(
        article_id="10.1016/example.conflict",
        source="crossref",
        doi="10.1016/example.conflict",
        work_type="review-article",
        oa_status="gold",
        container_title="Sleep Health",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        stats = db.insert_articles([second], dedupe=True)
        assert stats["merged"] == 1
        row = db.get_all_articles()[0]
        assert row["work_type"] == "journal-article"
        assert row["oa_status"] == "closed"
        assert row["container_title"] == "Sleep Health"
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert provenance["container_title"] == "crossref"
        assert provenance["conflicts"]["work_type"]["value"] == "review-article"
        assert provenance["conflicts"]["work_type"]["source"] == "crossref"
        assert provenance["conflicts"]["oa_status"]["value"] == "gold"
    finally:
        db.close()


def test_placeholder_journal_is_replaced_by_a_real_one(db_path):
    first = _paper(journal="OpenAIRE", doi="10.1016/example.journal")
    second = _paper(
        article_id="10.1016/example.journal",
        source="crossref",
        doi="10.1016/example.journal",
        journal="Labour / Le Travail",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        stats = db.insert_articles([second], dedupe=True)
        assert stats["merged"] == 1
        assert db.get_all_articles()[0]["journal"] == "Labour / Le Travail"
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert provenance["journal"] == "crossref"
    finally:
        db.close()


def test_staging_merge_and_swap_keep_notes_and_embeddings(db_path):
    live = _paper(doi="10.1016/example.stage", journal="Sleep Health")
    staged_openalex = _paper(doi="10.1016/example.stage", journal="Sleep Health")
    staged_crossref = _paper(
        article_id="10.1016/example.stage",
        source="crossref",
        doi="10.1016/example.stage",
        work_type="journal-article",
        container_title="Sleep Health",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([live], dedupe=True)
        db.upsert_note("W1", "openalex", note="keep me", starred=True)
        db.insert_embeddings(
            {("W1", "openalex"): np.ones(4, dtype=np.float32)},
            "general",
        )
        db.ensure_staging_articles()
        stats = db.insert_articles(
            [staged_openalex, staged_crossref], dedupe=True, staging=True
        )
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        assert stats["merged"] == 1
        assert db.count_staging_articles() == 1
        assert db.replace_from_staging() == 1
        row = db.get_article_by_id("W1", "openalex")
        assert row["work_type"] == "journal-article"
        assert row["container_title"] == "Sleep Health"
        note = db.get_note("W1", "openalex")
        assert note["note"] == "keep me"
        assert note["starred"] is True
        ids, embeddings = db.get_all_embeddings()
        assert ids == [("W1", "openalex")]
        assert embeddings.shape == (1, 4)
    finally:
        db.close()


def test_unicode_titles_match(db_path):
    first = _paper(title="Café study of widgets", doi=None)
    second = _paper(
        article_id="pmid-cafe",
        source="pubmed",
        title="Cafe study of widgets",
        doi=None,
        work_type="journal-article",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        assert stats["merged"] == 1
        japanese = _paper(
            article_id="W-jp",
            title="睡眠と健康の研究について",
            doi="10.1234/jp.merge",
        )
        other = _paper(
            article_id="10.1234/jp.merge",
            source="crossref",
            title="睡眠と健康の研究について",
            doi="10.1234/jp.merge",
            work_type="journal-article",
        )
        jp_stats = db.insert_articles([japanese, other], dedupe=True)
        assert jp_stats["inserted"] == 1
        assert jp_stats["skipped_duplicates"] == 1
        assert ArticleDatabase._norm_title("睡眠と健康の研究について")
    finally:
        db.close()


def test_stats_count_merged_or_identical(db_path):
    first = _paper(doi="10.1016/example.stats", work_type="journal-article")
    identical = _paper(
        article_id="10.1016/example.stats",
        source="crossref",
        doi="10.1016/example.stats",
        work_type="journal-article",
    )
    filling = _paper(
        article_id="10.1016/example.stats2",
        source="crossref",
        doi="10.1016/example.stats2",
        container_title="Sleep Health",
    )
    seed = _paper(
        article_id="W2",
        doi="10.1016/example.stats2",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        identical_stats = db.insert_articles([identical], dedupe=True)
        assert identical_stats["skipped_duplicates"] == 1
        assert identical_stats["merged"] == 0
        db.insert_articles([seed], dedupe=True)
        fill_stats = db.insert_articles([filling], dedupe=True)
        assert fill_stats["skipped_duplicates"] == 1
        assert fill_stats["merged"] == 1
    finally:
        db.close()


def test_notes_and_embeddings_on_existing_key_survive_merge(db_path):
    first = _paper(doi="10.1016/example.keep")
    second = _paper(
        article_id="10.1016/example.keep",
        source="crossref",
        doi="10.1016/example.keep",
        work_type="journal-article",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        db.upsert_note("W1", "openalex", note="student note", starred=True)
        db.insert_embeddings(
            {("W1", "openalex"): np.arange(4, dtype=np.float32)},
            "general",
        )
        db.insert_articles([second], dedupe=True)
        note = db.get_note("W1", "openalex")
        assert note["note"] == "student note"
        assert note["starred"] is True
        ids, embeddings = db.get_all_embeddings()
        assert ids == [("W1", "openalex")]
        np.testing.assert_array_equal(embeddings[0], np.arange(4, dtype=np.float32))
        assert db.get_article_by_id("W1", "openalex")["title"] == (
            "Widgets and sleep in adults"
        )
    finally:
        db.close()


def test_pipeline_forwards_merged_and_skipped_duplicate_counts(db_path, monkeypatch):
    first = _paper(doi="10.1016/example.pipe")
    second = _paper(
        article_id="10.1016/example.pipe",
        source="crossref",
        doi="10.1016/example.pipe",
        work_type="journal-article",
        container_title="Sleep Health",
    )

    class Crossref:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            return [dict(second)]

    monkeypatch.setitem(pipeline_mod.FETCHERS, "crossref", Crossref)
    pipe = LiteratureSearchPipeline(db_path=str(db_path))
    try:
        pipe.db.insert_articles([first], dedupe=True)
        result = pipe.fetch_articles_parallel("q", ["crossref"])
        assert result["crossref"]["skipped_duplicates"] == 1
        assert result["crossref"]["merged"] == 1
        assert result["crossref"]["count"] == 0
        assert len(pipe.db.get_all_articles()) == 1
    finally:
        pipe.db.close()
