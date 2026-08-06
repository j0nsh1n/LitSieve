# Changelog

All notable user-visible changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow Semantic Versioning for app version strings
(`app/main.py` / `GET /health`).

## [Unreleased]

### Added
- Daily backups of `users.db` and `user_data/` (`tools/backup.py` +
  `litsieve-backup.timer`). Databases are copied through the SQLite online
  backup API and integrity-checked before and after archiving; archives land
  outside the repo, are pruned to `BACKUP_KEEP`, and are written `0600` because
  they contain user data and `SECRET_KEY`.
- JavaScript syntax checking in the test suite. There is no npm or build step,
  so a broken browser script previously shipped with every Python test green.

### Fixed
- The Re-prepare card no longer appears while the automatic prepare is still
  running after a fetch. Progress is shown on the fetch bar during the chain,
  so the card had nothing to display and only advertised a "Re-prepare" action
  for work already in progress.
- Simple mode now offers a "Next: Clean up your papers" shortcut once papers
  are ready, instead of requiring a scroll back to the nav.
- All templates request the same `?v=` build of `theme-init.js` and
  `style.css`. Only `base.html` had been bumped, so returning visitors on the
  public pages (login, register, landing) kept a cached older script.

## [4.5.0] - 2026-08-05

### Added
- **Simple / Advanced UI mode** (client preference in `localStorage.uiMode`,
  applied pre-paint via `theme-init.js` as `data-mode`). New accounts seed
  Simple; existing accounts stay Advanced until they toggle.
- **Clean up** page (was Duplicates): duplicates, **Quick screen** (rank against
  a research question and screen out least-related papers with undo), and the
  screening report in one place.
- Per-result **Not relevant** on Search (`off_topic` exclusion).
- Auto **prepare-for-search** after a successful multi-source fetch (both modes).
- AI Refine “Save these as key points” stores `origin=ai` so rewrites survive
  re-search and append-fetch until a replace-fetch clears the library.
- Landing and `/learn/*` guides updated for the new workflow.
- Health watchdog (`tools/watchdog.py` + timer) for local app + Cloudflare
  tunnel connectivity alerts.
- Dev isolation defaults in `run_dev.sh` (`USERS_DB`, `USER_DATA_DIR`, `LOG_FILE`)
  so local work cannot touch live accounts.

### Changed
- Reading mode retired; Simple/Advanced occupies that nav control.
- Nav in Simple mode: Data Management → Clean up → Search (Clusters remains
  available by URL / Advanced).
- Mobile nav layout rebuilt so brand, steps menu, and controls fit on small
  screens.

### Fixed
- Fetch→prepare auto-chain reliability (`waitForJob` no longer resolves on a
  pre-start idle slot).
- Deploy note: new API routes (e.g. Quick screen) require a uvicorn restart.

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
