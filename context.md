# context.md — LitSieve

## Current State
- App version **5.4.0** (`app/main.py`, `GET /health`). Product name **LitSieve**.
- Example public deployment pattern: HTTPS at the edge (e.g. Cloudflare Tunnel)
  → `uvicorn` HTTP on `127.0.0.1:7860` only. Operator sets `PUBLIC_BASE_URL` and
  `DEBUG=false` with a real `SECRET_KEY` in gitignored `.env`.
- Python **3.14** (Dockerfile, CI, Render, ruff `py314`).
- Lint: `ruff check .` — partial select (E9/F63/F7/F82/F401/F541/E401/I).
- Types: `pyright app` via `pyrightconfig.json` (basic); CI **continue-on-error**
  (report-only). Last recorded baseline: **61 errors, 6 warnings** (2026-08-02).
- Tests: `SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q` — prefer
  `./venv` for sqlcipher. Count drifts with the branch; re-run before release.
- UI: Simple/Advanced via `localStorage.uiMode` + `data-mode` (theme-init pre-paint).
  Simple: one `/search` page (empty collect vs papers). `/data-management`
  redirects in Simple. Fetch asks for a topic; wait screen covers fetch +
  prepare (animated sieve, rotating copy, no live source rows). Bar maps
  fetch 0–60 and prepare 60–90; Narrow it down holds at 90% (apply or skip),
  then a short finish leg into Search. After papers exist, topics/fetch hide;
  Start over is a popup. Advanced: full steps including Clean up + Clusters;
  its progress bars share Simple height/tokens, with counts on a detail line.
  Airy glass tokens: accent `#2563eb` (dark `#93b4ff`), 10/16/22px radii.
  Source Serif 4 headings, Source Sans 3 body/UI (self-hosted). Hybrid frost
  cards on a soft wash, score ring on Search. Sieve pan as favicon, nav
  mark, and empty-state illustration (Search / Clean up / Clusters).
  CSS cache-bust `style.css?v=20260912k`. Mobile app nav is a one-row
  brand + menu; steps and tools open in a drawer.
- Reader Mode: **Explain this study** on Search/Clean up cards — structured
  plain-language reading of one abstract, cached per
  `(article_id, source, audience)` in the library DB, warnings-only verifier.
- Final Simple nav is one unnumbered Search tab (no stepper; collect via Start over); that contract supersedes the original Phase 10 “Simple/guest tests pass unchanged” criterion.
- Guest: `/guest` → sample corpus, auto-prepare (set `GUEST_AUTO_PREPARE=0` in
  tests), multi-source fetch 403, purge after 30 minutes. Search treats an
  empty source filter as “all sources” when no source chips are enabled.
- Operator Ship: `/ops` (same `ADMIN_USERNAMES`). Staging worktree edits,
  named actions (`tools/operator/*.py`), validate → commit → deploy with
  auto-rollback on failed `/health`. Never edits the live checkout in place.
  Unlock is timed (operator-chosen) with a manual Lock; Ask Grok holds the
  unlock so the timer cannot expire mid-run.
- Admin: `ADMIN_USERNAMES` unlocks `/admin`. Host snapshot, one-account lookup, unlock,
  session revoke, emailed reset / one-time login, notes, action log.
  Student-stuck tools: job queues, clear stale, retry fetch/prepare, set-email,
  quota bump, one-library delete, read-only student view, soft-disable,
  tickets, incident banner, versioned student-facing copy.
  Restart after changing `.env`.
- Ops: systemd user unit for uvicorn; optional backup + watchdog timers — see
  `docs/SELFHOST.md` and `docs/DEPLOY.md` (generic operator runbooks).
- Dev isolation: `./run_dev.sh 7861` → throwaway DB/data/log paths.
- Known gaps: no dependency lockfile; pyright not green/blocking; account cap
  still open (Phase 4 partial).

## Repo Landmarks
| Path | Role |
|------|------|
| `app/main.py` | FastAPI app, lifespan UMAP warm-up, static mount |
| `app/core.py` | Process state: user_db, pipeline cache, jobs, limiter, guest purge |
| `app/routes/` | pages, auth (incl. guest), admin, ops, support, libraries, shares, corpus, search, exports, ai, reader |
| `app/operator/` | named Ship actions (staging worktree, no shell interpolation) |
| `app/services/` | pipeline, embeddings, clustering, summarize, llm, reader_mode / facts / verify, citations, mailer |
| `app/storage/` | database, libraries, shares, user_db, quota, dbconn, helpdesk, ops_audit |
| `app/fetchers/` | 17 public sources + `base.py` |
| `app/content/` | source_catalog, feature_guides, sample_corpus, ui_flags |
| `templates/` + `partials/` | Jinja shell + Simple/guest partials |
| `static/` | vanilla JS/CSS (no npm); cache-bust `?v=` |
| `tests/` | pytest; policy in `tests/README.md` |
| `docs/` | DEPLOY, SELFHOST, plans, SCALE_NOTES |
| `tools/` | backup, watchdog, bench_scale, encrypt_databases, operator |

## Domain Model
- **User** (`users.db`): username, password hash, token_version; optional recovery
  email; `is_guest` + created_at for demo accounts
- **Library**: named collection; meta in `libraries.json`; SQLite
  `user_data/<uid>/libraries/<lib_id>/articles.db`
- **Article** key `(article_id, source)`: title, abstract, year, authors, journal
- **Embeddings / clusters / screening / notes / key_points / reader_explanations**: per library DB
- **Share / clone code**: registry in users.db; join copies library (not live)
- **Jobs**: fetch / embed progress per user; bind to active library at start
- **AI settings**: per account `{USER_DATA_DIR}/{user_id}/ai_settings.json`
  (keys encrypted). Host env is the deploy default. A student base URL
  never rides with the host API key.
- **Jobs**: fetch / embed progress per user; bind to an explicit owned
  library id when the client sends one, otherwise the active library at start
- **AI settings**: server-wide `user_data/ai_settings.json` (keys encrypted)
- **Quota**: disk under `user_data/<uid>/` vs `MAX_USER_STORAGE_MB`; optional
  per-account `quota_limit_mb` + `quota_limit_until` overlay (helpdesk bump)
- **Support view**: httponly `support_view` cookie overlays identity; admin JWT
  stays in `access_token`. Mutations blocked except Search ranking.
- **Tickets / notices**: `support_tickets`, `site_notices`, `site_content` in
  users.db (same file as accounts)
- **Ops**: `operator_audit` / `operator_deploys` in users.db; staging dir
  `LITSIEVE_STAGING` (default `~/.local/share/litsieve/staging`)

```
User 1---* Library 1---* Article
              |            +-- embeddings, screening, notes, key_points
              +-- jobs (fetch/embed) bind explicit library_id or active
ShareCode *---1 Library (owner); redeem → clone Library for joiner
Guest User (is_guest) → sample corpus only; purged by age
```

## Non-Obvious Decisions
- Student **starting point** product: 17 free sources; CORE removed (rate limits)
- Multi-library is the multi-collection story; clone codes are optional/power
- AI optional; extractive key points default; one-article Refine/Ask only
- Simple/Advanced is **client-only** (CSS + JS); Advanced must not lose capability
- Phase 6: no auto-clustering; screening ranks vs research question (embeddings)
- Guest accounts: reserved `guest_*` usernames; multi-source fetch 403
- SQLCipher opt-in via `DB_ENCRYPTION_KEY`; plaintext refuses key without migrate
- AI keys: AES-256-GCM `enc:v2:` (Fernet `enc:v1:` still decrypts)
- Duplicate default match strictness **0.98**
- Starred search **includes** starred papers in results (centroid ranking)
- Public pages must not load `common.js` (401 redirect); do not extend base.html
- Patch tests against `app.core.*`; enumerate routes via `conftest.route_paths`
- Password hashing is async in routes so bcrypt does not block the single worker
- Rate limiting keys IPv6 on the /64 (`core.client_bucket`)
- Embedding models shared process-wide (`get_shared_model`); validated names
  (`EXTRA_EMBEDDING_MODELS` escape hatch); CSP `style-src 'self'` → no style= in HTML
- Host entry: `app.main:app` port 7860; Linux `./venv`

## Session Handoff
- **Date:** 2026-09-13
- **Branch:** `fix/audit-a01-a11-a15` (PR #65). Version **5.4.0**.
- **Done:** A01 option 2 (per-account AI keys) plus A02, A11–A18 from the
  2026-09-06 audit. Reader verifier is v3 (CI bounds and p-value operators).
  Embedding aliases resolve to the configured repo. HDBSCAN on tiny libraries
  returns one group. Merged PR #64 so the airy glass UI is back on this
  branch (`style.css?v=20260912k`). Simple Search screening counts are a
  two-row funnel (collected, then kept vs removed). Show me what would
  go is a split-pane review of proposed set-aside vs stay, with per-paper
  keep/aside before confirm. Simple result cards have More like this,
  which re-ranks the same collected library from that paper (seed stays
  in the list; no new fetch). UX round 2 m1 (focused Simple Search list)
  and m3 (Account section nav) are in production CSS/HTML/JS, not the
  gitignored mockups. Funnel, split-pane screening, and More like this
  are unchanged.
- **Next:** Roadmap Phase 4 leftover: account cap and restore drill.
  A03–A08 exist on other local branches. spec.md still says AI keys live
  in `user_data/ai_settings.json` (drift, not edited). Spec lists seed
  paper and more like starred, not Simple per-card More like this, and
  does not describe the Simple split-pane screening review, the Simple
  focused-list card chrome, or the Account section nav.
- **Date:** 2026-09-09
- **Branch:** `fix/a06-backup-custom-paths`
- **Done:** Audit finding A06 — `tools/backup.py` discovers the live accounts
  DB via `USERS_DB` and the library tree via `USER_DATA_DIR`, archives them
  under stable `users.db` / `user_data/` prefixes, and `--restore` writes
  them back to those live paths.
- **Next:** A07 (unbounded notes bypass the storage cap). Do not push/PR
  until asked.
- **Date:** 2026-09-09
- **Branch:** `fix/a08-stale-tab-library`
- **Done:** A08 — Search/note/screening/fetch/prepare can bind to an owned
  `library_id` instead of whichever library is currently active. A tab
  that loaded library A reloads if another tab made B active. Tests in
  `tests/test_libraries_http.py`, `tests/test_libraries.py`, and
  `tests/test_static_js.py`.
- **Next:** A09+ of the 2026-09-06 code audit (not started). A06–A08 are
  separate branches off `origin/main` (A08 stacked on A07).
