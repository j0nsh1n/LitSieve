"""Sample-paper vectors are saved once and copied into later libraries (audit 21.9)."""

import numpy as np

from app.content import sample_corpus
from app.services import sample_embeddings
from app.services.pipeline import LiteratureSearchPipeline


def _library(tmp_path, name):
    p = LiteratureSearchPipeline(db_path=str(tmp_path / f"{name}.db"))
    p.db.insert_articles(sample_corpus.get_sample_articles(), dedupe=False)
    return p


def _embed_all(p, model="general"):
    keys = [(a["article_id"], a["source"]) for a in p.db.get_all_articles()]
    vectors = {k: np.full(4, i + 1, dtype=np.float32) for i, k in enumerate(keys)}
    p.db.insert_embeddings(vectors, model)
    return vectors


def test_saved_vectors_fill_a_new_sample_library(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    first = _library(tmp_path, "first")
    vectors = _embed_all(first)
    assert sample_embeddings.save(first, "general") is True
    assert sample_embeddings.save(first, "general") is False  # already on disk

    second = _library(tmp_path, "second")
    copied = sample_embeddings.restore(second, "general")
    assert copied == len(vectors)
    assert second.db.get_embedding_model() == "general"
    keys, matrix = second.db.get_all_embeddings()
    got = {tuple(k): matrix[i] for i, k in enumerate(keys)}
    for key, vec in vectors.items():
        assert np.array_equal(got[key], vec)
    assert sample_embeddings.restore(second, "general") == 0


def test_no_file_until_every_sample_paper_has_a_vector(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    p = _library(tmp_path, "partial")
    first = p.db.get_all_articles()[0]
    p.db.insert_embeddings({(first["article_id"], first["source"]): np.ones(4, np.float32)}, "general")
    assert sample_embeddings.save(p, "general") is False
    assert not sample_embeddings.cache_path("general").exists()


def test_a_library_on_another_model_gets_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    source = _library(tmp_path, "source")
    _embed_all(source)
    sample_embeddings.save(source, "general")
    other = _library(tmp_path, "other")
    art = other.db.get_all_articles()[0]
    other.db.insert_embeddings({(art["article_id"], art["source"]): np.ones(8, np.float32)}, "mpnet")
    assert sample_embeddings.restore(other, "general") == 0


def test_changed_sample_text_uses_a_new_file(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    before = sample_embeddings.cache_path("general")
    edited = [dict(a) for a in sample_corpus.get_sample_articles()]
    edited[0]["abstract"] += " Revised."
    monkeypatch.setattr(sample_embeddings, "get_sample_articles", lambda: edited)
    assert sample_embeddings.cache_path("general") != before
    assert sample_embeddings.cache_path("mpnet") != before
