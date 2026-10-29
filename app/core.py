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
from typing import Any, Optional, cast

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import get_current_user, verify_password_async
from app.content.appearance import PRESETS, SETTINGS, cookie_value, parse_overrides
from app.content.looks import DEFAULT_LOOK, LOOK_CARDS, normalize_look
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.libraries import (
    ensure_libraries,
    get_active_library_id,
    library_db_path,
    owned_library_id,
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
    from app.version import APP_VERSION

    return {
        "app_version": APP_VERSION,
        "support_view": (user or {}).get("support_view"),
        "site_notice": notice,
        "site_content": site,
        "known_issues": site.get("known_issues") or "",
        "support_links": site.get("support_links") or [],
        "look_cards": LOOK_CARDS,
        "appearance_settings": SETTINGS,
        "appearance_presets": PRESETS,
        "default_look": DEFAULT_LOOK,
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
    """Live sessions get their own bucket; anything else falls back to network.

    The session is checked against the database (account exists, token
    version matches), so a signed token for a purged guest or a revoked
    session cannot mint fresh buckets. Classroom NATs no longer share one
    budget once students are signed in.
    """
    user = current_user(request)
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

# --- Job progress: one slot per (account, library, task), LRU-bounded by account ---
# _all_progress[user_id][library_id][task] -> slot dict.
_all_progress: "OrderedDict[str, dict]" = OrderedDict()
_progress_lock = threading.Lock()
# Live workers for helpdesk stall detection. Keyed (user_id, library_id, task).
_job_futures: dict = {}
_job_sync: dict = {}
# Each library runs its own jobs, but one account may not run more than this
# at once across its libraries, so one student cannot fill the host (21.8).
MAX_JOBS_PER_ACCOUNT = 2
JOB_STALE_SECONDS = 300
JOB_QUEUE_CAP = 25
JOB_QUEUE_MAX = 10000
JOB_TASKS = ('fetch', 'embed', 'cluster')


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


def get_owned_pipeline(
    user_id: str, library_id: Optional[str] = None
) -> LiteratureSearchPipeline:
    """Like get_pipeline, but reject a library_id this account does not own.

    Omit library_id to use the active library. Raises ValueError for an
    unknown or foreign id so callers can return HTTP 400 instead of opening
    a new on-disk library by accident.
    """
    return get_pipeline(user_id, owned_library_id(user_id, library_id))


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
        _drop_markers(user_id)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _empty_job_slot(task: str) -> dict:
    slot = {
        'active': False, 'done': 0, 'total': 0, 'result': None, 'error': None,
        'cancel': False, 'articles_so_far': 0, 'message': '',
        'started_at': None, 'updated_at': None, 'library_id': None,
    }
    if task == 'fetch':
        slot.update(sources=[], by_source={}, source_status={}, source_progress={})
    return slot


def _markers_for(user_id: str) -> list:
    """Marker keys (user_id, library_id, task) of this account. Call under _progress_lock."""
    return [k for k in (*_job_sync, *_job_futures) if k[0] == user_id]


def _drop_markers(user_id: str) -> None:
    for key in _markers_for(user_id):
        _job_futures.pop(key, None)
        _job_sync.pop(key, None)


def _marker_live(key: tuple) -> bool:
    if _job_sync.get(key):
        return True
    fut = _job_futures.get(key)
    return fut is not None and not fut.done()


def _live_job_keys(user_id: str) -> set:
    """(library_id, task) of every job this account is running. Call under _progress_lock."""
    live = {k[1:] for k in _markers_for(user_id) if _marker_live(k)}
    for lib_id, tasks in (_all_progress.get(user_id) or {}).items():
        for task, slot in tasks.items():
            if slot.get('active'):
                live.add((lib_id, task))
    return live


def _evict_idle_progress(*, keep_user: Optional[str] = None) -> None:
    """Drop oldest idle progress rows until at cap. Never drop a live job."""
    while len(_all_progress) > MAX_CACHED_USERS:
        victim = None
        for uid in _all_progress:
            if uid != keep_user and not _live_job_keys(uid):
                victim = uid
                break
        if victim is None:
            break
        _all_progress.pop(victim, None)
        _drop_markers(victim)


def _ensure_progress(user_id: str, library_id: str) -> dict:
    """Task slots of one library, created if needed. Must be called under _progress_lock."""
    if user_id not in _all_progress:
        _all_progress[user_id] = {}
        _evict_idle_progress(keep_user=user_id)
    _all_progress.move_to_end(user_id)
    libs = _all_progress[user_id]
    if library_id not in libs:
        libs[library_id] = {task: _empty_job_slot(task) for task in JOB_TASKS}
    return libs[library_id]


def _release_job_markers(user_id: str, library_id: str, task: str) -> None:
    _job_futures.pop((user_id, library_id, task), None)
    _job_sync.pop((user_id, library_id, task), None)


def _job_outcome(slot: dict) -> str:
    """success | cancelled | quota_stopped | failed, for a slot that just stopped."""
    _res = slot.get('result')
    result = _res if isinstance(_res, dict) else {}
    status = result.get('status')
    if slot.get('error'):
        return 'failed'
    if result.get('quota_stopped') or status == 'quota_stopped':
        return 'quota_stopped'
    if status in (None, 'success', 'cancelled'):
        return status or 'success'
    return 'failed'


def _record_finished_job(user_id: str, library_id: str, task: str, slot: dict) -> None:
    _res = slot.get('result')
    kinds = (_res or {}).get('error_kinds') if isinstance(_res, dict) else None
    try:
        user_db.add_job_record(
            user_id, library_id, task, _job_outcome(slot),
            kinds if isinstance(kinds, dict) else {},
        )
    except Exception:
        logger.warning("Could not record the finished %s job", task, exc_info=True)


def update_progress(user_id: str, library_id: str, task: str, **kwargs):
    finished = None
    with _progress_lock:
        slot = _ensure_progress(user_id, library_id)[task]
        was_active = bool(slot.get('active'))
        slot.update(kwargs)
        slot['updated_at'] = _utc_stamp()
        if kwargs.get('active') is False:
            fut = _job_futures.get((user_id, library_id, task))
            if fut is None or fut.done():
                _release_job_markers(user_id, library_id, task)
            if was_active:
                finished = dict(slot)
    if finished is not None:
        _record_finished_job(user_id, library_id, task, finished)


def is_job_cancelled(user_id: str, library_id: str, task: str) -> bool:
    with _progress_lock:
        return bool(_ensure_progress(user_id, library_id)[task].get('cancel'))


def request_job_cancel(user_id: str, library_id: str, task: str) -> bool:
    """Set cancel flag for an active job. Returns False if nothing active."""
    with _progress_lock:
        slot = _ensure_progress(user_id, library_id)[task]
        if not slot.get('active'):
            return False
        slot['cancel'] = True
        slot['message'] = 'Cancelling…'
        slot['updated_at'] = _utc_stamp()
        return True


def job_worker_alive(user_id: str, library_id: str, task: str) -> bool:
    """True when a thread/request is still attached to this slot."""
    with _progress_lock:
        return _marker_live((user_id, library_id, task))


def library_progress(user_id: str, library_id: str) -> dict:
    """Copy of one library's task slots, for the page that polls it."""
    with _progress_lock:
        return {k: dict(v) for k, v in _ensure_progress(user_id, library_id).items()}


def account_jobs_full(user_id: str) -> bool:
    """True when this account already runs MAX_JOBS_PER_ACCOUNT jobs."""
    with _progress_lock:
        return len(_live_job_keys(user_id)) >= MAX_JOBS_PER_ACCOUNT


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
    alive = job_worker_alive(user_id, str(slot.get('library_id') or ''), task)
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
    """Helpdesk-safe snapshot of one job slot."""
    _res = slot.get('result')
    result = _res if isinstance(_res, dict) else {}
    status = result.get('status') if result else None
    state = classify_job_slot(user_id, task, slot)
    alive = job_worker_alive(user_id, str(slot.get('library_id') or ''), task)
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
            'email': last_fetch.get('email') or '',
        } if last_fetch else None,
        'can_cancel': task != 'cluster' and active and alive,
        'can_clear': active and not alive,
        'can_retry': task == 'embed' and not active,
        'can_retry_fetch': (
            task == 'fetch' and not active
            and bool(last_fetch.get('query'))
            and bool(last_fetch.get('sources'))
        ),
    }


def _pick_slot(slots: list) -> dict:
    """The slot an admin acts on: a running one first, else the newest."""
    return max(slots, key=lambda sl: (bool(sl.get('active')), str(sl.get('updated_at') or '')))


def snapshot_jobs(user_id: str) -> dict:
    """One view per task for this account, across its libraries.

    Each task shows its running slot, else its most recent one; the view
    carries ``library_id`` so a cancel or clear reaches the right library.
    """
    with _progress_lock:
        libs = {lib: {t: dict(sl) for t, sl in tasks.items()}
                for lib, tasks in (_all_progress.get(user_id) or {}).items()}
    out = {}
    for task in JOB_TASKS:
        slots = [tasks[task] for tasks in libs.values() if task in tasks]
        slot = _pick_slot(slots) if slots else _empty_job_slot(task)
        out[task] = job_view(user_id, task, slot)
    return out


def list_job_queue(limit: int = JOB_QUEUE_CAP, *, state: Optional[str] = None) -> list:
    """Active / stalled / failed jobs from the in-memory map only. Capped.

    Does not walk the accounts table.
    """
    cap = max(1, min(int(limit or JOB_QUEUE_CAP), JOB_QUEUE_MAX))
    wanted = state if state in ('active', 'stalled', 'failed') else None
    with _progress_lock:
        items = [(uid, {lib: dict(tasks) for lib, tasks in libs.items()})
                 for uid, libs in _all_progress.items()]
    out = []
    for uid, libs in reversed(items):
        for tasks in libs.values():
            for task in JOB_TASKS:
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


def clear_stale_job(user_id: str, library_id: str, task: str) -> tuple:
    """Reset a slot that says running when no worker is attached.

    Returns (ok, detail).
    """
    if task not in JOB_TASKS:
        return False, "task must be fetch, embed or cluster"
    if job_worker_alive(user_id, library_id, task):
        if task == 'cluster':
            return False, "Theme grouping is still running. Wait for it to finish."
        return False, "That job is still running. Cancel it instead of clearing."
    with _progress_lock:
        slot = _ensure_progress(user_id, library_id)[task]
        if not slot.get('active'):
            return False, f"No stale {task} slot to clear"
        slot['active'] = False
        slot['cancel'] = False
        slot['message'] = 'Cleared stale progress'
        slot['updated_at'] = _utc_stamp()
        _release_job_markers(user_id, library_id, task)
    return True, "cleared"


def refresh_storage_bytes(uid: str) -> None:
    """Store the account's bytes on disk for the admin over-quota queue (20.2).

    The queue and its tile read ``storage_bytes``, which used to change only
    when an admin opened the account.
    """
    try:
        from app.storage import quota
        user_db.set_storage_bytes(uid, quota.usage_bytes(uid))
    except Exception:
        logger.warning("Could not refresh stored usage for %s", uid, exc_info=True)


def refresh_all_storage_bytes() -> int:
    """Sweep every account's stored usage; returns how many were refreshed."""
    ids = user_db.all_user_ids()
    for uid in ids:
        refresh_storage_bytes(uid)
    return len(ids)


def try_begin_user_job(uid: str, library_id: str, task: str, **extra) -> bool:
    """Claim this library's slot for task. False if it is taken or the account is full.

    Covers wait=True and wait=False so two fetches cannot share staging.
    """
    now = _utc_stamp()
    key = (uid, library_id, task)
    with _progress_lock:
        tasks = _ensure_progress(uid, library_id)
        if tasks[task].get('active') or _marker_live(key):
            return False
        if len(_live_job_keys(uid)) >= MAX_JOBS_PER_ACCOUNT:
            return False
        slot = _empty_job_slot(task)
        slot.update(extra)
        slot.update(active=True, library_id=library_id, updated_at=now)
        slot['started_at'] = extra.get('started_at') or now
        tasks[task].update(slot)
        _job_sync[key] = True
        return True


def start_user_job(uid: str, library_id: str, task: str, fn, /, **kwargs) -> bool:
    """Run fn(pipeline, uid=, lib_id=, **kwargs) in a thread; progress in _all_progress.

    library_id must already be resolved to one this account owns. Returns
    False when that library's slot is taken or the account is full. The
    worker holds the pipeline ref until completion (release in done callback).
    """
    extra: dict[str, Any] = {}
    if task == "fetch":
        extra["last_fetch"] = {
            "query": kwargs.get("query") or "",
            "sources": list(kwargs.get("sources") or []),
            "max_results": kwargs.get("max_results"),
            "clear_first": bool(kwargs.get("clear_first")),
            "email": kwargs.get("email") or "",
        }
    if not try_begin_user_job(uid, library_id, task, **extra):
        return False

    try:
        pipe = get_pipeline(uid, library_id)
    except Exception as exc:
        update_progress(uid, library_id, task, active=False, result=None, error=safe_error_text(exc))
        raise
    def worker():
        return fn(pipe, uid=uid, lib_id=library_id, **kwargs)

    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, worker)
    except Exception as exc:
        update_progress(uid, library_id, task, active=False, result=None, error=safe_error_text(exc))
        release_pipeline(uid, library_id)
        raise
    with _progress_lock:
        _job_futures[(uid, library_id, task)] = future

    def _on_done(fut):
        try:
            result = fut.result()
            update_progress(uid, library_id, task, active=False, result=result, error=None, cancel=False)
        except Exception as exc:
            logger.exception("Background %s job failed for %s", task, uid)
            update_progress(uid, library_id, task, active=False, result=None, error=safe_error_text(exc), cancel=False)
        finally:
            with _progress_lock:
                _release_job_markers(uid, library_id, task)
            release_pipeline(uid, library_id)
            # A done callback runs on the event loop; the directory walk and
            # the users.db write go to a worker thread.
            loop.run_in_executor(None, refresh_storage_bytes, uid)

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
        return cast(Optional[dict], cached)

    user = _support_view_user(request) or _session_user(request)
    request.state._current_user = user
    return user


def _session_user(request: Request) -> Optional[dict]:
    """The account behind the access_token JWT, if that session is still live."""
    payload = get_current_user(request)
    if not payload or not payload.get("user_id"):
        return None
    record = user_db.get_by_id(payload["user_id"])
    if not record:
        return None
    if int(payload.get("tv", 0) or 0) != int(record.get("token_version") or 0):
        return None
    if user_db.is_disabled(record):
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
        return None
    username = record["username"]
    guest = bool(record.get("is_guest"))
    return {
        "user_id": record["id"],
        "username": username,
        "token_version": int(record.get("token_version") or 0),
        "is_guest": guest,
        "is_admin": (not guest) and is_admin_username(username),
        "created_at": record.get("created_at"),
        "look": normalize_look(record.get("look")),
        "appearance": record.get("appearance") or {},
    }


async def password_confirms(request: Request, user_id: str, password: str, purpose: str) -> bool:
    """Re-check a signed-in user's password before a sensitive step.

    A wrong password counts toward the same lockout as sign-in, and a locked
    account cannot re-check at all, so a stolen session cannot guess here.
    """
    record = user_db.get_by_id(user_id)
    if not record or user_db.is_locked(record):
        return False
    if await verify_password_async(password or "", record["hashed_password"]):
        return True
    user_db.record_login_failure(record["username"], client_bucket(request), purpose=purpose)
    return False


def _support_view_user(request: Request) -> Optional[dict]:
    """The student a live support view shows, while its admin's own session lasts.

    Logging out, losing admin rights, or a revoked or disabled admin session
    ends the view, so the student identity never outlives the admin's.
    """
    token = request.cookies.get(SUPPORT_VIEW_COOKIE)
    if not token:
        return None
    from app.storage import helpdesk
    view = helpdesk.get_support_view_by_token(user_db, token)
    if not view:
        return None
    admin = _session_user(request)
    if not admin or admin["user_id"] != view["admin_id"] or not admin["is_admin"]:
        helpdesk.end_support_view(user_db, view["id"], reason="admin-session-ended")
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
        "look": normalize_look(record.get("look")),
        "appearance": record.get("appearance") or {},
        "support_view": {
            "id": view["id"],
            "admin_id": view["admin_id"],
            "admin_username": view["admin_username"],
            "student_username": view["student_username"],
            "reason": view["reason"],
            "started_at": view["started_at"],
            "expires_at": view["expires_at"],
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
    # Keep the row until the files are gone, so the next purge retries them
    # instead of leaving an orphaned directory (audit 20.5).
    if udir.exists():
        raise OSError(f"Could not remove {udir}")
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


def _set_look_cookie(
    response,
    look: Optional[str],
    max_age: Optional[int] = None,
    appearance: Optional[dict] = None,
):
    """Readable cookies so theme-init can paint the account look and its
    changed settings before CSS."""
    age = 365 * 24 * 3600 if max_age is None else int(max_age)
    for name, value in (
        ("ui_look", normalize_look(look)),
        ("ui_appearance", cookie_value(parse_overrides(appearance or {}, look))),
    ):
        response.set_cookie(
            name,
            value,
            httponly=False,
            secure=COOKIE_SECURE,
            samesite="lax",
            max_age=age,
            path="/",
        )


def cross_site_form(request: Request) -> bool:
    """True when the browser says this form post came from another site.

    Sign-in and registration have no session to pair a CSRF token with, so
    they rely on the headers every current browser sends: Sec-Fetch-Site,
    else Origin compared with this host. A request with neither (a script,
    an old browser) passes, as it did before.
    """
    site = (request.headers.get("sec-fetch-site") or "").strip().lower()
    if site:
        return site == "cross-site"
    origin = (request.headers.get("origin") or "").strip()
    if not origin or origin == "null":
        return False
    from urllib.parse import urlsplit
    return urlsplit(origin).netloc.lower() != (request.headers.get("host") or "").lower()


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
