"""Type chip on ranked hits, and the Search type filter before ranking."""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from app.services.pipeline import LiteratureSearchPipeline
from app.services.work_types import WORK_TYPE_NOT_STORED
from app.storage.database import (
    ARTICLE_COLUMNS,
    SEARCH_ARTICLE_COLUMNS,
    ArticleDatabase,
)


def _paper(article_id, source, title, abstract, work_type=None, year="2020"):
    article = {
        "article_id": article_id,
        "source": source,
        "title": title,
        "abstract": abstract,
        "year": year,
        "authors": [],
        "journal": "J",
    }
    if work_type is not None:
        article["work_type"] = work_type
    return article


def _seed(db: ArticleDatabase):
    db.insert_articles([
        _paper("a", "pubmed", "Zyptron gene expression", "The zyptron pathway in cells.",
               "journal-article"),
        _paper("b", "crossref", "A history of zyptron", "Book about the zyptron pathway.",
               "book"),
        _paper("c", "arxiv", "Zyptron preprint", "Early zyptron notes.", "preprint"),
        _paper("legacy", "pubmed", "Old zyptron paper", "Legacy abstract about zyptron."),
    ], dedupe=False)
    db.insert_embeddings(
        {
            ("a", "pubmed"): np.array([1.0, 0.0], dtype=np.float32),
            ("b", "crossref"): np.array([0.2, 0.98], dtype=np.float32),
            ("c", "arxiv"): np.array([0.5, 0.5], dtype=np.float32),
            ("legacy", "pubmed"): np.array([0.7, 0.3], dtype=np.float32),
        },
        model_name="general",
    )


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "types.db"))
    _seed(p.db)

    def fake_embed(query_text: str):
        return np.array([1.0, 0.0], dtype=np.float32)

    monkeypatch.setattr(p.embedding_engine, "embed_query", fake_embed)
    yield p
    p.db.close()


def _ids(rows):
    return [row["article_id"] for row in rows]


def _rank_shape(rows):
    out = []
    for row in rows:
        item = {
            "article_id": row["article_id"],
            "source": row["source"],
            "similarity_score": row.get("similarity_score"),
            "semantic_score": row.get("semantic_score"),
            "title": row.get("title"),
        }
        out.append(item)
    return out


def test_search_results_include_work_type_for_the_chip(pipe):
    rows = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    by_id = {row["article_id"]: row for row in rows}
    assert by_id["a"]["work_type"] == "journal-article"
    assert by_id["b"]["work_type"] == "book"
    assert by_id["c"]["work_type"] == "preprint"
    assert "work_type" not in by_id["legacy"]


def test_type_filter_narrows_candidates_before_ranking(pipe):
    unfiltered = pipe.search_similar("zyptron", top_k=1, lexical_boost=False)
    assert _ids(unfiltered) == ["a"]
    books = pipe.search_similar(
        "zyptron", top_k=1, lexical_boost=False, work_type_filter=["book"],
    )
    assert _ids(books) == ["b"]
    assert books[0]["work_type"] == "book"


def test_type_not_stored_keeps_legacy_rows(pipe):
    rows = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False,
        work_type_filter=[WORK_TYPE_NOT_STORED],
    )
    assert _ids(rows) == ["legacy"]
    assert "work_type" not in rows[0]


def test_no_type_filter_matches_omitted_and_empty_filter(pipe):
    omitted = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    none = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, work_type_filter=None,
    )
    empty = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, work_type_filter=[],
    )
    assert omitted == none == empty


def test_no_filter_ranking_is_byte_identical_without_the_chip_field(pipe):
    rows = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    stripped = []
    for row in rows:
        item = dict(row)
        item.pop("work_type", None)
        stripped.append(item)
    # Same papers, order, and scores as the pre-chip ranking payload.
    assert _ids(stripped) == ["a", "legacy", "c", "b"]
    dumped = json.dumps(stripped, sort_keys=True)
    again = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    again_stripped = []
    for row in again:
        item = dict(row)
        item.pop("work_type", None)
        again_stripped.append(item)
    assert json.dumps(again_stripped, sort_keys=True) == dumped
    assert _rank_shape(rows) == _rank_shape(again)


def test_selecting_every_present_type_matches_no_filter(pipe):
    unfiltered = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    filtered = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False,
        work_type_filter=["journal-article", "book", "preprint", WORK_TYPE_NOT_STORED],
    )
    assert _rank_shape(unfiltered) == _rank_shape(filtered)
    assert unfiltered == filtered


def test_top_k_work_types_use_one_batched_query(pipe, monkeypatch):
    calls = []
    original = ArticleDatabase.get_work_types_for_keys

    def wrapped(self, keys):
        calls.append(list(keys))
        return original(self, keys)

    monkeypatch.setattr(ArticleDatabase, "get_work_types_for_keys", wrapped)
    rows = pipe.search_similar("zyptron", top_k=3, lexical_boost=False)
    assert len(calls) == 1
    assert len(calls[0]) == len(rows) == 3
    src = inspect.getsource(original)
    assert src.count("cursor.execute") == 1
    assert "IN (" in src


def test_search_corpus_read_excludes_biblio_even_with_a_type_filter(pipe, monkeypatch):
    seen = []
    original = ArticleDatabase.get_all_articles_with_clusters

    def wrapped(self, columns=ARTICLE_COLUMNS):
        seen.append(tuple(columns))
        return original(self, columns=columns)

    monkeypatch.setattr(ArticleDatabase, "get_all_articles_with_clusters", wrapped)
    pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, work_type_filter=["book"],
    )
    assert seen
    assert all("biblio" not in columns for columns in seen)
    assert SEARCH_ARTICLE_COLUMNS == ARTICLE_COLUMNS[:7]
    assert "biblio" not in SEARCH_ARTICLE_COLUMNS
    assert "work_type" not in SEARCH_ARTICLE_COLUMNS
    type_src = inspect.getsource(ArticleDatabase.get_article_work_types)
    assert "biblio" not in type_src
    assert "SELECT article_id, source, work_type FROM articles" in type_src


def test_no_type_filter_skips_the_corpus_work_type_read(pipe, monkeypatch):
    calls = []
    original = ArticleDatabase.get_article_work_types

    def wrapped(self):
        calls.append(True)
        return original(self)

    monkeypatch.setattr(ArticleDatabase, "get_article_work_types", wrapped)
    pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    assert calls == []
    pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, work_type_filter=["book"],
    )
    assert calls == [True]


def test_work_type_counts_group_legacy_rows(pipe):
    counts = pipe.db.get_statistics()["work_type_counts"]
    assert counts["journal-article"] == 1
    assert counts["book"] == 1
    assert counts["preprint"] == 1
    assert counts[WORK_TYPE_NOT_STORED] == 1


def test_seed_and_starred_honor_the_type_filter(pipe):
    pipe.db.upsert_note("b", "crossref", starred=True)
    starred = pipe.search_from_starred(top_k=10, work_type_filter=["book"])
    assert _ids(starred["results"]) == ["b"]
    seeded = pipe.search_by_seed(
        "Zyptron gene", top_k=10, include_seed=True, work_type_filter=["journal-article"],
    )
    assert _ids(seeded["results"]) == ["a"]
