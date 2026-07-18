# Scale & engineering hygiene notes (Phase R8)

Classroom demos are usually hundreds of papers per library, not millions.
Pagination (page size 50) was added so Search / Clusters / Duplicates stay
usable as corpora grow.

## Measured results (2026-07-18, tools/bench_scale.py)

Seeded corpora (synthetic articles + random unit 384-dim embeddings; query
embedding injected so no model load), Linux desktop CPU, median of 5:

| stage (ms)     | n=200 | n=1000 | n=2000 | notes |
|----------------|------:|-------:|-------:|-------|
| emb_cold       | 0.4   | 2.2    | 4.1    | once per corpus change (cached after) |
| emb_warm       | 0.0   | 0.0    | 0.0    | every search |
| articles_map   | 0.3   | 1.6    | 3.3    | every search (full corpus) |
| keypoints_map  | 0.2   | 1.1    | 2.2    | every search (full corpus) |
| notes_map      | 0.0   | 0.0    | 0.0    | every search |
| search_hybrid  | 2.5   | 3.9    | 5.9    | cosine + shortlist TF-IDF |
| dedup_095      | 6.3   | 7.4    | 17.2   | O(N²) cosine |
| kmeans_10      | 24.7  | 53.7   | 114.7  | incl. TF-IDF labels |
| hdbscan (warm) | ~150  | ~1100  | ~3100  | UMAP reduce dominates |

**Conclusions:**
- The whole per-search server cost at n=2000 is ~11ms + query encode
  (~10–50ms CPU). **TF-IDF caching, corpus-load reduction, and FAISS are all
  unnecessary at classroom scale (≤2k)** — parked permanently unless corpora
  grow 10×. Hybrid TF-IDF already fits only the ≤~250-doc shortlist.
- The one real cost was **UMAP's first call per process: ~8s of numba JIT**
  (7.8s cold vs 0.15s warm at n=200 — that's why naive first-click Density
  clustering felt slow). Fixed: `clustering.warm_density_reducer()` runs in a
  daemon thread at app startup, so the first Generate Clusters click costs
  ~0.15s/1.1s/3.1s at 200/1k/2k instead of +8s.

Re-run with:

```bash
SECRET_KEY=x DEBUG=true python tools/bench_scale.py --sizes 200,1000,2000 --repeats 5
```

(`tools/bench_corpus_memory.py` remains as a rough RSS-only smoke check.)

## Ruff / CI

CI runs `ruff check .` with a **critical** rule subset (`E9`, `F63`, `F7`,
`F82`) so undefined names and syntax fail the build. Full style clean (E501,
import order, etc.) remains gradual — do not flip to `select = ["ALL"]`
without a dedicated cleanup PR.

## GitHub LFS / history

History rewrite (2026-07-08) purged `*.db` from git. Active tree should not
track databases (see `.gitignore`). No active LFS-managed media blobs are
required for this app. If `git lfs ls-files` ever lists stale large binaries,
purge via a dedicated history rewrite only after coordinating all clones —
do not force-push casually.

## Out of scope (product)

Campus proxy full-text, Web of Science, JSTOR/EBSCO, SSO — see roadmap R7
and `/learn/finish-your-research`.
