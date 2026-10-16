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


def test_year_range_lists_undated_papers_last(pipe):
    # No range: unknown year included, in rank order, with no group flag.
    all_res = pipe.search_similar("methods", top_k=10, lexical_boost=False)
    ids = {a["article_id"] for a in all_res}
    assert "z" in ids
    assert not any("no_year" in a for a in all_res)

    # Range set: 2018 in, 2020 out, and the undated paper stays visible in
    # its own group after the dated results (decided 2026-10-16, audit 19.16).
    ranged = pipe.search_similar(
        "methods", top_k=10, year_min=2010, year_max=2019, lexical_boost=False,
    )
    assert [a["article_id"] for a in ranged] == ["y", "z"]
    assert [a["no_year"] for a in ranged] == [False, True]


def test_year_bounds_inclusive(pipe):
    res = pipe.search_similar(
        "methods", top_k=10, year_min=2018, year_max=2020, lexical_boost=False,
    )
    dated = {a["article_id"] for a in res if not a["no_year"]}
    assert dated == {"x", "y"}
    assert res[-1]["article_id"] == "z"


def test_undated_group_stays_last_after_the_pico_boost(pipe):
    from app.services.enrich import apply_pico_boost

    res = pipe.search_similar(
        "zyptron pathway", top_k=10, year_min=2010, year_max=2030, lexical_boost=False,
    )
    res[-1]["pico"] = {"population": ["zyptron pathway zyptron"]}
    apply_pico_boost(res, "zyptron pathway")
    assert res[-1]["article_id"] == "z"
    assert res[-1]["no_year"] is True


def test_hybrid_boost_promotes_token_match(pipe):
    # Pure semantic: Y (embedding [1,0]) ranks first against query embed [1,0].
    pure = pipe.search_similar("zyptron pathway", top_k=2, lexical_boost=False)
    assert pure[0]["article_id"] == "y"

    # Hybrid: X contains rare token "zyptron" → should rise above Y.
    hybrid = pipe.search_similar("zyptron pathway", top_k=2, lexical_boost=True)
    assert hybrid[0]["article_id"] == "x"
    assert "lexical_score" in hybrid[0]


def test_the_shown_score_is_the_score_the_list_is_sorted_by(pipe):
    res = pipe.search_similar("zyptron pathway", top_k=3, lexical_boost=True)
    scores = [a["similarity_score"] for a in res]
    assert scores == sorted(scores, reverse=True)
    for a in res:
        blend = 0.7 * a["semantic_score"] + 0.3 * a["lexical_score"]
        assert a["similarity_score"] == pytest.approx(blend, abs=1e-3)


def test_a_weak_word_overlap_does_not_get_the_full_word_weight(pipe):
    # Y shares no query word; Z shares one word with a long query. Under the
    # old min-max stretch Z's small overlap counted as a full 1.0.
    res = pipe.search_similar(
        "zyptron unrelated words about nothing in particular here", top_k=3, lexical_boost=True,
    )
    by_id = {a["article_id"]: a for a in res}
    assert 0 < by_id["z"]["lexical_score"] < 0.5
    assert by_id["y"]["similarity_score"] > by_id["z"]["similarity_score"]


def test_pico_boost_adds_to_the_blended_score(pipe):
    from app.services.enrich import apply_pico_boost

    res = pipe.search_similar("zyptron pathway", top_k=3, lexical_boost=True)
    before = {a["article_id"]: a["similarity_score"] for a in res}
    for a in res:
        a["pico"] = {}
    apply_pico_boost(res, "zyptron pathway")
    for a in res:
        assert a["similarity_score"] == pytest.approx(before[a["article_id"]] + a["pico_boost"], abs=1e-3)
    scores = [a["similarity_score"] for a in res]
    assert scores == sorted(scores, reverse=True)


def test_starred_centroid_and_empty(pipe, tmp_path):
    empty_p = LiteratureSearchPipeline(db_path=str(tmp_path / "empty.db"))
    with pytest.raises(ValueError, match="Star some papers first"):
        empty_p.search_from_starred(top_k=5)
    empty_p.db.close()

    # Star X and Y; Z is the other embedded paper. Starred stay in results.
    pipe.db.upsert_note("x", "pubmed", starred=True)
    pipe.db.upsert_note("y", "pubmed", starred=True)
    out = pipe.search_from_starred(top_k=5)
    assert out["seed_count"] == 2
    ids = [a["article_id"] for a in out["results"]]
    assert "x" in ids and "y" in ids
    assert "z" in ids
    # Stars sit near the centroid, so they should rank at least as high as Z.
    assert ids.index("z") >= min(ids.index("x"), ids.index("y"))
