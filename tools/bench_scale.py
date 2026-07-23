#!/usr/bin/env python3
"""Seeded-corpus latency benchmark for the search/cluster/dedup hot paths.

Seeds a throwaway library DB with N synthetic articles + random unit-norm
embeddings (no model download - query embeddings are injected), then times
each stage the server actually runs per request. Run from repo root:

  SECRET_KEY=x DEBUG=true python tools/bench_scale.py
  SECRET_KEY=x DEBUG=true python tools/bench_scale.py --sizes 200,1000,2000 --repeats 5

Stages reported (median of repeats, milliseconds):
  emb_cold        first embeddings-matrix load after invalidation (per corpus change)
  emb_warm        cached embeddings load (every search)
  articles_map    db.get_all_articles_with_clusters()  (every search, full corpus)
  keypoints_map   db.get_key_points_map()              (every search, full corpus)
  notes_map       db.get_notes_map()                   (every search)
  search_hybrid   pipeline.search_similar lexical_boost=True (warm caches)
  search_sem      pipeline.search_similar lexical_boost=False
  dedup_095       pipeline.detect_duplicates(0.95)     (O(N^2) cosine)
  kmeans_10       pipeline.cluster_articles(10, kmeans) incl. TF-IDF labels
  hdbscan         pipeline.cluster_articles(method=hdbscan)
"""

from __future__ import annotations

import argparse
import logging
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

DIM = 384  # matches the 'general' MiniLM model

TOPICS = [
    "climate change effects on coastal ecosystems and fisheries",
    "metformin treatment outcomes in adults with type 2 diabetes",
    "classroom interventions for reading comprehension in middle school",
    "machine learning models for protein structure prediction",
    "urban air pollution exposure and childhood asthma incidence",
    "renewable energy storage using lithium ion battery chemistry",
    "social media use and adolescent mental health outcomes",
    "soil microbiome diversity under regenerative agriculture",
]


def make_articles(n: int, rng: random.Random) -> list[dict]:
    arts = []
    for i in range(n):
        topic = TOPICS[i % len(TOPICS)]
        words = topic.split()
        rng.shuffle(words)
        arts.append({
            "article_id": f"bench-{i}",
            "source": ["openalex", "pubmed", "crossref", "doaj"][i % 4],
            "title": f"Study {i}: {' '.join(words[:5])}",
            "abstract": (
                f"BACKGROUND: We investigated {topic}. "
                f"METHODS: A synthetic cohort of {100 + i} records was analysed with "
                f"{' '.join(rng.sample(words, min(4, len(words))))} measures. "
                f"RESULTS: Outcome {i % 7} changed by {i % 40} percent across groups. "
                f"CONCLUSIONS: Findings on {' '.join(words[:3])} warrant replication."
            ),
            "year": str(2000 + (i % 26)),
            "authors": [f"Author {i % 60}", f"Coauthor {i % 31}"],
            "journal": f"Journal of Benchmarks {i % 12}",
        })
    return arts


def unit_rows(n: int, seed: int) -> np.ndarray:
    rs = np.random.RandomState(seed)
    m = rs.normal(size=(n, DIM)).astype(np.float32)
    m /= np.linalg.norm(m, axis=1, keepdims=True)
    return m


def timed(fn, repeats: int) -> float:
    """Median wall time of fn() over repeats, in ms."""
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def bench_size(n: int, repeats: int) -> dict[str, float]:
    from app.services.pipeline import LiteratureSearchPipeline

    rng = random.Random(42)
    out: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="lra-bench-") as td:
        p = LiteratureSearchPipeline(db_path=f"{td}/articles.db", embedding_model="general")
        arts = make_articles(n, rng)
        p.db.insert_articles(arts, dedupe=False)
        mat = unit_rows(n, seed=7)
        p.db.insert_embeddings(
            {(a["article_id"], a["source"]): mat[i] for i, a in enumerate(arts)},
            model_name="general",
        )
        p.db.insert_key_points({
            (a["article_id"], a["source"]): [
                "First key point about the study.",
                "Second key point with an outcome.",
                "Third key point on limitations.",
            ]
            for a in arts
        })

        def emb_cold():
            p.invalidate_corpus_cache()
            p._load_embeddings_cached()

        out["emb_cold"] = timed(emb_cold, repeats)
        out["emb_warm"] = timed(p._load_embeddings_cached, repeats)
        out["articles_map"] = timed(p.db.get_all_articles_with_clusters, repeats)
        out["keypoints_map"] = timed(p.db.get_key_points_map, repeats)
        out["notes_map"] = timed(p.db.get_notes_map, repeats)

        q = unit_rows(1, seed=99)[0]
        query = "climate change effects on coastal ecosystems"
        out["search_hybrid"] = timed(
            lambda: p.search_similar(query, top_k=10, query_embedding=q, lexical_boost=True),
            repeats,
        )
        out["search_sem"] = timed(
            lambda: p.search_similar(query, top_k=10, query_embedding=q, lexical_boost=False),
            repeats,
        )
        out["dedup_095"] = timed(lambda: p.detect_duplicates(threshold=0.95), repeats)
        # Clustering is slow enough that one repeat is representative.
        out["kmeans_10"] = timed(lambda: p.cluster_articles(n_clusters=10, method="kmeans"), 1)
        out["hdbscan"] = timed(lambda: p.cluster_articles(method="hdbscan"), 1)
        p.db.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="200,1000,2000")
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]

    logging.disable(logging.INFO)  # keep pipeline chatter out of timings/output

    results = {n: bench_size(n, args.repeats) for n in sizes}

    stages = list(next(iter(results.values())).keys())
    col = max(len(s) for s in stages) + 2
    header = "stage".ljust(col) + "".join(f"n={n}".rjust(12) for n in sizes)
    print("\nMedian latency in ms (repeats={}):".format(args.repeats))
    print(header)
    print("-" * len(header))
    for s in stages:
        print(s.ljust(col) + "".join(f"{results[n][s]:12.1f}" for n in sizes))
    print(
        "\nPer-search cost ~= emb_warm + articles_map + keypoints_map + notes_map"
        "\n+ search_* (query-embedding model excluded; add ~10-50ms CPU encode)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
