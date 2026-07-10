import numpy as np
import pytest

# embeddings.py imports scikit-learn at module load; skip cleanly if absent.
pytest.importorskip("sklearn")

from embeddings import EmbeddingEngine, select_device


def test_detect_duplicates_finds_near_identical_pairs():
    eng = EmbeddingEngine()  # no model load: detect_duplicates only does vector math
    # a and b are identical (a duplicate pair); c is orthogonal (not a duplicate).
    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    c = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    embs = np.vstack([a, b, c])
    ids = [("1", "pubmed"), ("2", "arxiv"), ("3", "pubmed")]

    dups = eng.detect_duplicates(embs, ids, threshold=0.95)

    assert len(dups) == 1
    id1, id2, sim = dups[0]
    assert {id1, id2} == {("1", "pubmed"), ("2", "arxiv")}
    assert sim >= 0.95


def test_detect_duplicates_threshold_excludes_moderate_similarity():
    # Two vectors ~0.7 cosine apart should not count as duplicates at 0.95.
    a = np.array([1.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 1.0], dtype=np.float32)  # cosine(a,b) ≈ 0.707
    embs = np.vstack([a, b])
    ids = [("1", "pubmed"), ("2", "pubmed")]

    assert eng_detect(embs, ids, 0.95) == []
    # ...but a low enough threshold does pick it up.
    assert len(eng_detect(embs, ids, 0.6)) == 1


def eng_detect(embs, ids, threshold):
    return EmbeddingEngine().detect_duplicates(embs, ids, threshold=threshold)


def test_detect_duplicates_empty_and_singleton():
    eng = EmbeddingEngine()
    assert eng.detect_duplicates(np.zeros((0, 4), dtype=np.float32), [], 0.9) == []
    assert eng.detect_duplicates(
        np.ones((1, 4), dtype=np.float32), [("1", "pubmed")], 0.9
    ) == []


def test_select_device_respects_override(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DEVICE", "cpu")
    assert select_device() == "cpu"
    # An empty override falls through to autodetection, which must still be a
    # non-empty string (cpu when no accelerator/torch is present).
    monkeypatch.setenv("EMBEDDING_DEVICE", "")
    assert select_device()
