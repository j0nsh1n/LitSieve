# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

The open phase is the host work from `docs/AUDIT_2026-10-15.md` section
23. Phases 19 to 22 and 23's code tasks (23.4's `.env.example`, 23.5) are
done on `fix/search-ranking` and `fix/audit-rest` (not yet pushed).
Phase N matches audit section N, and each task names the finding ids
(`16.1`, `18.4`, ...) that hold the evidence and file locations. Cite
those ids in branches and PRs, and mark a finding `Fixed in #NN` in the
audit when its PR merges.

## Phase 23 — Host
Audit section 23. The deploy, account cap, study aid, offline model loads and
the deploy record are done on the host (2026-10-16); what is left needs the
Cloudflare dashboard or new keys.
- Tasks:
  - (23.2) Let an external uptime check reach `/health`: find what
    challenges it (Cloudflare Security → Events, path `/health`) and add a
    skip rule for that path. Bot Fight Mode on the free plan cannot be
    skipped by a rule, only turned off
  - (23.4) Optional source keys when wanted: `S2_API_KEY`,
    `OPENALEX_API_KEY`, `NCBI_API_KEY`, and `NASA_ADS_TOKEN` (NASA ADS
    reports unavailable without it)
- Complete when: an external check reads `/health` as healthy
- Status: [ ] open

## Backlog (unscheduled)
- Persistent job records, so Admin Overview's job and source-error counts
  survive a restart (they say "since the last restart")
- Prune `auth_events` and expired token rows (audit 20.5; they only grow)
- Control edges: input and button borders (`--rule`, `--edge`) are 1.2 to
  2.1:1 against their background in every look, under the 3:1 WCAG asks
  for UI components; a `--control-edge` token across all seven looks
  (found 2026-10-16 while fixing the Broadsheet and Catalog dark palettes)
- Night light: accent text on the accent-soft chip is 4.47:1
- Laya cut-offs from real use: after Phase 19 has been live a few weeks,
  read `laya topic-area feedback` log lines and set `MIN_BEST` /
  `SECOND_RATIO` (`app/routes/laya.py`); spot-check Laya-tagged study
  types on real libraries before lowering `LAYA_MIN_P` (0.85)
- Looks beyond palette: per-look structure changes (`app/content/looks.py`
  calls this a later job)
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Prune `auth_events` and expired token tables; decide what account delete
  removes from the support tables (audit 20.5)
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
