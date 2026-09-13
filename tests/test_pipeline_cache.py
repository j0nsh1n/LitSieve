"""Corpus embedding cache must not publish a stale generation as fresh."""

import numpy as np

from app.services.pipeline import LiteratureSearchPipeline


def test_embedding_cache_does_not_publish_across_invalidation(tmp_path):
    """A bump during get_all_embeddings must force the next load to re-read.

    The loader snapshots the generation, then reads SQLite outside the lock.
    If it tags the result with the *current* generation after that read, an
    invalidation in between looks like a cache hit and Search keeps dead
    vectors.
    """
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "cache.db"))
    stale_ids = [("old", "pubmed")]
    stale_mat = np.array([[1.0, 0.0]], dtype=np.float32)
    fresh_ids = [("new", "pubmed")]
    fresh_mat = np.array([[0.0, 1.0]], dtype=np.float32)
    calls = {"n": 0}

    def fake_get_all_embeddings():
        calls["n"] += 1
        if calls["n"] == 1:
            p.invalidate_corpus_cache()
            return stale_ids, stale_mat
        return fresh_ids, fresh_mat

    p.db.get_all_embeddings = fake_get_all_embeddings
    first_ids, first_mat = p._load_embeddings_cached()
    assert first_ids == stale_ids
    np.testing.assert_array_equal(first_mat, stale_mat)

    second_ids, second_mat = p._load_embeddings_cached()
    assert second_ids == fresh_ids, second_ids
    np.testing.assert_array_equal(second_mat, fresh_mat)
    assert calls["n"] == 2
