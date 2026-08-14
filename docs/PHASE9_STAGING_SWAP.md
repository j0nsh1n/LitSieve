# Phase 9 Step 3 — Staging swap (design only)

**Status:** implemented 2026-08-13. Successful Start fresh reattaches notes,
stars, saved AI key points, screening, and embeddings for keys that still
exist. Papers that do not return are deleted.

**Defect:** `_run_multi_fetch` calls `clear_all()` before any source is queried.
`clear_all()` deletes `key_points`, `notes`, `screening`, `clusters`,
`embeddings`, and `articles`. A network drop or all-sources-failed fetch leaves
an empty library. Test:
`tests/test_phase9_reversible_fetch.py::test_failed_replace_fetch_leaves_collection_intact`
(`xfail` until this lands).

**Failure rule:** clearing must not be observable unless the fetch produced at
least one paper.

---

## Why the naive options are out

| Approach | Why not |
|---|---|
| Hold one SQLite transaction open for the whole fetch | Fetch takes minutes. This process uses WAL + a shared pipeline connection. Search, notes, and stats would block or `busy_timeout`. Restart would roll back (good) but the live UI would be frozen (not). |
| Copy the whole `articles.db` to a sidecar and swap files | Embeddings dominate disk. Peak usage is ~2× the library. `MAX_USER_STORAGE_MB` is measured as bytes under `user_data/<uid>/`. Replace-fetch is the **over-quota recovery hatch** (`corpus.py` skips `check_quota` when `clear_first`). A 2× copy blocks that hatch. SQLCipher would also need a second encrypted file. |
| Keep today's `clear_all()` and add a confirmation | Phase 8 removed Simple dialogs. A harder click does not fix a failed fetch. |

---

## Recommended: same-DB staging table, articles only

### Where staging lives

One table in the **same** library file:

```
user_data/<uid>/libraries/<lib_id>/articles.db
  articles, embeddings, notes, …     (live — untouched during fetch)
  staging_articles                   (created at replace-fetch start)
```

Same columns as `articles`. **No foreign keys** to live tables. Created at the
start of a `clear_first` fetch; dropped on cancel, on zero-paper finish, and
after a successful swap.

Append-fetch (`clear_first=False`) does not use staging. It keeps writing
straight into `articles` as today.

`fetch_articles_parallel` already inserts **per source as it completes** so a
hung source does not block others. Staging keeps that: each source inserts into
`staging_articles` (dedupe against staging only, not live — this is a replace).

Disk during fetch = live library (including embeddings) + new abstracts. A
large replace is tens of MB of text, not a second copy of the embedding
matrix. That is the quota-safe shape.

### What happens to notes / key_points / stars

They hang off `(article_id, source)` with `ON DELETE CASCADE`. A swap is not a
table rename.

**Failed, cancelled, or restarted fetch:** live rows never move. Notes, stars,
AI key points, screening, clusters, embeddings stay.

**Successful replace (`total_fetched >= 1`):** reattach student-authored rows
for keys that still exist.

Same transaction:

- snapshot `notes`, `key_points` where `origin='ai'`, and `screening`
  whose `(article_id, source)` is in `staging_articles`
- delete live children + articles
- insert new articles from staging
- restore the snapshotted notes / AI key points / screening
- drop staging
- drop clusters always (they describe the old set)
- drop embeddings for keys **not** in the new set; keep matching embedding
  rows so auto-prepare `only_missing` can skip them

Extractive key points are regenerated on prepare; they are not reattached.

### Cancel (`POST /api/jobs/fetch/cancel`)

Today: `request_job_cancel` sets an in-memory flag. `fetch_articles_parallel`
stops inserting. Live rows are already gone if `clear_all()` ran.

With staging:

1. Flag still stops further source inserts.
2. Job end (cancel or quota stop): `DROP TABLE IF EXISTS staging_articles`.
3. Live library unchanged. Report `cancelled` / `quota_stopped` as today.
4. UI keeps the old collection and the existing “Fetch cancelled after N”
   copy, except N is staged-and-discarded, not kept. Say that in the status
   line (“cancelled — your previous papers are unchanged”).

### Process restart

Jobs live in `core._all_progress` and die on restart. After a crash:

- Live tables are intact (we never cleared them).
- `staging_articles` may still exist.

On pipeline / `ArticleDatabase` open (or at the start of the next fetch):

- If `staging_articles` exists and no fetch job is active for this user →
  `DROP TABLE staging_articles`.
- Do not auto-swap on startup. The job result is gone; we cannot know if the
  operator wanted those rows.

WAL + `foreign_keys=ON` already roll back a swap transaction that did not
commit. No extra journal file.

### Quota

`usage_bytes` walks every file under `user_data/<uid>/`. Staging in the same
DB grows `articles.db` (and WAL) during the fetch.

Replace-fetch is allowed **while already over quota** so a student can recover
space. Mid-fetch `cancel_check` today calls `quota.is_over_quota(uid)` on raw
disk. If we leave that as-is, staging growth can abort a recovery replace.

**Replace credit:** while a `clear_first` fetch is running, treat the live
library file size as reclaimable:

```
effective = usage_bytes(uid) - live_library_bytes + staging_table_estimate
over = limit > 0 and effective >= limit
```

Preflight stays “skip `check_quota` when `clear_first`”. After a successful
swap, disk should drop (old embeddings gone unless reattached). After cancel,
drop staging so the bump goes away.

Do **not** stage embeddings or copy the whole DB. That is the 2× case.

### Swap commit (success only)

After `fetch_articles_parallel` returns, `_run_multi_fetch`:

```
if not clear_first:
    # today's path
elif staged_count == 0:
    drop staging
    return {total_fetched: 0, cleared_first: false, …}  # live unchanged
else:
    db.replace_from_staging()  # one locked transaction
    invalidate_corpus_cache()
    return {total_fetched: staged_count, cleared_first: true, …}
```

`cleared_first` in the response should mean “the live collection was
replaced”, not “we intended to clear”. A zero-paper replace reports
`cleared_first: false`.

Hold `ArticleDatabase._lock` for the swap only (milliseconds to a few seconds
for tens of thousands of article rows), not for the fetch.

### SQLCipher / one worker

Temp tables sit in the already-open encrypted connection. No second key, no
second file. Heavy work stays in `start_user_job`. No new endpoint.

---

## Unwind matrix

| Event | Live collection | Staging |
|---|---|---|
| All sources error / `total_fetched == 0` | Unchanged | Dropped |
| Cancel | Unchanged | Dropped |
| Mid-fetch `QuotaExceeded` with credit | Unchanged | Dropped |
| Process restart / deploy | Unchanged | Dropped on next open |
| Swap transaction crash | Unchanged (WAL rollback) | Dropped on next open if leftover |
| Success, ≥1 paper | Replaced; notes/stars/AI kp kept on overlap | Dropped inside the transaction |

---

## Out of scope for the first implementation

- Changing Advanced default radio away from replace.
- Server-side Simple-mode 403.
- Staging for `/api/load-sample-corpus` (Step 4 already fetches the list
  before clear; the list cannot fail from the network).
- A second full library file or ATTACH of a sidecar DB.
