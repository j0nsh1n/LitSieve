#!/usr/bin/env python3
"""Rough RSS smoke check for large in-memory article lists (Phase R8).

Not a full browser load test. Run from repo root:

  python tools/bench_corpus_memory.py
  python tools/bench_corpus_memory.py --n 2000
"""

from __future__ import annotations

import argparse
import resource
import sys


def rss_mb() -> float:
    # Linux: ru_maxrss is kilobytes.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=1000, help="Fake article count")
    args = p.parse_args()
    n = max(1, int(args.n))

    before = rss_mb()
    articles = []
    for i in range(n):
        articles.append({
            "article_id": f"bench-{i}",
            "source": "openalex",
            "title": f"Bench article {i} on climate and classrooms",
            "abstract": (
                "BACKGROUND: Synthetic abstract for memory smoke tests. "
                "METHODS: Fake cohort. RESULTS: Placeholder numbers. "
                "CONCLUSIONS: Not real research."
            ),
            "year": str(2000 + (i % 25)),
            "authors": [f"Author {i % 50}"],
            "journal": "Journal of Benchmarks",
            "similarity_score": 0.5,
        })
    # Touch fields like Search card builders might.
    total_chars = sum(len(a["title"]) + len(a["abstract"]) for a in articles)
    after = rss_mb()
    print(f"n={n} articles  total_title+abstract_chars={total_chars}")
    print(f"RSS max ~{before:.1f} → {after:.1f} MiB (process peak)")
    print("Use browser tools for real UI pagination timing.")
    # Keep a reference so GC does not free before measurement.
    assert len(articles) == n
    return 0


if __name__ == "__main__":
    sys.exit(main())
