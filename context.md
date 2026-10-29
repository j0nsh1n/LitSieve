# context.md — LitSieve

## Current State
- Tunnel maintenance (2026-10-26): host RPM `cloudflared-2026.10.4-1.fc44`
  was already installed. Restarted `cloudflared-litpilot-token.service` to
  replace its running 2026.10.3 process with 2026.10.4. Four connections
  registered; public and loopback `/health` returned HTTP 200. Cloudflare's
  eMudhra advisory requires 2026.10.2 or later. A separate system-wide
  `cloudflared.service` was in an auto-restart loop; it was not changed.
- App version **6.0.0**, released 2026-10-12. GitHub release `v6.0.0` (at
  `25356cb`) holds the tour video (1080p and 4K); the README opens with its
  poster. Live at `https://www.litpilot.org` from the production checkout,
  `main` through #106 (2026-10-16). The bare `litpilot.org` has no DNS record.
- Python **3.14** (Dockerfile, CI, Render, Ruff target).
- Latest full suite (2026-10-29, `fix/access-bounds-visibility`):
  **2127 passed** in 166.41 s, no skips or xfails. `ruff check .` clean;
  `pyright app` **0 errors**, 6 optional-import warnings (CI blocks on
  errors).
  `pip-audit` (2026-10-14): no known vulnerabilities; ROCm torch/triton are
  un-auditable. No dependency lockfile.
- P2.8: a starred Search card with no open copy listed, and no P2.4 open
  other copy, can show "Different work you can read (N)" (at most 3).
  Neighbors come from stored embeddings through `search_similar` (same path
  as more-like-starred / seed), cosine floor 0.45, same-work and set-aside
  rows dropped. Eligible neighbors are sorted by cosine before the cap of
  3, so a year filter cannot drop a closer undated paper. The client loads
  suggestions when the disclosure opens. The difference line uses year,
  stored type, and `question_concepts` on the current Search question. JSON
  route `POST /api/articles/different-work` takes one seed, a 1,000-character
  question, and at most 50 entries per filter list. Same-DOI lookup reads a
  key/DOI projection first. Open-copy existence uses `has_open_copy` before
  the five-copy display cap. Search.js cache-bust is `20261029a`.
- P2.4: a starred Search card with no open copy listed can show other listed
  copies of the same work (same-record locations, same DOI including
  set-aside rows, merged extra URLs). One batched JSON route, no schema
  change, cap five. Same-work DOI lookup uses `normalize_doi` on stored
  rows. Trailing-slash origins share one URL key. The client mounts copies
  only on a starred none_listed card and keeps a page request when another
  card is starred. Each listed URL keeps "Open copy listed" if any stored
  occurrence of that URL meets the P2.3 open rule, including after five
  copies are already selected. A merged-in copy uses that source's
  `oa_status` and `best_oa_url` in provenance. Missing evidence leaves it
  unlabeled. The copies payload includes `has_open_copy`.
- P2.3 shows an access label on Search cards from stored OA fields, with a
  Free to read filter next to Type. Closed cards keep every reporting
  source. Open labels need a real HTTP(S) host. Crossref needs a
  recognised CC licence identifier and version. The chip sits outside the
  source/type tags that Catalog and collapsed phone Table rows hide.
  style.css cache-bust is `20261029a`.
- P1.7 shows a type chip on Search cards and a Type filter next to Sources.
  The filter runs before ranking and reads only `work_type`. Ranked hits get
  that column in one batched query. Null and unknown types have no chip.
  "Type not stored" keeps legacy rows. No type filter leaves ranking as it
  was.
- P1.8 adds `tools/eval_search.py` (capture, replay, score, labelsheet) and
  five committed questions under `tools/bench/`. Replay snapshots now copy
  stored `work_type`, `doi` and `container_title` from the corpus row after
  ranking. The `baseline_v1` corpus and replay output live in
  `~/HealthDatabaseAccess-scratch/bench/` and are not in git. P1.9 labels
  are in `bench/labels_final/`. P2.1 adds `app/services/question_concepts.py`.
  Search uses it for the P2.8 difference line.
- P2.5a adds `tools/eval_laya_groups.py`. It scores Laya relevance groups on
  the dev split of the frozen top 30. The test split is not scored. The
  write-up is `~/HealthDatabaseAccess-scratch/bench/p25a_results.md`. The
  best run that stays under a 5% harmful-error rate sorts 16 of 91 dev papers
  and does not improve ndcg@10. The report lists each question's ndcg@10
  and relevant@10. No group setting is ready to show students. The one lead
  is F2 (decomposed yes/no per concept): with the different-group cut at
  0.65 it sorts 38 of 91 papers, puts 2 of 27 good papers in different
  (over the 5% cap), and still raises ndcg@10. The dev slice has only 2
  how_why papers, so it is too small to calibrate four groups.
- P2.2 re-ran the word-match sweep on the 15-question `baseline_v2` corpus.
  The chosen setting (`bonus_w0.2_bm25_keywords`) beat today's ranking on
  dev (ndcg@10 0.4381 vs 0.3973) and lost on test (0.5712 vs 0.5755), with
  Q1, Q5 and Q14 dropping more than 0.05. Search ranking is unchanged. Sweep
  notes: `~/HealthDatabaseAccess-scratch/bench/p22_dev_sweep_v2.md`.
- P1.6 stores Collect inputs and Search questions in the library database
  (`fetch_runs`, `question_log`), about 50 rows each. Writes come from
  `_run_multi_fetch` (background and sync, including cancel and error) and
  from `/api/search`, seed, starred, and Narrow it down preview. Contact
  email and API-key shaped strings are stripped. Clones drop the tables.
  Start over deletes the rows. Replace-fetch staging does not touch them.
  Admin and support routes do not read them. A failed write is logged and
  the request still succeeds.
- P1.5 merges a later copy of the same work into the stored row: DOI first,
  a DOI conflict blocks title merge, title match needs year ±1 plus compatible
  structured author and container (legacy `journal` counts), and generic
  titles never title-match on either side. Known full given names must agree;
  initials still match the expanded name. Edited books use the same vetoes as
  books. Empty metadata including year and authors is filled; title and
  abstract are left alone. `skipped_duplicates` still counts merged-or-identical
  rows; `merged` counts rows that gained a field or a new location. The fetch
  report names sources that only found papers already in the library.
- One `/search` workspace replaces the two UI modes. Old `/data-management`,
  `/statistics`, and `/clusters` URLs 301 to Search; a read-only legacy
  preference check supplies a one-time layout notice.
- Empty Search offers topic selection and fetch (sources and optional contact
  email in the fetch popup); fetch and preparation share one wait screen, then
  Narrow it down offers apply/skip. Search by offers Question, PICO and a
  paper seed; sort/source/type/starred chips keep the ranking query; More holds
  reports, duplicates, re-prepare, Start over, Set aside and Group by theme;
  Save your work exports visible results or the whole library.
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
  pagination, requests and retry waits. Pages already fetched survive any
  later error, a source that returns just after the budget keeps its papers,
  and a `Retry-After` longer than the time left fails at once. Progress
  reports queued/running/done states and elapsed time per source. Every
  source, PubMed included, goes through `HttpClient`; a 2xx body that is not
  JSON (a bot wall) is a typed `network` error with a sentence.
- P0.1 sanitizes DOAJ query syntax and encodes one URL path segment, escapes
  HAL Solr syntax, and escapes PLOS terms after boolean tokenization. DOAJ
  and HAL reject blank or punctuation-only topics as `bad_query` before a
  request; source reports explain unreadable search words in plain English.
  No keyword rewriting, schema or ranking change.
- P0.2 removes fake-journal fallbacks, excludes known placeholders from
  RIS, BibTeX and APA, cleans Crossref titles and containers, and corrects
  the publication-year hint. Repository raw journal recovery remains.
- P1.4 exports follow each record's type. RIS `UR` prefers the DOI, `L2` is
  only a listed open copy, and the discovery page goes in `N1`. APA uses
  `https://doi.org/<doi>` for every DOI. Zotero imports RIS `GEN` as a
  journal article; BibTeX `@misc` is the generic type. ERIC non-journal
  rows store the issuing organization as publisher.
- P1.1 adds nine nullable work-metadata fields, nonunique DOI indexes,
  `article_extra` and its staging mirror, and a shared article column list
  for readers, inserts and replace fetches. The provider-record helper stores
  UTF-8 JSON only when its zlib-compressed size is at most 4096 bytes.
  Search ranking uses the original article columns; API responses omit unset
  metadata keys. Quota is unchanged; clones keep article fields but exclude
  `article_extra`.
- P1.2 fills those fields on new OpenAlex, Crossref and DOAJ fetches, and
  writes provenance, locations and a trimmed provider record into
  `article_extra`. Search, ranking, exports and older rows are unchanged.
- P1.3 fills the same columns on new fetches from ERIC, PubMed, Europe PMC,
  bioRxiv, medRxiv, Semantic Scholar, HAL, OpenAIRE, Zenodo, arXiv, PLOS,
  ClinicalTrials.gov and NASA ADS. Exports, ranking, search filters and the
  UI stay unchanged.
- New support-view/ticket records omit mode; old history remains readable.
- Host (2026-10-16): `MAX_TOTAL_ACCOUNTS=100` (27 real accounts then); the
  study aid is `LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:14b` on the
  system Ollama service (port 11434, runs as user `ollama` with its own
  store; the model was imported from `/var/mnt/games/LLM_Models`, which
  `OLLAMA_MODELS` names for an app-started Ollama). `HF_HUB_OFFLINE=1` is a
  drop-in, `~/.config/systemd/user/litsieve-uvicorn.service.d/hf-offline.conf`.
  A detached rollback and deploy each wrote their own `operator_deploys`
  row (actor `phase23-check`). Cloudflare runs I'm Under Attack mode for
  the site; a rule sets Security Level to Essentially Off for `/health`
  only, so external checks get 200 while other paths still challenge
  non-browser clients. Semantic Scholar, OpenAlex and
  PubMed take optional host keys (`S2_API_KEY`, `OPENALEX_API_KEY`,
  `NCBI_API_KEY`); production sets none, so Semantic Scholar mostly answers
  429 and OpenAlex shares one free daily budget per IP.
- Code scanning is clean: route error messages are the app's own sentences
  (`app/errors.py`, `UserError` and `sentence_for`), shipped 2026-10-14.
- Full audit 2026-10-15: `docs/AUDIT_2026-10-15.md`, two independent passes
  (lead and a blind Grok pass) merged. Sections 16 to 23 match roadmap
  Phases 16 to 23; findings have ids (`16.1`, ...) that tasks and PRs cite;
  mark a finding `Fixed in #NN` when its PR merges. Every finding in
  sections 16 to 23 is fixed (#93 to #106, 23.2 on Cloudflare) except
  the optional source keys (23.4) and the bare `litpilot.org` record.
- Admin (`/admin`) is four tabs with the hash as its address (`#accounts/u/<id>`,
  `#accounts/<queue>`). Account actions come from `ACTIONS` in
  `app/routes/admin.py`: the template draws the buttons and `_begin_action`
  applies the reason and confirm rule; `tests/test_admin_actions.py` keeps
  them equal. Notes, sign-in events and the timeline page 25 at a time. The
  Tickets tab (`#tickets/<status>`, `#tickets/t/<id>`) lists, reads, replies
  and sets status over the four `/api/admin/tickets*` routes. The Host tab
  reads `GET /api/admin/host` (backup folder, `logs/watchdog_state.json`,
  disk, Laya `/health`, study-aid state) and `/api/ops/deploy-state`. Overview
  tiles come from `GET /api/admin/queue-counts` (SQL totals, the queue page's
  predicates) and the activity card from `GET /api/admin/activity`.

## Repo Landmarks
| Path | Role |
|------|------|
| `app/main.py` | FastAPI app, lifespan UMAP warm-up, static mount |
| `app/core.py` | Process state: user_db, pipeline cache, jobs, limiter, guest purge |
| `app/routes/` | pages, auth (incl. guest), admin, ops, support, libraries, shares, corpus, search, exports, ai, reader |
| `app/operator/` | named Ship actions (staging worktree, no shell interpolation) |
| `app/services/` | pipeline, embeddings, clustering, summarize, llm, reader_mode / facts / verify, citations, mailer |
| `app/storage/` | database, libraries, shares, user_db, quota, dbconn, helpdesk, ops_audit |
| `app/fetchers/` | 16 public sources + `base.py` (HTTP, `json_of`, `clean_text`), `terms.py` and `querytext.py` |
| `app/content/` | source_catalog, feature_guides, sample_corpus, ui_flags, looks |
| `templates/` + `partials/` | Jinja shell + Search/guest partials |
| `static/` | vanilla JS/CSS (no npm); cache-bust `?v=` |
| `tests/` | pytest; policy in `tests/README.md` |
| `docs/` | DEPLOY, SELFHOST, plans, SCALE_NOTES |
| `tools/` | backup, watchdog, bench_scale, eval_search, eval_laya_groups, encrypt_databases, operator |

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
- **Run record** (`fetch_runs`, `question_log`): private to the library file;
  not cloned; Start over clears it
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
- Student starting-point product: 16 free sources; CORE was removed for rate
  limits and DBLP (2026-10-16) for its bot wall and missing abstracts. Old
  `dblp` papers still link and show their name; a saved request naming a
  retired source drops it (`RETIRED_SOURCES`).
- bioRxiv and medRxiv search Europe PMC's preprint index
  (`SRC:PPR AND PUBLISHER:"bioRxiv"`): their own API has no search and lists
  30 posts a request. Papers stay keyed by DOI and link through doi.org.
- A blank contact email sends no address to the sources (no placeholder).
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
- Job slots are per (account, library, task), at most two running per
  account (`MAX_JOBS_PER_ACCOUNT`); pages poll `/api/progress?library_id=`.
  Finished jobs go to `job_records` in `users.db` (Admin Overview's 24-hour
  failures); the storage sweep prunes them, sign-in events (90 days) and
  tokens a week past expiry.
- Sample-paper vectors and key points are saved under
  `USER_DATA_DIR/.cache/sample-embeddings/` by the first guest prepare; the
  file name hashes the model and the embedded text, so edits make a new file.
- Field and button borders use `--control-edge` (text 58% into surface),
  declared on the controls so it follows local colors; `--rule` stays the
  divider hairline.

## Session Handoff
- **Date:** 2026-10-29. Branch `feat/word-bonus`, PR #122. Merged
  `origin/main` (`266195e`) and re-ran the P2.2 word-match sweep on the
  15-question `baseline_v2` corpus, dev split only. Chosen setting
  `bonus_w0.2_bm25_keywords` beat today's 0.7/0.3 TF-IDF ranking on dev
  (ndcg@10 0.4381 vs 0.3973) and lost on the one test pass (0.5712 vs
  0.5755). Q1, Q5 and Q14 dropped more than 0.05 on test, so the product
  ranking, card copy, CSV columns and spec ranking sentence stay as on
  main. The PR keeps the sweep ranker in `tools/eval_search.py` and
  `app/services/lexical.py`. Search.js and style.css cache-bust stay
  `20261029a`.
- Validation (production venv, this worktree, no install): `ruff check .`
  clean, `pyright app` 0 errors / 6 optional-import warnings, pytest 2133
  passed in 183.79 s. Scratch is
  `~/HealthDatabaseAccess-scratch/pytest-fix-a2-rerun`. Sweep notes:
  `~/HealthDatabaseAccess-scratch/bench/p22_dev_sweep_v2.md`.
- Open items remain the optional source keys, bare `litpilot.org` DNS record,
  and unscheduled roadmap backlog. Ship staging was last recorded at
  `522ff7e`. P1.9 labels are done: a three-model panel plus the owner's
  review of 29 rows, in `~/HealthDatabaseAccess-scratch/bench/labels_final/`
  and `labels_final_v2/` (not in git). The evidence redesign from #126
  follows in a separate PR.
- **Next step:** independent review of PR #122. Do not merge from the
  builder.
