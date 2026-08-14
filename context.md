# context.md — LitSieve

## Current State
- App version **5.0.1** (`app/main.py`, `GET /health`). Product name **LitSieve**.
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
  redirects in Simple. After papers exist, topics/fetch hide; Start over is a
  popup. Advanced: full steps including Clean up + Clusters. Phase 10
  broadsheet tokens: 2px/3px radii, warm-newsprint dark, masthead nav.
- Guest: `/guest` → sample corpus, multi-source fetch 403, purge after 30 minutes.
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
| `app/routes/` | pages, auth (incl. guest), libraries, shares, corpus, search, exports, ai |
| `app/services/` | pipeline, embeddings, clustering, summarize, llm, citations, mailer |
| `app/storage/` | database, libraries, shares, user_db, quota, dbconn |
| `app/fetchers/` | 17 public sources + `base.py` |
| `app/content/` | source_catalog, feature_guides, sample_corpus, ui_flags |
| `templates/` + `partials/` | Jinja shell + Simple/guest partials |
| `static/` | vanilla JS/CSS (no npm); cache-bust `?v=` |
| `tests/` | pytest; policy in `tests/README.md` |
| `docs/` | DEPLOY, SELFHOST, plans, SCALE_NOTES |
| `tools/` | backup, watchdog, bench_scale, encrypt_databases |

## Domain Model
- **User** (`users.db`): username, password hash, token_version; optional recovery
  email; `is_guest` + created_at for demo accounts
- **Library**: named collection; meta in `libraries.json`; SQLite
  `user_data/<uid>/libraries/<lib_id>/articles.db`
- **Article** key `(article_id, source)`: title, abstract, year, authors, journal
- **Embeddings / clusters / screening / notes / key_points**: per library DB
- **Share / clone code**: registry in users.db; join copies library (not live)
- **Jobs**: fetch / embed progress per user; bind to active library at start
- **AI settings**: server-wide `user_data/ai_settings.json` (keys encrypted)
- **Quota**: disk under `user_data/<uid>/` vs `MAX_USER_STORAGE_MB`

```
User 1---* Library 1---* Article
              |            +-- embeddings, screening, notes, key_points
              +-- jobs (fetch/embed) use active library
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
- **Date:** 2026-08-14
- **Branch:** `fix/start-over-keep-annotated` — PR #57 vs `main`
- **Done:** Start over option B, library rehydrate, fetch stall hint.
  Version **5.0.1**.
- **Next:** Human merges PR #57. `design_mockups/` stays untracked.
