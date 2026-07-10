# context.md — startup primer

Read this first on a fresh conversation. Update when things change materially.

## What this is
**Literature Research Aide** (**v3.1.0**) — multi-user FastAPI app for
**teachers & students**: fetch from **12 academic sources** in parallel → embed →
semantic search, clustering, screening triage, cross-source duplicate detection.
Per-user SQLite; JWT + bcrypt; CSRF; rate limits. Docker / HF Spaces / Render
(port 7860).

Stack: FastAPI, sentence-transformers, FAISS (optional), sklearn, Plotly, SQLite.
Local: `./run_dev.sh` or `uvicorn main:app`. Tests:
`SECRET_KEY=x DEBUG=true python -m pytest -q` (**39** tests expected).

---

## Architecture map
| File | Role |
|------|------|
| `main.py` | Routes, auth, pipeline LRU, progress, library/search export, notes, coverage |
| `pipeline.py` | Fetch → embed → cluster → search → seed search → dedup → briefings |
| `*_fetcher.py` + `base_fetcher.py` | 12 sources via `search_and_fetch` |
| `database.py` | Per-user articles/embeddings/clusters/**screening**/ **notes** |
| `user_db.py` | Accounts (`users.db`) |
| `embeddings.py` | EmbeddingEngine + PICOExtractor; device cuda>mps>cpu |
| `clustering.py` | KMeans / hierarchical / HDBSCAN; TF-IDF labels; Plotly viz |
| `utils.py` | Year sort, SOURCE_PRIORITY, coverage suggestions, briefings |
| `feature_guides.py` | Public `/learn/{slug}` content |
| `templates/` + `static/` | UI (Campus Editorial) |
| `run_dev.sh` | Dev server: stable SECRET_KEY + `--reload` |
| `tests/` | pytest (incl. `test_utils_features.py`, `test_screening.py`) |

Sources: pubmed, europepmc, clinicaltrials, openalex, arxiv, semanticscholar,
eric, zenodo, crossref, doaj, nasa_ads (`NASA_ADS_TOKEN`), core (`CORE_API_KEY`).

---

## Git / ops
- Branch: `feature/screening-triage` (large uncommitted working tree vs last commit
  `4d77c78` Density-default). Main: `main`.
- Remote: `https://github.com/j0nsh1n/ResearchDatabaseSearchTool.git`
- **History rewrite 2026-07-08**: `*.db` purged; force-push; re-clone other machines;
  treat old password hashes as exposed.
- Host: Linux. Use `./venv` (ROCm torch OK) — **not** Windows `.venv/`.
- Static CSS/JS use `?v=` cache-bust on templates; hard-refresh after UI changes.
- **Public pages must not load `common.js`** (landing, `/learn/*`) — it used to call
  `/api/statistics` and 401→redirect to login. Login/register have “← Back to home”.

---

## Product workflow (one place per job)
1. **Data Management** — topics → sources → **fetch** (replace or append) → **embeddings**
2. **Clusters** — **only place for topic/paper triage** (exclude/restore)
3. **Duplicates** — detect near-dupes; auto-resolve or keep one
4. **Search** — rank what you kept (text / PICO / seed); notes/stars; export
5. **Landing + `/learn/*`** — marketing + plain-language feature guides (no auth)

Search does **not** have a second cluster filter UI. Screening on Clusters (and
duplicate resolve) defines the pool; Search only ranks remaining papers.

---

## Features in v3.1.0
### Also in v3.1.0 (UX / mobile / auth polish)
- Email-style logins allowed (letters, digits, `. _ + - @`, length 3–64); null/control chars blocked
- Nav workflow order with step numbers; **mobile dropdown menu** (no drag strip)
- Theme toggle icon matches **current** mode (moon = dark, sun = light)
- Em-dashes removed from user-facing copy
- Broad mobile CSS (forms, tables, bars, touch targets, safe areas)
- Source breakdown box owns its bottom border; only-missing embed follows Add vs Replace fetch mode

### From v3.0.0 (major baseline)

### Screening / triage
- Table `screening`: excluded = (`manual` \| `cluster` \| `duplicate`)
- Search + dedup skip excluded; reversible include/restore
- Clusters page: Exclude/Restore cluster + per-article toggles; excluded badges
- Duplicates: Auto-Resolve All + per-group “Keep this”; Screened Out stat

### Clustering
- Density (**HDBSCAN**, default) — own k + noise/outliers bucket (-1)
- K-Means / Hierarchical — **Auto** checkbox + slider only show for these methods
  (Density hides them; UI note explains why)
- Distinct TF-IDF labels, bigrams, Title Case; representative title headline
- Auto-k via silhouette when not Density
- **Topic briefings** on each cluster (year span, summary, example titles)

### Fetch / embeddings
- **Replace vs Add** (`clear_first` on multi-fetch)
- Per-source ✓/✗ report after fetch
- **localStorage** prefs: query, sources, email, mode, model, topics
- **Coverage map**: bars per source + missing recommended sources for selected topics
- Embeddings: `only_missing`, timing (`seconds`), `device`, `model`, `skipped_existing`
- **“Only embed new papers” auto-syncs to fetch mode**:
  - **Add to collection** → checkbox ON
  - **Replace collection** → checkbox OFF  
  User can still toggle manually before Create Embeddings. Model switch re-embeds all.

### Search
- Text / **PICO** (snippets on results) / **Seed paper** (id or title fragment)
- Optional **Prefer PICO matches** (small ranking boost)
- **Numeric year sort** (`utils.sort_articles`; unknowns last)
- Query-term **highlights** in abstracts; long abstracts clamp + expand
- **Citation**: link out to [ZoteroBib](https://zbib.org/) (no auto-bibliography)
- **Library export** `GET /api/export/library?scope=all|included|excluded|starred`
- Search CSV/TXT export includes cluster id/label
- **Notes + stars** on results (`notes` table; private per user DB)

### Duplicates
- Auto-resolve: **longest abstract first**, then **SOURCE_PRIORITY**
  (PubMed > Europe PMC > ClinicalTrials > CrossRef > OpenAlex > …)

### UI / theme (Campus Editorial)
- Warm linen light / cool slate dark; **library teal** accent (`#2a5f6e` / `#7eb8c4`);
  error red separate from accent
- Reading mode (`Aa` in nav), theme toggle, frosted sticky nav, restrained motion
- **Nav workflow order**: `1 Data Management → 2 Clusters → 3 Duplicates → 4 Search`
  (step numbers + arrows in the bar; no separate banner; no green “done” states).
  Mobile: brand row + horizontally scrollable step strip with larger tap targets.
- Page transitions (View Transitions API + fallback); **never hide main content**
  until enter (pre-hide bug fixed)
- Wide layout (`container-wide`) on Clusters / Search / Duplicates
- Rounded compact **sliders** + pill **progress** bars (full width)
- **Source bars** (coverage + “Articles by Source”): self-contained **boxed list**
  (`#source-breakdown` / `#coverage-bars` own border). Last line under a source is
  the **div’s** bottom edge, not the parent `.card` section rule. Subgrid aligns
  labels to longest name (fallback flex if no subgrid).
- Auth pages: back-to-home links; landing feature cards → `/learn/{slug}`

### Feature guides
- `GET /learn/{slug}` public; content in `feature_guides.py`
- Six guides matching landing cards; prev/next + index; CTA into app if logged in

### ROCm / GPU
- `./venv` may have torch ROCm; `select_device()` picks cuda when available

### Tests
- Suite ~**39** tests: auth, database, embeddings, integration, screening, utils
  (`test_utils_features.py`: year sort, source priority, notes, seed lookup, coverage)

---

## API surface (auth unless noted)
| Method | Path | Notes |
|--------|------|--------|
| GET | `/` | Landing (public) |
| GET | `/learn/{slug}` | Feature guide (public) |
| POST | `/api/search` | sort, pico_boost; optional cluster_filter (API only) |
| POST | `/api/search/seed` | seed id/title → similar |
| GET | `/api/search/export` | ranked results CSV/TXT |
| GET | `/api/export/library` | full collection scopes |
| POST | `/api/fetch-articles-multi` | `clear_first`, by_source, errors |
| POST | `/api/create-embeddings` | `only_missing`, timing, device |
| GET | `/api/clusters` | + briefing per cluster |
| GET | `/api/clusters/briefings` | briefings only |
| POST | `/api/coverage` | topics → suggestions |
| POST | `/api/notes` | note / starred |
| POST | `/api/screening`, `/api/clusters/{id}/screening`, `/api/resolve-duplicates` | triage |

---

## Important UI/dev gotchas (learned the hard way)
1. **Landing must not load `common.js`** — `updateNavStats` → `/api/statistics` → 401 →
   forced `/login`. Public pages stay script-light; 401 redirect only inside app shell
   (`nav.navbar` present). Nav stats use raw `fetch`, not redirecting `apiCall`.
2. **Triage only on Clusters** — do not re-add a Search “topic pool” (was repetitive).
3. **Density mode** disables/hides Auto+slider; manual k requires K-Means/Hierarchical.
4. **Source list chrome** — borders live on `#source-breakdown` / `#coverage-bars`, not
   confused with `.card` padding + `border-bottom`.
5. Static assets: bump `?v=` on `base.html` (and public pages) after CSS/JS changes.

---

## Backlog / not built
*(Parked — do not implement unless asked.)*

**Classroom / product**
- Projects/workspaces; guided workflow checklist; teacher assignment codes
- Share read-only corpus link; demo sample corpus; guest/class accounts; SSO

**Scholar tooling**
- Full RIS/BibTeX/APA generation (we only link ZoteroBib)
- Inclusion reason codes beyond manual/cluster/duplicate
- Timeline by year; LLM summaries (need clear AI labels)

**Engineering**
- FK enforcement + ON DELETE CASCADE migration
- README still mentions old `amazing-tharp/` layout in places
- Password max-length warning (bcrypt 72-byte truncate)
- Virtualized lists for 1k+ articles; mobile table pass
- FAISS micro-opts; GitHub LFS leftover blob purge; password resets post-rewrite

---

## Conventions
- Article keys: `(article_id, source)`. Fields: article_id, source, title, abstract,
  year, authors, journal.
- Handlers: auth → CSRF (mutating) → `get_pipeline` / `release_pipeline`;
  blocking work in `run_in_thread`. ValueError→400, else `server_error()`.
- Fetchers skip abstract-less records.
- Notes: empty + unstarred rows deleted.

## Deferred deliberately
- `PRAGMA foreign_keys=ON` breaks `INSERT OR REPLACE` without CASCADE migration.
