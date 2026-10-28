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
    assert ArticleDatabase._norm_title("Résumé of widgets") == "resume of widgets"
    assert ArticleDatabase._norm_title("Resume of widgets") == "resume of widgets"
    decomposed = "Re\u0301sume\u0301 of widgets"
    assert ArticleDatabase._norm_title(decomposed) == "resume of widgets"
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
        assert provenance["conflicts"]["work_type"][0]["value"] == "review-article"
        assert provenance["conflicts"]["work_type"][0]["source"] == "crossref"
        assert provenance["conflicts"]["oa_status"][0]["value"] == "gold"
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


SHARED_TITLE = "A detailed study of shared widgets"


def _conflict_pairs(provenance, field):
    return {
        (item["value"] if not isinstance(item["value"], list) else tuple(item["value"]),
         item["source"])
        for item in provenance["conflicts"][field]
    }


def _insert_sequence(db, first, batch, *, staging=False):
    if staging:
        db.ensure_staging_articles()
    db.insert_articles([first], dedupe=True, staging=staging)
    return db.insert_articles(batch, dedupe=True, staging=staging)


def _staging_rows(db):
    from app.storage.database import ARTICLE_COLUMNS, _row_to_article

    rows = db.conn.execute(
        f"SELECT {', '.join(ARTICLE_COLUMNS)} FROM staging_articles"
    ).fetchall()
    return [_row_to_article(row) for row in rows]


@pytest.mark.parametrize("staging", [False, True])
def test_same_key_refresh_does_not_overwrite_later_doi(db_path, staging):
    seed = _paper(
        article_id="A",
        title=SHARED_TITLE,
        year="2020",
        authors=["Jane Doe"],
        doi=None,
    )
    refresh = _paper(
        article_id="A",
        title=SHARED_TITLE,
        year="2020",
        authors=["Jane Doe"],
        doi="10.1000/one",
    )
    other = _paper(
        article_id="B",
        source="crossref",
        title=SHARED_TITLE,
        year="2020",
        authors=["Jane Doe"],
        doi="10.1000/two",
        oa_status="gold",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = _insert_sequence(db, seed, [refresh, other], staging=staging)
        rows = _staging_rows(db) if staging else db.get_all_articles()
        dois = {row["doi"] for row in rows}
        keys = {(row["article_id"], row["source"]) for row in rows}
        assert stats["updated"] == 1
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 0
        assert stats["merged"] == 0
        assert len(rows) == 2
        assert dois == {"10.1000/one", "10.1000/two"}
        assert keys == {("A", "openalex"), ("B", "crossref")}
    finally:
        db.close()


@pytest.mark.parametrize("staging", [False, True])
def test_same_key_refresh_keeps_nonempty_metadata_for_later_source(db_path, staging):
    seed = _paper(
        article_id="A",
        title=SHARED_TITLE,
        doi=None,
    )
    refresh = _paper(
        article_id="A",
        title=SHARED_TITLE,
        oa_status="closed",
        container_title="Sleep Health",
        doi="10.1000/one",
    )
    other = _paper(
        article_id="B",
        source="crossref",
        title=SHARED_TITLE,
        doi="10.1000/one",
        oa_status="gold",
        container_title="Other Journal",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = _insert_sequence(db, seed, [refresh, other], staging=staging)
        rows = _staging_rows(db) if staging else db.get_all_articles()
        assert stats["updated"] == 1
        assert stats["skipped_duplicates"] == 1
        assert len(rows) == 1
        row = rows[0]
        assert row["oa_status"] == "closed"
        assert row["container_title"] == "Sleep Health"
        assert row["doi"] == "10.1000/one"
        provenance = json.loads(_extra(db, "A", "openalex", staging=staging)[0])
        assert _conflict_pairs(provenance, "oa_status") == {("gold", "crossref")}
        assert _conflict_pairs(provenance, "container_title") == {
            ("Other Journal", "crossref")
        }
    finally:
        db.close()


def test_pubmed_surname_initials_match_given_surname(db_path):
    from app.fetchers.pubmed import PubMedFetcher

    formatted = PubMedFetcher._authors(
        {"AuthorList": [{"LastName": "Doe", "Initials": "J"}]}
    )
    assert formatted == ["Doe J"]
    first = _paper(authors=["Jane Doe"], doi=None)
    second = _paper(
        article_id="pmid-1",
        source="pubmed",
        authors=formatted,
        doi=None,
        work_type="journal-article",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        assert stats["merged"] == 1
        assert len(db.get_all_articles()) == 1
    finally:
        db.close()


def test_different_surnames_same_initial_stay_two_rows(db_path):
    first = _paper(authors=["Smith J"], doi="10.1000/one")
    second = _paper(
        article_id="B",
        source="pubmed",
        authors=["Jones J"],
        doi=None,
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert stats["skipped_duplicates"] == 0
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_same_surname_conflicting_given_names_stay_two_rows(db_path):
    first = _paper(authors=["Jane Smith"], doi="10.1000/one")
    second = _paper(
        article_id="B",
        source="pubmed",
        authors=["Robert Smith"],
        doi=None,
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_legacy_journal_conflict_blocks_title_merge(db_path):
    first = _paper(
        article_id="A",
        title=SHARED_TITLE,
        doi="10.1000/book",
        journal="History Journal",
    )
    second = _paper(
        article_id="B",
        source="crossref",
        title=SHARED_TITLE,
        doi=None,
        journal="Literary Review",
        container_title="Literary Review",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert stats["merged"] == 0
        rows = db.get_all_articles()
        assert len(rows) == 2
        book = next(row for row in rows if row["article_id"] == "A")
        assert book["journal"] == "History Journal"
    finally:
        db.close()


@pytest.mark.parametrize("book_first", [True, False])
def test_book_versus_review_stays_two_rows_both_orders(db_path, book_first):
    book = _paper(
        article_id="A",
        title=SHARED_TITLE,
        doi="10.1000/book",
        authors=["Jane Doe"],
        work_type="book",
    )
    review = _paper(
        article_id="B",
        source="crossref",
        title=SHARED_TITLE,
        doi=None,
        authors=[],
        journal="",
        work_type="review-article",
    )
    incoming = [book, review] if book_first else [review, book]
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles(incoming, dedupe=True)
        assert stats["inserted"] == 2
        assert stats["skipped_duplicates"] == 0
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


@pytest.mark.parametrize(
    "left_type,right_type",
    [
        ("book", "book-chapter"),
        ("preprint", "journal-article"),
        ("dataset", "article"),
    ],
)
def test_incompatible_work_types_stay_two_rows(db_path, left_type, right_type):
    first = _paper(work_type=left_type, doi="10.1000/left")
    second = _paper(
        article_id="B",
        source="crossref",
        work_type=right_type,
        doi=None,
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 2
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


@pytest.mark.parametrize(
    "title",
    ["Chapter One", "Chapter I", "Einleitung", "Sleep Health"],
)
@pytest.mark.parametrize("doi_first", [True, False])
def test_generic_titles_do_not_merge_with_one_doi(db_path, title, doi_first):
    with_doi = _paper(
        article_id="A",
        title=title,
        doi="10.1000/generic",
        authors=["Jane Doe"],
        year="2020",
    )
    without_doi = _paper(
        article_id="B",
        source="crossref",
        title=title,
        doi=None,
        authors=["Jane Doe"],
        year="2020",
    )
    incoming = [with_doi, without_doi] if doi_first else [without_doi, with_doi]
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles(incoming, dedupe=True)
        assert stats["inserted"] == 2
        assert stats["skipped_duplicates"] == 0
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_empty_year_and_authors_are_filled(db_path):
    first = _paper(doi="10.1016/example.year", year="", authors=[])
    second = _paper(
        article_id="10.1016/example.year",
        source="crossref",
        doi="10.1016/example.year",
        year="2020",
        authors=["Jane Doe"],
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        stats = db.insert_articles([second], dedupe=True)
        assert stats["merged"] == 1
        row = db.get_all_articles()[0]
        assert row["year"] == "2020"
        assert row["authors"] == ["Jane Doe"]
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert provenance["year"] == "crossref"
        assert provenance["authors"] == "crossref"
    finally:
        db.close()


def test_populated_year_and_authors_are_kept(db_path):
    first = _paper(
        doi="10.1016/example.year2",
        year="2019",
        authors=["Ada Lovelace"],
    )
    second = _paper(
        article_id="10.1016/example.year2",
        source="crossref",
        doi="10.1016/example.year2",
        year="2020",
        authors=["Jane Doe"],
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        stats = db.insert_articles([second], dedupe=True)
        row = db.get_all_articles()[0]
        assert stats["skipped_duplicates"] == 1
        assert row["year"] == "2019"
        assert row["authors"] == ["Ada Lovelace"]
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert _conflict_pairs(provenance, "year") == {("2020", "crossref")}
        assert _conflict_pairs(provenance, "authors") == {(("Jane Doe",), "crossref")}
    finally:
        db.close()


def test_internal_accents_and_non_latin_titles_match_without_doi(db_path):
    first = _paper(title="Résumé of widgets in adults", doi=None)
    second = _paper(
        article_id="pmid-resume",
        source="pubmed",
        title="Resume of widgets in adults",
        doi=None,
        work_type="journal-article",
    )
    japanese = _paper(
        article_id="W-jp",
        title="睡眠と健康の研究について",
        doi=None,
    )
    other = _paper(
        article_id="jp-2",
        source="pubmed",
        title="睡眠と健康の研究について",
        doi=None,
        work_type="journal-article",
    )
    db = ArticleDatabase(str(db_path))
    try:
        stats = db.insert_articles([first, second], dedupe=True)
        assert stats["inserted"] == 1
        assert stats["skipped_duplicates"] == 1
        jp_stats = db.insert_articles([japanese, other], dedupe=True)
        assert jp_stats["inserted"] == 1
        assert jp_stats["skipped_duplicates"] == 1
        assert len(db.get_all_articles()) == 2
    finally:
        db.close()


def test_three_source_conflicts_keep_every_alternative(db_path):
    first = _paper(doi="10.1016/example.oa", oa_status="closed")
    gold = _paper(
        article_id="10.1016/example.oa",
        source="crossref",
        doi="10.1016/example.oa",
        oa_status="gold",
    )
    hybrid = _paper(
        article_id="10.1016/example.oa",
        source="pubmed",
        doi="10.1016/example.oa",
        oa_status="hybrid",
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        db.insert_articles([gold], dedupe=True)
        stats = db.insert_articles([hybrid], dedupe=True)
        assert stats["skipped_duplicates"] == 1
        row = db.get_all_articles()[0]
        assert row["oa_status"] == "closed"
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert _conflict_pairs(provenance, "oa_status") == {
            ("gold", "crossref"),
            ("hybrid", "pubmed"),
        }
    finally:
        db.close()


def test_biblio_provenance_is_per_leaf(db_path):
    first = _paper(
        doi="10.1016/example.biblio",
        biblio={"publisher": "OpenAlex Press"},
        _extra={"provenance": {"biblio.publisher": "openalex"}},
    )
    second = _paper(
        article_id="10.1016/example.biblio",
        source="crossref",
        doi="10.1016/example.biblio",
        biblio={"publisher": "OpenAlex Press", "issue": "3"},
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        stats = db.insert_articles([second], dedupe=True)
        assert stats["merged"] == 1
        row = db.get_all_articles()[0]
        biblio = json.loads(row["biblio"]) if isinstance(row["biblio"], str) else row["biblio"]
        assert biblio["publisher"] == "OpenAlex Press"
        assert biblio["issue"] == "3"
        provenance = json.loads(_extra(db, "W1", "openalex")[0])
        assert provenance["biblio.publisher"] == "openalex"
        assert provenance["biblio.issue"] == "crossref"
        assert provenance.get("biblio") != "crossref"
    finally:
        db.close()


def test_new_location_counts_as_merged(db_path):
    first = _paper(doi="10.1016/example.loc")
    filling = _paper(
        article_id="10.1016/example.loc",
        source="crossref",
        doi="10.1016/example.loc",
        _extra={"locations": [{"url": "https://example.org/pdf", "kind": "pdf"}]},
    )
    repeat = _paper(
        article_id="10.1016/example.loc",
        source="pubmed",
        doi="10.1016/example.loc",
        _extra={"locations": [{"url": "https://example.org/pdf", "kind": "pdf"}]},
    )
    db = ArticleDatabase(str(db_path))
    try:
        db.insert_articles([first], dedupe=True)
        filled = db.insert_articles([filling], dedupe=True)
        assert filled["skipped_duplicates"] == 1
        assert filled["merged"] == 1
        again = db.insert_articles([repeat], dedupe=True)
        assert again["skipped_duplicates"] == 1
        assert again["merged"] == 0
        _prov, locations = _extra(db, "W1", "openalex")
        assert json.loads(locations)[0]["url"] == "https://example.org/pdf"
    finally:
        db.close()


def test_run_multi_fetch_forwards_merge_counts(db_path, monkeypatch):
    from app.routes import corpus as corpus_mod
    from app.storage import quota

    first = _paper(doi="10.1016/example.route")
    second = _paper(
        article_id="10.1016/example.route",
        source="crossref",
        doi="10.1016/example.route",
        container_title="Sleep Health",
    )

    class Crossref:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            return [dict(second)]

    monkeypatch.setitem(pipeline_mod.FETCHERS, "crossref", Crossref)
    monkeypatch.setattr(corpus_mod, "update_progress", lambda *a, **k: None)
    monkeypatch.setattr(corpus_mod, "is_job_cancelled", lambda *a, **k: False)
    monkeypatch.setattr(quota, "is_over_quota", lambda *_a, **_k: False)
    monkeypatch.setattr(
        quota,
        "usage_report",
        lambda *_a, **_k: {
            "used_mb": 0.0,
            "limit_mb": 0,
            "percent": 0.0,
            "over_limit": False,
        },
    )
    pipe = LiteratureSearchPipeline(db_path=str(db_path))
    try:
        pipe.db.insert_articles([first], dedupe=True)
        result = corpus_mod._run_multi_fetch(
            pipe,
            query="q",
            sources=["crossref"],
            max_results=5,
            email=None,
            clear_first=False,
            uid="merge-route",
            lib_id="L1",
        )
        assert result["total_fetched"] == 0
        assert result["by_source"]["crossref"] == 0
        assert result["inserted"]["crossref"] == 0
        assert result["merged"]["crossref"] == 1
        assert result["skipped_duplicates"]["crossref"] == 1
        assert result["errors"] == {}
        assert len(pipe.db.get_all_articles()) == 1
        assert pipe.db.get_all_articles()[0]["container_title"] == "Sleep Health"
    finally:
        pipe.db.close()
