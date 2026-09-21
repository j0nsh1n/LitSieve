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
  - `chmod 600` `users.db` and its `-wal`/`-shm`, the TLS key, and
    `mailersend-smtp.txt`; `go-rwx` on `secrets/` and `user_data/`

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
Planned 2026-09-17 to follow the Workshop round, which shipped in 5.5.0. Simple's rules apply
to every moved function: one URL, popups only on tap, plain words, preview
before apply with one-click undo, hidden until needed, one wait screen.
- Tasks, one branch each off `main`, in this order:
  - First, before anything is removed: a Simple "Set aside" list that shows
    papers excluded for every reason, not only `low_relevance`, with restore.
    Today the Clusters page is the only screen that can restore any other
    reason: on 2026-09-21 that was 60 duplicate copies in 5 accounts, plus
    every Not relevant (`off_topic`) once its instant Undo is gone. It also
    covers duplicates ("N duplicates set aside" in the funnel); the silent
    0.98 resolve stays, the threshold control goes
  - Search chips: Years and Sources popovers, Newest first toggle, More like
    starred chip once a paper is starred, export-whole-library option in the
    export panel, PMID/DOI and study type moved inside the abstract
    disclosure; search state gains a `filters` shape the chips render from
  - Fetch dialog gains a Databases disclosure (topics still pick the
    defaults); the What we fetched popup gains per-source counts, coverage,
    and year spread, replacing the Data Management and Clean up cards
  - Re-prepare: only-missing becomes the default; embedding model picker
    leaves the UI (env default stays)
  - Clusters prototype gate: throwaway Group by theme popup, density only,
    on a real library with screenshots, then keep or drop; if kept, preview
    and undo through the existing screening endpoints
  - Remove Advanced in one wave: delete `/data-management`, `/statistics`,
    `/clusters` and their templates with a 301 to `/search`; delete the
    `ui_mode` and `ui_mode_seed` cookies (`app/routes/auth.py`,
    `app/routes/pages.py`), the mode branch in `theme-init.js`, `setUiMode`
    and the toggle in `common.js`, about 40 `isSimpleMode` branches across
    four JS files, 176 mode-gated CSS selectors flattened and 7 removed, the
    `-advanced` copy twins, and guide text that names both modes
    (`app/content/feature_guides.py`); rewrite the 52 tests in
    `tests/test_simple_mode.py` as one-behaviour tests; the helpdesk
    `ui_mode` column stays for old rows and stops being written
- Proposed drops, pending Jonathan's call: PICO fields, paste-a-paper seed
  input, lexical and PICO boost radios, results count, embedding model
  picker, duplicate threshold, similarity badge, email-on-fetch-finish (no
  account has a recovery email as of 2026-09-17)
- Also pending: clusters keep or drop after the prototype; release version
  (6.0.0 proposed, three pages and a mode disappear); old URLs redirect
  (proposed) or 404
- spec.md drift once the removal lands: the Simple / Advanced mode bullet
  and its nav lines (Required Behavior), the Simple and Advanced examples
  (User Experience), and the two-flow lines in Acceptance Criteria describe
  two modes (needs approval)
- Complete when: every function a student could reach only in Advanced is
  either on the Search page under Simple's rules or in the recorded drop
  list; no `data-mode`, `uiMode`, or `ui_mode` reference remains in `app/`,
  `static/`, `templates/`, or `tests/`; spec.md describes one flow
- Status: [ ] planned, not started

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
