# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

The open phases are the fix work from `docs/AUDIT_2026-10-15.md`, in the
order to take them: admin console, account safety, the sources, the
Search page, storage and quota, jobs, AI and exports, then the host.
Phase N matches audit section N, and each task names the finding ids
(`16.1`, `18.4`, ...) that hold the evidence and file locations. Cite
those ids in branches and PRs, and mark a finding `Fixed in #NN` in the
audit when its PR merges.

## Phase 16 — Admin console
Audit section 16.
- Tasks:
  - (16.1) Saving a banner draft must not touch the published row: write
    the draft as its own row (or keep `published` and `draft` as separate
    states), so "Save draft" never unpublishes
  - (16.2) Take `status` out of the banner save body; only `/publish` and
    `/disable` change it, both behind the `publish` word
  - (16.3) Refuse disable, revoke-sessions and set-email on the acting
    admin's own account, and refuse disable on any other admin; say so in
    the dialog before it opens
  - (16.4, 16.5) Clear the `support_view` cookie on `/logout`, and end a
    support view when the admin session that started it is gone (logged
    out, revoked, disabled, or no longer an admin); student-side state does
    not end a view (see audit 16.5)
  - (16.6, 16.7) Host tab: give the Laya probe long enough for a
    socket-activated worker to load, or show "asleep" when the socket
    accepts but the read times out; format the watchdog `checked_at` and
    `since` as times
  - (16.8) Activity feed: wording for every action the app writes
    (`support-view-end`, `export-packet`), no dangling preposition when the
    actor is the account, and student ticket actions labelled as such or
    left out of "Recent admin activity"
  - (16.9) Enable Unlock, Re-enable and Retry prepare only when the account
    state allows them; Retry fetch reuses the student's stored contact
    email rather than the placeholder
- Complete when: the banner sequence save, publish, save draft leaves the
  published banner in place; the self-targeting actions return 400 with a
  sentence; a logged-out browser gets 401 from `/api/libraries` after a
  support view; the Host tab shows a time, not an epoch, and an idle
  sidecar is not reported as down; `tests/test_admin_actions.py` covers
  each rule
- Status: [ ] open

## Phase 17 — Account safety
Audit section 17.
- Tasks:
  - (17.1) Lockout: reset `failed_logins` when `locked_until` has passed
    (or count only failures inside the window) and increment atomically;
    do not end live sessions on a lock
  - (17.2) Rate limiter: key on a verified session (database,
    token_version, account exists) or on the network bucket, never on a
    bare signed JWT; give guest tokens the guest lifetime
  - (17.3) Count failed password re-auths (admin view, ops re-auth, change
    password, delete account) toward the lockout and write auth events;
    rate-limit change-password and delete-account like login
  - (17.4) Check the CSRF double-submit token on the `/login` and
    `/register` POSTs
  - (17.5) Let a guest open `/register` (the guest banner links there) and
    replace the guest session with the new account on success
  - (17.6) Reserve `ADMIN_USERNAMES` at registration
  - (17.7) Run a dummy password hash for an unknown username so login
    timing does not reveal which handles exist
  - (17.8, 17.9) Show reset codes on screen only with
    `RESET_CODES_IN_RESPONSE`, never because `DEBUG` is on; refuse ops
    re-auth when `SECRET_KEY` is empty instead of falling back to
    `ops-dev-only`
  - (17.10) Key the fetch preferences in `localStorage` (topic, sources,
    contact email) by account and clear them on logout
  - (17.11) Add `SupportViewMiddleware` before `SecurityHeadersMiddleware`
    so its own 403 and 302 responses carry the security headers
  - (17.12) Ops: tie `last_validate_ok` to the staging SHA and reset it
    when `ask_grok` changes files
- Complete when: eight wrong passwords followed by one more after 15
  minutes do not relock; a purged guest's token gets no private
  rate-limit bucket; a cross-site login POST is refused; a guest reaches
  the register form; every response from the app carries the CSP; tests
  cover each
- Status: [ ] open

## Phase 18 — Sources
Audit section 18. Order by production impact: bioRxiv/medRxiv, DBLP,
Europe PMC, Semantic Scholar and OpenAlex keys, arXiv, the deadline race.
- Tasks:
  - (18.1) bioRxiv/medRxiv: read the page size from the response
    (`count`), page newest-first or by date window, and match
    `AND`/`OR`/`NOT` as operators
  - (18.2) DBLP: treat a 2xx that is not JSON (the bot challenge) as a
    typed `network` error with a student-facing sentence, and do the same
    in `HttpClient` for every source; drop records with no abstract and
    change `tests/test_new_fetchers.py` to expect the drop
  - (18.9) Europe PMC: read the journal from `journalInfo.journal.title`;
    strip HTML from abstracts; correct `PPR` preprint links
  - (18.3, 18.4) API keys: optional `S2_API_KEY`, `OPENALEX_API_KEY`,
    `NCBI_API_KEY` read from the environment and passed by the pipeline;
    `.env.example` and `docs/SELFHOST.md` say what each buys
  - (18.3, 18.5) NASA ADS without a token, and Semantic Scholar on a
    non-HTTP exception, report a typed error instead of `no_results`
  - (18.6) arXiv: join terms with `AND`; drop the second request per
    entry; keep the 3-second spacing the API asks for
  - (18.7) PLOS: wrap the query in parentheses so every word hits
    title/abstract
  - (18.8) Keep a fetch that finishes after the budget; attach the pages
    already fetched to `rate_limited`, `network` and `http` errors too;
    fail fast when `Retry-After` exceeds the remaining budget
  - (18.13, 18.16) PubMed: report `urllib` errors as errors, not
    `no_results`; parse `MedlineDate`; set timeouts on the Entrez calls
    instead of `socket.setdefaulttimeout(30)` at import; pass the deadline
    and cancel into Entrez where possible
  - (18.10, 18.11, 18.12) Strip tags and unescape entities in DOAJ and
    Zenodo abstracts; page by offset in DOAJ, Zenodo and OpenAIRE; link
    OpenAIRE ids to doi.org only when they are DOIs
  - (18.14, 18.15) Venue and authors: keep the ClinicalTrials sponsor out
    of the journal field; prefer the host venue over a repository name
    ("PubMed") in OpenAlex; keep every author, or mark the list as cut,
    instead of the first five in PubMed, Europe PMC, OpenAlex and
    ClinicalTrials
  - (18.17) Replace the shared placeholder contact email with the host's
    configured address when the student leaves the field empty
- Complete when: on the host, bioRxiv, medRxiv and DBLP each return papers
  for a plain two-word topic; the production log shows no
  "Expecting value" source errors for a week; Europe PMC papers show their
  journal and a RIS export from Europe PMC has no tags in `AB`; each
  fetcher has a test for its current live shape
- Status: [ ] open

## Phase 19 — Search page and ranking
Audit section 19.
- Tasks:
  - (19.1) Hybrid rank: normalise lexical scores against an absolute scale
    (or cap the lexical term when the TF-IDF cosine is small) and show the
    score the list is sorted by; make `pico_boost` re-sort the blended
    score
  - (19.2) Refresh the Kept / Removed / Screened out rail after Not
    relevant, Undo, Set aside and duplicate actions
  - (19.3) Duplicate resolution after prepare: either preview and undo as
    `spec.md` says, or change the spec (the human decides); make the
    Narrow it down counts and "papers ready" agree
  - (19.4) Show the layout notice only when `uiMode` was stored, and update
    the test that pins the opposite
  - (19.5) Narrow it down: load the level counts once per question; clear
    the status line after Back
  - (19.6) Laya topic areas: clear or relabel the selection when the answer
    is unsure or unavailable; ask for topics under 8 characters; after a
    hand click, offer the new pick on a changed topic instead of ignoring
    it, and drop Laya's own earlier pick from the set; re-ask at Find
    when the selection came from Laya for a different topic
  - (19.7) Render the elements `collect.js` writes to (`#prepare-section`
    and the rest) or delete the code that targets them; the fetch-lock
    banner and "Start fresh deletes N papers" must show
  - (19.8) Group by theme: restore the More dock when its wait screen
    closes
  - (19.9, 19.10) Re-enable the wait-screen Cancel after a cancel; give the
    90% hold an exit (reload mid-prepare, statistics failure, zero
    embeddings)
  - (19.11) Never use the fetch topic as the Narrow it down question;
    require a typed question in every apply path and in Re-prepare's
    pre-fill
  - (19.12, 19.13) `apiCall`: render 422 and 429 bodies as sentences;
    retry one failed progress poll before giving up
  - (19.14, 19.15) "Show original abstract" opens the details; source
    chips and Save your work refresh after the first fetch; look cards
    revert on a failed save; clear "Preparing papers…" after Re-prepare;
    keyboard access on topic cards; `escapeAttr` in attribute contexts;
    one Reader Escape listener; public copy says Narrow it down, not
    "Quick screen"
  - (19.16) Year bounds: decide whether undated records stay visible when
    a year range is set, and say so in the filter
  - Looks polish (not from the audit): tune the dark palettes of
    Broadsheet and Catalog; closed result rows show no star or note marker;
    More like this shows no visible banner after re-ranking; Save note says
    Saved only after the request returns; the Narrow it down step returns
    after Skip
- Complete when: a search's displayed scores are monotonic under
  Similarity; the rail updates without a reload; the audit's browser walk
  (guest, register, fetch, prepare, Narrow it down, star, note, Not
  relevant, export) passes with no stuck screen; the Laya reproduction in
  19.6 follows every topic change; the Looks items are checked in the
  browser in the looks they touch, light and dark, with ink contrast at or
  above 4.5:1 where colour changes
- Status: [ ] open

## Phase 20 — Storage and quota
Audit section 20.
- Tasks:
  - (20.1) Free space after deletes: `PRAGMA auto_vacuum=INCREMENTAL` on
    new library databases plus `incremental_vacuum` (or a `VACUUM`) after
    start over, replace-fetch swap and library clear; reword the 507
    message to say what frees space
  - (20.2) Refresh `storage_bytes` when a job finishes and in a periodic
    sweep, so the over-quota queue and tile are current
  - (20.3) Clone by an allow-list of tables; drop `_swap_*` tables on
    rollback
  - (20.4) `backup.py --restore`: remove `-wal` and `-shm`, write to a temp
    file and rename; `encrypt_databases.py`: honour `USERS_DB`, strip the
    key, verify after conversion
  - (20.5) Rollback around every batch writer in `database.py`; delete the
    guest row only after its directory is gone; parse
    `MAX_USER_STORAGE_MB` as a number of megabytes without truncating to
    zero
- Complete when: a user at the cap who starts over can fetch again; the
  quota tile matches `usage_bytes` within a minute of a job ending; a
  restore over a live WAL passes `integrity_check`; tests cover each
- Status: [ ] open

## Phase 21 — Jobs
Audit section 21.
- Tasks:
  - (21.1) Embed cancel that the worker reads between batches;
    `can_cancel` only where cancel works
  - (21.2) `library_id` on start-over, load-sample, detect-duplicates and
    cluster-screening, bound like fetch and embed
  - (21.3) `wait=true` embed goes through `try_begin_user_job`
  - (21.4, 21.5) Bounds on `DuplicateRequest.threshold`, validation of
    `MultiFetchRequest.sources` (non-empty, known, unique); detect
    duplicates in a thread
  - (21.6) Laya calls off the event loop (`run_in_thread` around
    enrichment) and `wake()` on the first failed call, not only on page
    load
  - (21.7) Admin retry-embed uses the library's stored model; retry-fetch
    uses the library on the job slot
  - (21.8) Job slots are per account, not per library: either key them by
    library or say on the page that one job runs per account; the wait
    screen ignores a progress payload for another library
- Complete when: cancelling a prepare stops it within one batch; two tabs
  on different libraries cannot wipe the wrong one; a sleeping sidecar
  does not delay other users' requests; tests cover each
- Status: [ ] open

## Phase 22 — AI study aids and exports
Audit section 22.
- Tasks:
  - (22.1) `GET /api/ai/settings` computes status inside `ai_for_user`
  - (22.2) Anthropic: add the package to `requirements.txt` and the venv,
    or remove the provider; declare `httpx`
  - (22.3) Never write `OLLAMA_MODEL` into `os.environ`; keep the
    per-request model in the runtime dict
  - (22.4, 22.5) Validate `openai_base_url` (https, no loopback or private
    ranges unless the host allows it) and bound `llm_timeout_seconds`;
    drop `settings_path` from the settings payload students receive
  - (22.6) Decide whether `HIDE_AI_BUTTONS` also refuses the three AI
    routes, and write the answer into `spec.md`
  - (22.7, 22.8, 22.9) CSV: escape leading `=`, `+`, `-`, `@`; fill
    Similarity and Cluster columns in the selection export or drop them;
    RIS and BibTeX: write `DO` for every DOI-shaped id; RIS: omit `JO` when
    unknown
  - (22.10) `GET /api/export/library`: build the file in a worker thread
    and give the route a rate limit
- Complete when: Account shows the student's own provider after a reload
  and a save keeps it; a CSV with a hostile title opens inert in a
  spreadsheet; tests cover each
- Status: [ ] open

## Phase 23 — Host
Audit section 23, and what was still open from running the live instance.
- Tasks:
  - (23.1) Deploy `main` (the admin slices and the fixes above) to the
    production checkout and restart
  - (23.4) Set `MAX_TOTAL_ACCOUNTS` in `.env` and restart; unset means no
    cap and registration is open
  - (23.4) Set `LLM_PROVIDER`, `OLLAMA_MODEL`, `OLLAMA_HOST` and
    `OLLAMA_MODELS` in `.env` and restart, so the built-in study aid is on
    for students again; decide on `NASA_ADS_TOKEN` and
    `AI_ALLOW_SETTINGS_WRITE`; give `.env.example` a line for each knob
    the code reads
  - (23.3) Set `HF_HUB_OFFLINE=1` on the app unit once the model cache is
    complete, so no model load contacts the Hub
  - (23.2) Let an external uptime check reach `/health` (a Cloudflare skip
    rule for that path, or check through the tunnel)
  - (23.5) One place for the version string (`app/main.py`, `pages.py`,
    `support.py`, `admin.py` today)
  - Confirm on the host that a detached deploy writes its
    `operator_deploys` row to the live `users.db` and that a console
    rollback closes its own record
- Complete when: the host serves the fixed build, an account cap is
  enforced, students have a working study aid, the log shows no Hub
  requests on model load, and the deploy record has been seen on the host
- Status: [ ] open

## Backlog (unscheduled)
- Laya cut-offs from real use: after Phase 19 has been live a few weeks,
  read `laya topic-area feedback` log lines and set `MIN_BEST` /
  `SECOND_RATIO` (`app/routes/laya.py`); spot-check Laya-tagged study
  types on real libraries before lowering `LAYA_MIN_P` (0.85)
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Precomputed sample-corpus embeddings so a guest start does not run an
  embed job (audit 21.9)
- Prune `auth_events` and expired token tables; decide what account delete
  removes from the support tables (audit 20.5)
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
