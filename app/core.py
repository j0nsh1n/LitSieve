"""Shared runtime state and helpers used by every route module.

Holds the things that must be process-wide singletons: the account database,
the per-library pipeline cache (with reference counting so a pipeline is never
closed while a request or background job still holds it), per-user job
progress, and the auth/CSRF helpers.

Tests patch state here (e.g. ``monkeypatch.setattr(core, "user_db", ...)``),
so route modules reach mutable state through the module (``core.user_db``)
rather than binding it at import time.
"""

import asyncio
import contextvars
import logging
import os
import secrets
import threading
from collections import OrderedDict
from functools import partial
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import get_current_user
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.libraries import (
    ensure_libraries,
    get_active_library_id,
    library_db_path,
    pipeline_cache_key,
)
from app.storage.user_db import UserDatabase

logger = logging.getLogger(__name__)

COOKIE_SECURE = os.getenv("DEBUG", "").strip().lower() not in ("1", "true", "yes")
MAX_CACHED_USERS = 50

templates = Jinja2Templates(directory="templates")


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


def run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, partial(func, *args, **kwargs))
