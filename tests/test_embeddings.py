import numpy as np
import pytest

# embeddings.py imports scikit-learn at module load; skip cleanly if absent.
pytest.importorskip("sklearn")

from app.services.embeddings import EmbeddingEngine, select_device


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


# --- Shared model registry --------------------------------------------------
# Pipelines are cached per (user, library), so before sharing, every concurrent
# user duplicated the weights. These tests pin the sharing contract; they use a
# stub so nothing is downloaded.

class _StubModel:
    def __init__(self, path, device="cpu"):
        self.path = path
        self.device = device


@pytest.fixture
def stub_st(monkeypatch):
    """Replace SentenceTransformer with a counting stub; isolate the registry."""
    import sentence_transformers

    from app.services import embeddings as emb

    calls = []

    def factory(path, device="cpu", **kwargs):
        calls.append((path, device))
        return _StubModel(path, device)

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", factory)
    monkeypatch.setenv("EMBEDDING_DEVICE", "cpu")
    emb.clear_model_cache()
    yield calls
    emb.clear_model_cache()


def test_engines_share_one_model_instance(stub_st):
    """Two engines on the same model must reuse one object, loaded once."""
    a = EmbeddingEngine('general')
    b = EmbeddingEngine('general')
    assert a.model is b.model
    assert len(stub_st) == 1, f"expected a single load, got {stub_st}"


def test_engine_does_not_pin_a_private_copy(stub_st):
    """Repeated .model access stays on the shared object (no per-engine cache)."""
    eng = EmbeddingEngine('general')
    first = eng.model
    assert eng.model is first
    assert len(stub_st) == 1
    assert eng.device == "cpu"


def test_distinct_models_are_cached_separately(stub_st):
    """Different model names are different entries, not one clobbering the other."""
    general = EmbeddingEngine('general').model
    mpnet = EmbeddingEngine('mpnet').model
    assert general is not mpnet
    assert len(stub_st) == 2


def test_registry_is_bounded(monkeypatch, stub_st):
    """The model name is unvalidated user input, so the registry must not grow."""
    from app.services import embeddings as emb

    monkeypatch.setattr(emb, "MAX_LOADED_MODELS", 2)
    for name in ("general", "mpnet", "specter", "multiqa"):
        EmbeddingEngine(name).model
    assert len(emb._model_cache) <= 2


def test_failed_device_falls_back_to_cpu(monkeypatch, stub_st):
    """A dead accelerator must degrade to CPU, not kill the embedding step."""
    import sentence_transformers

    from app.services import embeddings as emb

    def picky(path, device="cpu", **kwargs):
        if device != "cpu":
            raise RuntimeError("no driver")
        return _StubModel(path, "cpu")

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", picky)
    monkeypatch.setenv("EMBEDDING_DEVICE", "cuda")
    emb.clear_model_cache()

    eng = EmbeddingEngine('general')
    assert eng.model.device == "cpu"
    assert eng.device == "cpu"


def test_concurrent_first_use_loads_once(stub_st):
    """Two job threads racing on a cold cache must not both load the weights."""
    import threading

    seen = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        seen.append(EmbeddingEngine('general').model)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(stub_st) == 1, f"model loaded {len(stub_st)}x under concurrency"
    assert all(m is seen[0] for m in seen)
