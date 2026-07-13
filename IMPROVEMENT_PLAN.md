# IMPROVEMENT_PLAN.md — phased version releases

Exact instructions for an implementing model. Work top to bottom; phases are
ordered by dependency and risk. **Each phase ships as its own version** and
should land (merge) before the next phase starts. Read `context.md` FIRST —
it defines the architecture, conventions, and gotchas. Nothing here overrides it.

| Phase | Version | Branch | Theme |
|-------|---------|--------|-------|
| 1 | **3.2.0** | `chore/v3.2-hardening` | Safety nets (CI, WAL, rate limits) |
| 2 | **3.3.0** | `feature/v3.3-report-citations` | RIS/BibTeX + screening report |
| 3 | **3.4.0** | `feature/v3.4-accounts-jobs` | Password change + background jobs |
| 4 | **3.5.0** | `feature/v3.5-search-quality` | Year filter, hybrid rank, starred search |

Current baseline before Phase 1: **3.1.1**.

## Ground rules (apply to every task)

1. Start each phase from the default branch tip (`git checkout main && git pull`)
   after the previous phase has merged (unless the user says otherwise). One
   branch per PHASE (names in the table above). Do not push or open PRs unless
   the user asks.
2. Before starting and after every feature:
   `SECRET_KEY=x DEBUG=true python -m pytest -q` — suite must be green
   (39 tests at time of writing; grows as you add).
3. House conventions (from context.md, non-negotiable):
   - Handlers: auth check → CSRF (mutating only) → `get_pipeline(uid)` in
     `try` / `release_pipeline(uid)` in `finally`; blocking work via
     `run_in_thread`. `ValueError` → 400; everything else → `server_error(e)`.
   - Article key is the tuple `(article_id, source)`.
   - UI copy: **no em-dashes** in user-facing strings. Public pages
     (landing, `/learn/*`) must NOT load `common.js`.
   - After editing static CSS/JS, bump the `?v=` cache-bust query in
     `templates/base.html` (and public templates that reference the file).
4. Never touch `user_data/`, `users.db`, or `.env`. Never commit any `*.db`.
5. Every feature ships with tests. Put DB/pipeline tests beside the existing
   patterns in `tests/` (see `tests/test_screening.py` for fixtures style:
   tmp_path DBs, direct `insert_embeddings`, monkeypatched `embed_query`).
6. After each feature: update `context.md` (feature list + API table +
   backlog removal) in the same commit.
7. **Version closeout (end of every phase):** bump version strings from the
   previous version to **this phase's version** everywhere the old string
   appears (`main.py` ×2, `README.md`, `templates/base.html`,
   `templates/login.html`, `templates/landing.html`,
   `templates/feature_guide.html`). Then full suite + phase-specific manual
   checks. Report results honestly. **Stop.** Do not push, merge, or deploy —
   the user decides. Do not start the next phase until the user says so.

---

# PHASE 1 — safety nets → **v3.2.0** (branch: `chore/v3.2-hardening`)

Baseline in: **3.1.1**. Ship as: **3.2.0**.

## 1A. GitHub Actions CI

**Goal:** every push/PR runs the test suite automatically.

- Create `.github/workflows/ci.yml`:
  - Trigger: `push` and `pull_request` on all branches.
  - Ubuntu, Python 3.11 (`actions/setup-python@v5`).
  - Install ONLY what tests need (the suite self-skips heavy deps; torch,
    faiss, and umap are NOT required): `pytest numpy scikit-learn fastapi
    httpx jinja2 biopython plotly tqdm slowapi PyJWT "passlib[bcrypt]"
    "bcrypt<4.1" python-multipart requests python-dotenv`.
  - Env for the run: `SECRET_KEY: ci-test-key`, `DEBUG: "true"`.
  - Step: `python -m pytest -q`.
- Run `ruff check .` locally first. If it reports zero errors, add a blocking
  `ruff check .` step; if it reports pre-existing errors, do NOT add ruff to
  CI in this phase (note it in the commit message instead).
- **Accept:** workflow file passes `python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`;
  suite green locally with the exact package list above in a fresh venv is
  NOT required (trust the skip guards).

## 1B. SQLite WAL + busy timeout

**Goal:** eliminate rare "database is locked" errors.

- `database.py` `ArticleDatabase.__init__`: immediately after
  `sqlite3.connect(...)`, execute `PRAGMA journal_mode=WAL` and
  `PRAGMA busy_timeout=5000`.
- `user_db.py` `UserDatabase.__init__`: same two pragmas.
- `.gitignore`: ensure WAL sidecars are ignored — add `*.db-wal` and
  `*.db-shm` (the existing `*.db` does not cover them).
- **Tests:** in `tests/test_database.py` add one test asserting
  `PRAGMA journal_mode` returns `wal` on a fresh `ArticleDatabase`.
- **Accept:** suite green; creating a DB in tmp produces `-wal`/`-shm`
  sidecars while open.

## 1C. Per-user rate limiting

**Goal:** a classroom behind one NAT IP must not share one rate budget.

- In `main.py`, define ABOVE the `Limiter(...)` construction:
  ```python
  def rate_limit_key(request: Request) -> str:
      # Authenticated users get their own bucket; anonymous falls back to IP
      # (login/register stay IP-keyed, which is what we want for brute force).
      user = get_current_user(request)
      if user and user.get("user_id"):
          return f"user:{user['user_id']}"
      return get_remote_address(request)
  ```
  and change to `limiter = Limiter(key_func=rate_limit_key)`.
- Do NOT change any `@limiter.limit(...)` decorators or their rates.
- **Tests:** unit-test `rate_limit_key`: (a) request with a valid
  `access_token` cookie → `user:<uuid>`; (b) request without → an IP string.
  Build requests via `fastapi.Request` scope dicts or through `TestClient`
  capture; simplest is calling it inside a tiny test route registered in the
  test.
- **Accept:** suite green; manual check that two different logged-in
  TestClient sessions hitting `/api/fetch-articles-multi` (fake fetcher)
  never 429 each other under the 20/min limit.

## Phase 1 closeout

1. Bump **3.1.1 → 3.2.0** (all locations in Ground rule 7).
2. `context.md`: document CI, WAL, per-user rate limiting; remove from backlog.
3. Full suite green. Stop for user review/merge before Phase 2.

---

# PHASE 2 — product spine → **v3.3.0** (branch: `feature/v3.3-report-citations`)

Baseline in: **3.2.0** (merged). Ship as: **3.3.0**.

## 2A. RIS + BibTeX citation export

**Goal:** "Download citations" file that Zotero/EndNote/Mendeley import.

- New module `citations.py` (root, next to `utils.py`):
  - `SOURCE_URL` builders: port the `getArticleUrl` switch from
    `static/js/common.js` to a Python dict of `source -> lambda id: url`
    (keep the two in sync; add a comment in BOTH files pointing at each other).
  - `article_to_ris(article: dict) -> str`. Mapping:
    `TY  - JOUR`, `TI  - {title}`, one `AU  - {name}` line per author,
    `PY  - {year}` (omit if not a 4-digit int), `JO  - {journal}` (omit if
    empty), `AB  - {abstract}` with newlines collapsed to spaces,
    `DO  - {article_id}` ONLY when `source == "crossref"` (that id is a DOI),
    `UR  - {url}` from SOURCE_URL when available, `ID  - {source}:{article_id}`,
    terminator `ER  - ` plus blank line.
  - `article_to_bibtex(article: dict) -> str`: entry type `@article`; citation
    key `{source}_{article_id}` with every char not `[A-Za-z0-9_]` replaced by
    `_`; fields title (wrapped `{{...}}` to preserve case), author
    (names joined with ` and `), year, journal, doi (crossref only), url,
    note = `Source: {source}`. Escape `{`, `}`, `%`, `&`, `#` in values;
    collapse newlines.
  - `collection_to_ris(articles) -> str` / `collection_to_bibtex(articles) -> str`
    (join with blank lines).
- `main.py`: extend the existing `GET /api/export/library` endpoint:
  - New accepted `format` values: `ris` and `bibtex` (existing values keep
    working unchanged).
  - Response: `StreamingResponse`, media types `application/x-research-info-systems`
    (ris) / `application/x-bibtex` (bibtex); filenames `library.ris` /
    `library.bib`; same `scope` semantics as today.
- UI: wherever the library export buttons live on the Search page, add
  "RIS (Zotero/EndNote)" and "BibTeX" options using the same scope selector.
- **Tests:** new `tests/test_citations.py`:
  - RIS: multi-author → multiple AU lines; crossref article gets `DO`;
    non-crossref gets no `DO`; missing year omits `PY`; ends with `ER  - `.
  - BibTeX: key sanitization (`10.1234/ab.cd` → `crossref_10_1234_ab_cd`);
    ` and ` author joining; braces escaped in title.
  - Endpoint: authenticated `GET /api/export/library?format=ris&scope=all`
    returns 200, attachment header, body contains `TY  - JOUR`.
- **Accept:** a downloaded `.ris` file imports into https://zbib.org or
  Zotero without errors (structural validity is what the tests assert).

## 2B. PRISMA-style screening report

**Goal:** one click produces the "show your work" accounting.

- `utils.py`: add `build_screening_report(db) -> dict` returning:
  ```python
  {
    "total_articles": int,            # rows in articles
    "by_source": {source: count},
    "with_embeddings": int,
    "excluded": {"duplicate": n, "cluster": n, "manual": n, "total": n},
    "included": total_articles - excluded_total,
    "starred": int,                   # notes.starred = 1
    "clusters": int,                  # distinct cluster_id excluding -1
  }
  ```
  Add whatever small query helpers `database.py` is missing (e.g. counts of
  screening rows grouped by reason; starred count). Guard: all zeros on an
  empty DB, never an exception.
- `main.py`: `GET /api/screening-report?format=json|txt` (auth, read-only, no
  CSRF). `txt` renders this exact flow shape (fill numbers):
  ```
  SCREENING REPORT - {n} papers collected
  Sources: {source}: {n}; ...
  Duplicates removed (kept best copy): {n}
  Excluded as off-topic (cluster triage): {n}
  Excluded manually: {n}
  INCLUDED in final set: {n}
  Starred: {n}
  Note: counts reflect the current collection state.
  ```
  `txt` returns as attachment `screening_report.txt`.
- UI (Duplicates page `templates/statistics.html` + `static/js/statistics.js`):
  a "Screening report" button next to the stats cards; on click, fetch JSON,
  render the numbers inline in a bordered panel, plus a "Download (.txt)"
  link to the txt format.
- **Tests:** extend `tests/test_utils_features.py` (or new file): seed a tmp
  ArticleDatabase with 6 articles across 2 sources, exclude 1 as `duplicate`,
  1 as `cluster`, 1 as `manual`, star 1 → assert every field of the dict.
  Endpoint smoke: authenticated GET returns the same numbers.
- **Accept:** numbers exactly match the seeded fixture; empty-DB returns all
  zeros with 200.

## Phase 2 closeout

1. Bump **3.2.0 → 3.3.0** (all locations in Ground rule 7).
2. `context.md`: document RIS/BibTeX export + screening report endpoints/UI;
   remove from backlog.
3. Full suite green. Stop for user review/merge before Phase 3.

---

# PHASE 3 — accounts + resilience → **v3.4.0** (branch: `feature/v3.4-accounts-jobs`)

Baseline in: **3.3.0** (merged). Ship as: **3.4.0**.

## 3A. Change password + session revocation (token_version)

**Goal:** users can change passwords; doing so kills all other sessions.

- `user_db.py`:
  - Migration in `_create_tables` (follow the PRAGMA-check pattern used in
    `database.py.migrate_schema`): if `token_version` not in
    `PRAGMA table_info(users)`, run
    `ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0`.
  - `get_by_username` / `get_by_id`: include `token_version` in the dict.
  - New `update_password(user_id, hashed_password) -> bool`: sets the new
    hash AND `token_version = token_version + 1` in one UPDATE.
- `auth.py`:
  - `create_token(user_id, username, token_version: int = 0)`: add claim
    `"tv": token_version`.
  - `decode_token` unchanged (stays pure).
- `main.py` `current_user()`: after decoding, load the user via
  `user_db.get_by_id(payload["user_id"])`; return `None` if the user no
  longer exists or `payload.get("tv", 0) != user["token_version"]`.
  (One SQLite point-read per request is acceptable.)
  Update ALL `create_token(...)` call sites (login, register) to pass the
  user's current `token_version`.
- New endpoint `POST /api/change-password` (auth + CSRF), body
  `{current_password, new_password, new_password_confirm}`:
  - Verify current password against the stored hash; 400 `Incorrect password`
    if wrong.
  - Validate new: length ≥ 8; `len(new_password.encode("utf-8")) <= 72`
    (bcrypt truncates beyond 72 bytes — reject with a clear message);
    must match confirm.
  - `update_password(...)`, then mint a FRESH token with the NEW
    token_version and re-set both cookies via `_set_auth_cookies` so the
    current session survives while every other session dies.
- UI: `templates/account.html` gets a "Change password" card (current, new,
  confirm inputs + show-password toggle, submit button, status line);
  handler in `static/js/account.js` via `apiCall`.
- **Tests** (`tests/test_auth.py` + integration file):
  - `update_password` bumps `token_version`.
  - Integration: register → capture cookies in a second client → change
    password in the first → second client's old cookie now gets 401 on
    `/api/statistics`; first client still works; login with the new password
    succeeds; with the old fails; new password of 100 chars → 400.
- **Accept:** all above green; existing login/register tests untouched and
  passing (old tokens without `tv` claim validate against `token_version` 0).

## 3B. Background jobs for fetch + embeddings

**Goal:** long work survives a closed laptop; browser only polls.

- `main.py` — add a small job layer (module scope, near the progress dict):
  ```python
  def start_user_job(uid, task, fn, /, **kwargs) -> bool:
      """Run fn in a thread; progress + result live in _all_progress[uid][task].
      Returns False if a job of this task type is already active for uid."""
  ```
  Semantics:
  - Under `_progress_lock`: if `p[task]['active']` → return False (caller
    responds 409 `{detail: "A {task} is already running"}`).
  - Mark active, `result=None`, `error=None`, then
    `asyncio.get_running_loop().run_in_executor` the work.
  - The worker owns the pipeline reference: call `get_pipeline(uid)` INSIDE
    the job start (before scheduling) and `release_pipeline(uid)` in the
    executor callback (`future.add_done_callback`), NOT in the request
    handler. On completion store `result` (the dict the endpoint used to
    return) or `error=str(exc)` into the progress entry and set
    `active=False`.
- Convert `POST /api/fetch-articles-multi` and `POST /api/create-embeddings`:
  - Request handling (auth, CSRF, validation) unchanged.
  - On success return **202** `{"status": "started"}` immediately.
  - Keep a `wait` boolean on each request model (`wait: bool = False`);
    `wait=true` preserves the old synchronous behaviour — update the
    integration tests to pass `wait=true` where they assert on results, AND
    add new tests for the async path.
- `GET /api/progress` already returns per-task dicts; ensure `result` and
  `error` fields are included in the copy it returns.
- Frontend (`static/js/data_management.js`): both flows already poll
  progress for the bars. Change submit handlers: on 202, keep polling; when
  `active` flips false, read `result`/`error` from the progress payload and
  render the same success/error UI as before. Remove reliance on the POST
  response body (except the 409 case → toast "already running").
- **Tests:** integration with the `_FakeFetcher`: POST without wait → 202;
  poll `/api/progress` in a loop (cap ~5s) until `fetch.active == false`;
  assert `result.total_fetched == 1`; second POST while active → 409 (use a
  slow fake fetcher gated on an event to make this deterministic).
- **Accept:** suite green including the old `wait=true` paths; no pipeline
  refcount leak (after job completion, `_pipeline_refcounts` for uid is 0 —
  assert via `main._pipeline_refcounts` in the test).

## Phase 3 closeout

1. Bump **3.3.0 → 3.4.0** (all locations in Ground rule 7).
2. `context.md`: document change-password, token_version, background jobs
   (202 + poll + wait flag); remove from backlog.
3. Full suite green. Stop for user review/merge before Phase 4.

---

# PHASE 4 — search quality → **v3.5.0** (branch: `feature/v3.5-search-quality`)

Baseline in: **3.4.0** (merged). Ship as: **3.5.0**.

## 4A. Year-range filter

- `SearchRequest` (and seed + starred models): add
  `year_min: Optional[int] = None`, `year_max: Optional[int] = None`.
- `pipeline.search_similar` (and the seed/starred paths): accept both; filter
  the candidate pool BEFORE ranking, alongside the existing source/cluster
  filters. Parse years with the same logic `utils.sort_articles` uses;
  when either bound is set, articles with unparseable/unknown year are
  EXCLUDED (document in UI hint).
- Wire through `/api/search`, `/api/search/seed`, the starred endpoint (4C),
  and `GET /api/search/export` (as `year_min`/`year_max` query params).
- UI (Search page): two small number inputs "From year / To year" in the
  params row; include in `lastSearchParams` so exports match; hint text:
  "Papers with unknown year are hidden when a range is set."
- **Tests:** bounds are inclusive; unknown-year article excluded when a bound
  is set, included when not; export honours the range.

## 4B. Hybrid ranking (exact words + meaning)

- `pipeline.search_similar`: new parameter `lexical_boost: bool = True`
  (exposed on SearchRequest as `lexical_boost: bool = True`).
- Algorithm (only when `lexical_boost` and candidate pool > 0):
  1. Retrieve `k0 = min(len(pool), max(top_k * 5, 50))` candidates by
     embedding similarity (existing `find_similar`).
  2. Build TF-IDF over the k0 candidates' `title + " " + abstract`
     (sklearn `TfidfVectorizer`, `stop_words='english'`, `ngram_range=(1,2)`),
     transform the raw query text, take cosine → lexical score per candidate.
  3. Min-max normalize semantic and lexical scores WITHIN the k0 pool
     (guard zero ranges → treat as all-equal 0.5).
  4. `final = 0.7 * semantic_norm + 0.3 * lexical_norm`; re-sort; cut to
     `top_k`. Keep reporting the ORIGINAL cosine as `similarity_score`
     (UI badges keep their meaning); add `lexical_score` to the article dict.
  5. `pico_boost` (existing) applies AFTER the blend, unchanged.
- Vectorizer failure (e.g. all-stopword query) → log + fall back to pure
  semantic ranking; never 500.
- **Tests:** synthetic pool where doc X contains the exact rare token from
  the query but has the 2nd-best embedding score, doc Y has best embedding
  but no token overlap → with `lexical_boost=True` X ranks first; with
  `False`, Y ranks first (monkeypatch `embed_query`, craft embeddings).
- **Accept:** default Search behaviour changes only in ordering, response
  shape is additive (`lexical_score`); suite green.

## 4C. "More like my starred"

- `database.py`: `get_starred_keys() -> list[tuple]` (notes table,
  `starred = 1`).
- `pipeline.py`: `search_from_starred(top_k=10, source_filter=None,
  cluster_filter=None, year_min=None, year_max=None)`:
  - Load starred keys; `raise ValueError("Star some papers first")` if none
    (→ 400 by convention).
  - Fetch their embeddings; centroid = mean vector, L2-normalized.
  - Rank the remaining pool (existing filters + screening exclusions apply;
    ALSO exclude the starred papers themselves from results) using the
    centroid as the query embedding. Reuse `find_similar`.
- `main.py`: `POST /api/search/starred` (auth; read-only so no CSRF, matching
  `/api/search`), body = `{top_k, source_filter, year_min, year_max}`;
  response shape identical to `/api/search` plus `"seed_count": n_starred`.
- UI (Search page): button "More like my starred (N)" near the seed-paper
  panel; N loaded from the library/notes data already on the page (or a
  cheap count endpoint if not present); renders into the same results list.
- **Tests:** three articles with embeddings, star two clustered near axis A,
  one distant unstarred near A' → results exclude both starred, nearest
  unstarred first; zero starred → 400 with the exact message.

## Phase 4 closeout

1. Bump **3.4.0 → 3.5.0** (all locations in Ground rule 7).
2. `context.md`: document year filter, hybrid ranking, starred search;
   remove from backlog; add gotchas learned across phases if any remain.
3. Full suite green + Phase 4 manual checks. Stop for user review/merge.
   This is the last planned phase; do not invent further work.
