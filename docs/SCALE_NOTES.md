# Scale & engineering hygiene notes (Phase R8)

Classroom demos are usually hundreds of papers per library, not millions.
Pagination (page size 50) was added so Search / Clusters / Duplicates stay
usable as corpora grow.

## Measuring ~1k+ papers

After a fetch that reaches ~1000 included articles (or load sample repeatedly
is not enough — use real multi-source fetch or a seeded test DB):

1. **Prepare papers** once so embeddings exist.
2. Open **Search**, run a broad query, expand several cards; note:
   - time to first results paint
   - scroll / pagination click responsiveness
   - browser memory (devtools Performance / Memory)
3. Open **Clusters** article lists and **Duplicates** groups with pagination.
4. Record device (CPU vs GPU), model name, and approximate article count.

Optional local script (offline, no models):

```bash
SECRET_KEY=x DEBUG=true python tools/bench_corpus_memory.py
```

This builds an in-memory list of N fake article dicts and reports rough
process RSS before/after. It is a **smoke check**, not a full load test.

## Hybrid TF-IDF / FAISS

No micro-opts landed in R8. If Search feels slow at 2k+ embeddings:

- Profile `pipeline.search_similar` with a local corpus.
- Consider caching the TF-IDF matrix per library generation (invalidate on
  embed job complete).
- FAISS is optional; keep cosine correctness first.

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
