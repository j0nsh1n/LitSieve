"""
FastAPI Application — Literature Research Aide v3.5.0
Multi-user web interface for literature search and analysis.
"""

import io
import csv
import os
import re
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
from auth import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
    validate_login_name,
)
from utils import (
    sort_articles,
    coverage_suggestions,
    build_screening_report,
    format_screening_report_txt,
)
from citations import collection_to_ris, collection_to_bibtex
from feature_guides import get_guide, list_guides, neighbors

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(name)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

COOKIE_SECURE = os.getenv("DEBUG", "").strip().lower() not in ("1", "true", "yes")
MAX_CACHED_USERS = 50


def rate_limit_key(request: Request) -> str:
    """Authenticated users get their own bucket; anonymous falls back to IP.

    Login/register stay IP-keyed (no cookie yet), which is what we want for
    brute-force protection. Classroom NATs no longer share one budget once
    users are signed in.
    """
    user = get_current_user(request)
    if user and user.get("user_id"):
        return f"user:{user['user_id']}"
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)

# At top of file
app = FastAPI(title="Literature Research Aide", version="3.5.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
@app.get("/health")
async def health():
    return {"status": "healthy", "version": "3.5.0"}

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
            'fetch': {'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None},
            'embed': {'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None},
        }
        while len(_all_progress) > MAX_CACHED_USERS:
            _all_progress.popitem(last=False)
    _all_progress.move_to_end(user_id)
    # Backfill keys if an older in-memory entry lacks them.
    for task in ('fetch', 'embed'):
        slot = _all_progress[user_id].setdefault(
            task, {'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None}
        )
        slot.setdefault('result', None)
        slot.setdefault('error', None)
    return _all_progress[user_id]


def update_progress(user_id: str, task: str, **kwargs):
    with _progress_lock:
        _ensure_progress(user_id)[task].update(kwargs)


def start_user_job(uid: str, task: str, fn, /, **kwargs) -> bool:
    """Run fn(pipeline, **kwargs) in a thread; progress + result in _all_progress.

    Returns False if a job of this task type is already active for uid.
    The worker holds the pipeline ref until completion (release in done callback).
    """
    with _progress_lock:
        p = _ensure_progress(uid)
        if p[task].get('active'):
            return False
        p[task].update({
            'active': True, 'done': 0, 'total': 0, 'result': None, 'error': None,
        })

    pipe = get_pipeline(uid)
    loop = asyncio.get_running_loop()

    def worker():
        return fn(pipe, **kwargs)

    future = loop.run_in_executor(None, worker)

    def _on_done(fut):
        try:
            result = fut.result()
            update_progress(uid, task, active=False, result=result, error=None)
        except Exception as exc:
            logger.exception("Background %s job failed for %s", task, uid)
            update_progress(uid, task, active=False, result=None, error=str(exc))
        finally:
            release_pipeline(uid)

    future.add_done_callback(_on_done)
    return True


def current_user(request: Request) -> Optional[dict]:
    """JWT + live account check (token_version) so password change revokes old sessions."""
    payload = get_current_user(request)
    if not payload or not payload.get("user_id"):
        return None
    record = user_db.get_by_id(payload["user_id"])
    if not record:
        return None
    if int(payload.get("tv", 0) or 0) != int(record.get("token_version") or 0):
        return None
    return {
        "user_id": record["id"],
        "username": record["username"],
        "token_version": int(record.get("token_version") or 0),
    }


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
    # When true, slightly prefer abstracts that mention the user's PICO terms.
    pico_boost: bool = False
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    # Blend TF-IDF word overlap with embedding similarity (default on).
    lexical_boost: bool = True

class SeedSearchRequest(BaseModel):
    seed: str
    top_k: int = 10
    cluster_filter: Optional[List[int]] = None
    source_filter: Optional[List[str]] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    lexical_boost: bool = True

class StarredSearchRequest(BaseModel):
    top_k: int = 10
    source_filter: Optional[List[str]] = None
    cluster_filter: Optional[List[int]] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None

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
    # True = wipe collection first (default classroom "start fresh").
    # False = append / update without clearing.
    clear_first: bool = True
    # wait=true: block until done (tests / legacy). Default: 202 + poll progress.
    wait: bool = False

class EmbeddingsRequest(BaseModel):
    model: str = "general"
    # Skip articles that already have vectors (unless the model changes).
    only_missing: bool = True
    wait: bool = False

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    new_password_confirm: str

class NoteRequest(BaseModel):
    article_id: str
    source: str
    note: Optional[str] = None
    starred: Optional[bool] = None

class CoverageRequest(BaseModel):
    topics: Optional[List[str]] = None

class ClusterRequest(BaseModel):
    # None (or <= 0) means auto-select the count by silhouette score.
    n_clusters: Optional[int] = None
    # Density (HDBSCAN) is the default: it finds the topic count itself and sets
    # outliers aside, which beats a guessed/auto k on real corpora.
    method: str = "hdbscan"

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
    token = create_token(
        user["id"], user["username"], user.get("token_version", 0),
    )
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
    error = validate_login_name(username)

    if error is None and len(password) < 8:
        error = "Password must be at least 8 characters."
    elif error is None and password != password_confirm:
        error = "Passwords do not match."
    elif error is None and user_db.get_by_username(username):
        error = "That login is already taken."

    if error:
        return templates.TemplateResponse(
            request, "register.html",
            context={"error": error, "username": username},
            status_code=400,
        )

    try:
        user = user_db.create_user(username, hash_password(password))
    except ValueError:
        # Lost the race against a concurrent registration of the same login.
        return templates.TemplateResponse(
            request, "register.html",
            context={"error": "That login is already taken.", "username": username},
            status_code=400,
        )
    token = create_token(
        user["id"], user["username"], user.get("token_version", 0),
    )
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


@app.get("/learn/{slug}")
async def feature_guide_page(slug: str, request: Request):
    """Public detail pages for each landing feature card (no login required)."""
    guide = get_guide(slug)
    if not guide:
        return RedirectResponse(url="/", status_code=302)
    prev_g, next_g = neighbors(slug)
    user = current_user(request)
    return templates.TemplateResponse(
        request,
        "feature_guide.html",
        context={
            "guide": guide,
            "prev": prev_g,
            "next": next_g,
            "all_guides": list_guides(),
            "user": user,
        },
    )


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


def _attach_pico(results: List[dict]) -> None:
    """Add structured PICO snippets (sentences) to each result."""
    for article in results:
        pico = PICOExtractor.extract_pico(article.get("abstract", ""))
        # Cap snippets so the UI stays readable.
        article["pico"] = {
            k: (v[:3] if isinstance(v, list) else v) for k, v in pico.items()
        }


def _apply_pico_boost(results: List[dict], query_text: str) -> None:
    """Small re-rank boost when abstract PICO snippets overlap query terms."""
    q = (query_text or "").lower()
    # Pull meaningful tokens from a PICO-style or free-text query.
    tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", q) if t not in {
        "population", "intervention", "comparison", "outcome", "with", "from",
        "that", "this", "have", "been", "were", "their", "about",
    }]
    if not tokens:
        return
    for a in results:
        base = float(a.get("similarity_score") or 0)
        blob = " ".join(
            " ".join(a.get("pico", {}).get(k) or [])
            for k in ("population", "intervention", "comparison", "outcome")
        ).lower()
        if not blob:
            blob = (a.get("abstract") or "").lower()
        hits = sum(1 for t in tokens if t in blob)
        # At most +0.08 so similarity still dominates.
        boost = min(0.08, 0.015 * hits)
        a["similarity_score"] = round(base + boost, 4)
        a["pico_boost"] = round(boost, 4)
    results.sort(key=lambda x: x.get("similarity_score") or 0, reverse=True)


def _attach_notes(results: List[dict], p) -> None:
    notes = p.db.get_notes_map()
    for a in results:
        n = notes.get((a.get("article_id"), a.get("source"))) or {}
        a["note"] = n.get("note") or ""
        a["starred"] = bool(n.get("starred"))


def _attach_key_points(results: List[dict], p) -> None:
    """Attach stored extractive bullets (may be empty list)."""
    kp = p.db.get_key_points_map()
    for a in results:
        bullets = kp.get((a.get("article_id"), a.get("source")))
        a["key_points"] = list(bullets) if bullets else []


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
            year_min=req.year_min, year_max=req.year_max,
            lexical_boost=req.lexical_boost,
        )
        _attach_pico(results)
        if req.pico_boost:
            _apply_pico_boost(results, req.query_text)
        sort_articles(results, req.sort_by)
        _attach_notes(results, p)
        _attach_key_points(results, p)
        return {"results": results, "total": len(results)}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/search/seed")
async def api_search_seed(req: SeedSearchRequest, request: Request):
    """Find more papers like one you already have (by id or title fragment)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        data = await run_in_thread(
            p.search_by_seed, req.seed, req.top_k,
            req.source_filter, req.cluster_filter,
            req.year_min, req.year_max, req.lexical_boost,
        )
        results = data["results"]
        _attach_pico(results)
        _attach_notes(results, p)
        _attach_key_points(results, p)
        return {
            "seed": data["seed"],
            "results": results,
            "total": len(results),
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/search/starred")
async def api_search_starred(req: StarredSearchRequest, request: Request):
    """Rank papers near the centroid of your starred collection."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        data = await run_in_thread(
            p.search_from_starred,
            top_k=req.top_k,
            source_filter=req.source_filter,
            cluster_filter=req.cluster_filter,
            year_min=req.year_min,
            year_max=req.year_max,
        )
        results = data["results"]
        _attach_pico(results)
        _attach_notes(results, p)
        _attach_key_points(results, p)
        return {
            "results": results,
            "total": len(results),
            "seed_count": data["seed_count"],
        }
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
    pico_boost: bool = False,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    lexical_boost: bool = True,
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
            year_min=year_min, year_max=year_max,
            lexical_boost=lexical_boost,
        )
        if pico_boost:
            _attach_pico(results)
            _apply_pico_boost(results, query_text)
        sort_articles(results, sort_by)

        if format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Rank", "Similarity", "Title", "Year", "Journal", "Authors",
                "Source", "ID", "Cluster ID", "Cluster Label",
            ])
            for i, a in enumerate(results, 1):
                writer.writerow([
                    i, f"{a.get('similarity_score', 0):.3f}",
                    a.get('title', ''), a.get('year', ''),
                    a.get('journal', ''), "; ".join(a.get('authors', [])),
                    a.get('source', ''), a.get('article_id', ''),
                    a.get('cluster_id', ''), a.get('cluster_label', ''),
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
                if a.get("cluster_label"):
                    lines.append(f"   Cluster: {a.get('cluster_label')}")
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


@app.get("/api/export/library")
async def api_export_library(
    request: Request,
    scope: str = "all",
    format: str = "csv",
):
    """Export the collection with cluster membership and exclusion reasons.

    scope: all | included | excluded | starred
    format: csv | txt | ris | bibtex
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if scope not in ("all", "included", "excluded", "starred"):
        return JSONResponse(status_code=400, content={"detail": "Invalid scope"})
    fmt = (format or "csv").lower().strip()
    if fmt not in ("csv", "txt", "ris", "bibtex"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        rows = p.db.get_library_export_rows(scope=scope)
        if fmt == "ris":
            content = collection_to_ris(rows)
            media_type = "application/x-research-info-systems"
            filename = "library.ris"
        elif fmt == "bibtex":
            content = collection_to_bibtex(rows)
            media_type = "application/x-bibtex"
            filename = "library.bib"
        elif fmt == "txt":
            lines = []
            for a in rows:
                flag = "EXCLUDED" if a.get("excluded") else ("STARRED" if a.get("starred") else "INCLUDED")
                lines.append(f"[{flag}] {a.get('title', '')}")
                lines.append(
                    f"  Year: {a.get('year', '')} | Source: {a.get('source', '')} | "
                    f"ID: {a.get('article_id', '')}"
                )
                if a.get("cluster_label"):
                    lines.append(f"  Cluster: {a.get('cluster_label')}")
                if a.get("exclusion_reason"):
                    lines.append(f"  Exclusion reason: {a.get('exclusion_reason')}")
                if a.get("note"):
                    lines.append(f"  Note: {a.get('note')}")
                lines.append("")
            content = "\n".join(lines)
            media_type, filename = "text/plain", f"library_{scope}.txt"
        else:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Title", "Year", "Journal", "Authors", "Source", "ID",
                "Cluster ID", "Cluster Label", "Excluded", "Exclusion Reason",
                "Starred", "Note",
            ])
            for a in rows:
                writer.writerow([
                    a.get("title", ""), a.get("year", ""), a.get("journal", ""),
                    "; ".join(a.get("authors") or []),
                    a.get("source", ""), a.get("article_id", ""),
                    a.get("cluster_id", ""), a.get("cluster_label", ""),
                    "yes" if a.get("excluded") else "no",
                    a.get("exclusion_reason", ""),
                    "yes" if a.get("starred") else "no",
                    a.get("note", ""),
                ])
            content = output.getvalue()
            media_type, filename = "text/csv", f"library_{scope}.csv"
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/screening-report")
async def api_screening_report(request: Request, format: str = "json"):
    """PRISMA-style screening accounting (read-only). format: json | txt"""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    fmt = (format or "json").lower().strip()
    if fmt not in ("json", "txt"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        report = build_screening_report(p.db)
        if fmt == "txt":
            content = format_screening_report_txt(report)
            return StreamingResponse(
                io.BytesIO(content.encode()),
                media_type="text/plain",
                headers={
                    "Content-Disposition": "attachment; filename=screening_report.txt"
                },
            )
        return report
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


def _run_multi_fetch(p, *, query, sources, max_results, email, clear_first, uid):
    """Blocking multi-source fetch for sync wait= or background jobs."""
    update_progress(uid, 'fetch', done=0, total=len(sources))
    if clear_first:
        p.db.clear_all()

    def on_source_done(done, total):
        update_progress(uid, 'fetch', done=done, total=total)

    results = p.fetch_articles_parallel(
        query=query,
        sources=sources,
        max_results=max_results,
        email=email or "user@example.com",
        progress_callback=on_source_done,
    )
    total = sum(v['count'] for v in results.values())
    errors = {src: v['error'] for src, v in results.items() if v['error']}
    ok = {src: v['count'] for src, v in results.items() if not v['error']}
    return {
        "status": "success",
        "total_fetched": total,
        "by_source": {src: v['count'] for src, v in results.items()},
        "ok_sources": ok,
        "errors": errors,
        "cleared_first": clear_first,
    }


@app.post("/api/fetch-articles-multi")
@limiter.limit("20/minute")
async def api_fetch_multi(req: MultiFetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    job_kwargs = dict(
        query=req.query,
        sources=req.sources,
        max_results=req.max_results,
        email=req.email,
        clear_first=req.clear_first,
        uid=uid,
    )
    if not req.wait:
        if not start_user_job(uid, 'fetch', _run_multi_fetch, **job_kwargs):
            return JSONResponse(
                status_code=409,
                content={"detail": "A fetch is already running"},
            )
        return JSONResponse(status_code=202, content={"status": "started"})

    p = get_pipeline(uid)
    update_progress(uid, 'fetch', active=True, done=0, total=len(req.sources),
                    result=None, error=None)
    try:
        result = await run_in_thread(_run_multi_fetch, p, **job_kwargs)
        update_progress(uid, 'fetch', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, 'fetch', active=False, result=None, error=str(e))
        return server_error(e)
    finally:
        update_progress(uid, 'fetch', active=False)
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


def _run_create_embeddings(p, *, model, only_missing, uid):
    """Blocking embedding pass for sync wait= or background jobs."""
    update_progress(uid, 'embed', done=0, total=0)

    def on_batch_done(done, total):
        update_progress(uid, 'embed', done=done, total=total)

    # Engine swap happens inside create_embeddings under the pipeline lock.
    result = p.create_embeddings(
        model=model,
        progress_callback=on_batch_done,
        only_missing=only_missing,
    ) or {}
    stats = p.get_statistics()
    return {
        "status": "success",
        "articles_processed": stats["articles_with_embeddings"],
        "embeddings_created": result.get("embeddings_created", 0),
        "skipped_existing": result.get("skipped_existing", 0),
        "seconds": result.get("seconds", 0),
        "model": result.get("model") or model,
        "device": result.get("device") or "cpu",
    }


@app.post("/api/create-embeddings")
@limiter.limit("12/minute")
async def api_create_embeddings(req: EmbeddingsRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    job_kwargs = dict(model=req.model, only_missing=req.only_missing, uid=uid)
    if not req.wait:
        if not start_user_job(uid, 'embed', _run_create_embeddings, **job_kwargs):
            return JSONResponse(
                status_code=409,
                content={"detail": "A embed is already running"},
            )
        return JSONResponse(status_code=202, content={"status": "started"})

    p = get_pipeline(uid)
    update_progress(uid, 'embed', active=True, done=0, total=0, result=None, error=None)
    try:
        result = await run_in_thread(_run_create_embeddings, p, **job_kwargs)
        update_progress(uid, 'embed', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, 'embed', active=False, result=None, error=str(e))
        return server_error(e)
    finally:
        update_progress(uid, 'embed', active=False)
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
        clusters = p.db.get_all_clusters()
        briefings = await run_in_thread(p.get_cluster_briefings)
        by_id = {b["cluster_id"]: b for b in briefings}
        for c in clusters:
            c["briefing"] = by_id.get(c["cluster_id"])
        return {"clusters": clusters}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/clusters/briefings")
async def api_cluster_briefings(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return {"briefings": await run_in_thread(p.get_cluster_briefings)}
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
        _attach_key_points(articles, p)
        for a in articles:
            a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": label, "articles": articles}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/generate-key-points")
@limiter.limit("6/minute")
async def api_generate_key_points(request: Request, only_missing: bool = True):
    """Backfill extractive key points for articles missing them (or regenerate all)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = await run_in_thread(p.generate_key_points, only_missing=only_missing)
        return {"status": "success", **result}
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


@app.post("/api/notes")
async def api_upsert_note(req: NoteRequest, request: Request):
    """Save a private note and/or star flag on an article."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        note = p.db.upsert_note(req.article_id, req.source, note=req.note, starred=req.starred)
        return {"status": "success", "note": note}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.get("/api/notes")
async def api_get_note(request: Request, article_id: str = "", source: str = ""):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not article_id or not source:
        return JSONResponse(status_code=400, content={"detail": "article_id and source required"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return p.db.get_note(article_id, source)
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/coverage")
async def api_coverage(req: CoverageRequest, request: Request):
    """Coverage map: what you have vs sources usually useful for your topics."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        stats = p.get_statistics()
        sources = stats.get("sources") or {}
        suggestions = coverage_suggestions(sources, req.topics or [])
        return {
            "sources": sources,
            "total_articles": stats.get("total_articles", 0),
            "suggestions": suggestions,
            "embedding_model": stats.get("embedding_model"),
            "missing_embeddings": stats.get("missing_embeddings"),
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/change-password")
async def api_change_password(req: ChangePasswordRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    record = user_db.get_by_id(user["user_id"])
    if not record or not verify_password(req.current_password, record["hashed_password"]):
        return JSONResponse(status_code=400, content={"detail": "Incorrect password"})

    new_pw = req.new_password or ""
    if len(new_pw) < 8:
        return JSONResponse(
            status_code=400,
            content={"detail": "Password must be at least 8 characters"},
        )
    if len(new_pw.encode("utf-8")) > 72:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Password is too long (max 72 bytes for secure hashing)"
            },
        )
    if new_pw != (req.new_password_confirm or ""):
        return JSONResponse(
            status_code=400,
            content={"detail": "Passwords do not match"},
        )

    if not user_db.update_password(user["user_id"], hash_password(new_pw)):
        return JSONResponse(status_code=400, content={"detail": "Could not update password"})

    fresh = user_db.get_by_id(user["user_id"])
    token = create_token(
        fresh["id"], fresh["username"], fresh.get("token_version", 0),
    )
    response = JSONResponse(content={"status": "success"})
    _set_auth_cookies(response, token)
    return response


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
