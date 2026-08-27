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
import ipaddress
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
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
PROCESS_STARTED = time.time()
SUPPORT_VIEW_COOKIE = "support_view"
_SAFE_ERR_PATH = re.compile(r"(?:/[A-Za-z0-9._-]+){2,}")
_MISSING = object()


def _template_context(request: Request) -> dict:
    user = current_user(request)
    notice = None
    site = {}
    try:
        from app.storage import helpdesk
        notice = helpdesk.published_banner(user_db)
        site = helpdesk.public_site_content(user_db)
    except Exception:
        logger.exception("Could not load site notice/content")
    return {
        "support_view": (user or {}).get("support_view"),
        "site_notice": notice,
        "site_content": site,
        "known_issues": site.get("known_issues") or "",
        "support_links": site.get("support_links") or [],
    }


templates = Jinja2Templates(
    directory="templates",
    context_processors=[_template_context],
)


def client_bucket(request: Request) -> str:
    """Network-level identity for rate limiting.

    IPv4 is keyed on the address. IPv6 is keyed on the **/64 prefix**, because a
    single ordinary IPv6 client is handed a whole /64 and can rotate through
    billions of addresses for free -- keying the full address would make the
    login limiter trivially bypassable. Observed in our own access log: Meta's
    crawler hit us from 2a03:2880:18ff:1b::, :12ff:5::, :11ff:3:: and more, all
    one operator that per-address keying counts as separate clients.
    """
    addr = get_remote_address(request)
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Unparseable (or missing) -- key on whatever we were given rather than
        # collapsing every such caller into one shared bucket.
        return addr
    if ip.version == 6:
        return f"{ipaddress.ip_network(f'{addr}/64', strict=False).network_address}/64"
    return addr


def rate_limit_key(request: Request) -> str:
    """Authenticated users get their own bucket; anonymous falls back to network.

    Login/register stay network-keyed (no cookie yet), which is what we want for
    brute-force protection. Classroom NATs no longer share one budget once
    users are signed in.
    """
    user = get_current_user(request)
    if user and user.get("user_id"):
        return f"user:{user['user_id']}"
    return client_bucket(request)


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
# Live workers for helpdesk stall detection. Keyed (user_id, task).
_job_futures: dict = {}
_job_sync: dict = {}
JOB_STALE_SECONDS = 300
JOB_QUEUE_CAP = 25


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
        for task in ('fetch', 'embed'):
            _release_job_markers(user_id, task)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _empty_job_slot(task: str) -> dict:
    slot = {
        'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None,
        'cancel': False, 'articles_so_far': 0, 'message': '',
        'started_at': None, 'updated_at': None, 'library_id': None,
    }
    if task == 'fetch':
        slot.update(sources=[], by_source={}, source_status={})
    return slot


def _ensure_progress(user_id: str) -> dict:
    """Return progress dict for user, creating it if needed. Must be called under _progress_lock."""
    if user_id not in _all_progress:
        _all_progress[user_id] = {
            'fetch': _empty_job_slot('fetch'),
            'embed': _empty_job_slot('embed'),
        }
        while len(_all_progress) > MAX_CACHED_USERS:
            evicted, _ = _all_progress.popitem(last=False)
            for task in ('fetch', 'embed'):
                _job_futures.pop((evicted, task), None)
                _job_sync.pop((evicted, task), None)
    _all_progress.move_to_end(user_id)
    # Backfill keys if an older in-memory entry lacks them.
    for task in ('fetch', 'embed'):
        slot = _all_progress[user_id].setdefault(task, _empty_job_slot(task))
        slot.setdefault('result', None)
        slot.setdefault('error', None)
        slot.setdefault('cancel', False)
        slot.setdefault('articles_so_far', 0)
        slot.setdefault('message', '')
        slot.setdefault('started_at', None)
        slot.setdefault('updated_at', None)
        slot.setdefault('library_id', None)
        if task == 'fetch':
            slot.setdefault('sources', [])
            slot.setdefault('by_source', {})
            slot.setdefault('source_status', {})
    return _all_progress[user_id]


def _release_job_markers(user_id: str, task: str) -> None:
    _job_futures.pop((user_id, task), None)
    _job_sync.pop((user_id, task), None)


def update_progress(user_id: str, task: str, **kwargs):
    with _progress_lock:
        slot = _ensure_progress(user_id)[task]
        slot.update(kwargs)
        slot['updated_at'] = _utc_stamp()
        if kwargs.get('active') is False:
            fut = _job_futures.get((user_id, task))
            if fut is None or fut.done():
                _release_job_markers(user_id, task)


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
        slot['updated_at'] = _utc_stamp()
        return True


def job_worker_alive(user_id: str, task: str) -> bool:
    """True when a thread/request is still attached to this slot."""
    with _progress_lock:
        fut = _job_futures.get((user_id, task))
        if fut is not None and not fut.done():
            return True
        return bool(_job_sync.get((user_id, task)))


def _stamp_age_seconds(stamp) -> Optional[float]:
    if not stamp:
        return None
    try:
        dt = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def classify_job_slot(user_id: str, task: str, slot: dict) -> str:
    """active | stalled | failed | idle. Does not create progress rows."""
    _res = slot.get('result')
    result = _res if isinstance(_res, dict) else {}
    status = result.get('status') if result else None
    active = bool(slot.get('active'))
    error = slot.get('error')
    alive = job_worker_alive(user_id, task)
    age = _stamp_age_seconds(slot.get('updated_at'))
    stale = age is None or age >= JOB_STALE_SECONDS
    if active and (not alive or stale):
        return 'stalled'
    if active:
        return 'active'
    if error or result.get('quota_stopped') or status == 'quota_stopped':
        return 'failed'
    if status and status not in ('success', 'cancelled'):
        return 'failed'
    return 'idle'


def safe_error_text(raw, *, limit: int = 240) -> str:
    """One-line error for helpdesk. No filesystem paths or stack frames."""
    if not raw:
        return ""
    text = str(raw).split("\n")[0]
    text = _SAFE_ERR_PATH.sub("[path]", text)
    return text[:limit]


def job_view(user_id: str, task: str, slot: dict) -> dict:
    """Helpdesk-safe snapshot of one fetch/embed slot."""
    _res = slot.get('result')
    result = _res if isinstance(_res, dict) else {}
    status = result.get('status') if result else None
    state = classify_job_slot(user_id, task, slot)
    alive = job_worker_alive(user_id, task)
    active = bool(slot.get('active'))
    quota_stopped = bool(result.get('quota_stopped')) or status == 'quota_stopped'
    _lf = slot.get('last_fetch')
    last_fetch = _lf if isinstance(_lf, dict) else {}
    _kinds = result.get('error_kinds')
    kinds = _kinds if isinstance(_kinds, dict) else {}
    return {
        'task': task,
        'state': state,
        'active': active,
        'worker_alive': alive,
        'started_at': slot.get('started_at'),
        'updated_at': slot.get('updated_at'),
        'error': safe_error_text(slot.get('error')),
        'message': slot.get('message') or '',
        'done': slot.get('done') or 0,
        'total': slot.get('total') or 0,
        'articles_so_far': slot.get('articles_so_far') or 0,
        'library_id': slot.get('library_id'),
        'result_status': status,
        'quota_stopped': quota_stopped,
        'source_status': slot.get('source_status') or {},
        'by_source': slot.get('by_source') or {},
        'error_kinds': kinds,
        'last_fetch': {
            'query': (last_fetch.get('query') or '')[:200],
            'sources': list(last_fetch.get('sources') or [])[:20],
            'max_results': last_fetch.get('max_results'),
            'clear_first': bool(last_fetch.get('clear_first')),
        } if last_fetch else None,
        'can_cancel': active and alive,
        'can_clear': active and not alive,
        'can_retry': task == 'embed' and not active,
        'can_retry_fetch': (
            task == 'fetch' and not active
            and bool(last_fetch.get('query'))
            and bool(last_fetch.get('sources'))
        ),
    }


def snapshot_jobs(user_id: str) -> dict:
    """Copy of this account's job slots (creates the LRU entry if missing)."""
    with _progress_lock:
        raw = {k: dict(v) for k, v in _ensure_progress(user_id).items()}
    return {task: job_view(user_id, task, slot) for task, slot in raw.items()}


def list_job_queue(limit: int = JOB_QUEUE_CAP, *, state: Optional[str] = None) -> list:
    """Active / stalled / failed jobs from the in-memory map only. Capped.

    Does not walk the accounts table.
    """
    cap = max(1, min(int(limit or JOB_QUEUE_CAP), JOB_QUEUE_CAP))
    wanted = state if state in ('active', 'stalled', 'failed') else None
    with _progress_lock:
        items = list(_all_progress.items())
    out = []
    for uid, tasks in reversed(items):
        if not isinstance(tasks, dict):
            continue
        for task in ('fetch', 'embed'):
            slot = tasks.get(task)
            if not isinstance(slot, dict):
                continue
            view = job_view(uid, task, slot)
            if view['state'] not in ('active', 'stalled', 'failed'):
                continue
            if wanted and view['state'] != wanted:
                continue
            view['user_id'] = uid
            out.append(view)
            if len(out) >= cap:
                return out
    return out


def clear_stale_job(user_id: str, task: str) -> tuple:
    """Reset a slot that says running when no worker is attached.

    Returns (ok, detail).
    """
    if task not in ('fetch', 'embed'):
        return False, "task must be fetch or embed"
    if job_worker_alive(user_id, task):
        return False, "That job is still running. Cancel it instead of clearing."
    with _progress_lock:
        slot = _ensure_progress(user_id)[task]
        if not slot.get('active'):
            return False, f"No stale {task} slot to clear"
        slot['active'] = False
        slot['cancel'] = False
        slot['message'] = 'Cleared stale progress'
        slot['updated_at'] = _utc_stamp()
        _release_job_markers(user_id, task)
    return True, "cleared"


def try_begin_user_job(uid: str, task: str, **extra) -> bool:
    """Claim the per-user job slot. Returns False if that task is already active.

    Covers wait=True and wait=False so two fetches cannot share staging.
    """
    now = _utc_stamp()
    with _progress_lock:
        p = _ensure_progress(uid)
        if p[task].get('active'):
            return False
        slot = {
            'active': True, 'done': 0, 'total': 0, 'result': None, 'error': None,
            'cancel': False, 'articles_so_far': 0, 'message': '',
            'started_at': now, 'updated_at': now, 'library_id': extra.get('library_id'),
        }
        slot.update(extra)
        slot['started_at'] = extra.get('started_at') or now
        slot['updated_at'] = now
        p[task].update(slot)
        _job_sync[(uid, task)] = True
        return True


def start_user_job(uid: str, task: str, fn, /, **kwargs) -> bool:
    """Run fn(pipeline, **kwargs) in a thread; progress + result in _all_progress.

    Returns False if a job of this task type is already active for uid.
    The worker holds the pipeline ref until completion (release in done callback).
    Jobs bind to the library that was active when the job started.
    """
    lib_id = get_active_library_id(uid)
    extra = {"library_id": lib_id}
    if task == "fetch":
        extra["last_fetch"] = {
            "query": kwargs.get("query") or "",
            "sources": list(kwargs.get("sources") or []),
            "max_results": kwargs.get("max_results"),
            "clear_first": bool(kwargs.get("clear_first")),
        }
    if not try_begin_user_job(uid, task, **extra):
        return False

    pipe = get_pipeline(uid, lib_id)
    loop = asyncio.get_running_loop()

    def worker():
        return fn(pipe, **kwargs)

    future = loop.run_in_executor(None, worker)
    with _progress_lock:
        _job_futures[(uid, task)] = future

    def _on_done(fut):
        try:
            result = fut.result()
            update_progress(uid, task, active=False, result=result, error=None, cancel=False)
        except Exception as exc:
            logger.exception("Background %s job failed for %s", task, uid)
            update_progress(uid, task, active=False, result=None, error=safe_error_text(exc), cancel=False)
        finally:
            with _progress_lock:
                _release_job_markers(uid, task)
            release_pipeline(uid, lib_id)

    future.add_done_callback(_on_done)
    return True


# Ephemeral demo sessions: delete guest accounts and their libraries after this.
GUEST_MAX_AGE_MINUTES = 30


def current_user(request: Request) -> Optional[dict]:
    """JWT + live account check (token_version) so password change revokes old sessions.

    A live support-view cookie overrides the JWT identity (read-only student
    context). The admin JWT stays in access_token so Exit can restore it.
    """
    cached = getattr(request.state, "_current_user", _MISSING)
    if cached is not _MISSING:
        return cached

    view_user = _support_view_user(request)
    if view_user is not None:
        request.state._current_user = view_user
        return view_user

    payload = get_current_user(request)
    if not payload or not payload.get("user_id"):
        request.state._current_user = None
        return None
    record = user_db.get_by_id(payload["user_id"])
    if not record:
        request.state._current_user = None
        return None
    if int(payload.get("tv", 0) or 0) != int(record.get("token_version") or 0):
        request.state._current_user = None
        return None
    if user_db.is_locked(record) or user_db.is_disabled(record):
        request.state._current_user = None
        return None
    try:
        user_db.touch_last_seen(record["id"])
    except Exception:
        logger.exception("touch_last_seen failed for %s", record.get("id"))
    # Guest demos expire after GUEST_MAX_AGE_MINUTES — drop the account and treat as logged out.
    if record.get("is_guest") and user_db.guest_is_expired(
        record["id"], GUEST_MAX_AGE_MINUTES
    ):
        try:
            destroy_guest_account(record["id"])
        except Exception:
            logger.exception("Failed to expire guest %s", record["id"])
        request.state._current_user = None
        return None
    username = record["username"]
    guest = bool(record.get("is_guest"))
    result = {
        "user_id": record["id"],
        "username": username,
        "token_version": int(record.get("token_version") or 0),
        "is_guest": guest,
        "is_admin": (not guest) and is_admin_username(username),
        "created_at": record.get("created_at"),
    }
    request.state._current_user = result
    return result


def _support_view_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SUPPORT_VIEW_COOKIE)
    if not token:
        return None
    from app.storage import helpdesk
    view = helpdesk.get_support_view_by_token(user_db, token)
    if not view:
        return None
    record = user_db.get_by_id(view["student_id"])
    if not record:
        return None
    guest = bool(record.get("is_guest"))
    return {
        "user_id": record["id"],
        "username": record["username"],
        "token_version": int(record.get("token_version") or 0),
        "is_guest": guest,
        "is_admin": False,
        "created_at": record.get("created_at"),
        "support_view": {
            "id": view["id"],
            "admin_username": view["admin_username"],
            "student_username": view["student_username"],
            "reason": view["reason"],
            "started_at": view["started_at"],
            "expires_at": view["expires_at"],
            "ui_mode": view.get("ui_mode") or "simple",
        },
    }


def admin_usernames() -> set:
    """Handles listed in ADMIN_USERNAMES (comma-separated, case-insensitive)."""
    raw = (os.getenv("ADMIN_USERNAMES") or "").strip()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def is_admin_username(username: str) -> bool:
    return (username or "").strip().lower() in admin_usernames()


def is_admin_user(user: Optional[dict]) -> bool:
    """True for a non-guest session whose username is in ADMIN_USERNAMES."""
    if not user or user.get("is_guest") or user.get("support_view"):
        return False
    if "is_admin" in user:
        return bool(user["is_admin"])
    return is_admin_username(user.get("username") or "")


def admin_forbidden_response():
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=403,
        content={"detail": "Admin only.", "admin": True},
    )


def is_guest_user(user: Optional[dict]) -> bool:
    """True when the session is a demo guest (sample corpus only)."""
    return bool(user and user.get("is_guest"))


def guest_forbidden_response():
    """403 body when a guest hits a real-library action (fetch, shares, …)."""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=403,
        content={
            "detail": (
                "Demo mode only uses the built-in sample papers. "
                "Create a free account to fetch from research databases and keep your work."
            ),
            "guest": True,
        },
    )


def destroy_guest_account(user_id: str) -> None:
    """Evict pipelines, remove private data dir, delete the users row."""
    import shutil

    from app.storage.libraries import user_dir as lib_user_dir

    _evict_pipeline(user_id)
    udir = lib_user_dir(user_id)
    if udir.is_dir():
        shutil.rmtree(udir, ignore_errors=True)
    user_db.delete_user(user_id)


def purge_expired_guests(max_age_minutes: Optional[int] = None) -> int:
    """Delete guest accounts older than max_age_minutes. Returns how many were removed."""
    age = GUEST_MAX_AGE_MINUTES if max_age_minutes is None else int(max_age_minutes)
    ids = user_db.list_expired_guest_ids(age)
    n = 0
    for uid in ids:
        try:
            destroy_guest_account(uid)
            n += 1
        except Exception:
            logger.exception("purge_expired_guests: failed for %s", uid)
    if n:
        logger.info("Purged %s expired guest demo account(s)", n)
    return n


def _set_auth_cookies(response, token: str, max_age: Optional[int] = None):
    """Set the JWT (httponly) and a CSRF token (readable) as cookies."""
    # Default 30 days for real accounts; guests pass a short max_age.
    age = 30 * 24 * 3600 if max_age is None else int(max_age)
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        "access_token", token, httponly=True, secure=COOKIE_SECURE,
        samesite="lax", max_age=age,
    )
    response.set_cookie(
        "csrf_token", csrf_token, httponly=False, secure=COOKIE_SECURE,
        samesite="lax", max_age=age,
    )


def csrf_failed(request: Request) -> bool:
    """Double-submit cookie check for state-changing /api requests."""
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token")
    return not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token)


def server_error() -> JSONResponse:
    """Log the real exception server-side, return a generic message to the client.

    Takes no argument on purpose. Call it only from inside an `except` block:
    logger.exception() captures the active exception and its traceback by
    itself. Passing the exception in added nothing to the log and created a
    dataflow edge (py/stack-trace-exposure) suggesting it reached the client.
    """
    logger.exception("Unhandled error in API handler")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def run_in_thread(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, partial(func, *args, **kwargs))
