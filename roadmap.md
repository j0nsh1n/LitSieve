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
Audit section 23, and what was still open from running the live instance.
- Tasks:
  - (23.1) Deploy `main` (the admin slices and the fixes above) to the
    production checkout and restart
  - (23.4) Set `MAX_TOTAL_ACCOUNTS` in `.env` and restart; unset means no
    cap and registration is open
  - (23.4) Set `LLM_PROVIDER`, `OLLAMA_MODEL`, `OLLAMA_HOST` and
    `OLLAMA_MODELS` in `.env` and restart, so the built-in study aid is on
    for students again; decide on `NASA_ADS_TOKEN`, `AI_ALLOW_SETTINGS_WRITE`
    and the optional source keys (`S2_API_KEY`, `OPENALEX_API_KEY`,
    `NCBI_API_KEY`); `.env.example` now lists every setting the code reads
  - Run `pip install -r requirements.txt` in the production venv before the
    restart: `anthropic` and `httpx` are now declared (22.2)
  - (23.3) Set `HF_HUB_OFFLINE=1` on the app unit once the model cache is
    complete, so no model load contacts the Hub
  - (23.2) Let an external uptime check reach `/health` (a Cloudflare skip
    rule for that path, or check through the tunnel)
  - Confirm on the host that a detached deploy writes its
    `operator_deploys` row to the live `users.db` and that a console
    rollback closes its own record
- Complete when: the host serves the fixed build, an account cap is
  enforced, students have a working study aid, the log shows no Hub
  requests on model load, and the deploy record has been seen on the host
- Status: [ ] open

## Backlog (unscheduled)
- Job slots per library instead of per account (audit 21.8); for now the
  409 says one job runs per account and a page ignores another library's
  job
- Precomputed sample embeddings so `/guest` does not run an embed job each
  time (audit 21.9)
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
- Precomputed sample-corpus embeddings so a guest start does not run an
  embed job (audit 21.9)
- Prune `auth_events` and expired token tables; decide what account delete
  removes from the support tables (audit 20.5)
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
