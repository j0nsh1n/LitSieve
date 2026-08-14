# Changelog

All notable user-visible changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow Semantic Versioning for app version strings
(`app/main.py` / `GET /health`).

## [Unreleased]

### Fixed
- **Search broadsheet layout:** Simple Search now matches the approved mockup
  composition — kicker + title + count on one line, notice as a single
  italic band, full-width one-line query + Search, results with the Save
  rail on the right. Result cards use score / journal · year / tags, then
  title and text-link actions. Segmented Get papers → Search is back in
  the Simple masthead.

## [5.0.0] - 2026-08-13

### Changed
- **Broadsheet radii (Phase 10):** `--radius-sm` / `--radius-md` are 2px / 3px
  (was 4 / 8). Modal bottom sheets use `--radius-md` instead of an undefined
  `--radius-lg` fallback.
- **Dark theme (Phase 10):** warm newsprint charcoal (`#1c1a15` / `#242118`)
  in both the system-dark and `[data-theme=dark]` blocks.
- **Masthead nav (Phase 10):** double ink rule; desktop steps are a segmented
  control with inverted active; article count and library wrap are serif
  italic badges. Mobile menu is unchanged.
- **Search notice band (Phase 10):** “Please note” label, 4px accent spine,
  wash background, serif italic body. Query + Search are one joined boxed
  control. Result count is letterspaced caps.
- **Search result cards (Phase 10):** bordered cards with a teal spine, serif
  score numeral + 3px bar (`--score-pct` unchanged), uppercase meta, tag
  chips, and a hairline actions row.
- **Search rail (Phase 10):** boxed Simple Save panel at desktop (bottom bar
  at ≤900px unchanged). Advanced query cards boxed the same way. Simple rail
  shows Fetched / Duplicates / Screened out / Kept from the existing
  screening-report payload.

### Added
- **Guest demo** (`/guest`): temporary sample-corpus account (no multi-source
  fetch), 30-minute expiry/purge, landing/login CTA. Signed-in sessions are
  never swapped for a guest account.
- **Simple mode on two pages** (Phase 6): Get papers → Search. Inline
  screening card (Low/Medium/High with real counts, apply/undo/skip), silent
  duplicate resolve after auto-prepare, sticky Search export/report panel
  (desktop) and bottom bar (small screens). Clean up and Clusters stay in
  Advanced only.
- Skipped Simple screening remembered per library across reloads (localStorage).
- Account page uses **in-app site modals** for confirm / prompt / alert flows
  (no browser `confirm` / `prompt` / `alert`).
- Daily backups of `users.db` and `user_data/` (`tools/backup.py` +
  `litsieve-backup.timer`). Databases are copied through the SQLite online
  backup API and integrity-checked before and after archiving; archives land
  outside the repo, are pruned to `BACKUP_KEEP`, and are written `0600` because
  they contain user data and `SECRET_KEY`.
- JavaScript syntax checking in the test suite. There is no npm or build step,
  so a broken browser script previously shipped with every Python test green.
- **Search Show chips:** after a search, one-click filters on the current list
  (All, Starred, Has a note, Since last-five-years, plus a chip per source in
  the results). No new search. Export uses the filtered list.
- **Narrow it down** in Simple is a popup: Low / Medium / High, preview, set
  aside, and skip stay; the page only keeps a short button plus undo / Go to
  Search after you decide.
- **Simple Search is home** once papers are prepared: Get papers redirects to
  Search. A one-line strip on Search has Narrow it down, Re-prepare, and Start
  over (Start over opens Get papers with `?collect=1`). Empty libraries still
  open Get papers.
- **Simple is one page:** `/search` is collect (empty) or rank/export (papers).
  `/data-management` in Simple always redirects to Search (`?collect=1` opens
  start-over). Nav has no step 1/2. Topics, fetch form, and coverage hide after
  papers exist; source counts open from the papers chip.

### Changed
- **Start fresh copy (Simple):** the existing replace/add dialog now says notes,
  stars, and saved AI key points stay on papers that come back; papers that do
  not return (and their notes) are deleted. Same buttons, no extra click.
- **Advanced replace-fetch:** a live line next to the Replace radio names the
  paper / note / star / AI key-point counts when the collection is not empty.
  No new modal. Append and empty libraries hide the line.
- **Sample corpus load** now builds the demo list before clearing, so a missing
  sample set cannot wipe the library.
- **Replace-fetch is no longer wipe-first.** New papers land in a staging
  table and replace the library only if at least one paper arrived. Notes,
  stars, and saved AI key points stay on papers that come back; papers that
  do not return (and their notes) are deleted. A failed or cancelled fetch
  leaves the previous collection in place.
- **Simple fetch lock:** after this library has papers, Simple hides the Fetch
  Articles form so a second search is not the main action. A secondary
  **Start over or add papers** control reuses the existing replace/add dialog,
  then the form returns for that one fetch. Re-prepare, the source report,
  screening, and Advanced are unchanged. Guests still cannot fetch.
- **UI revamp Phase 8 (Reading Room A + Workbench B shell):** body-scale
  `.info-text` / larger `.help-text`; Search sticky query rail + results;
  numeric 0–1 score meters; summonable **Help** on Search, Data Management,
  Clean up, Clusters, and Account; Workbench shell splits **workflow steps**
  from **tools** (library / mode / theme / account) in `base.html`; dark
  graphite grounds; denser 380px chrome.
- **UI refresh (Phase 7):** design-system type / spacing / radius scales;
  editorial serif headings and abstracts with hairline card sections; live
  per-source fetch progress; list skeletons; optimistic star / note / Not
  relevant; denser 380px mobile layout; motion vocabulary with reduced-motion
  covering shimmer.
- Simple nav is **one Search page** (no step control). Clean up remains on
  `/statistics` for Advanced.
- Simple post-prepare shortcut is **Go to Search** (replaces the Phase 5
  “Next: Clean up your papers” bar once screening is applied or skipped).

### Fixed
- Simple Search bottom bar no longer covers the last result: padding tracks
  the measured bar height (`--simple-panel-h`) with a 40vh fallback; title and
  lead hide when the panel is a fixed bar.
- Guest **End demo** is a 44px secondary button on its own row (not an inline
  link next to Register) and asks before ending the session.
- Library switcher stays on the nav at ≤380px (article count hides instead).
- Site toasts stack above dialogs (`z-index` 1300 vs modal 1200).
- Mobile nav (≤640px) again exposes **Account**: the profile link was
  `display: none`, so phones could only log out. Shows a compact “Account”
  control that still opens `/account`.
- Fetch on Data Management no longer 405s: a `queueAnimationFrame` typo aborted
  page setup before the form submit handler bound, so Enter/click posted the
  HTML form to the GET-only page. Fixed to `requestAnimationFrame`; form no
  longer uses `method="post"` as a fallback.
- The Re-prepare card no longer appears while the automatic prepare is still
  running after a fetch. Progress is shown on the fetch bar during the chain.
- Source and year bar charts scale to each series max under CSP (`style-src
  'self'`) via `--bar-pct` CSS variables instead of ignored inline widths.
- Share/library panels render their spacing and the **Revoked** badge colour
  again. Five script-injected `style="…"` attributes in `account.js`, `join.js`,
  and `data_management.js` were silently dropped under CSP (`style-src 'self'`
  blocks `style-src-attr`), so join previews and the coverage hint lost their
  margins and the Revoked badge never turned red — it also referenced a
  `--danger` variable the themes do not define. Replaced with real classes
  (`.library-manage-badge.is-revoked` using `--err`, `.join-preview-lead`,
  `.u-m-0`, and the existing `.u-mt-sm`). Runtime `element.style` writes are
  unaffected by CSP and were left alone.
- All templates request the same `?v=` build of `theme-init.js` and
  `style.css`. Only `base.html` had been bumped, so returning visitors on the
  public pages (login, register, landing) kept a cached older script.
- Enter in the fetch query field starts fetch via a real form submit handler.

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
