"""Access chip on ranked hits, and the Free to read filter before ranking."""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from app.services.access import NONE_LISTED, OPEN_LISTED
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.database import (
    ARTICLE_COLUMNS,
    SEARCH_ARTICLE_COLUMNS,
    ArticleDatabase,
)


def _paper(article_id, source, title, abstract, **kwargs):
    article = {
        "article_id": article_id,
        "source": source,
        "title": title,
        "abstract": abstract,
        "year": kwargs.pop("year", "2020"),
        "authors": [],
        "journal": "J",
    }
    article.update(kwargs)
    return article


def _seed(db: ArticleDatabase):
    db.insert_articles([
        _paper(
            "a", "openalex", "Zyptron gene expression",
            "The zyptron pathway in cells.",
            oa_status="gold",
            best_oa_url="https://example.org/a.pdf",
        ),
        _paper(
            "b", "crossref", "A history of zyptron",
            "Book about the zyptron pathway.",
            _extra={"locations": [{
                "url": "https://api.elsevier.com/content/article/doi/10",
                "kind": "text-mining",
                "via": "crossref",
            }]},
        ),
        _paper(
            "c", "doaj", "Zyptron preprint",
            "Early zyptron notes.",
            _extra={"locations": [{
                "url": "https://example.org/c.pdf",
                "kind": "fulltext",
                "via": "doaj",
            }]},
        ),
        _paper(
            "legacy", "pubmed", "Old zyptron paper",
            "Legacy abstract about zyptron.",
        ),
    ], dedupe=False)
    db.insert_embeddings(
        {
            ("a", "openalex"): np.array([1.0, 0.0], dtype=np.float32),
            ("b", "crossref"): np.array([0.2, 0.98], dtype=np.float32),
            ("c", "doaj"): np.array([0.5, 0.5], dtype=np.float32),
            ("legacy", "pubmed"): np.array([0.7, 0.3], dtype=np.float32),
        },
        model_name="general",
    )


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "access.db"))
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
        out.append({
            "article_id": row["article_id"],
            "source": row["source"],
            "similarity_score": row.get("similarity_score"),
            "semantic_score": row.get("semantic_score"),
            "title": row.get("title"),
        })
    return out


def test_search_results_include_access_for_the_chip(pipe):
    rows = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    by_id = {row["article_id"]: row for row in rows}
    assert by_id["a"]["access"]["state"] == OPEN_LISTED
    assert by_id["a"]["access"]["url"] == "https://example.org/a.pdf"
    assert by_id["b"]["access"]["state"] == NONE_LISTED
    assert "url" not in by_id["b"]["access"]
    assert by_id["b"]["access"]["sources"] == ["CrossRef"]
    assert by_id["c"]["access"]["state"] == OPEN_LISTED
    assert by_id["c"]["access"]["url"] == "https://example.org/c.pdf"
    assert by_id["legacy"]["access"]["state"] == NONE_LISTED
    assert "url" not in by_id["legacy"]["access"]
    assert by_id["legacy"]["access"]["sources"] == ["PubMed"]
    assert all("_extra" not in row for row in rows)


def test_free_to_read_narrows_candidates_before_ranking(pipe):
    unfiltered = pipe.search_similar("zyptron", top_k=1, lexical_boost=False)
    assert _ids(unfiltered) == ["a"]
    listed = pipe.search_similar(
        "zyptron", top_k=1, lexical_boost=False, free_to_read=True,
    )
    assert _ids(listed) == ["a"]
    listed_all = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=True,
    )
    assert _ids(listed_all) == ["a", "c"]
    assert all(row["access"]["state"] == OPEN_LISTED for row in listed_all)


def test_closed_multi_source_keeps_all_display_names(pipe):
    pipe.db.insert_articles([
        _paper(
            "merged", "openalex", "Closed zyptron review",
            "A closed zyptron paper listed by two sources.",
            oa_status="closed",
            _extra={"locations": [
                {"url": "https://doi.org/10.0/merged", "via": "openalex"},
                {
                    "url": "https://api.elsevier.com/content/article/doi/10",
                    "kind": "text-mining",
                    "via": "crossref",
                },
            ]},
        ),
    ], dedupe=False)
    pipe.db.insert_embeddings(
        {("merged", "openalex"): np.array([0.95, 0.05], dtype=np.float32)},
        model_name="general",
    )
    rows = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    access = {row["article_id"]: row for row in rows}["merged"]["access"]
    assert access["state"] == NONE_LISTED
    assert "url" not in access
    assert access["sources"] == ["OpenAlex", "CrossRef"]
    listed = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=True,
    )
    assert "merged" not in _ids(listed)


def test_crossref_unlicensed_links_are_dropped_by_the_filter(pipe):
    rows = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=True,
    )
    assert "b" not in _ids(rows)
    assert "legacy" not in _ids(rows)


def test_no_free_to_read_matches_omitted_and_false(pipe):
    omitted = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    none = pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=False,
    )
    assert omitted == none


def test_no_filter_ranking_is_byte_identical_without_the_chip_field(pipe):
    rows = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    stripped = []
    for row in rows:
        item = dict(row)
        item.pop("access", None)
        item.pop("work_type", None)
        stripped.append(item)
    assert _ids(stripped) == ["a", "legacy", "c", "b"]
    dumped = json.dumps(stripped, sort_keys=True)
    again = pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    again_stripped = []
    for row in again:
        item = dict(row)
        item.pop("access", None)
        item.pop("work_type", None)
        again_stripped.append(item)
    assert json.dumps(again_stripped, sort_keys=True) == dumped
    assert _rank_shape(rows) == _rank_shape(again)


def test_top_k_access_fields_use_one_batched_query(pipe, monkeypatch):
    calls = []
    original = ArticleDatabase.get_access_fields_for_keys

    def wrapped(self, keys):
        calls.append(list(keys))
        return original(self, keys)

    monkeypatch.setattr(ArticleDatabase, "get_access_fields_for_keys", wrapped)
    rows = pipe.search_similar("zyptron", top_k=3, lexical_boost=False)
    assert len(calls) == 1
    assert len(calls[0]) == len(rows) == 3
    src = inspect.getsource(original)
    assert src.count("cursor.execute") == 1
    assert "IN (" in src


def test_search_corpus_read_excludes_biblio_even_with_free_to_read(pipe, monkeypatch):
    seen = []
    original = ArticleDatabase.get_all_articles_with_clusters

    def wrapped(self, columns=ARTICLE_COLUMNS):
        seen.append(tuple(columns))
        return original(self, columns=columns)

    monkeypatch.setattr(ArticleDatabase, "get_all_articles_with_clusters", wrapped)
    pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=True,
    )
    assert seen
    assert all("biblio" not in columns for columns in seen)
    assert SEARCH_ARTICLE_COLUMNS == ARTICLE_COLUMNS[:7]
    assert "biblio" not in SEARCH_ARTICLE_COLUMNS
    assert "oa_status" not in SEARCH_ARTICLE_COLUMNS
    access_src = inspect.getsource(ArticleDatabase.get_article_access_fields)
    assert "biblio" not in access_src
    assert "oa_status" in access_src
    assert "article_extra" in access_src


def test_no_free_to_read_skips_the_corpus_access_read(pipe, monkeypatch):
    calls = []
    original = ArticleDatabase.get_article_access_fields

    def wrapped(self):
        calls.append(True)
        return original(self)

    monkeypatch.setattr(ArticleDatabase, "get_article_access_fields", wrapped)
    pipe.search_similar("zyptron", top_k=10, lexical_boost=False)
    assert calls == []
    pipe.search_similar(
        "zyptron", top_k=10, lexical_boost=False, free_to_read=True,
    )
    assert calls == [True]


def test_seed_and_starred_honor_free_to_read(pipe):
    pipe.db.upsert_note("c", "doaj", starred=True)
    starred = pipe.search_from_starred(top_k=10, free_to_read=True)
    assert _ids(starred["results"]) == ["c", "a"]
    seeded = pipe.search_by_seed(
        "Zyptron gene", top_k=10, include_seed=True, free_to_read=True,
    )
    assert _ids(seeded["results"]) == ["a", "c"]
    closed = pipe.search_by_seed(
        "history of zyptron", top_k=10, include_seed=True, free_to_read=True,
    )
    assert _ids(closed["results"]) == ["a", "c"]
