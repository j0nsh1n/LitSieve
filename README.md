# LitSieve 📚 — v5.3.1

A multi-user web app for **students** to fetch, screen, and rank research papers
across public academic databases as a **research starting point**. Semantic
embeddings power clustering, duplicate detection, and hybrid search; each
account gets a private workspace with **multiple libraries** (separate paper
datasets), background jobs, screening reports, and citation export.

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

- 🔍 Fetch from **17 sources** in parallel (PubMed, Europe PMC, ClinicalTrials.gov,
  OpenAlex, arXiv, Semantic Scholar, ERIC, Zenodo, CrossRef, DOAJ, NASA ADS,
  bioRxiv, medRxiv, DBLP, OpenAIRE, PLOS, HAL)
  — replace or append; **background jobs** with progress, cancel, retries, and
  per-source error classes; **auto prepare-for-search** after a successful fetch
- 🧭 **Simple / Advanced** UI mode (client preference): Simple is one Search
  page (fetch by **topic** → wait screen → required **Narrow it down** → rank);
  Advanced keeps Clean up, Clusters, and full controls
- 🧠 Semantic embeddings (only-new or full re-embed; topic-based model pick; GPU when
  available; background job) + **extractive key points** from abstracts
- 📖 **Explain this study** (opt-in AI on a paper you already have): a structured
  plain-language reading of **that abstract only**, high-school or general-reader
  level. Automatic checks can warn; they do not claim the explanation is
  medically verified. Hidden with `HIDE_AI_BUTTONS`. Not a bulk rewrite.
- 🎯 Hybrid similarity search (meaning + exact words), **year range**, plain text /
  PICO / **seed paper** / **more like my starred**, highlights & private notes;
  paginated result lists; Simple sticky export / screening-report panel
- 🧹 **Clean up** (`/statistics`, Advanced nav): near-duplicates, preferred-source
  auto-resolve, **Quick screen**, screening report
- 🧩 Clustering (Advanced): Density (HDBSCAN), K-Means, Hierarchical — topic
  triage on Clusters (paginated lists); not auto-run after fetch
- 📋 **Screening report** (collected / excluded by reason / included / by year)
- 📈 Coverage map, papers-by-year timeline, and per-source breakdown
- 💾 Per-user SQLite, JWT + bcrypt, CSRF, **per-user rate limits**, change password
  (revokes other sessions via `token_version`), **password reset**
- 📤 Export ranked hits (CSV/TXT) or full library as **RIS** (Zotero / EndNote / Mendeley)
- 📖 Public landing + `/learn/…` feature guides; first-run checklist + empty states
- 🧪 **Guest demo** (`/guest`) and **sample corpus** (no multi-source APIs) for dry runs
- 📚 **Multiple libraries** per account (separate paper datasets / projects; switch in the nav)
- 🔗 Optional **library copy codes** (clone a collection into another account — not a live share or teacher LMS)

## Project Structure

```
.
├── app/                    # application package
│   ├── main.py             # FastAPI app + startup wiring (entry point)
│   ├── auth.py             # JWT + bcrypt password hashing
│   ├── utils.py            # Year sort, source priority, coverage, screening report
│   ├── fetchers/           # One module per source + base.py (HttpClient, retry/backoff)
│   ├── services/           # pipeline, embeddings, clustering, summarize, study_type, llm, reader_mode, citations
│   ├── storage/            # database, user_db, libraries, shares (SQLite)
│   └── content/            # feature guides, sample corpus, source catalog, UI flags
├── templates/              # Jinja2 HTML pages
├── static/                 # CSS + page JavaScript
├── tests/                  # pytest suite
├── tools/                  # backup, watchdog, bench_scale, encrypt_databases
├── docs/                   # deploy / self-host + Simple-mode plans
│   ├── DEPLOY.md           # Host checklist (SECRET_KEY, SMTP, quota, smoke)
│   └── SELFHOST.md         # Everyday systemd / tunnel commands
├── run_dev.sh              # Local dev with --reload
├── requirements.txt
├── Dockerfile              # Container build (any Docker host)
└── render.yaml             # Render.com deployment config
```

## Installation

### Prerequisites
- Python 3.14 (matches CI, Docker, and Render)
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
#   - Optionally set NASA_ADS_TOKEN to enable NASA ADS.
```

> The app refuses to start without `SECRET_KEY` unless `DEBUG=true`.

## Running

```bash
uvicorn app.main:app --host 0.0.0.0 --port 7860
```

Then open <http://localhost:7860>. Public landing and `/learn/…` guides need no
account. **Try the demo** (`/guest`) loads sample papers without registering.
Register/login for a private workspace, then:

**Simple mode (default for new accounts)**

1. **Search** (`/search`) — empty library: pick topics, type a **topic** (not
   your full question), **Fetch**. A wait screen covers fetch + prepare. Then
   **Narrow it down** (required: apply or skip) before ranking. After that:
   rank, Show chips, export RIS. **Re-prepare** and **Start over** stay on
   the Search strip.

**Advanced mode** (toggle in the nav)

1. **Data Management** → topics/sources, **Fetch** (auto-prepare; optional re-prepare).
2. **Clean up** → duplicates + Quick screen + screening report.
3. **Clusters** → Density / K-Means / Hierarchical; exclude off-topic groups or papers.
4. **Search** → text / PICO / seed / more-like-starred; notes/stars; export.
5. **Account** → change password (other sessions sign out) or delete account.

### Running it for real (self-hosted)

Do not leave `uvicorn` running in a terminal — it dies with the session and does
not come back after a reboot. Install the systemd user unit instead:

```bash
cp deploy/litsieve-uvicorn.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now litsieve-uvicorn.service
```

Then the whole day-to-day loop — reboot, deploy a code change, develop against
throwaway data, read the logs — is in
**[docs/SELFHOST.md → Everyday commands](docs/SELFHOST.md#everyday-commands)**.
The short version:

```bash
systemctl --user restart litsieve-uvicorn.service   # publish a code change
./run_dev.sh 7861                                   # develop (isolated data)
journalctl --user -u litsieve-uvicorn -f            # logs
```

### Docker

```bash
docker build -t litsieve .
docker run -p 7860:7860 -e SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')" litsieve
```

### Production / host deploy

See **[docs/DEPLOY.md](docs/DEPLOY.md)** for the full operator checklist:

- Required `SECRET_KEY` when `DEBUG=false`
- Optional SMTP, storage quota, SQLCipher, AI keys
- `PUBLIC_BASE_URL` for recovery-email links
- Smoke: `GET /health` → `200` (`status: healthy`)

Render: `render.yaml` generates `SECRET_KEY` and health-checks `/health`. Set
`PUBLIC_BASE_URL` and any SMTP/quota vars in the platform dashboard.

## Programmatic use (pipeline)

The web app is the primary interface, but the pipeline can be driven directly:

```python
from app.services.pipeline import LiteratureSearchPipeline

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
duplicates = pipeline.detect_duplicates(threshold=0.98)
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

Each **library** is its own SQLite file at
`user_data/<user_id>/libraries/<library_id>/articles.db`, so collections are
fully isolated. Which libraries exist (and which is active) is tracked in
`user_data/<user_id>/libraries.json`. Tables are keyed by the composite
`(article_id, source)`:

- **articles** — `article_id`, `source`, `title`, `abstract`, `year`, `authors`, `journal`
- **embeddings** — raw numpy bytes + `dtype` + `shape` + `model_name` (no pickle)
- **clusters** — `cluster_id`, `cluster_label`
- **screening** — exclusion state + reason (`manual` / `cluster` / `duplicate`)
- **notes** — private note text + starred flag
- **key_points** — extractive bullets generated after embedding

User accounts and optional library copy codes live in a separate `users.db`.

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

## Security

- **Transport** — TLS is terminated upstream, never by the app: Cloudflare in
  the current self-hosted deployment, or the platform router on a PaaS. The app
  sends `Strict-Transport-Security` (outside `DEBUG`), plus `X-Content-Type-Options`,
  `X-Frame-Options: DENY`, `Referrer-Policy` and a CSP that blocks scripts from
  any external origin (`app/security.py`).
- **Sessions** — JWT in an `HttpOnly` + `Secure` + `SameSite=Lax` cookie, with a
  `token_version` claim so changing a password revokes that user's other
  sessions. CSRF uses a double-submit token on every mutating request.
- **Passwords** — bcrypt (used directly; passlib dropped). Never stored or logged in the clear.
- **Provider API keys** — encrypted at rest in `user_data/ai_settings.json`
  with **AES-256-GCM** (`enc:v2:`, fresh nonce each save; key via HKDF from
  `SECRET_KEY`). Older Fernet (`enc:v1:`) blobs still load and upgrade on the
  next save. File is `chmod 600`. Rotating `SECRET_KEY` drops unreadable keys
  rather than sending ciphertext to a provider.
- **Databases at rest (optional)** — set `DB_ENCRYPTION_KEY` to open every
  SQLite file through SQLCipher. Off by default. Convert existing databases
  first, or the app will refuse to open them:

  ```bash
  # Key from env only (avoids argv / shell history). Do not pass --key on shared hosts.
  export DB_ENCRYPTION_KEY='…'
  python tools/encrypt_databases.py                 # dry run
  python tools/encrypt_databases.py --apply         # convert
  python tools/encrypt_databases.py --decrypt --apply
  ```

  This protects a stolen disk or a copied backup. It cannot protect a
  compromised running server, which necessarily holds the key. **Losing the key
  means losing the data** — keep it in your host's secret store.
- **Secrets in the repo** — `.env*` and `user_data/` are gitignored; keep `.env`
  at `chmod 600`. Production keys should come from the platform's secret
  manager (`render.yaml` generates `SECRET_KEY` automatically).
- **Deploy checklist** — step-by-step host setup and smoke tests:
  [docs/DEPLOY.md](docs/DEPLOY.md).

## Troubleshooting

**"SECRET_KEY is not configured"** — set `SECRET_KEY` in `.env`, or `DEBUG=true`
for local development.

**Login succeeds but bounces straight back to the login page (locally)** — over
plain `http://localhost` the browser drops the `Secure` auth cookie. Set
`DEBUG=true` in `.env` for local development; keep it `false` on HTTPS deploys.

**FAISS not installed** — the app falls back to scikit-learn for similarity
search (slower on large corpora). Install `faiss-cpu` to re-enable it.

**NASA ADS returns nothing** — set `NASA_ADS_TOKEN` (free token from ADS);
the source is skipped when the token is unset.

**No search results** — make sure you fetched articles *and* created embeddings
first; check counts on the Duplicates (statistics) page.

## License

For educational purposes. Please cite original papers when using results in
publications.
