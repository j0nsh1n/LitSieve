# context.md — LitSieve

## Current State
- App version **6.0.0** (`app/main.py`, `/health`, admin summary and footers),
  completed locally on `fix/ops-rollback-and-fetch-deadline`; nothing deployed.
- Python **3.14** (Dockerfile, CI, Render, Ruff target).
- Latest full suite (2026-10-09): **966 passed**, no xfails. All 15 feature
  parity rows pass. Required ops/fetch suite: **67 passed**.
- `ruff check app tests` and `ruff check .` pass. `pyright app` has **0 errors,
  1 optional Anthropic import warning**; CI blocks on errors.
- The isolated upgraded dependency audit reports no known vulnerabilities;
  custom ROCm torch/triton packages are un-auditable. Production dependencies
  are unchanged. There is no dependency lockfile.
- One `/search` workspace replaces the two UI modes. Old `/data-management`,
  `/statistics`, and `/clusters` URLs return permanent 301 redirects to Search.
  The mode toggle, preference writes, cookies and CSS gates are removed.
  A read-only legacy preference check supplies a one-time layout notice.
- Empty Search offers topic selection and fetch; source choices and optional
  contact email are in the fetch popup. Fetch and preparation share one wait
  screen, then Narrow it down offers apply/skip before Search.
- Search by offers Question, PICO and a paper seed. Sort/source/starred chips
  preserve the ranking query. More holds reports, duplicates, re-prepare,
  Start over, Set aside and optional background Group by theme. Save your work
  offers visible results or whole-library scope exports.
- Result identifiers/study type are inside the abstract. Stars, notes,
  Not relevant/reasons/Undo and one-paper AI study aids remain available.
- Workshop, Broadsheet, Lab, Night and Catalog remain account looks; light/dark
  remains a browser preference. Shared changed assets use `?v=20261009j`.
- Guest sessions use sample papers, cannot fetch public sources and expire
  after 30 minutes. Search includes all available sources when unset.
- Ship rollback dispatches detached when supported, carries its actor, and
  polls completion. Deploy history persistence has database-reopen tests.
- Fetch sources share a configurable 90-second whole-source budget across
  pagination, requests and retry waits. Completed pages survive timeout;
  progress reports queued/running/done states and elapsed time per source.
- New support-view/ticket records omit mode; old history remains readable.
- Known host gaps: live account cap/AI configuration (Phase 4), actual detached
  deployment history completion (Phase 11), and disconnected browser automation.

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
| `app/content/` | source_catalog, feature_guides, sample_corpus, ui_flags, looks |
| `templates/` + `partials/` | Jinja shell + Search/guest partials |
| `static/` | vanilla JS/CSS (no npm); cache-bust `?v=` |
| `tests/` | pytest; policy in `tests/README.md` |
| `docs/` | DEPLOY, SELFHOST, plans, SCALE_NOTES |
| `tools/` | backup, watchdog, bench_scale, encrypt_databases, operator |

## Domain Model
- **User** (`users.db`): username, password hash, token_version; optional recovery
  email; `is_guest` + created_at for demo accounts; `look` (workshop default)
- **Library**: named collection; meta in `libraries.json`; SQLite
  `user_data/<uid>/libraries/<lib_id>/articles.db`
- **Article** key `(article_id, source)`: title, abstract, year, authors, journal
- **Embeddings / clusters / screening / notes / key_points / reader_explanations**: per library DB
- **Share / clone code**: registry in users.db; join copies library (not live)
- **AI settings**: per account `{USER_DATA_DIR}/{user_id}/ai_settings.json`
  (keys encrypted). Host env is the deploy default. A student base URL
  never rides with the host API key.
- **Jobs**: fetch / embed / cluster progress per user; bind to an explicit owned
  library id when the client sends one, otherwise the active library at start
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
              +-- jobs (fetch/embed/cluster) bind explicit library_id or active
ShareCode *---1 Library (owner); redeem → clone Library for joiner
Guest User (is_guest) → sample corpus only; purged by age
```

## Non-Obvious Decisions
- Student starting-point product: 17 free sources; CORE was removed for rate limits.
- Multi-library is the multi-collection story; share codes clone rather than live-share.
- AI is optional; extractive key points remain the default; study aids read one abstract.
- Grouping is optional, runs in the background, and does not itself exclude papers.
- Duplicate strictness: Strict **0.99**, Normal **0.98**, Loose **0.95**.
  Duplicate/theme previews apply selected exclusions with Undo for those papers.
- Guest usernames use `guest_*`; multi-source fetch returns 403.
- SQLCipher is opt-in via `DB_ENCRYPTION_KEY`; wrong keys fail closed.
- AI keys use AES-256-GCM `enc:v2:`; older Fernet `enc:v1:` still decrypts.
- Starred centroid search includes the starred seeds in its results.
- Public pages load theme-init without authenticated common.js APIs.
- Password hashing runs asynchronously; IPv6 rate limits use a /64 bucket.
- Shared embedding models are validated; `EXTRA_EMBEDDING_MODELS` is the
  operator escape hatch. CSP blocks inline style attributes.
- Pipeline references stay held during background jobs; LRU eviction retains
  the owning user's progress while a referenced job is active.

## Session Handoff
- **Date:** 2026-10-09. **Branch:** `fix/ops-rollback-and-fetch-deadline`.
- Original fixes: `5887f2c` detached rollback, `369882e` deploy-history
  persistence tests/host checklist, `3f97f40` source deadlines/partial pages.
- Reliability/security: `053b2a4`. Search migration: `5090a61` Slices 2/3,
  `fc195c1` Search by, `197325d` scoped exports, `807d62e` fetch choices,
  `3270337` reports/duplicates, `76513b9` re-prepare, `2e2f4f4` background themes.
- Slice 10 completes the single Search flow, version 6.0.0, permanent legacy
  redirects, historical support compatibility and the explicitly approved spec
  rewrite. Luna through Codex provided bounded work/review; main reviewed it.
- Final checks: full pytest **966 passed**; required ops/fetch **67 passed**;
  Ruff, JavaScript syntax and diff checks pass; Pyright **0 errors / 1 warning**;
  temporary environment dependency audit is clean with the custom-package skips.
  Intentional regressions were detected in isolated copies, including notice
  preference writes and historical support mode writes.
- Browser evidence: earlier real-route checks cover Slices 2/3, five looks in
  light/dark at 375px, keyboard focus and selected-chip contrast ≥5.04:1.
  Later actual-helper/headless previews cover exports, fetch/report popups,
  preparation, themes and the final collect template. All five final looks
  light/dark fit at 375px; desktop fits at 1280px. Fonts fell back in headless
  previews. Authenticated automation stopped with “No preview automation host
  is available”; remaining real-route/mobile Ship checks are incomplete.
- Theme prototype used a 53-paper isolated real-library snapshot (four groups);
  external APIs, real model quality and host service actions were not exercised.
- Phase 13 code is complete locally. Phase 4/11 host confirmations remain open;
  conditional future backlog items remain unscheduled. Nothing pushed or deployed.
- Artifacts/check logs: `/tmp/litsieve-roadmap-ovp9uE/`. The live checkout and
  services are unchanged; the temporary preview used isolated data and stubs.
