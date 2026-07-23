---
title: Health Database Search
emoji: 📚
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# Literature Research Aide 📚 — v4.2.0

A multi-user web app for **teachers and students** to fetch, screen, and rank
research papers across many academic databases. Semantic embeddings power
clustering, duplicate detection, and hybrid search; each account gets a private
workspace with background jobs, screening reports, and citation export.

Built with **FastAPI**, sentence-transformers, FAISS, and scikit-learn.

> **Starting point only.** This tool searches a set of **publicly accessible**
> research databases and helps you organise what you fetch. It is **not** a
> complete library search, not a substitute for your school library or librarian,
> and not medical, legal, or professional advice. Always verify important papers
> in the original sources and with your teacher or assignment requirements.
>
> *(In-app copy lives in `templates/macros/disclaimers.html` so landing, app,
> guides, and auth pages stay in sync.)*

## Features

- 🔍 Fetch from **18 sources** in parallel (PubMed, Europe PMC, ClinicalTrials.gov,
  OpenAlex, arXiv, Semantic Scholar, ERIC, Zenodo, CrossRef, DOAJ, NASA ADS, CORE,
  bioRxiv, medRxiv, DBLP, OpenAIRE, PLOS, HAL)
  — replace or append; **background jobs** with progress, cancel, retries, and
  per-source error classes
- 🧠 Semantic embeddings (only-new or full re-embed; topic-based model pick; GPU when
  available; background job) + **extractive key points** from abstracts
- 🎯 Hybrid similarity search (meaning + exact words), **year range**, plain text /
  PICO / **seed paper** / **more like my starred**, highlights & private notes;
  paginated result lists
- 🧩 Clustering: Density (HDBSCAN), K-Means, Hierarchical — **triage only on Clusters**
  (paginated article lists)
- 🔄 Cross-source duplicate detection + preferred-source auto-resolve
- 📋 **Screening report** (collected / excluded by reason / included / by year) on Duplicates
- 📈 Coverage map, papers-by-year timeline, and per-source breakdown
- 💾 Per-user SQLite, JWT + bcrypt, CSRF, **per-user rate limits**, change password
  (revokes other sessions via `token_version`), **password reset**
- 📤 Export ranked hits (CSV/TXT) or full library as **RIS** (Zotero / EndNote / Mendeley)
- 📖 Public landing + `/learn/…` feature guides; first-run checklist + empty states
- 🧪 **Sample demo corpus** (no APIs) for classroom dry runs
- 📚 **Multiple libraries** per account (separate collections; switch in the nav)
- 🔗 **Share a library** via class code (teacher publishes; students get their own clone)

## Project Structure

```
.
├── app/                    # application package
│   ├── main.py             # FastAPI app + startup wiring (entry point)
│   ├── auth.py             # JWT + bcrypt password hashing
│   ├── utils.py            # Year sort, source priority, coverage, screening report
│   ├── fetchers/           # One module per source + base.py (HttpClient, retry/backoff)
│   ├── services/           # pipeline, embeddings, clustering, summarize, study_type, llm, citations
│   ├── storage/            # database, user_db, libraries, shares (SQLite)
│   └── content/            # feature guides, sample corpus, source catalog, UI flags
├── templates/              # Jinja2 HTML pages
├── static/                 # CSS + page JavaScript
├── tests/                  # pytest suite
├── tools/                  # bench_scale.py (offline latency benchmark)
├── docs/                   # engineering notes
├── run_dev.sh              # Local dev with --reload
├── requirements.txt
├── Dockerfile              # Container build (HF Spaces / any Docker host)
└── render.yaml             # Render.com deployment config
```

## Installation

### Prerequisites
- Python 3.11 recommended
- pip

### Setup

```bash
# 1. Install CPU-only PyTorch first (smaller than the default build)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2. Install the rest of the dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
#   - Set SECRET_KEY (required), e.g.:
#       python -c "import secrets; print(secrets.token_urlsafe(48))"
#   - Or set DEBUG=true to run locally without a SECRET_KEY.
#   - Optionally set NASA_ADS_TOKEN / CORE_API_KEY to enable those sources.
```

> The app refuses to start without `SECRET_KEY` unless `DEBUG=true`.

## Running

```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Then open <http://localhost:7860>. Public landing and `/learn/…` guides need no
account. Register/login for your private workspace, then:

1. **Data Management** → topics/sources, **Fetch** (replace or add; background job),
   then **Create embeddings** (background job).
2. **Clusters** → Density / K-Means / Hierarchical; **exclude** off-topic groups
   or single papers (**only** place for topic triage).
3. **Duplicates** → near-duplicates + auto-resolve; **screening report** for hand-ins.
4. **Search** → text / PICO / seed / more-like-starred; hybrid rank + year filter;
   notes/stars; export ranked hits (CSV/TXT) or library as **RIS**.
5. **Account** → change password (other sessions sign out) or delete account.

### Docker

```bash
docker build -t literature-aide .
docker run -p 7860:7860 -e SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" literature-aide
```

## Programmatic use (pipeline)

The web app is the primary interface, but the pipeline can be driven directly:

```python
from pipeline import LiteratureSearchPipeline

pipeline = LiteratureSearchPipeline(db_path="articles.db", embedding_model="general")

# Fetch from a single source...
pipeline.fetch_articles(query="machine learning healthcare", max_results=500,
                        email="you@example.com", source="pubmed")
# ...or several sources in parallel
pipeline.fetch_articles_parallel(query="machine learning healthcare",
                                 sources=["pubmed", "europepmc", "openalex"],
                                 max_results=200, email="you@example.com")

pipeline.create_embeddings()
pipeline.cluster_articles(n_clusters=8, method="kmeans")

results = pipeline.search_similar("deep learning to predict patient outcomes", top_k=10)
duplicates = pipeline.detect_duplicates(threshold=0.95)
pipeline.close()
```

## Performance & hardware acceleration

The pipeline has two distinct cost centres, accelerated differently:

- **Pulling articles** from the source databases is **network I/O**, not compute.
  It is already concurrent across sources (a thread pool fans out to all
  selected databases at once); within a single source, pages are fetched
  sequentially on purpose to respect each API's rate limits. This stage does not
  benefit from a GPU.
- **Embeddings** run on a GPU when one is available. The device is auto-detected
  as **cuda → mps (Apple Silicon) → cpu**, overridable with `EMBEDDING_DEVICE`.
  If an accelerator fails to initialise, it falls back to CPU instead of
  crashing the embedding step. Vectors are L2-normalised at creation so
  similarity is a plain dot product downstream.
  > The bundled Dockerfile installs CPU-only torch; for GPU, install a
  > CUDA-enabled torch build in your image/host.
- **Similarity search & duplicate detection** use **FAISS**. Search builds a
  transient inner-product index; duplicate detection uses a FAISS *range search*
  that only materialises the pairs above your threshold, instead of a dense
  N×N matrix — so it scales to large corpora. (Without FAISS installed, both
  fall back to scikit-learn.)

## Embedding Models

Selectable via the `model` field on the embeddings request:

| Key | Model | Best for |
|-----|-------|----------|
| `general` | `all-MiniLM-L6-v2` | Fast general-purpose (default) |
| `pubmedbert` | `S-PubMedBert-MS-MARCO` | Biomedical research |
| `biosentbert` | `BioBERT-...-stsb` | Medical text |
| `specter` | `allenai/specter` | Scientific papers |

Start with `general`; switch to a biomedical model for medical corpora.

## Database Schema

Each user gets their own `user_data/<user_id>/articles.db` with three tables,
all keyed by the composite `(article_id, source)`:

- **articles** — `article_id`, `source`, `title`, `abstract`, `year`, `authors`, `journal`
- **embeddings** — raw numpy bytes + `dtype` + `shape` + `model_name` (no pickle)
- **clusters** — `cluster_id`, `cluster_label`

User accounts live in a separate `users.db`.

## Testing

```bash
pytest
```

`tests/conftest.py` sets a throwaway `SECRET_KEY` so the auth module imports
cleanly during tests. Coverage includes:

- **Unit** — password hashing/verification, JWT round-trip + expiry, user-DB
  CRUD, duplicate-username rejection, embedding storage.
- **Integration** (`test_integration_accounts.py`) — drives the real ASGI app
  with FastAPI's `TestClient` through register → authenticated fetch →
  statistics for two users, asserting per-account data isolation, CSRF
  enforcement, login, and rejection of bad credentials. Network/model work is
  stubbed (a fake fetcher), so it runs offline; it self-skips if app runtime
  deps aren't installed.

## Troubleshooting

**"SECRET_KEY is not configured"** — set `SECRET_KEY` in `.env`, or `DEBUG=true`
for local development.

**Login succeeds but bounces straight back to the login page (locally)** — over
plain `http://localhost` the browser drops the `Secure` auth cookie. Set
`DEBUG=true` in `.env` for local development; keep it `false` on HTTPS deploys.

**FAISS not installed** — the app falls back to scikit-learn for similarity
search (slower on large corpora). Install `faiss-cpu` to re-enable it.

**NASA ADS / CORE return nothing** — set `NASA_ADS_TOKEN` / `CORE_API_KEY`; those
sources are skipped when their token/key is unset.

**No search results** — make sure you fetched articles *and* created embeddings
first; check counts on the Duplicates (statistics) page.

## License

For educational purposes. Please cite original papers when using results in
publications.
