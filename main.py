"""
FastAPI Application
Web interface for the Literature Search & Similarity Tool
"""

import io
import csv
from typing import List, Optional

from fastapi import FastAPI, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from pipeline import LiteratureSearchPipeline
from embeddings import EmbeddingEngine, PICOExtractor

app = FastAPI(title="Literature Search Tool")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

pipeline = None


def get_pipeline():
    global pipeline
    if pipeline is None:
        pipeline = LiteratureSearchPipeline(db_path="articles.db", embedding_model="general")
    return pipeline


# --- Pydantic models ---

class SearchRequest(BaseModel):
    query_text: str
    top_k: int = 10
    sort_by: str = "similarity"
    cluster_filter: Optional[List[int]] = None


class FetchRequest(BaseModel):
    source: str = "pubmed"
    query: str
    max_results: int = 500
    email: Optional[str] = None


class EmbeddingsRequest(BaseModel):
    model: str = "general"


class ClusterRequest(BaseModel):
    n_clusters: int = 10
    method: str = "kmeans"


class DuplicateRequest(BaseModel):
    threshold: float = 0.95


# --- Page routes ---

@app.get("/")
async def root():
    return RedirectResponse(url="/search")


@app.get("/search")
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request, "active_page": "search"})


@app.get("/data-management")
async def data_management_page(request: Request):
    return templates.TemplateResponse("data_management.html", {"request": request, "active_page": "data_management"})


@app.get("/statistics")
async def statistics_page(request: Request):
    return templates.TemplateResponse("statistics.html", {"request": request, "active_page": "statistics"})


# --- API routes ---

@app.post("/api/search")
async def api_search(req: SearchRequest):
    try:
        results = get_pipeline().search_similar(req.query_text, top_k=req.top_k)

        for article in results:
            article['pico'] = PICOExtractor.extract_pico(article.get('abstract', ''))

        if req.cluster_filter:
            results = [a for a in results if a.get('cluster_id') in req.cluster_filter]

        if req.sort_by == "year":
            results.sort(key=lambda a: a.get('year', '0'), reverse=True)
        elif req.sort_by == "journal":
            results.sort(key=lambda a: (a.get('journal') or '').lower())
        elif req.sort_by == "title":
            results.sort(key=lambda a: (a.get('title') or '').lower())

        return {"results": results, "total": len(results)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/search/export")
async def api_search_export(
    query_text: str,
    top_k: int = 10,
    sort_by: str = "similarity",
    cluster_filter: str = "",
    format: str = "csv"
):
    try:
        results = get_pipeline().search_similar(query_text, top_k=top_k)

        cluster_ids = [int(x) for x in cluster_filter.split(",") if x.strip()] if cluster_filter else None
        if cluster_ids:
            results = [a for a in results if a.get('cluster_id') in cluster_ids]

        if sort_by == "year":
            results.sort(key=lambda a: a.get('year', '0'), reverse=True)
        elif sort_by == "journal":
            results.sort(key=lambda a: (a.get('journal') or '').lower())
        elif sort_by == "title":
            results.sort(key=lambda a: (a.get('title') or '').lower())

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Rank", "Similarity", "Title", "Year", "Journal", "Authors", "Source", "ID"])
            for i, a in enumerate(results, 1):
                writer.writerow([
                    i, f"{a.get('similarity_score', 0):.3f}",
                    a.get('title', ''), a.get('year', ''),
                    a.get('journal', ''), "; ".join(a.get('authors', [])),
                    a.get('source', ''), a.get('article_id', '')
                ])
            content = output.getvalue()
            media_type = "text/csv"
            filename = "search_results.csv"
        else:
            lines = []
            for i, a in enumerate(results, 1):
                lines.append(f"{i}. [{a.get('similarity_score', 0):.3f}] {a.get('title', '')}")
                lines.append(f"   Year: {a.get('year', '')} | Journal: {a.get('journal', '')}")
                lines.append(f"   Authors: {'; '.join(a.get('authors', []))}")
                lines.append(f"   Source: {a.get('source', '')} | ID: {a.get('article_id', '')}")
                lines.append("")
            content = "\n".join(lines)
            media_type = "text/plain"
            filename = "search_results.txt"

        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/clear-articles")
async def api_clear_articles():
    try:
        get_pipeline().db.clear_all()
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/fetch-articles")
async def api_fetch(req: FetchRequest):
    try:
        articles = get_pipeline().fetch_articles(
            query=req.query, max_results=req.max_results,
            email=req.email or "user@example.com", source=req.source
        )
        return {"status": "success", "articles_fetched": len(articles) if articles else 0, "source": req.source}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/create-embeddings")
async def api_create_embeddings(req: EmbeddingsRequest):
    try:
        p = get_pipeline()
        if req.model != p.embedding_model_name:
            p.embedding_engine = EmbeddingEngine(req.model)
            p.embedding_model_name = req.model
        p.create_embeddings()
        stats = p.get_statistics()
        return {"status": "success", "articles_processed": stats['articles_with_embeddings']}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/create-clusters")
async def api_create_clusters(req: ClusterRequest):
    try:
        get_pipeline().cluster_articles(n_clusters=req.n_clusters, method=req.method)
        clusters = get_pipeline().db.get_all_clusters()
        return {"status": "success", "clusters": clusters}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/clusters")
async def api_get_clusters():
    try:
        clusters = get_pipeline().db.get_all_clusters()
        return {"clusters": clusters}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/clusters/{cluster_id}/articles")
async def api_get_cluster_articles(cluster_id: int):
    try:
        articles = get_pipeline().db.get_articles_by_cluster(cluster_id)
        cluster_label = articles[0].get('cluster_label', f'Cluster {cluster_id}') if articles else f'Cluster {cluster_id}'
        # Remove abstract from response to keep it lightweight
        for a in articles:
            a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": cluster_label, "articles": articles}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/statistics")
async def api_statistics():
    try:
        return get_pipeline().get_statistics()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/detect-duplicates")
async def api_detect_duplicates(req: DuplicateRequest):
    try:
        p = get_pipeline()
        duplicates = p.detect_duplicates(threshold=req.threshold)
        result = []
        for id1, id2, sim in duplicates[:20]:
            a1 = p.db.get_article_by_id(*id1)
            a2 = p.db.get_article_by_id(*id2)
            if a1 and a2:
                result.append({
                    "article1": {"article_id": a1['article_id'], "source": a1['source'], "title": a1['title']},
                    "article2": {"article_id": a2['article_id'], "source": a2['source'], "title": a2['title']},
                    "similarity": round(sim, 3)
                })
        return {"duplicates": result, "total": len(duplicates)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
