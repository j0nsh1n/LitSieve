# context.md — Literature Research Aide

## Current State
- App version **4.3.1** (`app/main.py`, `GET /health`).
- Python **3.14** (Dockerfile, CI, Render, ruff `py314`).
- Lint: `ruff check .` — partial select (E9/F63/F7/F82/F401/F541/E401/I); passes.
- Types: `pyright app` via `pyrightconfig.json` (basic); CI runs it
  **continue-on-error** until ~76 app/ errors are cleaned (report-only).
- Tests: `DEBUG=true ./venv/bin/python -m pytest -q` — **268 passed**
  (2026-07-30; screening suite expanded); use `./venv` so sqlcipher runs.
- CI: `.github/workflows/ci.yml` (ruff + pyright report + pytest + docker),
  `codeql.yml`. Dependabot config **removed** locally (2026-07-30); not
  necessarily on origin until pushed.
- Recovery email: on main (PR #38); MailerSend SMTP in gitignored `.env`
  confirmed working by human. Secrets never committed.
- Known gaps: no dependency lockfile; pyright not yet green / blocking;
  Phase 3 deploy checklist / host stabilize still open.

## Repo Landmarks
| Path | Role |
|------|------|
| `app/main.py` | FastAPI app, lifespan UMAP warm-up, static mount |
| `app/core.py` | Process state: user_db, pipeline cache, jobs, limiter |
| `app/routes/` | pages, auth, libraries, shares, corpus, search, exports, ai |
| `app/services/` | pipeline, embeddings, clustering, summarize, llm, citations, mailer |
| `app/storage/` | database, libraries, shares, user_db, quota, dbconn |
| `app/fetchers/` | 17 public sources + `base.py` |
| `app/content/` | source_catalog, feature_guides, sample_corpus, ui_flags |
| `templates/` + `static/` | Jinja + vanilla JS/CSS (no npm) |
| `tests/` | pytest; see `tests/README.md` |
| `run_dev.sh` | local server port 7860, `./venv` |
| `docs/SCALE_NOTES.md` | measured latency; parked scale opts |

## Domain Model
- **User** (`user_db` / `users.db`): username (not filesystem path), password hash,
  token_version; optional recovery email fields when feature enabled
- **Library**: named collection per user; meta in `libraries.json`; SQLite
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
```

## Non-Obvious Decisions
- Student **starting point** product: 17 free sources; CORE removed (rate limits)
- Multi-library is the multi-collection story; clone codes are optional/power
- AI optional; extractive key points default; one-article Refine/Ask only
- SQLCipher opt-in via `DB_ENCRYPTION_KEY`; plaintext refuses key without migrate
- AI keys: AES-256-GCM `enc:v2:` (Fernet `enc:v1:` still decrypts)
- Duplicate default match strictness **0.98**
- Starred search **includes** starred papers in results (centroid ranking)
- Reading mode does **not** cap abstract width at 68ch (full card width)
- Public pages must not load `common.js` (401 redirect)
- Patch tests against `app.core.*`, not frozen imports; routes via OpenAPI
  `conftest.route_paths`
- Host: Linux `./venv` (ROCm torch possible); entry `app.main:app` port 7860

## Session Handoff
- **Date:** 2026-07-30
- **Branch:** `main` (local uncommitted screening tests + earlier unpushed
  Dependabot/docs commits; behind origin on #49 merge until human allows sync)
- **Done:** Expanded screening tests (DB + pipeline + HTTP); full suite 268
  green. Dead-code audit findings noted (not deleted): `_load_excluded_cached`,
  `get_cluster_assignments`, `calculate_similarity_matrix`, share bound consts,
  `HttpClient.get_json`.
- **Next:** Phase 3 host stabilize when human wants it. No push until asked.
