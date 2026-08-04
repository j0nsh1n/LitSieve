"""
Embeddings Module
Creates semantic embeddings for articles using pre-trained models
Now uses FAISS for fast similarity search (v2.3.0)
"""

import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning(
        "FAISS not installed - falling back to scikit-learn "
        "(slower for large datasets)"
    )

from sklearn.metrics.pairwise import cosine_similarity


def select_device() -> str:
    """Pick the best available torch device for embedding work.

    Preference order is cuda > mps (Apple Silicon) > cpu. Set EMBEDDING_DEVICE
    to force a specific device (e.g. EMBEDDING_DEVICE=cpu). Returns "cpu" if
    torch isn't importable so the CPU path always works.
    """
    override = os.getenv("EMBEDDING_DEVICE", "").strip().lower()
    if override:
        return override
    try:
        import torch
    except Exception:
        return "cpu"
    try:
        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        return "cpu"
    return "cpu"


# --- Process-wide model registry -------------------------------------------
# Every pipeline used to build its own EmbeddingEngine, and every engine loaded
# its own copy of the weights. Measured on CPU, a second concurrent user cost
# ~46 MB (MiniLM) or ~330 MB (PubMedBERT) purely to duplicate a model that is
# read-only during inference. Sharing one instance per (path, device) makes the
# marginal user cost ~0, so RAM scales with the number of *distinct models in
# use*, not the number of logged-in users.
#
# Safe to share: encode() runs the model in eval mode under no_grad and does not
# mutate weights, so concurrent calls from job threads only contend for CPU.
#
# Bounded on purpose: schemas.EmbeddingsRequest.model is a free-form string and
# MODELS.get(name, name) falls through to it as a HuggingFace path, so an
# unbounded dict here would let odd model names grow memory without limit.
MAX_LOADED_MODELS = max(1, int(os.getenv("MAX_LOADED_MODELS", "3") or 3))

_model_cache: "OrderedDict[Tuple[str, str], Any]" = OrderedDict()
_model_cache_lock = threading.Lock()
# Per-key load locks so two threads asking for the same model load it once,
# while different models can still load in parallel.
_model_load_locks: "Dict[Tuple[str, str], threading.Lock]" = {}


def _build_model(model_path: str, device: str) -> Tuple[Any, str]:
    """Construct a SentenceTransformer, falling back to CPU if the device fails."""
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s on device %s", model_path, device)
    try:
        model = SentenceTransformer(model_path, device=device)
        logger.info("Model loaded successfully")
        return model, device
    except Exception as e:
        # An accelerator can fail to initialise (driver mismatch, OOM,
        # unsupported op on mps). Fall back to CPU rather than crash the whole
        # embedding step.
        logger.warning(
            "Failed to load model on %s (%s); falling back to CPU", device, e,
        )
        return SentenceTransformer(model_path, device="cpu"), "cpu"


def get_shared_model(model_path: str, device: str) -> Tuple[Any, str]:
    """Return the process-wide model for (model_path, device), loading once.

    Returns (model, resolved_device); resolved_device differs from `device`
    when the accelerator failed and we fell back to CPU.
    """
    key = (model_path, device)
    with _model_cache_lock:
        hit = _model_cache.get(key)
        if hit is not None:
            _model_cache.move_to_end(key)
            return hit, getattr(hit, "_lra_device", device)
        load_lock = _model_load_locks.setdefault(key, threading.Lock())

    # Load outside the registry lock: pulling weights off disk takes seconds and
    # must not stall unrelated lookups.
    with load_lock:
        with _model_cache_lock:
            hit = _model_cache.get(key)
            if hit is not None:
                _model_cache.move_to_end(key)
                return hit, getattr(hit, "_lra_device", device)

        model, resolved = _build_model(model_path, device)
        try:
            model._lra_device = resolved  # remember where it actually landed
        except Exception:
            pass

        with _model_cache_lock:
            _model_cache[key] = model
            _model_cache.move_to_end(key)
            if resolved != device:
                # Alias the resolved key so a later CPU request reuses this one.
                _model_cache[(model_path, resolved)] = model
            # Evicted models stay alive until their last user drops them; this
            # only stops the registry itself from pinning them forever.
            while len(_model_cache) > MAX_LOADED_MODELS:
                _model_cache.popitem(last=False)
        return model, resolved


def clear_model_cache() -> None:
    """Drop registry references (tests; frees memory once users release them)."""
    with _model_cache_lock:
        _model_cache.clear()


class EmbeddingEngine:
    """Handles creation and comparison of semantic embeddings"""

    # Short name -> HuggingFace path. All models here must work with plain
    # cosine similarity (no query/passage prefixes), since search, clustering,
    # and dedup all compare vectors directly.
    MODELS = {
        'pubmedbert': 'pritamdeka/S-PubMedBert-MS-MARCO',
        'biosentbert': 'pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb',
        'specter': 'allenai/specter',
        'general': 'sentence-transformers/all-MiniLM-L6-v2',
        'mpnet': 'sentence-transformers/all-mpnet-base-v2',
        'multiqa': 'sentence-transformers/multi-qa-MiniLM-L6-cos-v1',
        'multilingual': 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2',
    }
    # Backwards-compatible alias (registry outgrew the biomedical-only name).
    BIOMEDICAL_MODELS = MODELS

    @classmethod
    def allowed_models(cls) -> Dict[str, str]:
        """Catalog names plus any the operator allow-listed via env.

        `MODELS.get(name, name)` treats an unknown name as a HuggingFace path,
        which is a useful escape hatch but must not be driven by request bodies:
        that would let any logged-in user trigger arbitrary model downloads onto
        the host's disk. Extra models are therefore an operator decision, set as
        a comma-separated EXTRA_EMBEDDING_MODELS (either "org/model" or
        "shortname=org/model").
        """
        allowed = dict(cls.MODELS)
        for item in os.getenv("EXTRA_EMBEDDING_MODELS", "").split(","):
            item = item.strip()
            if not item:
                continue
            name, _, path = item.partition("=")
            name, path = name.strip(), path.strip()
            allowed[name] = path or name
        return allowed

    def __init__(self, model_name: str = 'general'):
        self.model_name = model_name
        self.device = None  # resolved lazily when the model is first loaded

    @property
    def model(self) -> Any:
        """The shared model for this engine's name.

        Deliberately does NOT keep a per-engine reference: engines are held by
        long-lived cached pipelines, so caching here would pin one copy per
        pipeline and undo the sharing. Callers hit this once per batch/query,
        so a locked dict lookup is noise next to the encode itself.
        """
        model_path = self.MODELS.get(self.model_name, self.model_name)
        model, resolved = get_shared_model(model_path, select_device())
        self.device = resolved
        return model

    def embed_articles(self, articles: List[Dict], batch_size: int = 32, progress_callback=None) -> Dict[Tuple[str, str], np.ndarray]:
        logger.info("Creating embeddings for %s articles...", len(articles))

        texts = []
        keys = []
        for article in articles:
            texts.append(f"{article['title']} {article['abstract']}")
            keys.append((article['article_id'], article['source']))

        total = len(texts)
        all_embeddings = []

        for i in range(0, total, batch_size):
            batch = texts[i:i + batch_size]
            batch_emb = self.model.encode(
                batch,
                convert_to_numpy=True,
                show_progress_bar=False,
                batch_size=batch_size,
                normalize_embeddings=True,
            )
            all_embeddings.append(batch_emb)
            if progress_callback:
                progress_callback(min(i + batch_size, total), total)

        embeddings = np.concatenate(all_embeddings, axis=0) if all_embeddings else np.array([])
        logger.info("Created embeddings of shape: %s", embeddings.shape)

        return {key: emb for key, emb in zip(keys, embeddings)}

    def embed_query(self, query_text: str) -> np.ndarray:
        return self.model.encode(
            query_text, convert_to_numpy=True, normalize_embeddings=True
        )

    def find_similar(self, query_embedding: np.ndarray, article_embeddings: np.ndarray, article_ids: list, top_k: int = 10) -> list:
        corpus_size = len(article_ids)
        if corpus_size == 0:
            return []
        top_k = min(top_k, corpus_size)

        if FAISS_AVAILABLE and len(article_embeddings) > 0:
            # Build a transient FAISS index from the supplied embeddings.
            # Defensive copy + cast to float32 so we don't mutate the caller's array
            # (faiss.normalize_L2 normalises in place).
            corpus = np.array(article_embeddings, dtype=np.float32, copy=True)
            faiss.normalize_L2(corpus)
            index = faiss.IndexFlatIP(corpus.shape[1])
            index.add(corpus)

            query = query_embedding.reshape(1, -1).astype(np.float32, copy=True)
            faiss.normalize_L2(query)
            distances, indices = index.search(query, top_k)
            results = []
            for i, idx in enumerate(indices[0]):
                if idx < 0:
                    continue
                results.append((article_ids[idx], float(distances[0][i])))
            return results
        else:
            # Fallback to scikit-learn
            query_embedding = query_embedding.reshape(1, -1)
            similarities = cosine_similarity(query_embedding, article_embeddings)[0]
            top_indices = np.argsort(similarities)[::-1][:top_k]
            return [(article_ids[idx], float(similarities[idx])) for idx in top_indices]

    def detect_duplicates(self, article_embeddings: np.ndarray, article_ids: list, threshold: float = 0.98) -> list:
        """Find near-duplicate pairs whose cosine similarity >= threshold.

        Uses a FAISS range search so we only ever materialise the pairs that
        actually exceed the threshold (sparse for realistic dedup thresholds),
        instead of building a dense N×N similarity matrix that costs O(N^2)
        memory and blows up on large corpora. Falls back to scikit-learn when
        FAISS is unavailable.
        """
        logger.info("Detecting potential duplicates (threshold: %s)...", threshold)
        n = len(article_ids)
        if n < 2:
            return []

        duplicates = []
        if FAISS_AVAILABLE:
            # Normalise so inner product == cosine similarity.
            corpus = np.array(article_embeddings, dtype=np.float32, copy=True)
            faiss.normalize_L2(corpus)
            index = faiss.IndexFlatIP(corpus.shape[1])
            index.add(corpus)

            # range_search returns, per row, neighbours with inner product
            # strictly above the radius. Nudge the radius down by an epsilon so
            # a pair landing exactly on `threshold` is still returned, then keep
            # the exact >= filter below. lims[i]:lims[i+1] delimits row i.
            radius = float(threshold) - 1e-6
            lims, distances, indices = index.range_search(corpus, radius)
            for i in range(n):
                for pos in range(lims[i], lims[i + 1]):
                    j = int(indices[pos])
                    if j <= i:
                        continue  # skip self-matches and mirror pairs
                    sim = float(distances[pos])
                    if sim >= threshold:
                        duplicates.append((article_ids[i], article_ids[j], sim))
        else:
            # scikit-learn fallback (dense O(N^2) — acceptable only for small sets).
            sim_matrix = cosine_similarity(article_embeddings)
            for i in range(n):
                for j in range(i + 1, n):
                    similarity = sim_matrix[i, j]
                    if similarity >= threshold:
                        duplicates.append((article_ids[i], article_ids[j], float(similarity)))

        duplicates.sort(key=lambda x: x[2], reverse=True)
        logger.info("Found %s potential duplicate pairs", len(duplicates))
        return duplicates


class PICOExtractor:
    """Simple rule-based PICO (Population, Intervention, Comparison, Outcome) extractor"""

    # Common PICO keywords
    POPULATION_KEYWORDS = [
        'patients', 'participants', 'subjects', 'adults', 'children',
        'elderly', 'men', 'women', 'cohort', 'sample'
    ]

    INTERVENTION_KEYWORDS = [
        'treatment', 'therapy', 'intervention', 'drug', 'medication',
        'procedure', 'surgery', 'training', 'program'
    ]

    COMPARISON_KEYWORDS = [
        'versus', 'vs', 'compared', 'placebo', 'control', 'standard care'
    ]

    OUTCOME_KEYWORDS = [
        'outcome', 'mortality', 'survival', 'efficacy', 'effectiveness',
        'improvement', 'reduction', 'increase', 'change'
    ]

    @staticmethod
    def extract_pico(text: str) -> Dict[str, List[str]]:
        """
        Extract PICO elements from text using keyword matching

        Args:
            text: Abstract or study description

        Returns:
            Dictionary with PICO components
        """
        sentences = (text or '').split('.')

        pico = {
            'population': [],
            'intervention': [],
            'comparison': [],
            'outcome': []
        }

        # Simple keyword-based extraction
        for sentence in sentences:
            sent_lower = sentence.lower()

            if any(kw in sent_lower for kw in PICOExtractor.POPULATION_KEYWORDS):
                pico['population'].append(sentence.strip())

            if any(kw in sent_lower for kw in PICOExtractor.INTERVENTION_KEYWORDS):
                pico['intervention'].append(sentence.strip())

            if any(kw in sent_lower for kw in PICOExtractor.COMPARISON_KEYWORDS):
                pico['comparison'].append(sentence.strip())

            if any(kw in sent_lower for kw in PICOExtractor.OUTCOME_KEYWORDS):
                pico['outcome'].append(sentence.strip())

        return pico
