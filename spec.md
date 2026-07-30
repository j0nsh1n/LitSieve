# spec.md — Literature Research Aide

## Problem
Students need a **starting point** for literature review without a full academic
library subscription. This app fetches abstracts from free public databases in
parallel, groups them, screens out noise, finds near-duplicates, ranks remaining
papers by meaning, and exports citations (especially RIS for Zotero). It is
explicitly **not** a complete library search, not medical/legal advice, and not
a substitute for school library databases.

## Intended Users
- **Students** (high school / early college) doing classroom research projects
- **Deployers / teachers** who host a shared instance (env config, optional AI
  keys, storage cap) — not a full LMS product surface

## Required Behavior
- Multi-user accounts (register / login / logout); JWT session; CSRF on mutations
- Each account has **multiple named libraries** (separate paper collections);
  nav switcher sets the active library; jobs bind to the library active at start
- Fetch from **17 public sources** in parallel (background job, cancellable,
  per-source errors); skip abstract-less records
- Prepare papers (embeddings) as a background job; extractive key points default
- Clusters page is the only triage UI (exclude/restore with reason codes)
- Duplicates: detect near-dups, auto-resolve preferred source; screening report
- Search: hybrid rank (semantic + optional lexical), year/source filters, seed
  paper, **more like starred** (starred papers **remain** in the result list),
  notes/stars, export on-screen results as RIS
- Optional AI Refine / Ask: one abstract at a time; never silent bulk rewrite
- Optional library **clone codes** (copy, not live share)
- Optional recovery email (SMTP-gated; verified before trusted) on current product
  path when SMTP is configured
- Fail-closed: corrupt library meta, wrong DB encryption key, quota exceeded
  (HTTP 507 on corpus growth unless `clear_first` recovery path)

## User Experience
- **Web UI** (FastAPI + Jinja2 templates + vanilla JS/CSS under `static/`).
  **No npm / no frontend build.**
- Local run: `./run_dev.sh` → http://127.0.0.1:7860  
  Or: `DEBUG=true SECRET_KEY=… ./venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 7860 --reload`
- Example: log in → Data Management → pick topics/sources → Fetch → Prepare
  Papers → Clusters (screen) → Duplicates → Search → Download RIS
- Health: `GET /health` → `{"status":"healthy","version":"4.3.1"}` (version as of
  this writing; bump when releasing)

## Architecture
- Language/runtime: **Python 3.14** — PINNED in `Dockerfile` (`python:3.14-slim`),
  `.github/workflows/ci.yml` (`python-version: "3.14"`), `render.yaml`
  (`PYTHON_VERSION=3.14`), `pyproject.toml` (`target-version = "py314"`).
- Frameworks (minimum versions from `requirements.txt`; **no lockfile** —
  ranges, not fully frozen):
  - FastAPI `>=0.115.0`, uvicorn `>=0.30.0`, Jinja2, python-multipart
  - sentence-transformers, scikit-learn, optional FAISS, umap-learn
  - PyJWT, bcrypt `>=4.1`, cryptography, sqlcipher3-binary (optional encryption)
  - slowapi, python-dotenv, pytest
- Storage:
  - Per-account SQLite under `user_data/<uid>/libraries/<lib_id>/`
  - Accounts / shares in `users.db` (path via user_db)
  - Optional whole-DB SQLCipher via `DB_ENCRYPTION_KEY` (`app/storage/dbconn.py`)
  - AI API keys in `user_data/ai_settings.json` encrypted AES-256-GCM (`enc:v2:`)
- Major components:
  - `app/main.py` — FastAPI app wiring, lifespan (UMAP warm-up), static mount
  - `app/core.py` — process state: user_db, pipeline LRU, jobs, auth helpers
  - `app/routes/` — pages, auth, libraries, shares, corpus, search, exports, ai
  - `app/services/` — pipeline, embeddings, clustering, summarize, llm, citations, mailer
  - `app/storage/` — database, libraries, shares, user_db, quota, dbconn
  - `app/fetchers/` — one module per public source + base HttpClient
  - `app/content/` — source catalog, feature guides, sample corpus, UI flags
  - `templates/` + `static/` — UI (repo root)
  - `tests/` — pytest suite; `tests/README.md` policy
- External APIs: 17 free academic sources (PubMed, Europe PMC, OpenAlex, arXiv,
  Semantic Scholar, ERIC, CrossRef, DOAJ, ClinicalTrials.gov, NASA ADS with
  token, bioRxiv, medRxiv, DBLP, OpenAIRE, PLOS, HAL, Zenodo). Optional:
  Ollama (local), OpenAI-compatible / Anthropic keys, SMTP for email.

## Security & Privacy
- No secrets in source. Credentials via environment / `.env` (gitignored).
- Dependencies: minimum versions in `requirements.txt` (not fully lockfile-pinned;
  Dependabot is **not** installed in live `.github/` — do not assume auto PRs).
- JWT HttpOnly cookie + CSRF double-submit; password change bumps `token_version`
- CSP / security headers (`app/security.py`); HSTS skipped when `DEBUG=true`
- Per-account storage cap `MAX_USER_STORAGE_MB` (default 500; `0` = off)
- AI optional; extractive key points never silently replaced by LLM
- Research corpora and notes are private to the account (share = clone only)

## Validation & Tooling
- Lint: `ruff check .` — must pass (partial rule set in `pyproject.toml`:
  E9/F63/F7/F82/F401/F541/E401/I; E501/UP/E402 deferred).
- Types: **not configured** in live CI (no pyright/mypy project config). Treat
  as report-only until added with human approval.
- Tests:  
  `SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q`  
  Prefer `./venv`. Install deps: `./venv/bin/pip install -r requirements.txt`
  (includes `sqlcipher3-binary` for encryption tests). CI sets `CI=1` so
  encryption suite hard-fails if sqlcipher missing.
- Docker CI job builds image and hits `/health` and `/` (retries on Hub timeouts).
- Quirk: many tests use `TestClient`; patch `app.core` attributes (e.g. `user_db`),
  not stale imports. Enumerate routes via `conftest.route_paths(app)` (OpenAPI).

## Acceptance Criteria
- [ ] Student can fetch → prepare → cluster/screen → dedup → search → export RIS
      on a local or hosted instance with public sources only
- [ ] Libraries isolate data; clone codes do not grant live write access
- [ ] With SMTP unset, app runs without requiring email; with SMTP set, recovery
      email verification works as designed on this product path
- [ ] `ruff check .` and full pytest (with SECRET_KEY) exit 0
- [ ] CHANGELOG.md updated for user-visible releases
- [ ] Version string in `app/main.py` / `/health` matches release
