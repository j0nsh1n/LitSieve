# Changelog

All notable user-visible changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow Semantic Versioning for app version strings
(`app/main.py` / `GET /health`).

## [Unreleased]

### Added
- Health watchdog (`tools/watchdog.py` + `deploy/litsieve-watchdog.timer`,
  every 5 min). Checks that the app answers locally **and** that the Cloudflare
  tunnel currently holds registered connections, then emails on state changes
  using the existing SMTP settings. Set `WATCHDOG_EMAIL_TO` to receive alerts.
- `USERS_DB` env var for the accounts database path, so a dev server can use a
  throwaway accounts file. `run_dev.sh` now sets `USERS_DB`, `USER_DATA_DIR`
  and `LOG_FILE` to dev-only values **by default** — previously it opened the
  live accounts DB and real paper libraries, so a local test could write into a
  student's library or change a real password.

- Logs are written to a rotating file (`logs/litpilot.log`) as well as the
  console, including uvicorn's access log. Configure with `LOG_FILE`,
  `LOG_LEVEL`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`; total size is capped
  (~30 MB by default) so a home server cannot fill its disk.
- `.env.example` now documents logging plus `MAX_LOADED_MODELS` and
  `EXTRA_EMBEDDING_MODELS`, which shipped earlier undocumented.

### Fixed
- `run_dev.sh` and `tools/setup_cloudflare_tunnel.sh` are executable again;
  `./run_dev.sh` failed with "Permission denied" (mode 644 in git).
- Duplicate usernames and share-code collisions stay clean errors under
  SQLCipher. Three `except sqlite3.IntegrityError` catches stopped matching when
  `DB_ENCRYPTION_KEY` selects the sqlcipher3 driver, turning "username already
  taken" into a 500 on encrypted deployments only.
- `run_dev.sh` no longer passes `--reload-include`, which uvicorn silently
  ignores without `watchfiles` installed.

- Starring or annotating a paper that has left your library now returns a clear
  404 instead of a 500. Reachable from an ordinary stale tab: a "replace" fetch
  or a library switch changes every article id under an already-open results
  page.

### Changed
- Product name **LitPilot** → **LitSieve** (UI, page titles, emails, FastAPI
  title, docs, Docker/Render service names, default log file). The public
  hostname stays `www.litpilot.org` — that is a registrar/Cloudflare fact, not
  a product name — as do the `*-litpilot.service` systemd units already
  installed on the host.

- All 65 `print()` calls in `app/` are now logger calls with levels. Fetcher
  errors in particular were going to stdout, so they had no level, could not be
  filtered, and carried no traceback.

### Security
- `POST /api/search`, `/api/search/seed` and `/api/search/starred` now require
  the CSRF token, matching `/api/notes`. The frontend already sent it on every
  non-GET request, so nothing changes for users.

### Documentation
- Hugging Face **Hub** (where the embedding models come from, ~3.5 GB cached
  under `~/.cache/huggingface`) is now documented in `docs/DEPLOY.md`, including
  that an uncached model downloads *inside* a user's job and that the cache sits
  outside `user_data/` — so it is not covered by the storage quota or by a
  backup of the app directory.
- Corrected "TLS is terminated by the host (Render / HF Spaces)" in `README.md`
  and `app/security.py`: TLS terminates at Cloudflare in the current deployment.
- Removed Hugging Face **Spaces** hosting references, including the Spaces
  config frontmatter in `README.md` (no Space exists; the only remote is
  GitHub). This is the hosting product, unrelated to the model Hub above.
- `roadmap.md`: Phase 3 recorded as actually shipped (live on
  https://www.litpilot.org via Cloudflare Tunnel, no PaaS), plus a new Phase 4
  covering the account cap and backups that going live created.

### Removed
- Server-side `tqdm` progress bars in four fetchers. They drew to the server
  console where nobody could see them (users get progress from the jobs API)
  and their carriage returns would have corrupted the new log file. `tqdm` is
  no longer a dependency.
- Superseded deploy tooling: host cert renewal and :80/:443 helpers (TLS is
  terminated at Cloudflare), and the quick-tunnel script/unit (replaced by the
  named tunnel for www.litpilot.org).
- DuckDNS helpers and docs (updater script, systemd timer/service, examples).
  Self-host public DNS is operator-owned (Cloudflare Tunnel + purchased domain).

## [4.4.0] - 2026-08-03

### Added
- CI dependency audit via `pip-audit` (**blocking**), covering known-CVE
  reporting after Dependabot's weekly auto-PRs were disabled. CI now also keeps
  `setuptools` current, since undeclared runner packages are audited too.
- Self-host deploy notes for Cloudflare Tunnel and optional Caddy
  (`docs/SELFHOST.md`, `docs/DEPLOY.md`).

### Changed
- Product name **Literature Research Aide** → **LitPilot** (UI, emails, docs,
  FastAPI title).
- Embedding models are now shared process-wide instead of loaded once per
  cached pipeline. Concurrent users no longer each pay for a copy of the
  weights: measured on CPU, 10 simultaneous PubMedBERT users dropped from
  ~4.6 GB to ~1.6 GB. Matters most for small self-hosted boxes. Registry is
  bounded by `MAX_LOADED_MODELS` (default 3).
- Startup warnings for missing `SECRET_KEY` (DEBUG) and missing FAISS now print
  plain `WARNING:` text instead of an emoji prefix.

### Security
- `cryptography` floor raised to `>=50.0.0` for CVE-2026-69247 (caught by the
  new pip-audit gate on its first real run).
- Embedding model names in `POST /api/create-embeddings` are now validated
  against the model catalog (HTTP 422 otherwise). Previously an unknown name
  was passed through as a HuggingFace path, so any signed-in user could make
  the server download arbitrary models. Operators can still allow extras via
  `EXTRA_EMBEDDING_MODELS`.
- IPv6 rate limiting keys on the /64 prefix instead of the full address. A
  client is normally handed an entire /64, so per-address keying let anyone
  bypass the login limiter by rotating addresses. IPv4 is unchanged.

### Removed
- Unused `pandas` dependency (declared in `requirements.txt`, imported nowhere).
  Slightly smaller installs; no behaviour change.

### Fixed
- Site no longer stalls for everyone while someone signs in or registers.
  Password hashing (~157 ms) ran on the single event loop, so a burst of
  signups froze all other requests — reported by a user as the site "hanging".
  Measured: 6 concurrent signups took 942 ms and a bystander's page load went
  from 1.6 ms to 933 ms; now 172 ms and 1.3 ms. Hash cost is unchanged.
- `/favicon.ico` and `/robots.txt` are served instead of returning 404.

## [4.3.2] - 2026-08-01

### Added
- Governance files: `agents.md`, `spec.md`, `roadmap.md`, tracked `context.md`,
  and this `CHANGELOG.md`.
- Live `.github/` from former templates: CodeQL workflow, pyright in CI
  (report-only until backlog cleared), markdownlint (non-blocking).
- Optional verified recovery email (username separate from email; SMTP-gated)
  — PR #38; human-confirmed with MailerSend SMTP.
- `tools/send_test_email.py` SMTP smoke CLI (PR #49).
- Host deploy checklist: `docs/DEPLOY.md` (SECRET_KEY, DEBUG, SMTP, quota,
  SQLCipher, smoke commands); README links to it.

### Changed
- Dependabot weekly auto-PRs disabled (removed `.github/dependabot.yml`).
- Expanded screening tests; purged unused pipeline/clustering/embedding/HTTP
  helpers; share create bounds single-sourced from `app.storage.shares`.

### Fixed
- Article PICO / similarity labels no longer lift or scale on hover — PR #36.

## [4.3.1] - 2026-07-26

### Fixed
- Search abstract layout (full width) and whole-word query highlighting.
- Starred papers included in “more like my starred” results.

## [4.3.0] - 2026-07-26

### Added
- Per-account storage quota (`MAX_USER_STORAGE_MB`, default 500; `0` = off).
- AES-256-GCM encryption for AI API keys at rest (`enc:v2:`).
- Docker CI smoke job (`/health` and landing).

### Changed
- Python 3.14 for CI, Docker, and Render.
- Passwords via bcrypt directly (passlib removed).
- FastAPI lifespan for UMAP warm-up (replaces deprecated `on_event`).

### Fixed
- Quota mid-fetch status is `quota_stopped` (not user cancel).
- `clear_first` fetch/sample allowed when over quota to recover space.
