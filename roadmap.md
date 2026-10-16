# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

The open phases are the fix work from `docs/AUDIT_2026-10-15.md`, in the
order to take them: AI and exports, then the host. Phases 19 to 21 are
done on `fix/search-ranking` and `fix/audit-rest` (not yet pushed).
Phase N matches audit section N, and each task names the finding ids
(`16.1`, `18.4`, ...) that hold the evidence and file locations. Cite
those ids in branches and PRs, and mark a finding `Fixed in #NN` in the
audit when its PR merges.

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
  - (22.6) `HIDE_AI_BUTTONS` also refuses the three AI routes, so hidden
    means off and the host key is not spent; write that into `spec.md`
    (decided 2026-10-16)
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
