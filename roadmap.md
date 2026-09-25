# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

## Phase 4 — Operate a live instance
Shipping changed the risk profile: there are real accounts with real data on a
home desktop, and the link has been shared publicly.
- Tasks:
  - Cap total accounts (registration is open; per-account quota bounds disk per
    user but nothing bounds the number of users)
  - Back up `users.db` + `user_data/` — `tools/backup.py` +
    `litsieve-backup.timer` (daily; integrity-checked archives)
  - Watch `logs/litsieve.log` after incidents (rotating; ~30 MB ceiling)
  - Health watchdog (`tools/watchdog.py` + timer) for app + tunnel
  - Keep the HF model cache warm so no student pays for a first download
- Complete when: an account cap (or invite gate) is enforced, a restore has been
  tested at least once from a backup, and the operator can answer "what happened
  at 14:05?" from the log file
- Status: [ ] in progress. Open as of 2026-09-17:
  - merge the account cap on `fix/phase4-account-cap` (`b6e9d45`,
    `MAX_TOTAL_ACCOUNTS`, guests exempt, HTTP-level tests)
  - run one restore drill on the host from a real archive and record the
    date here
  - set `LLM_PROVIDER`, `OLLAMA_MODEL`, `OLLAMA_HOST`, `OLLAMA_MODELS` in
    `.env` and restart: 5.4.0 stopped reading `user_data/ai_settings.json`,
    so the built-in study aid has been off for every student since the
    15 September restart
  - hide the AI buttons when no provider is set: `show_ai_buttons` is
    still true, and students got 503s from `/api/reader/explain` (2) and
    `/api/ai/refine-article` (1)

## Phase 11 — Audit follow-ups
Left over after v5.4.0. Findings: `docs/CODE_AUDIT_2026-09-06.md` (on
`audit/full-code-review`) and the follow-up audits of 2026-09-12 and
2026-09-17 (session record).
- Tasks:
  - Confirm on the host that a detached deploy writes its `operator_deploys`
    row to the live `users.db` (the fix is in code; not yet confirmed on the host)
  - Run rollback detached like deploy. `POST /api/ops/rollback` runs as a
    child of the web service through `run_action`, and the unit sets no
    `KillMode`, so the `systemctl --user restart` inside `_do_deploy` stops
    it before `_finish_deploy`; the record is left interrupted and no audit
    row is written (read from the code on 2026-09-20, not reproduced)
  - Delete spent branches: `feat/ux2-m2-split-pane`,
    `fix/critical-account-security`, `chore/bump-5.4.0`,
    `fix/audit-a01-a11-a15`
- Complete when: a detached deploy on the host has been seen writing its
  `operator_deploys` row to the live `users.db`; a console rollback closes
  its own record; no audit-era branch is left unmerged
- Status: [ ] open

## Phase 12 — UX round 2 leftovers
Presentation items from the 2026-09-17 audit of the airy glass restyle.
- Tasks:
  - Decide whether to revive m2 split-pane triage (reverted on
    `feat/ux2-m2-split-pane`, `57b7624` to `41fa5b9`) or drop it
- Complete when: the decision is recorded and the branch is merged or
  deleted
- Status: [ ] open

## Phase 13 — One flow: fold Advanced into Simple, then remove Advanced mode
Simple's rules apply to every moved function: one URL, popups only on
tap, plain words, preview before apply with one-click undo, hidden until
needed, one wait screen. Advanced stays live until the last slice. Each
slice is its own branch off `main`.

Jonathan's call on 2026-09-24: integrate Advanced functions into Simple,
then remove Advanced. Do not drop features to shorten the work.

Counts as of 2026-09-24: 30 `isSimpleMode` branches in four JS files,
272 mode-gated CSS selectors, 54 tests in `tests/test_simple_mode.py`
and 8 in `tests/test_simple_one_page.py`. Search loads
`data_management.js`; deleting `/data-management` must keep that script
(rename to `collect.js` in the removal slice).

Where each Advanced-only feature lands in Simple:

| Advanced feature | Simple home | Slice |
|---|---|---|
| Restore papers set aside for any reason (Clusters only today) | "Set aside" popup, grouped by reason, restore one, a group, or all | 1 |
| Choose an exclusion reason (Clusters page reason select) | Reason chips in the Set aside popup, plus an optional "Why?" on the Not relevant undo toast | 2 |
| Sort by year, journal, newest | Sort chip | 3 |
| Filter results by source | Sources chip, with counts per source | 3 |
| More like my starred | Starred chip gains "Find more like these" once a paper is starred | 3 |
| Exact-word and PICO boosts | Ranking section in the Search options popup; PICO boost shows only when PICO fields hold text | 3 |
| PICO input, paste-a-paper seed | "Search by" switch under the search bar (Question, PICO, Start from a paper) | 4 |
| Export the whole library | Scope choice in Save your work | 5 |
| Choose databases by hand | Databases disclosure in the fetch dialog | 6 |
| PubMed and Europe PMC contact email | Same disclosure, shown only when one of those two is checked; the browser keeps remembering it | 6 |
| Articles by source, papers-by-year chart, coverage (recommended sources that came back empty, Refresh) | "What we fetched" popup | 7 |
| Detect duplicates, auto-resolve, threshold | Duplicates group in the Set aside popup: "Check again" with Strict / Normal / Loose (Normal is today's 0.98), preview, undo | 7 |
| Re-prepare options, model picker | Re-prepare popup: only-missing is the default, model sits in a disclosure | 8 |
| Clusters (generate, browse, set aside a theme) | "Group by theme" popup with preview and undo | 9 |

Already in Simple, and staying where they are: Quick screen, the
screening report, and the result count and year range (Search options
popup, `static/js/search.js`).

- Tasks, in this order:
  - Slice 0: `tests/test_advanced_parity.py` with one row per feature in
    the table. Each row names the Simple control and starts expected-to-fail.
    Later slices flip their own rows. The removal cannot merge while any
    row still fails. Before writing it, check the table against the
    2026-09-21 control inventory: a feature with no row is a feature the
    test does not protect.
  - Slice 1 (first, data safety, about a day): Simple "Set aside" list
    for every exclusion reason, with restore. Today
    `GET /api/screening/excluded` returns only `article_id` and `source`
    for one reason (default `low_relevance`). Change it to accept every
    reason and return title, year, source, and reason. The three calls in
    `simple_tools.js` and the one in `data_management.js` stop asking only
    for `low_relevance`. Restore uses existing `POST /api/screening` include.
    On 2026-09-21 that was 60 duplicate copies in 5 accounts, plus every
    Not relevant (`off_topic`) once its instant Undo is gone. Tests: set
    aside as duplicate, `off_topic`, and `low_relevance`, list all three,
    restore one, assert it is back in search. Browser-check against a
    copy of an account that has hidden duplicates. The silent 0.98
    resolve stays; the threshold control moves in slice 7.
  - Slice 2: exclusion reason chips (about half a day). Simple sets only
    `off_topic` (Not relevant) and `low_relevance` (Narrow it down) today,
    so a Simple student's screening report has two categories; the chips
    add the PRISMA-style ones (wrong population, wrong study type,
    language, too little information).
  - Slices 3 to 8: result chips and ranking (3), search-by switch (4),
    whole-library export (5), fetch databases and contact email (6),
    What we fetched plus duplicates (7), re-prepare and model (8). Each
    is half a day to a day and a half. Search state gains one `filters`
    shape that the chips draw from. PMID/DOI and study type move inside
    the abstract disclosure with the result chips.
  - Slice 9: Group by theme (2 to 3 days). Last fold before removal.
    First a throwaway prototype on a real library with screenshots, to
    settle layout and labels before the real build. Clustering runs
    inside the request today (`api_create_clusters` awaits
    `run_in_thread`), so the page waits with no progress; move it to a
    background job behind the one wait screen before every student gets
    the button. Reuses the existing cluster endpoints. Preview and undo
    through the existing screening endpoints, same pattern as Narrow it
    down.
  - Slice 10: remove Advanced in one pull request (about 2 days). Delete
    `/data-management`, `/statistics`, `/clusters` and their templates
    with a 301 to `/search`. Delete the `ui_mode` and `ui_mode_seed`
    cookies (`app/routes/auth.py`, `app/routes/pages.py`), the mode
    branch in `theme-init.js`, `setUiMode` and the toggle in `common.js`,
    the 30 `isSimpleMode` branches, and the 272 CSS selectors. Rewrite
    the tests in `tests/test_simple_mode.py` and
    `tests/test_simple_one_page.py` as one-behaviour tests. Move "About
    this page" copy into the feature guides
    (`app/content/feature_guides.py`). The helpdesk `ui_mode` column
    stays for old rows and stops being written. Rename
    `data_management.js` to `collect.js` in the same PR; Search keeps
    loading it. A browser whose saved `uiMode` is `advanced`, or unset
    (`theme-init.js` treats unset as Advanced), gets a one-time notice
    that the layout changed; the mode lives in `localStorage`, so the
    notice is client-side. `spec.md` rewrite of the two-mode lines needs
    approval in this slice.
- Every slice, before its PR: drive it in Chromium on a throwaway
  server (never the live `users.db`), in all five looks light and dark
  for anything visual; measure contrast where colour is added; break each
  new test once on purpose; check the commit's claims with Jev; full
  suite green. After merge: pull the live checkout and restart the
  service.
- After slice 10: watch 301 hits for a week, then prune dead CSS.
- Pending Jonathan (does not block slice 1):
  - Old URLs: 301 to `/search` (recommended) or 404. From 2026-09-08 to
    2026-09-24 the three pages got 38 requests and only 6 rendered; the
    rest were redirects, so students have these links saved.
  - Removal version: 6.0.0 proposed (three pages and a mode disappear)
  - `spec.md` two-mode lines at removal (Required Behavior, User
    Experience, Acceptance Criteria)
- spec.md drift until the removal lands: the Simple / Advanced mode
  bullet and its nav lines (Required Behavior), the Simple and Advanced
  examples (User Experience), and the two-flow lines in Acceptance
  Criteria still describe two modes
- Complete when: every function a student could reach only in Advanced
  is on the Search page under Simple's rules; the parity test is all
  passing; no `data-mode`, `uiMode`, or `ui_mode` reference remains in
  `app/`, `static/`, `templates/`, or `tests/` except the helpdesk
  history column; spec.md describes one flow
- Status: [ ] planned. Slice 1 is the next code. Slices 0 and 1 do not
  wait on the pending calls.

## Backlog (unscheduled)
- Make `pyright app` blocking in CI after clearing the current error backlog
  (56 errors, 6 warnings on 2026-09-12)
- Tell all three AI prompts (`_REFINE_SYSTEM`, `_ASK_SYSTEM`, Reader) that the
  abstract is data, not instructions; one change covering all three
- Startup warning when `user_data/ai_settings.json` exists and no AI env is set
- Prune CSS left by the reverted split-pane work (stylesheet is 8,396 lines
  on 2026-09-20)
- A test that parses the look list in `app/content/looks.py`,
  `static/js/theme-init.js`, and `templates/partials/look_picker.html` and
  fails when they differ; today the three match only by hand
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
