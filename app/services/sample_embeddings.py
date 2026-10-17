"""Saved vectors and key points for the built-in sample papers (audit 21.9).

Every guest start used to embed the same sample corpus again. The first
prepare of the sample set writes its vectors and extractive key points (which
are built with the same model) to disk; later guests and "Load sample papers"
copy them in, so the prepare job loads no model at all.

The file name carries a digest of the model path and the exact text each
paper is embedded from, so editing the sample papers or the embedding text
makes a new file instead of reusing stale vectors.
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from app.content.sample_corpus import get_sample_articles
from app.services.embeddings import EmbeddingEngine

logger = logging.getLogger(__name__)

# Bump when EmbeddingEngine.embed_articles changes how it builds the text,
# key points change how they are made, or the file layout changes.
CACHE_VERSION = 2


def _cache_dir() -> Path:
    return Path(os.getenv("USER_DATA_DIR", "user_data")) / ".cache" / "sample-embeddings"


def _sample_keys() -> list:
    return sorted((a["article_id"], a["source"]) for a in get_sample_articles())


def cache_path(model: str) -> Path:
    texts = sorted(
        (a["article_id"], a["source"], f"{a['title']} {a['abstract']}")
        for a in get_sample_articles()
    )
    blob = json.dumps(
        [CACHE_VERSION, EmbeddingEngine.resolve_model_path(model), texts],
        ensure_ascii=False,
    ).encode("utf-8")
    digest = hashlib.sha256(blob).hexdigest()[:16]
    safe_model = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in model)
    return _cache_dir() / f"{safe_model}-{digest}.npz"


def save(pipeline, model: str) -> bool:
    """Write the sample vectors once every sample paper has one from this model."""
    path = cache_path(model)
    if path.exists() or pipeline.db.get_embedding_model() != model:
        return False
    wanted = _sample_keys()
    keys, matrix = pipeline.db.get_all_embeddings()
    row = {tuple(k): i for i, k in enumerate(keys)}
    points = pipeline.db.get_key_points_map()
    origin = pipeline.db.get_key_points_origin_map()
    if any(k not in row or k not in points or origin.get(k) != "extractive" for k in wanted):
        return False
    vectors = np.stack([matrix[row[k]] for k in wanted])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(
        tmp,
        keys=np.array(["\t".join(k) for k in wanted]),
        vectors=vectors,
        key_points=np.array([json.dumps(points[k]) for k in wanted]),
    )
    os.replace(tmp, path)
    logger.info("Saved sample-paper vectors for %s (%d papers)", model, len(wanted))
    return True


def restore(pipeline, model: Optional[str] = None) -> int:
    """Copy saved vectors and key points into this library where they are missing.

    Uses the library's own model when it has one; returns how many were copied.
    """
    model = pipeline.db.get_embedding_model() or model or "general"
    path = cache_path(model)
    if not path.exists():
        return 0
    try:
        with np.load(path) as data:
            keys = [tuple(str(k).split("\t", 1)) for k in data["keys"]]
            vectors = data["vectors"]
            bullets = [json.loads(str(b)) for b in data["key_points"]]
    except (OSError, ValueError, KeyError):
        logger.warning("Ignoring unreadable sample vector file %s", path.name)
        return 0
    have = pipeline.db.get_embedding_keys()
    present = {(a["article_id"], a["source"]) for a in pipeline.db.get_all_articles()}
    missing = {
        key: vectors[i] for i, key in enumerate(keys)
        if key in present and key not in have
    }
    if missing:
        pipeline.db.insert_embeddings(missing, model)
        pipeline.invalidate_corpus_cache()
    have_points = pipeline.db.get_key_points_keys()
    points = {
        key: bullets[i] for i, key in enumerate(keys)
        if key in present and key not in have_points
    }
    if points:
        pipeline.db.insert_key_points(points)
    return len(missing)
