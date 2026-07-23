"""Year filter, hybrid ranking, and more-like-starred search."""

import numpy as np
import pytest

from app.services.pipeline import LiteratureSearchPipeline
from app.storage.database import ArticleDatabase


def _seed_three(db: ArticleDatabase):
    """Three papers with 2-d embeddings along simple axes."""
    articles = [
        {
            "article_id": "x",
            "source": "pubmed",
            "title": "Zyptron gene expression",
            "abstract": "The zyptron pathway in cells.",
            "year": "2020",
            "authors": [],
            "journal": "J",
        },
        {
            "article_id": "y",
            "source": "pubmed",
            "title": "General methods overview",
            "abstract": "Broad methodological review without the rare token.",
            "year": "2018",
            "authors": [],
            "journal": "J",
        },
        {
            "article_id": "z",
            "source": "arxiv",
            "title": "Unknown year paper",
            "abstract": "Something about zyptron as well.",
            "year": "Unknown",
            "authors": [],
            "journal": "J",
        },
    ]
    db.insert_articles(articles)
    # X near axis for "query" second, Y best pure embedding, Z unknown year.
    # Y slightly best for pure embedding; X second so lexical can flip order.
    db.insert_embeddings(
        {
            ("x", "pubmed"): np.array([0.95, 0.1], dtype=np.float32),
            ("y", "pubmed"): np.array([1.0, 0.0], dtype=np.float32),
            ("z", "arxiv"): np.array([0.5, 0.5], dtype=np.float32),
        },
        model_name="general",
    )


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "s.db"))
    _seed_three(p.db)

    def fake_embed(query_text: str):
        # Prefer the Y direction for pure semantic ranking.
        return np.array([1.0, 0.0], dtype=np.float32)

    monkeypatch.setattr(p.embedding_engine, "embed_query", fake_embed)
    yield p
    p.db.close()


def test_year_range_excludes_unknown(pipe):
    # No range: unknown year included.
    all_res = pipe.search_similar("methods", top_k=10, lexical_boost=False)
    ids = {a["article_id"] for a in all_res}
    assert "z" in ids

    # Range set: unknown year dropped; 2018 included, 2020 out of range.
    ranged = pipe.search_similar(
        "methods", top_k=10, year_min=2010, year_max=2019, lexical_boost=False,
    )
    ids = {a["article_id"] for a in ranged}
    assert "y" in ids
    assert "z" not in ids
    assert "x" not in ids


def test_year_bounds_inclusive(pipe):
    res = pipe.search_similar(
        "methods", top_k=10, year_min=2018, year_max=2020, lexical_boost=False,
    )
    ids = {a["article_id"] for a in res}
    assert ids == {"x", "y"}


def test_hybrid_boost_promotes_token_match(pipe):
    # Pure semantic: Y (embedding [1,0]) ranks first against query embed [1,0].
    pure = pipe.search_similar("zyptron pathway", top_k=2, lexical_boost=False)
    assert pure[0]["article_id"] == "y"

    # Hybrid: X contains rare token "zyptron" → should rise above Y.
    hybrid = pipe.search_similar("zyptron pathway", top_k=2, lexical_boost=True)
    assert hybrid[0]["article_id"] == "x"
    assert "lexical_score" in hybrid[0]


def test_starred_centroid_and_empty(pipe, tmp_path):
    empty_p = LiteratureSearchPipeline(db_path=str(tmp_path / "empty.db"))
    with pytest.raises(ValueError, match="Star some papers first"):
        empty_p.search_from_starred(top_k=5)
    empty_p.db.close()

    # Star X and Y; remaining embedded paper is Z.
    pipe.db.upsert_note("x", "pubmed", starred=True)
    pipe.db.upsert_note("y", "pubmed", starred=True)
    out = pipe.search_from_starred(top_k=5)
    assert out["seed_count"] == 2
    ids = [a["article_id"] for a in out["results"]]
    assert "x" not in ids and "y" not in ids
    assert ids[0] == "z"
