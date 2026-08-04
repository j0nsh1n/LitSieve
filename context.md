# context.md — LitPilot

## Current State
- App version **4.4.0** (`app/main.py`, `GET /health`). Product name **LitPilot**.
- Public origin: operator domain via Cloudflare Tunnel (`PUBLIC_BASE_URL` in
  gitignored `.env`; `DEBUG=false` for HTTPS cookies). DuckDNS removed.
- Python **3.14** (Dockerfile, CI, Render, ruff `py314`).
- Lint: `ruff check .` — partial select (E9/F63/F7/F82/F401/F541/E401/I); passes.
- Types: `pyright app` via `pyrightconfig.json` (basic); CI runs it
  **continue-on-error** (report-only): **61 errors, 6 warnings** (2026-08-02).
- Tests: `DEBUG=true ./venv/bin/python -m pytest -q` — **302 passed**
  (2026-08-03; +6 model-registry, +13 model-validation, +15 loop/edges);
  `./venv` for sqlcipher.
- RAM (measured CPU, single uvicorn worker): ~175 MB imports, first model load
  ~1.1–1.4 GB one-time (torch runtime), then **~0 per extra concurrent user**
  since models are shared process-wide. Before sharing: +46 MB/user (MiniLM),
  +330 MB/user (PubMedBERT). Bound: `MAX_LOADED_MODELS` (default 3).
- CI: `.github/workflows/ci.yml` (ruff + pyright report + **pip-audit
  blocking** + pytest + docker), `codeql.yml`. Dependabot config **removed**
  locally (2026-07-30); not necessarily on origin until pushed. spec.md records
  it as deliberate; `pip-audit` now covers the CVE half.
- Dependency audit (2026-08-02): **clean, exit 0**. Local venv `setuptools`
  upgraded 78.1.0 → 83.0.0 (clears PYSEC-2025-49 / PYSEC-2026-3447); CI install
  step now upgrades setuptools too. `torch`/`triton-rocm` are skipped as
  un-auditable (PyTorch index, not PyPI) — skips don't fail without `--strict`,
  so torch CVEs stay a manual check.
- Recovery email: on main (PR #38); MailerSend SMTP in gitignored `.env`
  confirmed working by human. Secrets never committed.
- Deploy: `docs/DEPLOY.md` checklist (SECRET_KEY, SMTP, quota, smoke).
- Known gaps: no dependency lockfile; pyright not yet green / blocking;
  public cloud host env still operator-owned after local Phase 3 docs/smoke.

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
- Password hashing MUST use `hash_password_async` / `verify_password_async` in
  routes. Sync bcrypt (~157 ms) on the single event loop froze the whole app
  during signup bursts; a guardrail test greps `routes/auth.py` for regressions.
- Rate limiting keys IPv6 on the /64 (`core.client_bucket`) — per-address
  keying is bypassable since one client owns a whole /64.
- Public templates (landing/login/register/feature_guide/reset_password/
  verify_email) do NOT extend base.html — head changes must be repeated there.
- Embedding models shared via `embeddings.get_shared_model` registry; the
  `EmbeddingEngine.model` property must NOT cache per-engine (cached pipelines
  would each pin a copy). Safe to share: inference is read-only.
- `EmbeddingsRequest.model` validated against `EmbeddingEngine.allowed_models()`
  (422 on unknown); operator escape hatch `EXTRA_EMBEDDING_MODELS`
  (`name=org/model` or bare path). Stored/DB model names are NOT hard-failed, so
  libraries embedded before the gate keep working.
- Host: Linux `./venv` (ROCm torch possible); entry `app.main:app` port 7860

## Session Handoff
- **Date:** 2026-08-04
- **Branch:** `chore/doc-drift-and-hygiene` (PR #51 + follow-ups)
- **Done:** LitPilot v4.4.0 rebrand; Cloudflare Tunnel for public access;
  **removed DuckDNS** tooling/docs. Tunnel token service on this host.
- **Next:** Point purchased domain at tunnel Public Hostname; set
  `PUBLIC_BASE_URL=https://YOUR_DOMAIN` in `.env`. Rotate exposed tunnel token.
