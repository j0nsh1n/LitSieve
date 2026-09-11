# Changelog

All notable user-visible changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow Semantic Versioning for app version strings
(`app/main.py` / `GET /health`).

## [Unreleased]

### Changed
- Refreshed the look with an airy glass style: frosted cards on a light
  wash, a softer blue accent, pill buttons and nav chips with frost fill
  and hairline edges (no ink outlines), Source Serif 4 on headings, and
  denser search results. Layout and workflow are unchanged.

## [5.3.1] - 2026-08-31

### Fixed
- **Reader Mode verification could not fail on three of its checks.** Found by an
  independent audit of 5.3.0 (`docs/READER_MODE_AUDIT.md`):
  - Cached explanations kept showing verdicts from an older, noisier verifier.
    The version stamp that exists to invalidate them was never bumped, so a
    warning a student saw could outlive the rule that produced it. Explanations
    regenerate the next time they are opened.
  - The negation check read the explanation's "What this study does not show"
    section, which is always phrased negatively, so it counted as preserved
    negation for free while the abstract's actual negative finding went missing.
  - The hedging check treated "about", "roughly" and "on average" as caution.
    Those describe how exact a number is, not how confident a claim is, so an
    explanation could assert a flat causal claim and still pass.
  - The number check took whichever figures came first, which are usually
    statistical diagnostics, so a study's headline result could be dropped
    without a warning. Figures stated in an abstract's conclusion are now required.

### Changed
- Dropped the entity-retention check. It skipped on 10 of 12 test abstracts and
  could only trigger in a case the storage keys already prevent, so it took a row
  in the verification report without ever saying anything useful.

## [5.3.0] - 2026-08-29

### Added
- **Explain this study** (Reader Mode): on a paper in Search or Clean up, students
  can ask for a structured plain-language reading of that abstract (high school
  or general reader). Automatic checks flag dropped numbers, lost hedging, and
  similar issues as warnings — they never claim the explanation is “verified”.
  Generated text stays visually distinct from the abstract. Hidden with
  `HIDE_AI_BUTTONS`.

## [5.2.0] - 2026-08-28

### Added
- **Sieve wait screen:** the Simple-mode fetch/prepare screen now shows an
  animated sieve - grains pour in, the pan rocks, a few fall through - with
  status lines in a panning voice ("Scooping up your first batch", "Washing out
  the repeats"). Screen scaled up for legibility.
- **Sieve brand mark:** SVG favicon and a nav wordmark mark drawn from the same
  pan. The previous favicon predated two redesigns.
- **Empty states** on Search, Clean up and Clusters now show an empty pan
  instead of text alone.

### Changed
- **Source Serif 4 for headings**, replacing Public Sans. Body and UI stay on
  Source Sans 3 - same superfamily, so the two harmonise. Self-hosted WOFF2,
  net payload change +4.6 KB.
- **Advanced mode matches Simple:** progress bars share the Simple bar's height
  and tokens; progress copy rewritten in the same voice, with counts kept as a
  secondary detail line rather than dropped.
- Copy swept across Clean up and Clusters: "screened out" is now "set aside",
  matching what Simple mode already said.

### Fixed
- Empty-state guidance told students to press "Prepare papers for search"; no
  such control exists. It now names "Re-prepare Papers" (also fixed in the
  sample-corpus toast).
- Progress bar gradient hardcoded #fff, which broke in dark mode.
- Removed a shimmer animation that ran forever against a flat colour after the
  gradient was dropped - it animated background-position with no gradient to move.

### Removed
- Public Sans (both WOFF2s and its licence), unused once headings moved to a serif.

## [5.1.0] - 2026-08-22

### Added
- **Admin student-stuck tools:** stuck fetch/prepare job queue; clear a
  dead job slot or retry prepare on that account’s current library;
  set/replace email and send verification (never auto-verifies); time-boxed
  per-account quota bump; delete one named library. Reason + timeline on
  every action.
- **Read-only student view** from a selected account (password re-auth,
  15-minute cookie, persistent banner, mutating routes blocked).
- **Service snapshot** on Admin (version, uptime, SMTP/AI/quota, job
  counts, bounded source-error counts). Retry last fetch.
- **Soft-disable / re-enable** with student-facing explanation and optional
  expiry.
- **Ask for help** tickets (safe diagnostics only) with admin status and
  replies (timeline + email if SMTP is on).
- **Incident banner** (draft / publish / expire / disable / rollback) and a
  versioned editor for support links, help text, topic-preset labels, and
  known-issue notices (plain text / JSON, no HTML).
- **Ship** (`/ops`, operator only): edit files in a staging worktree, review
  the diff, validate, commit (`remote-edit:`), deploy with health-check
  rollback, and redeploy a previous SHA. Named actions only; no shell
  interpolation. Re-auth required before save/deploy. Workbench UI; optional
  Grok Build CLI against staging (no shell tools). Unlock duration is
  configurable (5 min–8 hours) with a manual Lock. The timer pauses while
  Ask Grok is running so the console does not lock mid-run. `/ops` is a
  VS Code-like workbench (activity bar, file tabs, panel, status bar).
  Python files in the editor use Dark+/Light+ token colors.

### Changed
- **Teal Soft** visual pass: accent `#0f766e` (dark `#5eead4`) on cool paper
  `#f7f8f8` / `#ffffff`. Self-hosted Public Sans for titles; Source Sans 3
  for body/UI (wider at small sizes). Page canvas is a flat fill (no grain
  or radial wash). Primary buttons are teal-filled. Radii are 8 / 12 /
  18px. Search similarity is a ring (same
  `--score-pct` as before). Star controls use an SVG icon, not a glyph.
  Amber caution is `#96640c` (AA on white). Theme toggle uses sun/moon
  icons and a circular wipe (color fade where View Transitions are
  unavailable; off when reduced-motion is set). Hero, Simple/Advanced,
  and the eight guides stay in place.

### Fixed
- Simple Search field stays visible on phones after Narrow it down
  (no longer hidden while screening state is unknown; stacked query +
  Search on small screens).
- Feature Guide renders one theme toggle (duplicate control dropped).
- Simple Search score ring stays centered (grid overlay, not flex).
- Score number sits inside the ring hole (larger concentric meter, small
  tabular figures; 0.000–1.000 no longer clip the arc).

## [5.0.3] - 2026-08-17

### Added
- **Admin** at `/admin` (`ADMIN_USERNAMES`). Host snapshot, search one
  account, unlock,
  revoke sessions, email a password reset or one-time sign-in link, add a
  note, and download a per-student support packet. Actions are logged.
  The console never lists the full roster or sets a password.

### Changed
- Failed sign-ins lock an account after 8 tries (15 minutes). Admin
  unlock clears that.
- **Simple fetch** asks for a **topic** (not the full research question).
  The question is entered in Narrow it down, then used to search the
  collection.
- **Narrow it down** opens as a required step before Search your
  collection. Apply or skip to continue; closing the dialog does not
  skip it.
- **Simple fetch** shows a wait screen (fetch, then prepare) instead of
  the collect form. Narrow it down opens after that finishes.
- Simple collect: **Narrow your lens** (required general areas), no quick
  packs, and **Find articles on your topic** instead of Fetch Articles.

### Fixed
- Narrow it down no longer sits on a gray empty overlay. It is a page
  step (same background as the rest of Simple) until you apply or skip.
- After Narrow it down, Search keeps **Set aside N papers** + **Undo**
  in the same strip row and type as Re-prepare / Start over.
- **Guest / demo Search:** sample papers are source `sample`, which is not
  a Search checkbox. Ranking no longer requires a source chip when none
  are available. `/guest` starts preparing the sample in the background
  and Search waits on that job instead of showing an empty collect form.
- Account data paths reject `..` / slashes; admin routes only accept a
  UUID account id (CodeQL path-injection / exception leak on `/admin`).

## [5.0.1] - 2026-08-14

### Added
- Public homepage and `/learn` guides use the Phase 10 broadsheet masthead,
  boxed path/guide cards, and a dark/light toggle (no `common.js` on public
  pages).
- Simple Search asks **how many papers** (1–50) and an optional **year range**
  in a dialog before ranking. Advanced still uses the rail.

### Fixed
- **Start over** now keeps starred and noted papers and removes the rest
  immediately (`POST /api/start-over`). If those papers are already
  prepared, you stay on Search (prepare / Narrow it down are not undone).
  An empty leftover collection still opens collect so you can fetch.
- **Library switcher after idle:** rehydrates the nav library select on tab
  focus / visibility change so long idle no longer drops the active library.
- **Fetch progress stall hint:** when a source makes no progress for ~45s,
  the progress label explains that large sources can pause without hanging.

- Replace-fetch that hits the storage cap keeps the current library
  instead of swapping in a partial new collection.
- Sync and background fetches share one per-account job slot so two
  Start-over fetches cannot mix staging rows.
- Start over keeps embeddings only when title and abstract are unchanged
  (changed text is re-prepared).
- **Start over** clears the last search query/results, Show chips, and
  Narrow it down set-asides. Stars, notes, and saved AI key points stay
  on papers that come back.
- Simple result cards show **key points** and **Refine with AI** again.
- Homepage masthead: brand left, theme toggle right; LitSieve title centered
  without reusing Search’s `.pagehead`.
- **Search broadsheet layout:** Simple Search now matches the approved mockup
  composition — kicker + title + count on one line, notice as a single
  italic band, full-width one-line query + Search, results with the Save
  rail on the right. Result cards use score / journal · year / tags, then
  title and text-link actions. Segmented Get papers → Search is back in
  the Simple masthead.
- **Simple Get papers step** goes to `/search?collect=1` (collect state), not
  `/data-management`.
- **Advanced query toggle** sits with the top search bar; PICO/seed open
  under it. Rail keeps ranking options and starred search.
- Simple rail **Collected / Duplicates / Screened out / Kept** no longer
  double-count duplicates.
- Simple nav is one page again (no 1 / 2 stepper). The query bar is a
  single-line field joined to Search (no textarea spinner).
- Library (and other) `<select>` option lists use dark ink on paper so
  dark-mode cream text is not washed out until hover.
- Simple mobile nav: brand + tools on the first row, library on its own
  full-width row (no more 5rem “Parkinso” chip).
- LitSieve wordmark in the app nav links to `/` (the public homepage).
- Simple nav shows an unnumbered **Search** tab (no 1/2 stepper).
- Light/dark toggle interpolates only background-color, color, and
  border-color at 160ms (no lag from transitioning background images).

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
