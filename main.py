"""
FastAPI Application — Literature Research Aide v4.1.1
Multi-user web interface for literature search and analysis.
Multiple libraries (workspaces) per account.
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
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from functools import partial
import asyncio
import contextvars

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
from citations import collection_to_ris, collection_to_bibtex, collection_to_apa
from feature_guides import get_guide, list_guides, neighbors
from sample_corpus import get_sample_articles
from screening_reasons import (
    EXCLUSION_REASONS,
    USER_SELECTABLE_REASONS,
    normalize_reason,
    reason_label,
)
from libraries import (
    create_library,
    delete_library,
    get_active_library_id,
    list_libraries,
    library_db_path,
    pipeline_cache_key,
    rename_library,
    set_active_library,
    ensure_libraries,
)
import shares as shares_mod
from pathlib import Path
from urllib.parse import quote, unquote

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
app = FastAPI(title="Literature Research Aide", version="4.1.1")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
@app.get("/health")
async def health():
    return {"status": "healthy", "version": "4.1.1"}


@app.get("/api/ui-flags")
async def api_ui_flags():
    """Deployer toggles for classroom UI (env: HIDE_STUDY_TYPE_TAGS, HIDE_AI_BUTTONS).

    Public so the app shell can load flags before authenticated API calls.
    Extractive key points are never gated by these flags.
    """
    from ui_flags import get_ui_flags
    return get_ui_flags()


@app.get("/api/sources")
async def api_sources():
    """Public source catalog: names, student tips, topics, HS packs (Phase R4).

    Single source of truth is source_catalog.py so Data Management, coverage,
    and duplicate priority stay aligned.
    """
    from source_catalog import public_catalog
    return public_catalog()


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- User account database ---
user_db = UserDatabase()

# --- Per-library pipeline cache (lazy-initialised, LRU-bounded) ---
# Keys are "user_id:library_id" (see libraries.pipeline_cache_key).
_pipelines: "OrderedDict[str, LiteratureSearchPipeline]" = OrderedDict()
# Number of in-flight requests holding each pipeline. A pipeline is only safe
# to close when its refcount hits 0; otherwise eviction defers the close.
_pipeline_refcounts: "OrderedDict[str, int]" = OrderedDict()
# Pipelines evicted while still in use, keyed by cache key — closed on last
# release. A key can accumulate several evicted generations (evict → recreate
# → evict again while requests still hold references), so each entry is a list.
_pending_close: "dict[str, list[LiteratureSearchPipeline]]" = {}
# Guards _pipelines, _pipeline_refcounts and _pending_close together.
_pipelines_lock = threading.Lock()

# Bind library id for the current request/task so release_pipeline(uid) matches
# the same library even if the user switches active library in another tab.
_pipeline_lib_ctx: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "pipeline_lib_id", default=None
)

# --- Per-user progress tracking (LRU-bounded; one job type at a time per user) ---
_all_progress: "OrderedDict[str, dict]" = OrderedDict()
_progress_lock = threading.Lock()


def get_pipeline(
    user_id: str, library_id: Optional[str] = None
) -> LiteratureSearchPipeline:
    """Return the pipeline for the user's active (or given) library.

    The caller MUST pair every get_pipeline() with a release_pipeline() in a
    finally block so deferred closes can run once the request completes.
    """
    ensure_libraries(user_id)
    lib_id = library_id or _pipeline_lib_ctx.get() or get_active_library_id(user_id)
    _pipeline_lib_ctx.set(lib_id)
    key = pipeline_cache_key(user_id, lib_id)
    with _pipelines_lock:
        if key not in _pipelines:
            db_path = library_db_path(user_id, lib_id)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            pipe = LiteratureSearchPipeline(
                db_path=str(db_path),
                embedding_model="general",
            )
            setattr(pipe, "_lra_cache_key", key)
            setattr(pipe, "_lra_library_id", lib_id)
            _pipelines[key] = pipe
            # Evict least-recently-used pipelines to bound memory.
            while len(_pipelines) > MAX_CACHED_USERS:
                old_key, old_pipeline = _pipelines.popitem(last=False)
                if _pipeline_refcounts.get(old_key, 0) > 0:
                    _pending_close.setdefault(old_key, []).append(old_pipeline)
                    continue
                try:
                    old_pipeline.db.close()
                except Exception:
                    logger.exception("Failed to close evicted pipeline for %s", old_key)
        _pipelines.move_to_end(key)
        _pipeline_refcounts[key] = _pipeline_refcounts.get(key, 0) + 1
        return _pipelines[key]


def release_pipeline(user_id: str, library_id: Optional[str] = None) -> None:
    """Drop an in-flight reference, closing a deferred-evicted pipeline at 0."""
    try:
        lib_id = library_id or _pipeline_lib_ctx.get() or get_active_library_id(user_id)
        key = pipeline_cache_key(user_id, lib_id)
    except Exception:
        key = user_id
    with _pipelines_lock:
        count = _pipeline_refcounts.get(key, 0) - 1
        if count > 0:
            _pipeline_refcounts[key] = count
            return
        _pipeline_refcounts.pop(key, None)
        for pipeline in _pending_close.pop(key, []):
            try:
                pipeline.db.close()
            except Exception:
                logger.exception("Failed to close deferred pipeline for %s", key)
    # Clear request binding after last matching release for this task context.
    if library_id is None or _pipeline_lib_ctx.get() == library_id:
        _pipeline_lib_ctx.set(None)


def _evict_pipeline(user_id: str) -> None:
    """Forcibly drop and close all cached pipelines for a user (account delete)."""
    prefix = f"{user_id}:"
    with _pipelines_lock:
        # Union of live, pending-close, and refcount keys: an entry can exist
        # in _pending_close (or hold a refcount) without a live counterpart.
        keys = {
            k
            for k in [*_pipelines, *_pending_close, *_pipeline_refcounts]
            if k == user_id or k.startswith(prefix)
        }
        for key in keys:
            live = _pipelines.pop(key, None)
            pending = _pending_close.pop(key, [])
            _pipeline_refcounts.pop(key, None)
            for pipe in [live, *pending]:
                if pipe is not None:
                    try:
                        pipe.db.close()
                    except Exception:
                        logger.exception(
                            "Failed to close pipeline for %s during deletion", key
                        )
    with _progress_lock:
        _all_progress.pop(user_id, None)


def _ensure_progress(user_id: str) -> dict:
    """Return progress dict for user, creating it if needed. Must be called under _progress_lock."""
    if user_id not in _all_progress:
        _all_progress[user_id] = {
            'fetch': {
                'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None,
                'cancel': False, 'articles_so_far': 0, 'message': '',
            },
            'embed': {
                'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None,
                'cancel': False, 'articles_so_far': 0, 'message': '',
            },
        }
        while len(_all_progress) > MAX_CACHED_USERS:
            _all_progress.popitem(last=False)
    _all_progress.move_to_end(user_id)
    # Backfill keys if an older in-memory entry lacks them.
    for task in ('fetch', 'embed'):
        slot = _all_progress[user_id].setdefault(
            task, {
                'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None,
                'cancel': False, 'articles_so_far': 0, 'message': '',
            }
        )
        slot.setdefault('result', None)
        slot.setdefault('error', None)
        slot.setdefault('cancel', False)
        slot.setdefault('articles_so_far', 0)
        slot.setdefault('message', '')
    return _all_progress[user_id]


def update_progress(user_id: str, task: str, **kwargs):
    with _progress_lock:
        _ensure_progress(user_id)[task].update(kwargs)


def is_job_cancelled(user_id: str, task: str) -> bool:
    with _progress_lock:
        return bool(_ensure_progress(user_id)[task].get('cancel'))


def request_job_cancel(user_id: str, task: str) -> bool:
    """Set cancel flag for an active job. Returns False if nothing active."""
    with _progress_lock:
        slot = _ensure_progress(user_id)[task]
        if not slot.get('active'):
            return False
        slot['cancel'] = True
        slot['message'] = 'Cancelling…'
        return True


def start_user_job(uid: str, task: str, fn, /, **kwargs) -> bool:
    """Run fn(pipeline, **kwargs) in a thread; progress + result in _all_progress.

    Returns False if a job of this task type is already active for uid.
    The worker holds the pipeline ref until completion (release in done callback).
    Jobs bind to the library that was active when the job started.
    """
    with _progress_lock:
        p = _ensure_progress(uid)
        if p[task].get('active'):
            return False
        p[task].update({
            'active': True, 'done': 0, 'total': 0, 'result': None, 'error': None,
            'cancel': False, 'articles_so_far': 0, 'message': '',
        })

    lib_id = get_active_library_id(uid)
    pipe = get_pipeline(uid, lib_id)
    loop = asyncio.get_running_loop()

    def worker():
        return fn(pipe, **kwargs)

    future = loop.run_in_executor(None, worker)

    def _on_done(fut):
        try:
            result = fut.result()
            update_progress(uid, task, active=False, result=result, error=None, cancel=False)
        except Exception as exc:
            logger.exception("Background %s job failed for %s", task, uid)
            update_progress(uid, task, active=False, result=None, error=str(exc), cancel=False)
        finally:
            release_pipeline(uid, lib_id)

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

class MultiFetchRequest(BaseModel):
    sources: List[str]
    query: str
    max_results: int = Field(default=100, ge=1, le=1000)
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

class AIArticleRequest(BaseModel):
    """Identify one paper in the active library for optional AI assist."""
    article_id: str
    source: str
    # When true, store refined key_points in the library (overwrites extractive).
    # API convenience only — the UI saves the displayed points via
    # /api/ai/key-points instead, so a second generation can't diverge from
    # what the student approved.
    save_key_points: bool = False

class AISaveKeyPointsRequest(BaseModel):
    """Persist the AI key points the student actually saw (no regeneration)."""
    article_id: str
    source: str
    key_points: List[str]

class AIAskRequest(BaseModel):
    article_id: str
    source: str
    question: str

class AISettingsUpdate(BaseModel):
    """Server-wide AI deploy settings (keys stored in user_data/ai_settings.json)."""
    llm_provider: Optional[str] = None
    ollama_host: Optional[str] = None
    ollama_model: Optional[str] = None
    ollama_models_dir: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_timeout_seconds: Optional[str] = None

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
    # Exclusion reason code (see screening_reasons.EXCLUSION_REASONS).
    reason: Optional[str] = "manual"

class ClusterScreeningRequest(BaseModel):
    action: str = Field(default="exclude", pattern="^(exclude|include)$")
    reason: Optional[str] = "cluster"

class SampleCorpusRequest(BaseModel):
    # True = wipe collection first (demo reset). False = append samples.
    clear_first: bool = True

class LibraryCreateRequest(BaseModel):
    name: str = Field(default="New library", min_length=1, max_length=64)

class LibraryRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)

class LibrarySwitchRequest(BaseModel):
    library_id: str

class ResolveDuplicatesRequest(BaseModel):
    threshold: float = Field(default=0.95, ge=0.5, le=1.0)

class DeleteAccountRequest(BaseModel):
    password: str


class ShareCreateRequest(BaseModel):
    library_id: Optional[str] = None
    expires_days: Optional[int] = Field(default=14, ge=1, le=365)
    max_uses: Optional[int] = Field(default=None, ge=1, le=10000)
    include_embeddings: bool = True


class ExportArticleKey(BaseModel):
    article_id: str
    source: str


class ExportSelectionRequest(BaseModel):
    """Export an ordered list of library papers (e.g. current search hits)."""
    format: str = "ris"  # ris | bibtex | csv | txt
    items: List[ExportArticleKey] = Field(default_factory=list)


class ShareJoinRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=32)


def _safe_next_url(raw: Optional[str]) -> str:
    """Allow only same-origin relative paths (open-redirect safe)."""
    if not raw:
        return "/data-management"
    path = unquote(raw).strip()
    if not path.startswith("/") or path.startswith("//"):
        return "/data-management"
    if any(c in path for c in ("\n", "\r", "\\")):
        return "/data-management"
    if "://" in path:
        return "/data-management"
    return path


# ============================================================
# Auth routes
# ============================================================

@app.get("/login")
async def login_page(request: Request):
    next_url = _safe_next_url(request.query_params.get("next"))
    if current_user(request):
        return RedirectResponse(url=next_url, status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        context={"error": "", "info": "", "next": next_url if next_url != "/data-management" else ""},
    )


@app.post("/login")
@limiter.limit("10/minute")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    next_url = _safe_next_url(next or request.query_params.get("next"))
    username = username.strip().lower()
    user = user_db.get_by_username(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": "Invalid username or password",
                "info": "",
                "next": next if next else "",
            },
            status_code=400,
        )
    token = create_token(
        user["id"], user["username"], user.get("token_version", 0),
    )
    response = RedirectResponse(url=next_url, status_code=302)
    _set_auth_cookies(response, token)
    return response


@app.get("/register")
async def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "register.html", context={"error": "", "username": ""})


def _reset_codes_in_response() -> bool:
    """Classroom/self-host: show the reset code when DEBUG or explicit flag is set."""
    if os.getenv("RESET_CODES_IN_RESPONSE", "").strip().lower() in ("1", "true", "yes"):
        return True
    return os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes")


@app.get("/reset-password")
async def reset_password_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(
        request, "reset_password.html",
        context={"error": "", "info": "", "username": "", "reset_code": ""},
    )


@app.post("/reset-password/request")
@limiter.limit("5/minute")
async def reset_password_request(request: Request, username: str = Form(...)):
    """Issue a one-time reset code. Always looks successful (no user enum)."""
    username = (username or "").strip().lower()
    token = user_db.create_password_reset_token(username) if username else None
    if token:
        logger.info("Password reset code issued for %s", username)
    info = (
        "If that login exists, a reset code was created. "
        "Enter it below with a new password."
    )
    reset_code = ""
    if token and _reset_codes_in_response():
        # Self-hosted / DEBUG: surface the code so teachers don't need SMTP.
        reset_code = token
        info = (
            "Reset code created (shown once below — DEBUG/classroom mode). "
            "Use it with your new password."
        )
    return templates.TemplateResponse(
        request, "reset_password.html",
        context={
            "error": "",
            "info": info,
            "username": username,
            "reset_code": reset_code,
        },
    )


@app.post("/reset-password/confirm")
@limiter.limit("10/minute")
async def reset_password_confirm(
    request: Request,
    username: str = Form(...),
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    username = (username or "").strip().lower()
    error = None
    if len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != password_confirm:
        error = "Passwords do not match."
    elif len(password.encode("utf-8")) > 72:
        error = "Password is too long (max 72 bytes)."
    if error:
        return templates.TemplateResponse(
            request, "reset_password.html",
            context={"error": error, "info": "", "username": username, "reset_code": ""},
            status_code=400,
        )
    ok, err = user_db.consume_password_reset_token(
        username, token, hash_password(password),
    )
    if not ok:
        return templates.TemplateResponse(
            request, "reset_password.html",
            context={"error": err, "info": "", "username": username, "reset_code": ""},
            status_code=400,
        )
    return templates.TemplateResponse(
        request, "login.html",
        context={"error": "", "info": "Password updated. You can log in now.", "next": ""},
    )


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


@app.get("/join")
async def join_page(request: Request):
    """Join a shared library by class code (auth required)."""
    code = (request.query_params.get("code") or "").strip()
    user = current_user(request)
    if not user:
        next_path = "/join" + (f"?code={quote(code)}" if code else "")
        return RedirectResponse(
            url=f"/login?next={quote(next_path, safe='')}",
            status_code=302,
        )
    return templates.TemplateResponse(
        request,
        "join.html",
        context={
            "active_page": "account",
            "user": user,
            "join_code": code,
        },
    )


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


def _attach_study_types(results: List[dict]) -> None:
    """Heuristic study-type tags at search time (cheap; may be wrong)."""
    from ui_flags import get_ui_flags
    if not get_ui_flags().get("show_study_type_tags", True):
        return
    from study_type import attach_study_types
    attach_study_types(results)


def _enrich_search_results(results: List[dict], p, *, query_text: str = "", pico_boost: bool = False) -> None:
    """Shared post-rank enrichment for search / seed / starred."""
    _attach_pico(results)
    if pico_boost and query_text:
        _apply_pico_boost(results, query_text)
    _attach_notes(results, p)
    _attach_key_points(results, p)
    _attach_study_types(results)


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
        _enrich_search_results(
            results, p, query_text=req.query_text, pico_boost=req.pico_boost,
        )
        sort_articles(results, req.sort_by)
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
        _enrich_search_results(results, p)
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
        _enrich_search_results(results, p)
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


def _format_ranked_export(results: List[dict], fmt: str):
    """Build download body for an ordered result list (search hits or selection)."""
    fmt = (fmt or "csv").lower().strip()
    if fmt == "ris":
        return collection_to_ris(results), "application/x-research-info-systems", "search_results.ris"
    if fmt == "bibtex":
        return collection_to_bibtex(results), "application/x-bibtex", "search_results.bib"
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Rank", "Similarity", "Title", "Year", "Journal", "Authors",
            "Source", "ID", "Cluster ID", "Cluster Label",
        ])
        for i, a in enumerate(results, 1):
            writer.writerow([
                i, f"{a.get('similarity_score', 0):.3f}" if a.get("similarity_score") is not None else "",
                a.get("title", ""), a.get("year", ""),
                a.get("journal", ""), "; ".join(a.get("authors") or []),
                a.get("source", ""), a.get("article_id", ""),
                a.get("cluster_id", ""), a.get("cluster_label", ""),
            ])
        return output.getvalue(), "text/csv", "search_results.csv"
    # txt
    lines = []
    for i, a in enumerate(results, 1):
        sim = a.get("similarity_score")
        rank_bit = f"[{sim:.3f}] " if isinstance(sim, (int, float)) else ""
        lines.append(f"{i}. {rank_bit}{a.get('title', '')}")
        lines.append(f"   Year: {a.get('year', '')} | Journal: {a.get('journal', '')}")
        lines.append(f"   Authors: {'; '.join(a.get('authors') or [])}")
        lines.append(f"   Source: {a.get('source', '')} | ID: {a.get('article_id', '')}")
        if a.get("cluster_label"):
            lines.append(f"   Cluster: {a.get('cluster_label')}")
        lines.append("")
    return "\n".join(lines), "text/plain", "search_results.txt"


@app.post("/api/export/selection")
@limiter.limit("30/minute")
async def api_export_selection(req: ExportSelectionRequest, request: Request):
    """Export the exact ordered list of papers shown in Search (what you see is what you get)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    fmt = (req.format or "ris").lower().strip()
    if fmt not in ("csv", "txt", "ris", "bibtex"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    items = list(req.items or [])
    if not items:
        return JSONResponse(
            status_code=400,
            content={"detail": "No papers to export. Run a search first."},
        )
    if len(items) > 2000:
        return JSONResponse(status_code=400, content={"detail": "Too many papers (max 2000)."})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        def _load():
            rows = []
            for key in items:
                art = p.db.get_article_by_id(key.article_id, key.source)
                if art:
                    rows.append(art)
            return rows

        results = await run_in_thread(_load)
        if not results:
            return JSONResponse(
                status_code=400,
                content={"detail": "None of those papers were found in the active library."},
            )
        content, media_type, filename = _format_ranked_export(results, fmt)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


def _library_rows_to_csv(rows: List[dict]) -> str:
    """CSV for GET /api/export/library?format=csv (includes Starred / Note columns)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Year", "Journal", "Authors", "Source", "ID",
        "Cluster ID", "Cluster Label", "Excluded", "Exclusion Reason",
        "Starred", "Note",
    ])
    for a in rows:
        writer.writerow([
            a.get("title", ""),
            a.get("year", ""),
            a.get("journal", ""),
            "; ".join(a.get("authors") or []),
            a.get("source", ""),
            a.get("article_id", ""),
            a.get("cluster_id", ""),
            a.get("cluster_label", ""),
            "yes" if a.get("excluded") else "no",
            a.get("exclusion_reason", ""),
            "yes" if a.get("starred") else "no",
            a.get("note", ""),
        ])
    return output.getvalue()


@app.get("/api/export/library")
async def api_export_library(
    request: Request,
    scope: str = "all",
    format: str = "csv",
):
    """Export the collection with cluster membership and exclusion reasons.

    scope: all | included | excluded | starred
    format: csv | txt | ris | bibtex | apa
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if scope not in ("all", "included", "excluded", "starred"):
        return JSONResponse(status_code=400, content={"detail": "Invalid scope"})
    fmt = (format or "csv").lower().strip()
    if fmt not in ("csv", "txt", "ris", "bibtex", "apa"):
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
        elif fmt == "apa":
            content = collection_to_apa(rows)
            media_type = "text/plain"
            filename = "library_apa.txt"
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
            content = _library_rows_to_csv(rows)
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


def _run_multi_fetch(p, *, query, sources, max_results, email, clear_first, uid):
    """Blocking multi-source fetch for sync wait= or background jobs."""
    update_progress(
        uid, 'fetch', done=0, total=len(sources),
        articles_so_far=0, message='Starting fetch…', cancel=False,
    )
    if clear_first:
        p.db.clear_all()
        p.invalidate_corpus_cache()

    def on_source_done(done, total, **extra):
        arts = extra.get('articles_so_far', 0)
        src = extra.get('source') or ''
        sc = extra.get('source_count', 0)
        kind = extra.get('error_kind')
        if kind and kind not in (None, 'no_results'):
            msg = f"{done}/{total} sources · {arts} papers · {src}: {kind}"
        else:
            msg = f"{done}/{total} sources · {arts} papers · last: {src} (+{sc})"
        update_progress(
            uid, 'fetch', done=done, total=total,
            articles_so_far=arts, message=msg,
        )

    results = p.fetch_articles_parallel(
        query=query,
        sources=sources,
        max_results=max_results,
        email=email or "user@example.com",
        progress_callback=on_source_done,
        cancel_check=lambda: is_job_cancelled(uid, 'fetch'),
    )
    p.invalidate_corpus_cache()
    total = sum(v['count'] for v in results.values())
    errors = {src: v['error'] for src, v in results.items() if v['error']}
    error_kinds = {
        src: v.get('error_kind')
        for src, v in results.items()
        if v.get('error_kind')
    }
    ok = {src: v['count'] for src, v in results.items() if not v['error']}
    cancelled = is_job_cancelled(uid, 'fetch')
    return {
        "status": "cancelled" if cancelled else "success",
        "total_fetched": total,
        "by_source": {src: v['count'] for src, v in results.items()},
        "ok_sources": ok,
        "errors": errors,
        "error_kinds": error_kinds,
        "cleared_first": clear_first,
        "cancelled": cancelled,
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
                    result=None, error=None, cancel=False, articles_so_far=0)
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


@app.post("/api/jobs/{task}/cancel")
@limiter.limit("30/minute")
async def api_cancel_job(task: str, request: Request):
    """Request cancel for an active background job (fetch or embed)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if task not in ("fetch", "embed"):
        return JSONResponse(status_code=400, content={"detail": "Unknown task"})
    ok = request_job_cancel(user["user_id"], task)
    if not ok:
        return JSONResponse(
            status_code=409,
            content={"detail": f"No active {task} job to cancel"},
        )
    return {"status": "cancelling", "task": task}


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


@app.get("/api/ai/settings")
async def api_ai_settings_get(request: Request):
    """Masked AI deploy settings for the Account page."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    from llm_service import public_ai_settings, status as ai_status
    return {"settings": public_ai_settings(), "status": ai_status()}


@app.post("/api/ai/settings")
@limiter.limit("20/minute")
async def api_ai_settings_save(req: AISettingsUpdate, request: Request):
    """Save server-wide AI keys/models (user_data/ai_settings.json)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from llm_service import public_ai_settings, save_ai_settings, status as ai_status
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if "llm_provider" in payload:
        prov = str(payload["llm_provider"]).strip().lower()
        if prov not in ("auto", "ollama", "openai", "anthropic"):
            return JSONResponse(
                status_code=400,
                content={"detail": "llm_provider must be auto, ollama, openai, or anthropic"},
            )
        payload["llm_provider"] = prov
    save_ai_settings(payload)
    return {
        "status": "success",
        "settings": public_ai_settings(),
        "status_detail": ai_status(),
    }


@app.post("/api/ai/ollama/start")
@limiter.limit("6/minute")
async def api_ai_ollama_start(request: Request):
    """Start local Ollama (detached), using OLLAMA_MODELS when set.

    Internal/ops endpoint: no UI caller (Refine/Ask auto-start the built-in
    service themselves). Kept as a deployer escape hatch, gated by
    ollama_control_allowed().
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from llm_service import start_ollama, status as ai_status
    ok, msg = await run_in_thread(start_ollama)
    return {
        "ok": ok,
        "message": msg,
        "status": ai_status(),
    }


@app.post("/api/ai/ollama/stop")
@limiter.limit("6/minute")
async def api_ai_ollama_stop(request: Request):
    """Stop Ollama server and model runners (frees VRAM).

    Internal/ops endpoint: no UI caller. Kept as a deployer escape hatch,
    gated the same way as /api/ai/ollama/start.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from llm_service import stop_ollama, status as ai_status
    ok, msg = await run_in_thread(stop_ollama)
    return {
        "ok": ok,
        "message": msg,
        "status": ai_status(),
    }


def _ai_unconfigured_detail() -> str:
    return (
        "AI is unavailable (not configured). Open Account → AI study aid and choose "
        "Built-in study aid or Cloud API key. Extractive key points still work."
    )


def _friendly_ai_unavailable(detail: str) -> str:
    low = (detail or "").lower()
    if "ollama" in low or "not running" in low or "not reachable" in low:
        return (
            "Built-in study aid is not ready (503). Try again in a moment, or switch "
            "to Cloud API key on Account. Extractive key points still work without AI."
        )
    return detail or "AI study aid unavailable."


@app.post("/api/ai/refine-article")
@limiter.limit("8/minute")
async def api_ai_refine_article(req: AIArticleRequest, request: Request):
    """Optional LLM rewrite of summary/key points from the abstract only.

    Built-in mode: start local service → refine → stop when idle (ephemeral).
    Default corpus key points stay extractive. Never bulk-rewrites a library.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from llm_service import (
            LLMError,
            LLMUnavailable,
            is_configured,
            refine_article,
            run_with_ephemeral_builtin,
        )

        if not is_configured():
            return JSONResponse(status_code=503, content={"detail": _ai_unconfigured_detail()})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})
        existing = (p.db.get_key_points_map().get((req.article_id, req.source)) or [])

        def _work():
            return run_with_ephemeral_builtin(
                lambda: refine_article(
                    title=article.get("title") or "",
                    abstract=article.get("abstract") or "",
                    existing_key_points=existing,
                    source=req.source or "",
                    article_id=req.article_id or "",
                )
            )

        result = await run_in_thread(_work)
        if req.save_key_points and result.get("key_points"):
            p.db.insert_key_points({
                (req.article_id, req.source): result["key_points"],
            })
            result["saved"] = True
        else:
            result["saved"] = False
        result["article_id"] = req.article_id
        result["source"] = req.source
        result["label"] = "AI rewrite (from the abstract only — not extractive)"
        return result
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"detail": _friendly_ai_unavailable(str(e))})
    except LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/ai/key-points")
@limiter.limit("30/minute")
async def api_ai_save_key_points(req: AISaveKeyPointsRequest, request: Request):
    """Save the displayed AI key points for one article (explicit user action).

    Deliberately does not re-run the model: what the student approved is
    exactly what gets stored.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        points = [str(x).strip()[:500] for x in (req.key_points or []) if str(x).strip()]
        points = points[:6]
        if not points:
            return JSONResponse(status_code=400, content={"detail": "No key points to save."})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})
        p.db.insert_key_points({(req.article_id, req.source): points})
        return {"status": "success", "saved": True, "key_points": points}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/ai/ask-article")
@limiter.limit("8/minute")
async def api_ai_ask_article(req: AIAskRequest, request: Request):
    """Answer a question using only this paper's title + abstract (opt-in AI).

    Same lifecycle as Refine for built-in mode: start → answer → stop when idle.
    One paper per request — no whole-library Q&A (R5).
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from llm_service import (
            LLMError,
            LLMUnavailable,
            ask_article,
            is_configured,
            run_with_ephemeral_builtin,
        )

        if not is_configured():
            return JSONResponse(status_code=503, content={"detail": _ai_unconfigured_detail()})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})

        def _work():
            return run_with_ephemeral_builtin(
                lambda: ask_article(
                    question=req.question,
                    title=article.get("title") or "",
                    abstract=article.get("abstract") or "",
                    source=req.source or "",
                    article_id=req.article_id or "",
                )
            )

        result = await run_in_thread(_work)
        result["article_id"] = req.article_id
        result["source"] = req.source
        result["label"] = "AI answer (title + abstract only)"
        return result
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"detail": _friendly_ai_unavailable(str(e))})
    except LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
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
            reason = normalize_reason(req.reason, default="manual")
            count = p.db.exclude_articles(keys, reason=reason)
        else:
            count = p.db.include_articles(keys)
            reason = None
        p.invalidate_corpus_cache()
        return {
            "status": "success",
            "action": req.action,
            "count": count,
            "reason": reason,
        }
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
            reason = normalize_reason(req.reason, default="cluster")
            count = p.db.exclude_articles(keys, reason=reason)
        else:
            count = p.db.include_articles(keys)
            reason = None
        p.invalidate_corpus_cache()
        return {
            "status": "success",
            "action": req.action,
            "cluster_id": cluster_id,
            "count": count,
            "reason": reason,
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@app.post("/api/load-sample-corpus")
@limiter.limit("6/minute")
async def api_load_sample_corpus(req: SampleCorpusRequest, request: Request):
    """Load the built-in demo paper set (no external API calls)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        if req.clear_first:
            p.db.clear_all()
        articles = get_sample_articles()
        stats = p.db.insert_articles(articles, dedupe=True)
        p.invalidate_corpus_cache()
        inserted = stats.get("inserted", 0) if isinstance(stats, dict) else 0
        return {
            "status": "success",
            "loaded": len(articles),
            "inserted": inserted,
            "updated": stats.get("updated", 0) if isinstance(stats, dict) else 0,
            "cleared_first": req.clear_first,
            "hint": "Prepare papers for search next (or it auto-runs after a normal fetch).",
        }
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


# ---------- Libraries (multi-collection workspaces) ----------

@app.get("/api/libraries")
async def api_list_libraries(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        return list_libraries(user["user_id"])
    except Exception as e:
        return server_error(e)


@app.post("/api/libraries")
@limiter.limit("30/minute")
async def api_create_library(req: LibraryCreateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = create_library(user["user_id"], req.name)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@app.post("/api/libraries/switch")
@limiter.limit("60/minute")
async def api_switch_library(req: LibrarySwitchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = set_active_library(user["user_id"], req.library_id)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@app.patch("/api/libraries/{library_id}")
@limiter.limit("30/minute")
async def api_rename_library(library_id: str, req: LibraryRenameRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = rename_library(user["user_id"], library_id, req.name)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@app.delete("/api/libraries/{library_id}")
@limiter.limit("20/minute")
async def api_delete_library(library_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        # Refuse to delete while requests or background jobs still hold the
        # pipeline (jobs keep a reference until completion): closing the DB
        # under them would abort work or remove the file mid-write.
        key = pipeline_cache_key(uid, library_id)
        with _pipelines_lock:
            if _pipeline_refcounts.get(key, 0) > 0:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "This library is in use (an active job or "
                        "request). Wait for it to finish, then try again."
                    },
                )
            # Drop cached pipeline for this library before deleting files.
            pipe = _pipelines.pop(key, None)
            pending = _pending_close.pop(key, [])
        for p in [pipe, *pending]:
            if p is not None:
                try:
                    p.db.close()
                except Exception:
                    pass
        result = delete_library(uid, library_id)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


# ---------- Shares (class codes → clone library) ----------

@app.post("/api/shares")
@limiter.limit("10/hour")
async def api_create_share(req: ShareCreateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        ensure_libraries(uid)
        lib_id = (req.library_id or "").strip() or get_active_library_id(uid)
        if not shares_mod.library_exists(uid, lib_id):
            return JSONResponse(status_code=400, content={"detail": "Library not found."})
        title = shares_mod.library_name(uid, lib_id) or "Shared library"
        expires_at = None
        if req.expires_days is not None:
            expires_at = (
                datetime.now(timezone.utc) + timedelta(days=int(req.expires_days))
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Retry a few times on rare code collision.
        share = None
        last_err = None
        for _ in range(5):
            code = shares_mod.generate_share_code()
            try:
                share = user_db.create_share(
                    owner_user_id=uid,
                    owner_library_id=lib_id,
                    title_snapshot=title,
                    code=code,
                    include_embeddings=bool(req.include_embeddings),
                    expires_at=expires_at,
                    max_uses=req.max_uses,
                )
                break
            except ValueError as e:
                last_err = e
                continue
        if share is None:
            raise last_err or ValueError("Could not create share code.")
        return {
            "status": "success",
            "share": {
                **share,
                "join_path": f"/join?code={share['code']}",
            },
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@app.get("/api/shares")
@limiter.limit("60/minute")
async def api_list_shares(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        items = user_db.list_shares_for_owner(user["user_id"])
        out = []
        for s in items:
            out.append({
                **s,
                "join_path": f"/join?code={s['code']}",
                "active": (
                    not s.get("revoked_at")
                    and shares_mod.is_share_usable(s)[0]
                ),
            })
        return {"shares": out}
    except Exception as e:
        return server_error(e)


@app.delete("/api/shares/{share_id}")
@limiter.limit("30/minute")
async def api_revoke_share(share_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        ok = user_db.revoke_share(share_id, user["user_id"])
        if not ok:
            existing = user_db.get_share_by_id(share_id)
            if existing and existing.get("owner_user_id") == user["user_id"]:
                return {"status": "success", "revoked": True, "already": True}
            return JSONResponse(status_code=404, content={"detail": "Share not found."})
        return {"status": "success", "revoked": True}
    except Exception as e:
        return server_error(e)


@app.get("/api/shares/preview")
@limiter.limit("30/minute")
async def api_preview_share(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    code = request.query_params.get("code") or ""
    try:
        preview = await run_in_thread(
            shares_mod.preview_share, user_db, user["user_id"], code
        )
        return preview
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@app.post("/api/shares/join")
@limiter.limit("20/hour")
async def api_join_share(req: ShareJoinRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = await run_in_thread(
            shares_mod.join_share,
            user_db,
            user["user_id"],
            user["username"],
            req.code,
        )
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


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
        # 1. Close + drop every cached pipeline for this user (all libraries).
        _evict_pipeline(uid)
        # 2. Remove the user's data directory (all libraries + meta). Errors
        # propagate: the account record is only deleted after the private data
        # is confirmed gone, so a failed removal keeps the account (and this
        # endpoint retryable) instead of orphaning data with no owner.
        # Honour USER_DATA_DIR the same way libraries.py does.
        from libraries import user_dir as lib_user_dir
        udir = lib_user_dir(uid)
        if udir.is_dir():
            shutil.rmtree(udir)
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
