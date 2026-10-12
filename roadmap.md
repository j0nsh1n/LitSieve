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
- Status: [ ] in progress. Restore drill done 2026-09-25 from
  `litsieve-20260925-120511.tar.gz` (25 accounts, 23 libraries, 5,494
  papers, every database intact, app served from the copy). Open:
  - set `MAX_TOTAL_ACCOUNTS` in `.env` and restart; the cap ships unset,
    which means no cap
  - set `LLM_PROVIDER`, `OLLAMA_MODEL`, `OLLAMA_HOST`, `OLLAMA_MODELS` in
    `.env` and restart: 5.4.0 stopped reading `user_data/ai_settings.json`,
    so the built-in study aid has been off for every student since the
    15 September restart (the buttons now hide until this is set)

## Phase 11 — Audit follow-ups
Left over after v5.4.0. Findings: `docs/CODE_AUDIT_2026-09-06.md` and the
follow-up audits of 2026-09-12 and 2026-09-17 (session record).
- Tasks:
  - Confirm on the host that a detached deploy writes its `operator_deploys`
    row to the live `users.db` (the fix is in code; not yet confirmed on the host)
  - [x] Run rollback detached like deploy. `POST /api/ops/rollback` runs as a
    child of the web service through `run_action`, and the unit sets no
    `KillMode`, so the `systemctl --user restart` inside `_do_deploy` stops
    it before `_finish_deploy`; the record is left interrupted and no audit
    row is written (read from the code on 2026-09-20, not reproduced)
- Complete when: a detached deploy on the host has been seen writing its
  `operator_deploys` row to the live `users.db`; a console rollback closes
  its own record
- Status: [ ] open

## Phase 12 — UX round 2 leftovers
Presentation items from the 2026-09-17 audit of the airy glass restyle.
- Tasks:
  - [x] Drop m2 split-pane triage (Jonathan's decision, 2026-10-09).
    The design was reverted from `57b7624` by `41fa5b9`; no matching local
    branch remains, and a read-only remote heads check found none either.
- Complete when: the decision is recorded and the branch is merged or
  deleted
- Status: [x] complete 2026-10-09

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
  - Slice 0 (`tests/test_advanced_parity.py`) and slice 1 (the Set aside
    list) shipped 2026-09-25. Each later slice flips its own parity rows.
    Note for slices that touch screening: Undo, Start over, and Re-prepare
    ask `/api/screening/excluded?reason=low_relevance` on purpose; they
    must restore only Narrow it down's group, never duplicates or Not
    relevant.
  - [x] Slice 2: exclusion reason chips (completed locally 2026-10-09). Simple sets only
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
    Slices 3 to 8 are complete locally (2026-10-09).
  - [x] Slice 9: Group by theme (completed locally 2026-10-09). Last fold before removal.
    First a throwaway prototype on a real library with screenshots, to
    settle layout and labels before the real build. Clustering runs
    inside the request today (`api_create_clusters` awaits
    `run_in_thread`), so the page waits with no progress; move it to a
    background job behind the one wait screen before every student gets
    the button. Reuses the existing cluster endpoints. Preview and undo
    through the existing screening endpoints, same pattern as Narrow it
    down.
  - [x] Slice 10: mode removal completed locally 2026-10-09. Removed
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
- Jonathan approved permanent 301 redirects to Search, version 6.0.0,
  and the concrete one-flow spec rewrite; that rewrite is applied.
- Complete when: every function a student could reach only in Advanced
  is on the Search page under Simple's rules; the parity test is all
  passing; no active mode preference, cookie, or conditional layout remains.
  Read-only legacy notice/history compatibility and regression assertions
  remain; spec.md describes one flow
- Status: [x] code complete locally 2026-10-09. Slices 2–10 are integrated,
  independently reviewed, and tested. The final suite has 966 passing tests,
  with all 15 parity rows passing and no xfails. Required ops/fetch checks
  have 67 passing tests; Ruff and Pyright have no errors. Headless previews
  cover all five looks light/dark at 375px and desktop at 1280px with fallback
  fonts. Authenticated browser automation disconnected, so the remaining live
  interaction review is incomplete. Nothing new is pushed, merged, or deployed.

## Phase 14 — Looks: polish

- Tasks:
  - Tune the dark palettes of Broadsheet and Catalog
  - Closed result rows show no star or note marker
  - More like this shows no visible banner after re-ranking
  - Save note says Saved before the request finishes
  - The Narrow it down step returns after Skip
- Complete when: every item above is fixed and checked in the browser in the
  looks it touches, light and dark, with ink contrast still at or above
  4.5:1 where colour changes
- Status: [ ] open

## Phase 15 — Laya switches: calibrate on real use
- Tasks:
  - Read `laya topic-area feedback` log lines after a few weeks and set
    `MIN_BEST` / `SECOND_RATIO` (app/routes/laya.py) from how often students
    kept Laya's areas
  - Spot-check Laya-tagged study types on real libraries before lowering
    `LAYA_MIN_P` (0.85)
- Complete when: both cut-offs are set from logged use, not the 2026-10-12
  sample evaluation
- Status: [ ] open

## Backlog (unscheduled)
- [x] Clear app type errors and make `pyright app` blocking in CI (2026-10-09)
- [x] Tell all three AI prompts (`_REFINE_SYSTEM`, `_ASK_SYSTEM`, Reader) that
  source text is data, not instructions (2026-10-09)
- [x] Startup warning for legacy global AI settings without host configuration
  (2026-10-09)
- [x] Audit CSS left by the reverted split-pane work: `41fa5b9` already
  removed the full 149-line block; no split-pane selectors remain (2026-10-09)
- [x] A test that parses the look list in `app/content/looks.py`,
  `static/js/theme-init.js`, and `templates/partials/look_picker.html` and
  fails when they differ (2026-10-09)
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
