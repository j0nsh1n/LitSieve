"""Narrow it down checks stored work_type (P2.7)."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.pipeline import LiteratureSearchPipeline


def _paper(article_id, title, abstract, work_type=None, source="pubmed"):
    article = {
        "article_id": article_id,
        "source": source,
        "title": title,
        "abstract": abstract,
        "year": "2020",
        "authors": [],
        "journal": "J",
    }
    if work_type is not None:
        article["work_type"] = work_type
    return article


def _ids(rows):
    return [row["article_id"] for row in rows]


def _keys(rows):
    return {(row["article_id"], row["source"]) for row in rows}


def _vec(x, y):
    return np.array([x, y], dtype=np.float32)


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "narrow-type.db"))
    p.db.insert_articles(
        [
            _paper("ja", "Sleep in teens", "School start times and sleep."),
            _paper("review", "A book review", "Review of a sleep monograph.", "book-review"),
            _paper("trial", "NCT sleep trial", "Registry record of a sleep trial.", "registry-record"),
            _paper("nulltype", "Untyped sleep paper", "Abstract about adolescent sleep."),
            _paper("book_abs", "Sleep book", "A book with an abstract about sleep.", "book"),
            _paper("chapter", "Sleep chapter", "", "book-chapter"),
            _paper("edited", "Edited sleep book", "   ", "edited-book"),
            _paper("book_empty", "Silent sleep book", "", "book"),
        ],
        dedupe=False,
    )
    p.db.insert_embeddings(
        {
            ("ja", "pubmed"): _vec(1.0, 0.0),
            ("review", "pubmed"): _vec(0.5, 0.5),
            ("trial", "pubmed"): _vec(0.4, 0.6),
            ("nulltype", "pubmed"): _vec(0.2, 0.8),
            ("book_abs", "pubmed"): _vec(0.15, 0.85),
            ("chapter", "pubmed"): _vec(0.05, 0.9),
            ("edited", "pubmed"): _vec(0.02, 0.95),
            ("book_empty", "pubmed"): _vec(0.0, 1.0),
        },
        model_name="general",
    )
    monkeypatch.setattr(
        p.embedding_engine,
        "embed_query",
        lambda _t: _vec(1.0, 0.0),
    )
    yield p
    p.close()


def test_book_without_abstract_is_kept_not_proposed(pipe):
    before = set(pipe.db.get_excluded_keys())
    result = pipe.propose_low_relevance("How do school start times affect sleep?", fraction=0.25)
    assert set(pipe.db.get_excluded_keys()) == before
    assert result["total_ranked"] == 8
    assert result["proposed_count"] == 2
    assert set(_ids(result["kept_no_abstract"])) == {"book_empty", "edited", "chapter"}
    assert "book_empty" not in _ids(result["candidates"])
    assert "chapter" not in _ids(result["candidates"])
    assert "edited" not in _ids(result["candidates"])
    assert _keys(result["kept_no_abstract"]).isdisjoint(_keys(result["candidates"]))
    assert _keys(result["kept_no_abstract"]).isdisjoint(_keys(result["staying"]))


def test_book_with_abstract_is_ranked_normally(pipe):
    result = pipe.propose_low_relevance("How do school start times affect sleep?", fraction=0.25)
    assert "book_abs" in _ids(result["candidates"])
    assert "book_abs" not in _ids(result["kept_no_abstract"])


def test_null_types_match_today(pipe, tmp_path, monkeypatch):
    untyped = LiteratureSearchPipeline(db_path=str(tmp_path / "narrow-untyped.db"))
    try:
        arts = [
            _paper(str(i), f"Title {i}", f"abstract {i}")
            for i in range(8)
        ]
        untyped.db.insert_articles(arts, dedupe=False)
        untyped.db.insert_embeddings(
            {(str(i), "pubmed"): np.eye(8, dtype=np.float32)[i] for i in range(8)},
            model_name="general",
        )
        monkeypatch.setattr(
            untyped.embedding_engine,
            "embed_query",
            lambda _t: np.eye(8, dtype=np.float32)[0],
        )
        before = set(untyped.db.get_excluded_keys())
        result = untyped.propose_low_relevance("diabetes adolescents", fraction=0.25)
        assert set(untyped.db.get_excluded_keys()) == before
        assert result["kept_no_abstract"] == []
        assert result["optional_type_aside"] == []
        assert result["total_ranked"] == 8
        assert result["proposed_count"] >= 1
        assert result["proposed_count"] < 8
        assert len(result["staying"]) == result["total_ranked"] - result["proposed_count"]
        assert "0" not in _ids(result["candidates"])
    finally:
        untyped.close()


def test_optional_type_list_and_apply_flag(pipe):
    result = pipe.propose_low_relevance("How do school start times affect sleep?", fraction=0.25)
    optional_ids = set(_ids(result["optional_type_aside"]))
    assert optional_ids == {"review", "trial"}
    assert optional_ids.isdisjoint(set(_ids(result["candidates"])))
    assert optional_ids <= set(_ids(result["staying"]))

    high = pipe.propose_low_relevance("How do school start times affect sleep?", fraction=0.50)
    assert "review" in _ids(high["candidates"]) or "trial" in _ids(high["candidates"])
    proposed = set(_ids(high["candidates"]))
    assert set(_ids(high["optional_type_aside"])).isdisjoint(proposed)

    cand_keys = [(c["article_id"], c["source"]) for c in result["candidates"]]
    opt_keys = [(c["article_id"], c["source"]) for c in result["optional_type_aside"]]
    pipe.db.exclude_articles(cand_keys, reason="low_relevance")
    excluded = set(pipe.db.get_excluded_keys())
    assert set(cand_keys) <= excluded
    assert set(opt_keys).isdisjoint(excluded)

    pipe.db.exclude_articles(opt_keys, reason="low_relevance")
    excluded = set(pipe.db.get_excluded_keys())
    assert set(opt_keys) <= excluded
    pipe.db.include_articles(opt_keys + cand_keys)
    assert set(pipe.db.get_excluded_keys()) == set()
