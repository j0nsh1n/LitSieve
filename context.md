# context.md — LitSieve

## Current State
- App version **6.0.0**, released 2026-10-12. GitHub release `v6.0.0` (at
  `25356cb`) holds the tour video (1080p and 4K); the README opens with its
  poster. Live at `https://www.litpilot.org` from the production checkout at
  `0374605` (2026-10-14). The bare `litpilot.org` has no DNS record.
- Python **3.14** (Dockerfile, CI, Render, Ruff target).
- Latest full suite (2026-10-14): **1021 passed**, no xfails; all 15 parity
  rows pass. `ruff check .` clean; `pyright app` **0 errors**, 6 optional-import
  warnings (CI blocks on errors). `pip-audit` (2026-10-14): no known
  vulnerabilities; ROCm torch/triton are un-auditable. No dependency lockfile.
- One `/search` workspace replaces the two UI modes. Old `/data-management`,
  `/statistics`, and `/clusters` URLs 301 to Search; a read-only legacy
  preference check supplies a one-time layout notice.
- Empty Search offers topic selection and fetch; source choices and optional
  contact email are in the fetch popup. Fetch and preparation share one wait
  screen, then Narrow it down offers apply/skip before Search.
- Search by offers Question, PICO and a paper seed. Sort/source/starred chips
  preserve the ranking query. More holds reports, duplicates, re-prepare,
  Start over, Set aside and optional background Group by theme. Save your work
  offers visible results or whole-library scope exports.
- Result identifiers/study type are inside the abstract. Stars, notes,
  Not relevant/reasons/Undo and one-paper AI study aids remain available.
- Seven account looks (Workshop, Broadsheet, Lab, Night, Catalog,
  Observatory, Reading room), each a preset students fine-tune; light/dark
  remains a browser preference. Account opens as a dockable panel over any
  page for signed-in users. Shared assets carry dated `?v=` values.
- Laya sidecar (`tools/laya_worker.py`, port 7880) is socket-activated and
  exits after 5 idle minutes; Search wakes it. Its checkpoint is uncalibrated
  for questions with 11+ options (topic areas has 13).
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
  Semantic Scholar runs without an API key, so it sometimes answers 429; the
  pipeline logs it and continues with the other sources.
- GitHub code scanning lists 51 open alerts: 50 routes return `str(e)` of a
  controlled `ValueError` in JSON `detail`, and the login redirect is already
  sanitised by `_safe_next_url`. A fix is in progress (one helper for route
  error messages).

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
  and `appearance` (JSON of settings changed on top of the look)
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
- **Date:** 2026-10-14. **Branch:** `docs/freeze-6.0`. Final audit before
  the freeze: tests, lint, types, pip-audit, version copies, release assets,
  secrets, backups and the watchdog all checked clean. The account panel
  (PR #85), Laya idle-exit, and the README tour video (PR #86) are merged
  and live; the brag scratch, `opencode.json` and the merged branches are
  deleted.
- Host notes: the LAN's primary DNS server (192.168.12.132) times out, so
  cloudflared logs a DNS refresh error every 5 minutes but stays connected.
  `litpilot.org` needs an apex record or redirect rule in Cloudflare.
- Still open: Phase 14 polish, Phase 15 Laya calibration, the Phase 4 and
  11 host checks, and the code-scanning alerts above.
- **Next step:** merge the code-scanning helper PR, then freeze.
