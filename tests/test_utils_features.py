"""Unit tests for year sort, source priority, coverage, notes, seed lookup."""

import numpy as np

from database import ArticleDatabase
from utils import (
    build_cluster_briefing,
    build_screening_report,
    coverage_suggestions,
    duplicate_quality_key,
    format_screening_report_txt,
    parse_year,
    sort_articles,
)


def test_parse_year_numeric_and_unknown():
    assert parse_year("2024") == 2024
    assert parse_year("Published 2019-06") == 2019
    assert parse_year("Unknown") == 0
    assert parse_year("") == 0
    assert parse_year(None) == 0


def test_sort_articles_year_newest_first_unknowns_last():
    rows = [
        {"title": "a", "year": "Unknown"},
        {"title": "b", "year": "2018"},
        {"title": "c", "year": "2022"},
        {"title": "d", "year": ""},
    ]
    sort_articles(rows, "year")
    # Newest first
    assert rows[0]["year"] == "2022"
    assert rows[1]["year"] == "2018"
    # Unknowns sink to the bottom
    assert parse_year(rows[2]["year"]) == 0
    assert parse_year(rows[3]["year"]) == 0


def test_duplicate_quality_prefers_longer_abstract_then_source():
    short_pubmed = {"abstract": "short"}
    long_zenodo = {"abstract": "a much longer abstract body"}
    # Longer abstract wins even if source rank is lower.
    assert duplicate_quality_key(long_zenodo, ("2", "zenodo")) > \
        duplicate_quality_key(short_pubmed, ("1", "pubmed"))
    # Equal length → pubmed beats zenodo.
    a = {"abstract": "same length abstract!!"}
    b = {"abstract": "same length abstract!!"}
    assert duplicate_quality_key(a, ("1", "pubmed")) > \
        duplicate_quality_key(b, ("2", "zenodo"))


def test_coverage_suggestions_missing_sources():
    tips = coverage_suggestions({"openalex": 3}, ["education"])
    missing = {t["source"] for t in tips}
    assert "eric" in missing  # education usually wants ERIC
    assert "openalex" not in missing


def test_cluster_briefing_year_span():
    b = build_cluster_briefing(
        0, "Climate, Warming",
        ["Paper A", "Paper B"],
        ["2010", "2020", "Unknown"],
        2,
        representative_title="Paper A",
    )
    assert b["year_span"] == "2010-2020"
    assert b["bullets"][0] == "Paper A"


def test_notes_and_seed_lookup(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "t.db"))
    db.insert_articles([{
        "article_id": "10.1234/abc",
        "source": "crossref",
        "title": "Ocean Warming Trends",
        "abstract": "Seas are warming rapidly.",
        "year": "2021",
        "authors": ["Ada"],
        "journal": "Nature",
    }])
    note = db.upsert_note("10.1234/abc", "crossref", note="read this", starred=True)
    assert note["starred"] is True
    assert db.get_note("10.1234/abc", "crossref")["note"] == "read this"

    found = db.find_article_by_seed("Ocean Warming")
    assert found and found["article_id"] == "10.1234/abc"
    found2 = db.find_article_by_seed("10.1234/abc")
    assert found2 and found2["source"] == "crossref"

    rows = db.get_library_export_rows(scope="starred")
    assert len(rows) == 1
    assert rows[0]["exclusion_reason"] == ""
    db.close()


def test_embedding_status_missing_count(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "e.db"))
    db.insert_articles([
        {"article_id": "1", "source": "pubmed", "title": "T", "abstract": "A",
         "year": "2020", "authors": [], "journal": "J"},
        {"article_id": "2", "source": "pubmed", "title": "U", "abstract": "B",
         "year": "2021", "authors": [], "journal": "J"},
    ])
    db.insert_embeddings({
        ("1", "pubmed"): np.array([1.0, 0.0], dtype=np.float32),
    }, model_name="general")
    st = db.get_embedding_status()
    assert st["total_articles"] == 2
    assert st["with_embeddings"] == 1
    assert st["missing_embeddings"] == 1
    assert st["model"] == "general"
    db.close()


def test_screening_report_empty_and_seeded(tmp_path):
    empty = ArticleDatabase(db_path=str(tmp_path / "empty.db"))
    er = build_screening_report(empty)
    assert er["total_articles"] == 0
    assert er["by_source"] == {}
    assert er["with_embeddings"] == 0
    assert er["excluded"]["total"] == 0
    assert er["excluded"]["duplicate"] == 0
    assert er["excluded"]["cluster"] == 0
    assert er["excluded"]["manual"] == 0
    assert er["included"] == 0
    assert er["starred"] == 0
    assert er["clusters"] == 0
    empty.close()

    db = ArticleDatabase(db_path=str(tmp_path / "report.db"))
    articles = []
    for i in range(4):
        articles.append({
            "article_id": str(i + 1),
            "source": "pubmed",
            "title": f"P{i}",
            "abstract": "A",
            "year": "2020",
            "authors": [],
            "journal": "J",
        })
    for i in range(2):
        articles.append({
            "article_id": str(i + 10),
            "source": "arxiv",
            "title": f"A{i}",
            "abstract": "B",
            "year": "2021",
            "authors": [],
            "journal": "J",
        })
    db.insert_articles(articles)
    db.insert_embeddings({
        ("1", "pubmed"): np.array([1.0, 0.0], dtype=np.float32),
        ("2", "pubmed"): np.array([0.0, 1.0], dtype=np.float32),
    }, model_name="general")
    db.exclude_articles([("1", "pubmed")], reason="duplicate")
    db.exclude_articles([("2", "pubmed")], reason="cluster")
    db.exclude_articles([("3", "pubmed")], reason="manual")
    db.upsert_note("4", "pubmed", note="keep", starred=True)
    # Two real clusters + noise (-1)
    db.insert_clusters(
        {
            ("1", "pubmed"): (0, "Theme A"),
            ("2", "pubmed"): (0, "Theme A"),
            ("3", "pubmed"): (1, "Theme B"),
            ("10", "arxiv"): (-1, "Noise"),
        },
        cluster_titles={0: "P0", 1: "P2", -1: "A0"},
    )

    r = build_screening_report(db)
    assert r["total_articles"] == 6
    assert r["by_source"] == {"pubmed": 4, "arxiv": 2}
    assert r["with_embeddings"] == 2
    assert r["excluded"]["duplicate"] == 1
    assert r["excluded"]["cluster"] == 1
    assert r["excluded"]["manual"] == 1
    assert r["excluded"]["total"] == 3
    assert r["included"] == 3
    assert r["starred"] == 1
    assert r["clusters"] == 2

    txt = format_screening_report_txt(r)
    assert "SCREENING REPORT - 6 papers collected" in txt
    assert "Duplicates removed (kept best copy): 1" in txt
    assert "Excluded as cluster triage: 1" in txt
    assert "Excluded (Manual): 1" in txt
    assert "INCLUDED in final set: 3" in txt
    assert "Starred: 1" in txt
    assert "With embeddings: 2" in txt
    assert "Clusters (excl. noise): 2" in txt
    db.close()
