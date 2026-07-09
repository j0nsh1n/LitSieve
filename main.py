"""
FastAPI Application — Literature Research Aide v2.6.0
Multi-user web interface for literature search and analysis.
"""

import io
import csv
import os
import shutil
import secrets
import logging
import threading
from collections import OrderedDict
from typing import List, Optional
from functools import partial
import asyncio

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from pipeline import LiteratureSearchPipeline
from embeddings import PICOExtractor
from user_db import UserDatabase
from auth import hash_password, verify_password, create_token, get_current_user

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

COOKIE_SECURE = os.getenv("DEBUG", "").strip().lower() not in ("1", "true", "yes")
MAX_CACHED_USERS = 50

limiter = Limiter(key_func=get_remote_address)

# At top of file
app = FastAPI(title="Literature Research Aide", version="2.6.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
@app.get("/health")
async def health():
    return {"status": "healthy", "version": "2.6.0"}

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- User account database ---
user_db = UserDatabase()

# --- Per-user pipeline cache (lazy-initialised, LRU-bounded) ---
_pipelines: "OrderedDict[str, LiteratureSearchPipeline]" = OrderedDict()
# Number of in-flight requests holding each pipeline. A pipeline is only safe
# to close when its refcount hits 0; otherwise eviction defers the close.
_pipeline_refcounts: "OrderedDict[str, int]" = OrderedDict()
# Pipelines evicted while still in use, keyed by uid — closed on last release.
_pending_close: "dict[str, LiteratureSearchPipeline]" = {}
# Guards _pipelines, _pipeline_refcounts and _pending_close together.
_pipelines_lock = threading.Lock()

# --- Per-user progress tracking (LRU-bounded) ---
_all_progress: "OrderedDict[str, dict]" = OrderedDict()
_progress_lock = threading.Lock()


def get_pipeline(user_id: str) -> LiteratureSearchPipeline:
    """Return the user's pipeline and register an in-flight reference.

    The caller MUST pair every get_pipeline() with a release_pipeline() in a
    finally block so deferred closes can run once the request completes.
    """
    with _pipelines_lock:
        if user_id not in _pipelines:
            user_dir = f"user_data/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            _pipelines[user_id] = LiteratureSearchPipeline(
                db_path=f"{user_dir}/articles.db",
                embedding_model="general"
            )
            # Evict least-recently-used pipelines to bound memory. Never close a
            # pipeline that has in-flight references — defer until last release.
            while len(_pipelines) > MAX_CACHED_USERS:
                old_uid, old_pipeline = _pipelines.popitem(last=False)
                if _pipeline_refcounts.get(old_uid, 0) > 0:
                    _pending_close[old_uid] = old_pipeline
                    continue
                try:
                    old_pipeline.db.close()
                except Exception:
                    logger.exception("Failed to close evicted pipeline for %s", old_uid)
        _pipelines.move_to_end(user_id)
        _pipeline_refcounts[user_id] = _pipeline_refcounts.get(user_id, 0) + 1
        return _pipelines[user_id]


def release_pipeline(user_id: str) -> None:
    """Drop an in-flight reference, closing a deferred-evicted pipeline at 0."""
    with _pipelines_lock:
        count = _pipeline_refcounts.get(user_id, 0) - 1
        if count > 0:
            _pipeline_refcounts[user_id] = count
            return
        _pipeline_refcounts.pop(user_id, None)
        # A pipeline evicted while in use is held in _pending_close (separate
        # from any newer live pipeline under the same uid in _pipelines). Close
        # the deferred object only — never the current live one.
        pipeline = _pending_close.pop(user_id, None)
        if pipeline is not None:
            try:
                pipeline.db.close()
            except Exception:
                logger.exception("Failed to close deferred pipeline for %s", user_id)


def _evict_pipeline(user_id: str) -> None:
    """Forcibly drop and close a user's cached pipeline and progress state.

    Used when an account is deleted: the SQLite connection must be closed before
    the user's data directory can be removed on Windows (open file handle would
    block rmtree).
    """
    with _pipelines_lock:
        live = _pipelines.pop(user_id, None)
        pending = _pending_close.pop(user_id, None)
        _pipeline_refcounts.pop(user_id, None)
        for pipe in (live, pending):
            if pipe is not None:
                try:
                    pipe.db.close()
                except Exception:
                    logger.exception("Failed to close pipeline for %s during deletion", user_id)
    with _progress_lock:
        _all_progress.pop(user_id, None)


def _ensure_progress(user_id: str) -> dict:
    """Return progress dict for user, creating it if needed. Must be called under _progress_lock."""
    if user_id not in _all_progress:
        _all_progress[user_id] = {
            'fetch': {'active': False, 'done': 0, 'total': 0},
            'embed': {'active': False, 'done': 0, 'total': 0},
        }
        while len(_all_progress) > MAX_CACHED_USERS:
            _all_progress.popitem(last=False)
    _all_progress.move_to_end(user_id)
    return _all_progress[user_id]


def update_progress(user_id: str, task: str, **kwargs):
    with _progress_lock:
        _ensure_progress(user_id)[task].update(kwargs)


def current_user(request: Request) -> Optional[dict]:
    return get_current_user(request)


def _set_auth_cookies(response, token: str):
    """Set the JWT (httponly) and a CSRF token (readable) as cookies."""
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        "access_token", token, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=30 * 24 * 3600,
    )
    response.set_cookie(
        "csrf_token", csrf_token, httponly=False, secure=COOKIE_SECURE,
        samesite="lax", max_age=30 * 24 * 3600,
    )


def csrf_failed(request: Request) -> bool:
    """Double-submit cookie check for state-changing /api requests."""
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token")
    return not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token)


def server_error(e: Exception) -> JSONResponse:
    """Log the real exception server-side, return a generic message to the client."""
    logger.exception("Unhandled error in API handler: %s", e)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# --- Pydantic models ---

class SearchRequest(BaseModel):
    query_text: str
    top_k: int = 10
    sort_by: str = "similarity"
    cluster_filter: Optional[List[int]] = None
    source_filter: Optional[List[str]] = None

class FetchRequest(BaseModel):
    source: str = "pubmed"
    query: str
    max_results: int = Field(default=500, ge=1, le=1000)
    email: Optional[str] = None

class MultiFetchRequest(BaseModel):
    sources: List[str]
    query: str
    max_results: int = Field(default=200, ge=1, le=1000)
    email: Optional[str] = None

class EmbeddingsRequest(BaseModel):
    model: str = "general"

class ClusterRequest(BaseModel):
    # None (or <= 0) means auto-select the count by silhouette score.
    n_clusters: Optional[int] = None
    method: str = "kmeans"

class DuplicateRequest(BaseModel):
    threshold: float = 0.95

class ScreeningItem(BaseModel):
    article_id: str
    source: str

class ScreeningRequest(BaseModel):
    items: List[ScreeningItem]
    action: str = Field(default="exclude", pattern="^(exclude|include)$")

class ClusterScreeningRequest(BaseModel):
    action: str = Field(default="exclude", pattern="^(exclude|include)$")

class ResolveDuplicatesRequest(BaseModel):
    threshold: float = Field(default=0.95, ge=0.5, le=1.0)

class DeleteAccountRequest(BaseModel):
    password: str


# ============================================================
# Auth routes
# ============================================================

@app.get("/login")
async def login_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "login.html", context={"error": ""})


@app.post("/login")
@limiter.limit("10/minute")
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
    _set_auth_cookies(response, token)
    return response


@app.get("/register")
async def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "register.html", context={"error": "", "username": ""})


@app.post("/register")
@limiter.limit("10/minute")
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

    try:
        user = user_db.create_user(username, hash_password(password))
    except ValueError:
        # Lost the race against a concurrent registration of the same username.
        return templates.TemplateResponse(
            request, "register.html",
            context={"error": "That username is already taken.", "username": username},
            status_code=400,
        )
    token = create_token(user["id"], user["username"])
    response = RedirectResponse(url="/data-management", status_code=302)
    _set_auth_cookies(response, token)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return response


# ============================================================
# Page routes  (all require auth)
# ============================================================

@app.get("/")
async def root(request: Request):
    # The landing page is the default page for everyone. The CTA adapts: signed-in
    # users get an "Open App" button, logged-out visitors get login/register.
    user = current_user(request)
    return templates.TemplateResponse(request, "landing.html", context={"user": user})


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


@app.get("/clusters")
async def clusters_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "clusters.html", context={"active_page": "clusters", "user": user})


@app.get("/account")
async def account_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse(request, "account.html", context={"active_page": "account", "user": user})


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
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        results = await run_in_thread(
            p.search_similar, req.query_text,
            top_k=req.top_k, source_filter=req.source_filter,
            cluster_filter=req.cluster_filter,
        )
        for article in results:
            article['pico'] = PICOExtractor.extract_pico(article.get('abstract', ''))
        if req.sort_by == "year":
            results.sort(key=lambda a: a.get('year', '0'), reverse=True)
        elif req.sort_by == "journal":
            results.sort(key=lambda a: (a.get('journal') or '').lower())
        elif req.sort_by == "title":
            results.sort(key=lambda a: (a.get('title') or '').lower())
        return {"results": results, "total": len(results)}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/search/export")
async def api_search_export(
    request: Request,
    query_text: str = "",
    top_k: int = 10,
    sort_by: str = "similarity",
    cluster_filter: str = "",
    source_filter: str = "",
    format: str = "csv",
):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        sources = [s for s in source_filter.split(",") if s.strip()] or None
        try:
            cluster_ids = [int(x) for x in cluster_filter.split(",") if x.strip()] if cluster_filter else None
        except ValueError:
            return JSONResponse(status_code=400, content={"error": "Invalid cluster_filter"})
        results = await run_in_thread(
            p.search_similar, query_text, top_k=top_k, source_filter=sources,
            cluster_filter=cluster_ids,
        )
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
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/clear-articles")
async def api_clear_articles(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        await run_in_thread(p.db.clear_all)
        return {"status": "success"}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/fetch-articles-multi")
@limiter.limit("20/minute")
async def api_fetch_multi(req: MultiFetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    update_progress(uid, 'fetch', active=True, done=0, total=len(req.sources))
    try:
        def on_source_done(done, total):
            update_progress(uid, 'fetch', done=done, total=total)

        results = await run_in_thread(
            p.fetch_articles_parallel,
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
        return server_error(e)
    finally:
        update_progress(uid, 'fetch', active=False, done=0, total=0)
        release_pipeline(uid)


@app.post("/api/fetch-articles")
@limiter.limit("20/minute")
async def api_fetch(req: FetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        articles = await run_in_thread(
            p.fetch_articles,
            query=req.query, max_results=req.max_results,
            email=req.email or "user@example.com", source=req.source,
        )
        return {"status": "success", "articles_fetched": len(articles) if articles else 0, "source": req.source}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/create-embeddings")
@limiter.limit("12/minute")
async def api_create_embeddings(req: EmbeddingsRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    update_progress(uid, 'embed', active=True, done=0, total=0)
    try:
        def on_batch_done(done, total):
            update_progress(uid, 'embed', done=done, total=total)

        # The engine swap happens inside create_embeddings under the pipeline's
        # engine lock, so it stays atomic with the embedding pass.
        await run_in_thread(p.create_embeddings, model=req.model, progress_callback=on_batch_done)
        stats = p.get_statistics()
        return {"status": "success", "articles_processed": stats['articles_with_embeddings']}
    except Exception as e:
        return server_error(e)
    finally:
        update_progress(uid, 'embed', active=False, done=0, total=0)
        release_pipeline(uid)


@app.post("/api/create-clusters")
async def api_create_clusters(req: ClusterRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = await run_in_thread(p.cluster_articles, n_clusters=req.n_clusters, method=req.method)
        # cluster_articles returns (labels, cluster_labels, by_cluster, resolved_n)
        # or None when there are no embeddings yet.
        resolved_n = result[3] if result else 0
        return {
            "status": "success",
            "clusters": p.db.get_all_clusters(),
            "resolved_n_clusters": resolved_n,
            "auto": req.n_clusters is None or req.n_clusters <= 0,
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/clusters")
async def api_get_clusters(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return {"clusters": p.db.get_all_clusters()}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/clusters/{cluster_id}/articles")
async def api_get_cluster_articles(cluster_id: int, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        articles = p.db.get_articles_by_cluster(cluster_id)
        label = articles[0].get('cluster_label', f'Cluster {cluster_id}') if articles else f'Cluster {cluster_id}'
        for a in articles:
            a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": label, "articles": articles}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/statistics")
async def api_statistics(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return p.get_statistics()
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/detect-duplicates")
async def api_detect_duplicates(req: DuplicateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
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
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/screening")
async def api_screening(req: ScreeningRequest, request: Request):
    """Exclude (screen out) or re-include specific articles."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        keys = [(item.article_id, item.source) for item in req.items]
        if req.action == "exclude":
            count = p.db.exclude_articles(keys, reason='manual')
        else:
            count = p.db.include_articles(keys)
        return {"status": "success", "action": req.action, "count": count}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/clusters/{cluster_id}/screening")
async def api_cluster_screening(cluster_id: int, req: ClusterScreeningRequest, request: Request):
    """Bulk exclude/include every article in a cluster (screening triage)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        keys = p.db.get_cluster_article_keys(cluster_id)
        if not keys:
            return JSONResponse(status_code=404, content={"detail": f"Cluster {cluster_id} has no articles"})
        if req.action == "exclude":
            count = p.db.exclude_articles(keys, reason='cluster')
        else:
            count = p.db.include_articles(keys)
        return {"status": "success", "action": req.action, "cluster_id": cluster_id, "count": count}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/resolve-duplicates")
async def api_resolve_duplicates(req: ResolveDuplicatesRequest, request: Request):
    """Auto-resolve duplicate groups: keep the best copy of each, exclude the rest."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = await run_in_thread(p.resolve_duplicates, threshold=req.threshold)
        return {"status": "success", **result}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/delete-account")
async def api_delete_account(req: DeleteAccountRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    uid = user["user_id"]
    # Re-verify the password before destroying anything.
    record = user_db.get_by_username(user["username"])
    if not record or not verify_password(req.password, record["hashed_password"]):
        return JSONResponse(status_code=400, content={"detail": "Incorrect password"})

    try:
        # 1. Close + drop the cached pipeline so the SQLite file is released.
        _evict_pipeline(uid)
        # 2. Remove the user's data directory (articles/embeddings/clusters).
        user_dir = os.path.join("user_data", uid)
        if os.path.isdir(user_dir):
            shutil.rmtree(user_dir, ignore_errors=True)
        # 3. Delete the account record.
        user_db.delete_user(uid)
    except Exception as e:
        return server_error(e)

    # Clear auth cookies so the now-deleted session can't keep being used.
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port)
