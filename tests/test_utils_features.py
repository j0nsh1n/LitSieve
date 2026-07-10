"""Unit tests for year sort, source priority, coverage, notes, seed lookup."""

import numpy as np
import pytest

from database import ArticleDatabase
from utils import (
    parse_year,
    sort_articles,
    duplicate_quality_key,
    coverage_suggestions,
    build_cluster_briefing,
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
