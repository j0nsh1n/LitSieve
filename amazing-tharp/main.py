"""
FastAPI Application — Literature Research Aide v2.2.1
Multi-user web interface for literature search and analysis.
"""

import io
import csv
import os
import threading
from typing import List, Optional
from functools import partial
import asyncio

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

from pipeline import LiteratureSearchPipeline
from embeddings import EmbeddingEngine, PICOExtractor
from user_db import UserDatabase
from auth import hash_password, verify_password, create_token, get_current_user

# At top of file
app = FastAPI(title="Literature Research Aide", version="2.3.0")
@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.3.0"}

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- User account database ---
user_db = UserDatabase()

# --- Per-user pipeline cache (lazy-initialised) ---
_pipelines: dict = {}
_pipelines_lock = threading.Lock()

# --- Per-user progress tracking ---
_all_progress: dict = {}
_progress_lock = threading.Lock()


def get_pipeline(user_id: str) -> LiteratureSearchPipeline:
    with _pipelines_lock:
        if user_id not in _pipelines:
            user_dir = f"user_data/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            _pipelines[user_id] = LiteratureSearchPipeline(
                db_path=f"{user_dir}/articles.db",
                embedding_model="general"
            )
    return _pipelines[user_id]


def _ensure_progress(user_id: str) -> dict:
    """Return progress dict for user, creating it if needed. Must be called under _progress_lock."""
    if user_id not in _all_progress:
        _all_progress[user_id] = {
            'fetch': {'active': False, 'done': 0, 'total': 0},
            'embed': {'active': False, 'done': 0, 'total': 0},
        }
    return _all_progress[user_id]


def update_progress(user_id: str, task: str, **kwargs):
    with _progress_lock:
        _ensure_progress(user_id)[task].update(kwargs)


def current_user(request: Request) -> Optional[dict]:
    return get_current_user(request)


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

class MultiFetchRequest(BaseModel):
    sources: List[str]
    query: str
    max_results: int = 200
    email: Optional[str] = None

class EmbeddingsRequest(BaseModel):
    model: str = "general"

class ClusterRequest(BaseModel):
    n_clusters: int = 10
    method: str = "kmeans"

class DuplicateRequest(BaseModel):
    threshold: float = 0.95


# ============================================================
# Auth routes
# ============================================================

@app.get("/login")
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "login.html", context={"error": ""})


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username = username.strip().lower()
    user = user_db.get_by_username(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return templates.TemplateResponse(
            request, "login.html",
            context={"error": "Invalid username or password"},
            status_code=400,
        )
    token = create_token(user["id"], user["username"])
    response = RedirectResponse(url="/data-management", status_code=302)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return response


@app.get("/register")
async def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "register.html", context={"error": "", "username": ""})


@app.post("/register")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    username = username.strip().lower()
    error = None

    if len(username) < 3 or len(username) > 20:
        error = "Username must be 3–20 characters."
    elif not all(c.isalnum() or c in "_-" for c in username):
        error = "Username can only contain letters, numbers, _ and -."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != password_confirm:
        error = "Passwords do not match."
    elif user_db.get_by_username(username):
        error = "That username is already taken."

    if error:
        return templates.TemplateResponse(
            request, "register.html",
            context={"error": error, "username": username},
            status_code=400,
        )

    user = user_db.create_user(username, hash_password(password))
    token = create_token(user["id"], user["username"])
    response = RedirectResponse(url="/data-management", status_code=302)
    response.set_cookie("access_token", token, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response


# ============================================================
# Page routes  (all require auth)
# ============================================================

@app.get("/")
async def root(request: Request):
    if not current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/data-management", status_code=302)


@app.get("/search")
async def search_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "search.html", context={"active_page": "search", "user": user})


@app.get("/data-management")
async def data_management_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "data_management.html", context={"active_page": "data_management", "user": user})


@app.get("/statistics")
async def statistics_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "statistics.html", context={"active_page": "statistics", "user": user})


# ============================================================
# API routes  (all require auth, return 401 if missing)
# ============================================================

def run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, partial(func, *args, **kwargs))


@app.get("/api/progress")
async def api_progress(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    with _progress_lock:
        p = _ensure_progress(user["user_id"])
        return {k: dict(v) for k, v in p.items()}


@app.post("/api/search")
async def api_search(req: SearchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        results = await run_in_thread(get_pipeline(user["user_id"]).search_similar, req.query_text, top_k=req.top_k)
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
    request: Request,
    query_text: str = "",
    top_k: int = 10,
    sort_by: str = "similarity",
    cluster_filter: str = "",
    format: str = "csv",
):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        results = await run_in_thread(get_pipeline(user["user_id"]).search_similar, query_text, top_k=top_k)
        try:
            cluster_ids = [int(x) for x in cluster_filter.split(",") if x.strip()] if cluster_filter else None
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid cluster_filter"})
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
            media_type, filename = "text/csv", "search_results.csv"
        else:
            lines = []
            for i, a in enumerate(results, 1):
                lines.append(f"{i}. [{a.get('similarity_score', 0):.3f}] {a.get('title', '')}")
                lines.append(f"   Year: {a.get('year', '')} | Journal: {a.get('journal', '')}")
                lines.append(f"   Authors: {'; '.join(a.get('authors', []))}")
                lines.append(f"   Source: {a.get('source', '')} | ID: {a.get('article_id', '')}")
                lines.append("")
            content = "\n".join(lines)
            media_type, filename = "text/plain", "search_results.txt"

        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/clear-articles")
async def api_clear_articles(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        await run_in_thread(get_pipeline(user["user_id"]).db.clear_all)
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/fetch-articles-multi")
async def api_fetch_multi(req: MultiFetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    update_progress(uid, 'fetch', active=True, done=0, total=len(req.sources))
    try:
        def on_source_done(done, total):
            update_progress(uid, 'fetch', done=done, total=total)

        results = await run_in_thread(
            get_pipeline(uid).fetch_articles_parallel,
            query=req.query,
            sources=req.sources,
            max_results=req.max_results,
            email=req.email or "user@example.com",
            progress_callback=on_source_done,
        )
        total = sum(v['count'] for v in results.values())
        errors = {src: v['error'] for src, v in results.items() if v['error']}
        return {
            "status": "success",
            "total_fetched": total,
            "by_source": {src: v['count'] for src, v in results.items()},
            "errors": errors,
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        update_progress(uid, 'fetch', active=False, done=0, total=0)


@app.post("/api/fetch-articles")
async def api_fetch(req: FetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        articles = await run_in_thread(
            get_pipeline(user["user_id"]).fetch_articles,
            query=req.query, max_results=req.max_results,
            email=req.email or "user@example.com", source=req.source,
        )
        return {"status": "success", "articles_fetched": len(articles) if articles else 0, "source": req.source}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/create-embeddings")
async def api_create_embeddings(req: EmbeddingsRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    update_progress(uid, 'embed', active=True, done=0, total=0)
    try:
        p = get_pipeline(uid)
        if req.model != p.embedding_model_name:
            p.embedding_engine = EmbeddingEngine(req.model)
            p.embedding_model_name = req.model

        def on_batch_done(done, total):
            update_progress(uid, 'embed', done=done, total=total)

        await run_in_thread(p.create_embeddings, progress_callback=on_batch_done)
        stats = p.get_statistics()
        return {"status": "success", "articles_processed": stats['articles_with_embeddings']}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
    finally:
        update_progress(uid, 'embed', active=False, done=0, total=0)


@app.post("/api/create-clusters")
async def api_create_clusters(req: ClusterRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        p = get_pipeline(user["user_id"])
        await run_in_thread(p.cluster_articles, n_clusters=req.n_clusters, method=req.method)
        return {"status": "success", "clusters": p.db.get_all_clusters()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/clusters")
async def api_get_clusters(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        return {"clusters": get_pipeline(user["user_id"]).db.get_all_clusters()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/clusters/{cluster_id}/articles")
async def api_get_cluster_articles(cluster_id: int, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        articles = get_pipeline(user["user_id"]).db.get_articles_by_cluster(cluster_id)
        label = articles[0].get('cluster_label', f'Cluster {cluster_id}') if articles else f'Cluster {cluster_id}'
        for a in articles:
            a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": label, "articles": articles}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.get("/api/statistics")
async def api_statistics(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        return get_pipeline(user["user_id"]).get_statistics()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


@app.post("/api/detect-duplicates")
async def api_detect_duplicates(req: DuplicateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        p = get_pipeline(user["user_id"])
        duplicates = p.detect_duplicates(threshold=req.threshold)
        result = []
        for id1, id2, sim in duplicates[:50]:
            a1 = p.db.get_article_by_id(*id1)
            a2 = p.db.get_article_by_id(*id2)
            if a1 and a2:
                result.append({
                    "article1": {
                        "article_id": a1['article_id'], "source": a1['source'],
                        "title": a1.get('title', ''), "abstract": a1.get('abstract', ''),
                        "authors": a1.get('authors', []), "year": a1.get('year', ''),
                        "journal": a1.get('journal', ''),
                    },
                    "article2": {
                        "article_id": a2['article_id'], "source": a2['source'],
                        "title": a2.get('title', ''), "abstract": a2.get('abstract', ''),
                        "authors": a2.get('authors', []), "year": a2.get('year', ''),
                        "journal": a2.get('journal', ''),
                    },
                    "similarity": round(sim, 3),
                })
        return {"duplicates": result, "total": len(duplicates)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
