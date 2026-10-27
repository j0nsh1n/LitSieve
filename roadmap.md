# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

No phase is open. The 2026-10-15 audit (`docs/AUDIT_2026-10-15.md`,
sections 16 to 23) is fixed and deployed (#93 to #106); its findings keep
their ids (`16.1`, `18.4`, ...) for anyone tracing a change back.

## Backlog (unscheduled)
- Field test 2026-10-27 (`docs/FIELD_TEST_2026-10-27.md`): export every
  record's real type (RIS `BOOK`/`CHAP`, BibTeX `@book`) instead of always
  `JOUR`; stop using a source's name ("OpenAIRE", "HAL", "PLOS") as the
  journal; rank by the relationship the question asks about, not only its
  topic (build an evaluation set from that run first); decide on a
  primary-source collection
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
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
