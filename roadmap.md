# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

No phase is open. The 2026-10-15 audit (`docs/AUDIT_2026-10-15.md`,
sections 16 to 23) is fixed and deployed (#93 to #106); its findings keep
their ids (`16.1`, `18.4`, ...) for anyone tracing a change back.

## Backlog (unscheduled)
- Field test 2026-10-27 (`docs/FIELD_TEST_2026-10-27.md`, audit and phased
  plan in `docs/SEARCH_AUDIT_2026-10-27.md`):
  - DOAJ rejects any query containing `?`;
  - keep each record's type, DOI and open-access status, and export by type
    instead of always `JOUR`;
  - stop using source or repository names as the journal;
  - let books and chapters without abstracts through;
  - rank by the question's relationship, not only its topic (benchmark first);
  - decide on a Library of Congress primary-source channel
- Optional source keys on the host when wanted (audit 23.4): `S2_API_KEY`,
  `OPENALEX_API_KEY`, `NCBI_API_KEY`, and `NASA_ADS_TOKEN` (NASA ADS
  reports unavailable without it)
- Laya cut-offs from real use: after Phase 19 has been live a few weeks,
  read `laya topic-area feedback` log lines and set `MIN_BEST` /
  `SECOND_RATIO` (`app/routes/laya.py`); spot-check Laya-tagged study
  types on real libraries before lowering `LAYA_MIN_P` (0.85)
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Decide what account delete removes from the support tables (tickets,
  notes, admin actions, sign-in events); today they keep the deleted
  account's id, and only sign-in events age out (90 days) (audit 20.5)
- Trust older papers' open-copy fields again: per-row trust for never-merged
  legacy rows; a clone marker the encryption tool preserves; lazily marking
  pre-existing clones. Starting point is the round-4 review of PR #128
  (`reviews/b6_sol_r4.md`).
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
