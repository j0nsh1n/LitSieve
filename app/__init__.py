"""Literature Research Aide application package.

Layout:
    app/main.py       FastAPI app + startup wiring
    app/routes/       HTTP endpoints grouped by area
    app/fetchers/     one module per academic source (all via search_and_fetch)
    app/services/     the work: pipeline, embeddings, clustering, summarize, llm
    app/storage/      SQLite access: articles, accounts, libraries, shares
    app/content/      static product content: guides, catalogs, sample corpus
"""
