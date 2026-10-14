# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

## Phase 4 — Operate a live instance
Shipping changed the risk profile: there are real accounts with real data on a
home desktop, and the link has been shared publicly.
- Tasks:
  - Turn on the account cap: the code shipped, but `MAX_TOTAL_ACCOUNTS` is
    unset on the host, so registration is still open
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
- Complete when: a detached deploy on the host has been seen writing its
  `operator_deploys` row to the live `users.db`, and a console rollback has
  been seen closing its own record
- Status: [ ] open

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
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
