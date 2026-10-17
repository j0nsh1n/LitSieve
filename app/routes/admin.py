"""Operator admin console: what needs attention, one account at a time,
tickets, the site's banner and copy, and the host.

Reuses ADMIN_USERNAMES / is_admin_user. No roster export, bulk delete,
promote/demote, or writable global settings from this page. Every account
action is an entry in ACTIONS: the template draws its button from the entry,
and _begin_action enforces the same reason and confirm rule for its route.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app import core
from app.auth import validate_email
from app.core import (
    admin_forbidden_response,
    client_bucket,
    csrf_failed,
    current_user,
    get_pipeline,
    is_admin_user,
    limiter,
    release_pipeline,
    request_job_cancel,
    run_in_thread,
    templates,
)
from app.errors import sentence_for
from app.services import mailer
from app.storage import helpdesk, quota
from app.storage.libraries import (
    delete_library,
    library_db_path,
    list_libraries,
    owned_library_id,
    pipeline_cache_key,
)
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_EMBEDDING_MODEL = "general"


def _stored_embedding_model(user_id: str, library_id: str) -> Optional[str]:
    """The model this library's embeddings were built with, or None if it has none."""
    pipe = core.get_pipeline(user_id, library_id)
    try:
        return pipe.db.get_embedding_model()
    finally:
        core.release_pipeline(user_id, library_id)


@dataclass(frozen=True)
class AdminAction:
    """One account action: its route suffix, button, and confirm rule.

    The messages are the accounts it refuses: guests, the acting admin's own
    account, or any admin. The page shows them before a dialog opens.
    """

    name: str
    label: str
    group: str
    destructive: bool = False
    per_task: bool = False
    guest_message: Optional[str] = None
    self_message: Optional[str] = None
    admin_message: Optional[str] = None


ACTIONS: tuple[AdminAction, ...] = (
    AdminAction("unlock", "Unlock account", "access"),
    AdminAction("resend-verification", "Resend verification", "access"),
    AdminAction("set-email", "Set email + send verification", "access", destructive=True,
                guest_message="Guest demos cannot change email. They must register.",
                admin_message="An admin's email is changed from their own Account page."),
    AdminAction("send-reset", "Email password reset", "access", destructive=True,
                guest_message="Guest demos have no password."),
    AdminAction("send-login-link", "Email one-time sign-in", "access", destructive=True,
                guest_message="Guest demos cannot use a login link."),
    AdminAction("revoke-sessions", "Revoke all sessions", "access", destructive=True,
                self_message="This would sign you out of the console. Use Log out instead."),
    AdminAction("cancel-job", "Cancel", "jobs", destructive=True, per_task=True),
    AdminAction("clear-job", "Clear stale", "jobs", destructive=True, per_task=True),
    AdminAction("retry-embed", "Retry prepare", "jobs"),
    AdminAction("retry-fetch", "Retry fetch", "jobs",
                guest_message="Guest demos cannot fetch."),
    AdminAction("quota-bump", "Temporary quota bump", "storage", destructive=True),
    AdminAction("delete-library", "Delete one library", "storage", destructive=True),
    AdminAction("view", "View as student", "account"),
    AdminAction("disable", "Disable account", "account", destructive=True,
                guest_message="Guest demos cannot be disabled. They expire on their own.",
                admin_message="Admins cannot be disabled here. Take the name out of "
                              "ADMIN_USERNAMES first."),
    AdminAction("enable", "Re-enable account", "account"),
)
ACTION_BY_NAME = {a.name: a for a in ACTIONS}
TASK_WORDS = (("fetch", "fetch"), ("embed", "prepare"))
BANNER_CONFIRM = "publish"
HISTORY_KINDS = ("timeline", "notes", "activity")
HISTORY_PAGE = 25
_QUOTA_BUMP_MAX_MB = 10 * 1024
_QUOTA_BUMP_MAX_DAYS = 90
_QUEUE_KINDS = frozenset({
    "locked", "unverified", "quota", "errors", "jobs",
    "jobs-active", "jobs-stalled", "jobs-failed",
    "disabled", "tickets",
})


def _account_id(raw: str) -> Optional[str]:
    try:
        return str(uuid.UUID(str(raw or "").strip()))
    except (ValueError, AttributeError, TypeError):
        return None


def _load_account(user_id: str):
    """UUID-check then DB lookup. Use rec['id'] afterward (not the raw path)."""
    uid = _account_id(user_id)
    if not uid:
        return None, JSONResponse(status_code=404, content={"detail": "Account not found"})
    rec = core.user_db.get_by_id(uid)
    if not rec:
        return None, JSONResponse(status_code=404, content={"detail": "Account not found"})
    return rec, None


def _require_admin(request: Request):
    user = current_user(request)
    if not user:
        return None, JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not is_admin_user(user):
        return None, admin_forbidden_response()
    return user, None


@dataclass(frozen=True)
class AdminPost:
    admin: dict
    body: dict


@dataclass(frozen=True)
class ActionCall:
    admin: dict
    rec: dict
    body: dict


async def _begin_post(request: Request, *, confirm: Optional[str] = None):
    """Auth, CSRF, body and the reason (and confirm word) for a site-wide admin POST."""
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=confirm)
    if bad:
        return bad
    return AdminPost(admin=admin, body=body)


def _refusal(action: AdminAction, rec: dict, admin: dict) -> Optional[str]:
    if rec.get("is_guest"):
        return action.guest_message
    if action.self_message and rec["id"] == admin["user_id"]:
        return action.self_message
    if action.admin_message and core.is_admin_username(rec["username"]):
        return action.admin_message
    return None


async def _begin_action(request: Request, user_id: str, name: str):
    """The same checks for an account action, with the confirm rule from ACTIONS."""
    action = ACTION_BY_NAME[name]
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(status_code=404, content={"detail": "Account not found"})
    refused = _refusal(action, rec, admin)
    if refused:
        return JSONResponse(status_code=400, content={"detail": refused})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=rec["username"] if action.destructive else None)
    if bad:
        return bad
    return ActionCall(admin=admin, rec=rec, body=body)


def _public(rec: dict) -> dict:
    """Account fields safe for the admin UI. Never includes password hashes."""
    locked = core.user_db.is_locked(rec)
    return {
        "id": rec["id"],
        "username": rec["username"],
        "email": rec.get("email") or "",
        "email_verified": bool(rec.get("email_verified")),
        "is_guest": bool(rec.get("is_guest")),
        "is_admin": (not rec.get("is_guest")) and core.is_admin_username(rec["username"]),
        "role": (
            "guest" if rec.get("is_guest")
            else ("admin" if core.is_admin_username(rec["username"]) else "student")
        ),
        "created_at": rec.get("created_at"),
        "locked": locked,
        "locked_until": rec.get("locked_until"),
        "failed_logins": int(rec.get("failed_logins") or 0),
        "last_login_at": rec.get("last_login_at"),
        "last_seen_at": rec.get("last_seen_at"),
        "password_changed_at": rec.get("password_changed_at"),
        "storage_bytes": int(rec.get("storage_bytes") or 0),
        "quota_limit_mb": rec.get("quota_limit_mb"),
        "quota_limit_until": rec.get("quota_limit_until"),
        "disabled": core.user_db.is_disabled(rec),
        "disabled_until": rec.get("disabled_until"),
        "disabled_message": rec.get("disabled_message") or "",
        "class_section": None,
        "display_name": rec["username"],
    }


async def _read_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _require_reason(body: dict, *, confirm: Optional[str] = None) -> Optional[JSONResponse]:
    reason = str(body.get("reason") or "").strip()
    if len(reason) < 3:
        return JSONResponse(
            status_code=400,
            content={"detail": "A short reason is required (at least 3 characters)."},
        )
    if confirm is not None:
        typed = str(body.get("confirm") or "").strip()
        if typed != confirm:
            return JSONResponse(
                status_code=400,
                content={"detail": f"Type {confirm} to confirm this action."},
            )
    return None


def _parse_quota_until(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    candidate = text.replace("T", " ").replace("Z", "")
    parsed = None
    for fmt, end_of_day in (
        ("%Y-%m-%d %H:%M:%S", False),
        ("%Y-%m-%d %H:%M", False),
        ("%Y-%m-%d", True),
    ):
        try:
            parsed = datetime.strptime(candidate[:19] if fmt.endswith("%S") else candidate[:16] if "%H" in fmt else candidate[:10], fmt)
            if end_of_day:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            break
        except ValueError:
            continue
    if parsed is None:
        return None
    parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if parsed <= now:
        return None
    if parsed > now + timedelta(days=_QUOTA_BUMP_MAX_DAYS):
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _library_sizes(user_id: str, libs: dict) -> list:
    active_id = libs.get("active_id")
    out = []
    for entry in list(libs.get("libraries") or []):
        lid = entry.get("id")
        size = 0
        if lid:
            try:
                size = quota.library_file_bytes(str(library_db_path(user_id, lid)))
            except Exception:
                logger.exception("Library size failed for %s / %s", user_id, lid)
        out.append({
            "id": lid,
            "name": entry.get("name") or "",
            "created_at": entry.get("created_at"),
            "active": lid == active_id,
            "size_bytes": size,
            "size_mb": quota.mb(size),
        })
    return out


def _close_library_pipeline(user_id: str, library_id: str) -> Optional[JSONResponse]:
    key = pipeline_cache_key(user_id, library_id)
    with core._pipelines_lock:
        if core._pipeline_refcounts.get(key, 0) > 0:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": "This library is in use (an active job or request). "
                    "Wait for it to finish, then try again.",
                },
            )
        pipe = core._pipelines.pop(key, None)
        pending = core._pending_close.pop(key, [])
    for item in [pipe, *pending]:
        if item is not None:
            try:
                item.db.close()
            except Exception:
                logger.exception("Could not close pipeline before library delete")
    return None


@router.get("/admin")
async def admin_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not is_admin_user(user):
        return RedirectResponse(url="/account", status_code=302)
    return templates.TemplateResponse(
        request, "admin.html",
        context={"active_page": "admin", "user": user, "actions": ACTIONS, "task_words": TASK_WORDS},
    )


JOB_WINDOW_HOURS = 24


@router.get("/api/admin/overview")
@limiter.limit("30/minute")
async def api_admin_overview(request: Request):
    """Counts and host flags only — no account list."""
    _admin, err = _require_admin(request)
    if err:
        return err
    counts = core.user_db.account_counts()
    cap = quota.limit_bytes()
    guest_prep = (os.getenv("GUEST_AUTO_PREPARE") or "1").strip().lower()
    from app.content.source_catalog import SOURCE_CATALOG
    from app.services import llm as llm_svc
    # Running and stalled jobs are live state; failures and source errors come
    # from job_records, so they survive a restart.
    job_counts = {"active": 0, "stalled": 0}
    for job in core.list_job_queue(limit=core.JOB_QUEUE_MAX):
        if job.get("state") in job_counts:
            job_counts[job["state"]] += 1
    day_ago = (datetime.now(timezone.utc) - timedelta(hours=JOB_WINDOW_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    summary = await core.run_in_thread(core.user_db.job_record_summary, day_ago)
    job_counts["failed"] = summary["failed"]
    job_counts["finished"] = summary["finished"]
    source_fails = summary["source_errors"]
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    with core.user_db._lock:
        auth_hour = core.user_db.conn.execute(
            "SELECT kind, COUNT(*) FROM auth_events WHERE created_at >= ? "
            "GROUP BY kind LIMIT 20",
            (hour_ago,),
        ).fetchall()
    source_health = [
        {"id": sid, "name": (meta or {}).get("name") or sid, "needs_key": bool((meta or {}).get("needs_key")),
         "recent_errors": int(source_fails.get(sid) or 0)}
        for sid, meta in list(SOURCE_CATALOG.items())[:20]
    ]
    return {
        "counts": counts,
        "smtp": mailer.is_configured(),
        "ai": llm_svc.is_configured(),
        "quota_mb": round(cap / (1024 * 1024)) if cap else 0,
        "guest_auto_prepare": guest_prep not in ("0", "false", "no", "off"),
        "version": APP_VERSION,
        "uptime_seconds": int(max(0, __import__("time").time() - core.PROCESS_STARTED)),
        "jobs": job_counts,
        "jobs_window_hours": JOB_WINDOW_HOURS,
        "auth_events_1h": {str(k): int(v) for k, v in auth_hour},
        "source_health": source_health,
    }


@router.get("/api/admin/queue-counts")
@limiter.limit("30/minute")
async def api_admin_queue_counts(request: Request):
    """Uncapped totals for each queue kind without returning an account roster."""
    _admin, err = _require_admin(request)
    if err:
        return err
    counts = core.user_db.queue_counts(quota.limit_bytes())
    jobs = core.list_job_queue(limit=core.JOB_QUEUE_MAX)
    for kind in ("jobs", "jobs-active", "jobs-stalled", "jobs-failed"):
        state = kind.removeprefix("jobs-") if kind != "jobs" else None
        counts[kind] = len({
            str(job.get("user_id")) for job in jobs
            if job.get("user_id") and (state is None or job.get("state") == state)
        })
    counts["tickets"] = helpdesk.count_tickets(core.user_db, status="open")
    return {"counts": {kind: int(counts.get(kind, 0)) for kind in _QUEUE_KINDS}}


@router.get("/api/admin/activity")
@limiter.limit("30/minute")
async def api_admin_activity(request: Request, limit: int = 50):
    """Newest admin actions across accounts, with no private account fields."""
    _admin, err = _require_admin(request)
    if err:
        return err
    rows = core.user_db.list_admin_activity(limit=max(1, min(int(limit), 50)))
    return {"items": rows}


def _backup_status() -> Optional[dict]:
    """The newest backup archive: name, size and age. Never the folder's path."""
    folder = Path(os.getenv("BACKUP_DIR") or (Path.home() / "litsieve-backups"))
    try:
        archives = sorted(folder.glob("litsieve-*.tar.gz"))
    except OSError:
        archives = []
    if not archives:
        return None
    newest = archives[-1]
    try:
        stat = newest.stat()
    except OSError:
        return None
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return {
        "name": newest.name,
        "size_bytes": stat.st_size,
        "modified_at": modified.strftime("%Y-%m-%d %H:%M:%S"),
        "age_hours": round((datetime.now(timezone.utc) - modified).total_seconds() / 3600, 1),
    }


def _watchdog_status() -> Optional[dict]:
    """What tools/watchdog.py last wrote to logs/watchdog_state.json."""
    path = Path("logs") / "watchdog_state.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return {
        "healthy": bool(raw.get("healthy")),
        "since": _utc_text(raw.get("since")),
        "checked_at": _utc_text(raw.get("checked_at")),
        "summary": str(raw.get("summary") or "")[:240],
    }


def _utc_text(value) -> str:
    """The watchdog writes epoch seconds; show them like every other admin time."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return ""
    return str(value or "")


def _disk_status() -> Optional[dict]:
    target = Path(os.getenv("USER_DATA_DIR", "user_data"))
    probe = target if target.exists() else Path.cwd()
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    return {"free_bytes": usage.free, "total_bytes": usage.total}


def _laya_status() -> dict:
    from app.services import laya_client

    url = laya_client.base_url()
    if not url:
        return {"state": "unset"}
    try:
        import requests

        resp = requests.get(f"{url}/health", timeout=1.5)
        if not resp.ok:
            return {"state": "down"}
        payload = resp.json()
    except requests.exceptions.ReadTimeout:
        # The socket accepted, so systemd is starting a worker that idled out.
        return {"state": "waking"}
    except Exception:
        return {"state": "down"}
    loaded = payload.get("loaded") if isinstance(payload, dict) else False
    return {"state": "up", "loaded": bool(loaded)}


def _ai_status() -> dict:
    from app.services import llm as llm_svc

    status = llm_svc.status()
    return {
        "provider": status.get("provider"),
        "ollama_running": bool(status.get("ollama_running")),
        "ollama_models": list(status.get("ollama_models") or [])[:6],
        "control_allowed": bool(status.get("ollama_control_allowed")) and llm_svc.ai_settings_write_allowed(),
        "detail": str(status.get("detail") or ""),
    }


@router.get("/api/admin/host")
@limiter.limit("30/minute")
async def api_admin_host(request: Request):
    """Read-only host facts for the Host tab: backup, watchdog, disk, Laya, the study aid."""
    _admin, err = _require_admin(request)
    if err:
        return err
    def probe() -> dict:
        return {
            "backup": _backup_status(),
            "watchdog": _watchdog_status(),
            "disk": _disk_status(),
            "laya": _laya_status(),
            "ai": _ai_status(),
        }

    return await run_in_thread(probe)


@router.get("/api/admin/search")
@limiter.limit("30/minute")
async def api_admin_search(request: Request, q: str = "", limit: int = 25):
    _admin, err = _require_admin(request)
    if err:
        return err
    rows = core.user_db.search_accounts(q, limit=limit)
    return {
        "users": [_public(r) for r in rows],
        "total": len(rows),
        "exact_first": True,
    }


@router.get("/api/admin/queue")
@limiter.limit("30/minute")
async def api_admin_queue(request: Request, filter: str = "locked"):
    _admin, err = _require_admin(request)
    if err:
        return err
    kind = (filter or "locked").strip().lower()
    if kind not in _QUEUE_KINDS:
        return JSONResponse(status_code=400, content={"detail": "Unknown queue filter."})
    if kind == "tickets":
        rows = helpdesk.list_tickets(core.user_db, status="open", limit=25)
        return {"filter": kind, "tickets": rows, "total": len(rows), "users": []}
    if kind.startswith("jobs"):
        state = None
        if kind in ("jobs-active", "jobs-stalled", "jobs-failed"):
            state = kind.split("-", 1)[1]
        items = core.list_job_queue(limit=25, state=state)
        users = []
        by_id = {}
        for job in items:
            uid = job.get("user_id")
            rec = core.user_db.get_by_id(uid) if uid else None
            if not rec:
                continue
            if rec["id"] not in by_id:
                pub = _public(rec)
                pub["jobs_queue"] = []
                by_id[rec["id"]] = pub
                users.append(pub)
            by_id[rec["id"]]["jobs_queue"].append({
                "task": job.get("task"),
                "state": job.get("state"),
                "error": job.get("error"),
                "result_status": job.get("result_status"),
                "quota_stopped": job.get("quota_stopped"),
                "updated_at": job.get("updated_at"),
            })
        return {"filter": kind, "users": users, "total": len(users), "jobs": items}
    rows = core.user_db.queue_accounts(kind, limit=25)
    if kind == "quota":
        kept = []
        for rec in rows:
            cap = quota.account_limit_bytes(rec["id"], rec=rec)
            if cap and int(rec.get("storage_bytes") or 0) >= cap:
                kept.append(rec)
        rows = kept
    return {"filter": kind, "users": [_public(r) for r in rows], "total": len(rows)}


@router.get("/api/admin/users/{user_id}")
@limiter.limit("30/minute")
async def api_admin_user_detail(user_id: str, request: Request):
    admin, err = _require_admin(request)
    if err or not admin:
        return err
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(
            status_code=404, content={"detail": "Account not found"}
        )
    user_id = rec["id"]
    used = quota.usage_bytes(user_id)
    core.user_db.set_storage_bytes(user_id, used)
    rec["storage_bytes"] = used
    report = quota.usage_report(user_id)
    libs = list_libraries(user_id)
    library_rows = _library_sizes(user_id, libs)
    stats = {}
    last_job_error = None
    p = get_pipeline(user_id)
    try:
        stats = p.get_statistics()
    except Exception:
        logger.exception("Helpdesk stats failed for %s", user_id)
        last_job_error = "Could not read library statistics."
    finally:
        release_pipeline(user_id)
    jobs = core.snapshot_jobs(user_id)
    for slot in jobs.values():
        if slot.get("error"):
            last_job_error = slot.get("error")
        elif slot.get("quota_stopped"):
            last_job_error = "Fetch stopped at the storage cap (507 / quota_stopped)."
    active_lib = next((row for row in library_rows if row.get("active")), None)
    auth_ev = core.user_db.list_auth_events(user_id, limit=HISTORY_PAGE)
    notes = core.user_db.list_support_notes(user_id, limit=HISTORY_PAGE)
    timeline = core.user_db.list_support_actions(user_id, limit=HISTORY_PAGE)
    return {
        **_public(rec),
        "quota": report,
        "libraries": {
            "active_id": libs.get("active_id"),
            "active_name": (active_lib or {}).get("name") or "",
            "libraries": library_rows,
        },
        "statistics": {
            "total_articles": stats.get("total_articles", 0),
            "articles_with_embeddings": stats.get("articles_with_embeddings", 0),
            "starred": stats.get("starred", 0),
            "notes": stats.get("notes", 0),
        },
        "jobs": jobs,
        "refusals": {
            a.name: msg for a in ACTIONS if (msg := _refusal(a, rec, admin))
        },
        "quota_stopped": any(slot.get("quota_stopped") for slot in jobs.values()),
        "last_error": last_job_error or (
            next((e["detail"] for e in auth_ev if e["kind"] in ("login_fail", "lockout")), None)
        ),
        "activity": auth_ev,
        "support_notes": notes,
        "timeline": timeline,
        "smtp_configured": mailer.is_configured(),
        "tickets": helpdesk.list_tickets(core.user_db, student_id=user_id, limit=25),
        "support_views": helpdesk.list_support_views_for_student(core.user_db, user_id, limit=10),
    }


@router.get("/api/admin/users/{user_id}/history")
@limiter.limit("60/minute")
async def api_admin_user_history(user_id: str, request: Request):
    """One page of an account's timeline, notes or auth events, oldest last."""
    _admin, err = _require_admin(request)
    if err:
        return err
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(status_code=404, content={"detail": "Account not found"})
    kind = str(request.query_params.get("kind") or "timeline")
    if kind not in HISTORY_KINDS:
        return JSONResponse(status_code=400, content={"detail": "Unknown history kind."})
    try:
        offset = max(0, int(request.query_params.get("offset") or 0))
        limit = max(1, min(int(request.query_params.get("limit") or HISTORY_PAGE), 50))
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "offset and limit must be numbers."})
    query = {
        "timeline": core.user_db.list_support_actions,
        "notes": core.user_db.list_support_notes,
        "activity": core.user_db.list_auth_events,
    }[kind]
    rows = query(rec["id"], limit=limit + 1, offset=offset)
    return {"kind": kind, "offset": offset, "items": rows[:limit], "more": len(rows) > limit}


@router.post("/api/admin/users/{user_id}/note")
@limiter.limit("30/minute")
async def api_admin_note(user_id: str, request: Request):
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(
            status_code=404, content={"detail": "Account not found"}
        )
    user_id = rec["id"]
    body = await _read_json(request)
    try:
        note = core.user_db.add_support_note(
            user_id, admin["user_id"], admin["username"], str(body.get("body") or ""),
        )
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "Note cannot be empty or is too long."},
        )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "note",
        reason="support note",
        new_value=note["body"][:80],
        ip=client_bucket(request),
    )
    return {"status": "ok", "note": note}


@router.post("/api/admin/users/{user_id}/unlock")
@limiter.limit("20/minute")
async def api_admin_unlock(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "unlock")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    old = rec.get("locked_until") or ""
    core.user_db.unlock_account(user_id)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "unlock",
        reason=str(body.get("reason") or ""),
        old_value=str(old), new_value="",
        ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "unlock", client_bucket(request), admin["username"],
    )
    return {"status": "ok"}


@router.post("/api/admin/users/{user_id}/revoke-sessions")
@limiter.limit("20/minute")
async def api_admin_revoke(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "revoke-sessions")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    old = str(rec.get("token_version") or 0)
    core.user_db.bump_sessions(user_id)
    fresh = core.user_db.get_by_id(user_id)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "revoke-sessions",
        reason=str(body.get("reason") or ""),
        old_value=old, new_value=str((fresh or {}).get("token_version") or ""),
        ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "session_revoke", client_bucket(request),
        admin["username"],
    )
    return {"status": "ok"}


@router.post("/api/admin/users/{user_id}/resend-verification")
@limiter.limit("12/minute")
async def api_admin_resend_verify(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "resend-verification")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    email = (rec.get("email") or "").strip()
    if not email:
        return JSONResponse(status_code=400, content={"detail": "This account has no email on file."})
    if rec.get("email_verified"):
        return JSONResponse(status_code=400, content={"detail": "Email is already verified."})
    if not mailer.is_configured():
        return JSONResponse(status_code=503, content={"detail": "Email is not set up on this server."})
    token = core.user_db.start_email_verification(rec["username"], email)
    try:
        await run_in_thread(mailer.send_verification, email, rec["username"], token)
    except Exception:
        logger.exception("Helpdesk verification email failed for %s", rec["username"])
        return JSONResponse(status_code=502, content={"detail": "Could not send the verification email."})
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "resend-verification",
        reason=str(body.get("reason") or ""),
        new_value=email, ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "verify_sent", client_bucket(request), email,
    )
    return {"status": "sent"}


@router.post("/api/admin/users/{user_id}/send-reset")
@limiter.limit("12/minute")
async def api_admin_send_reset(user_id: str, request: Request):
    """Email a password-reset code. Never returns the code to the helpdesk."""
    call = await _begin_action(request, user_id, "send-reset")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    verified = core.user_db.get_verified_email(rec["username"])
    if not verified:
        return JSONResponse(
            status_code=400,
            content={"detail": "No verified email on this account — cannot email a reset."},
        )
    if not mailer.is_configured():
        return JSONResponse(status_code=503, content={"detail": "Email is not set up on this server."})
    token = core.user_db.create_password_reset_token(rec["username"])
    if not token:
        return JSONResponse(status_code=500, content={"detail": "Could not create a reset code."})
    try:
        await run_in_thread(mailer.send_password_reset, verified, rec["username"], token)
    except Exception:
        logger.exception("Helpdesk reset email failed for %s", rec["username"])
        return JSONResponse(status_code=502, content={"detail": "Could not send the reset email."})
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "send-reset",
        reason=str(body.get("reason") or ""),
        new_value=verified, ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "password_reset_sent", client_bucket(request),
        admin["username"],
    )
    return {"status": "sent", "emailed_to": verified}


@router.post("/api/admin/users/{user_id}/send-login-link")
@limiter.limit("12/minute")
async def api_admin_send_login_link(user_id: str, request: Request):
    """Email a 15-minute one-time sign-in link. Token is not shown to helpdesk."""
    call = await _begin_action(request, user_id, "send-login-link")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    verified = core.user_db.get_verified_email(rec["username"])
    if not verified:
        return JSONResponse(
            status_code=400,
            content={"detail": "No verified email on this account — cannot email a login link."},
        )
    if not mailer.is_configured():
        return JSONResponse(status_code=503, content={"detail": "Email is not set up on this server."})
    token = core.user_db.create_one_time_login(user_id)
    if not token:
        return JSONResponse(status_code=500, content={"detail": "Could not create a login link."})
    link = f"{mailer.public_base_url()}/login/once?token={token}"
    try:
        await run_in_thread(mailer.send_one_time_login, verified, rec["username"], link)
    except Exception:
        logger.exception("Helpdesk one-time login email failed for %s", rec["username"])
        return JSONResponse(status_code=502, content={"detail": "Could not send the login link."})
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "send-login-link",
        reason=str(body.get("reason") or ""),
        new_value=verified, ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "otl_sent", client_bucket(request), admin["username"],
    )
    return {"status": "sent", "emailed_to": verified}


def _job_library(user_id: str, task: str, body: dict) -> Optional[str]:
    """The library a job action targets: the one the panel showed, else the shown slot's."""
    raw = str(body.get("library_id") or "") or str(core.snapshot_jobs(user_id)[task].get("library_id") or "")
    try:
        return owned_library_id(user_id, raw or None)
    except ValueError:
        return None


@router.post("/api/admin/users/{user_id}/cancel-job")
@limiter.limit("30/minute")
async def api_admin_cancel_job(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "cancel-job")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    task = str(body.get("task") or "").strip()
    if task not in ("fetch", "embed"):
        return JSONResponse(status_code=400, content={"detail": "task must be fetch or embed"})
    lib_id = _job_library(user_id, task, body)
    if lib_id is None:
        return JSONResponse(status_code=400, content={"detail": "That library no longer exists."})
    ok = request_job_cancel(user_id, lib_id, task)
    if not ok:
        return JSONResponse(
            status_code=409,
            content={"detail": f"No active {task} job to cancel"},
        )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "cancel-job",
        reason=str(body.get("reason") or ""),
        new_value=task, ip=client_bucket(request),
    )
    return {"status": "cancelling", "task": task}


@router.post("/api/admin/users/{user_id}/clear-job")
@limiter.limit("30/minute")
async def api_admin_clear_job(user_id: str, request: Request):
    """Clear a slot that still says running after the worker is gone."""
    call = await _begin_action(request, user_id, "clear-job")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    task = str(body.get("task") or "").strip()
    if task not in core.JOB_TASKS:
        return JSONResponse(status_code=400, content={"detail": "task must be fetch, embed or cluster"})
    lib_id = _job_library(user_id, task, body)
    if lib_id is None:
        return JSONResponse(status_code=400, content={"detail": "That library no longer exists."})
    ok, detail = core.clear_stale_job(user_id, lib_id, task)
    if not ok:
        return JSONResponse(status_code=409, content={"detail": detail})
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "clear-job",
        reason=str(body.get("reason") or ""),
        new_value=task, ip=client_bucket(request),
    )
    return {"status": "cleared", "task": task}


@router.post("/api/admin/users/{user_id}/retry-embed")
@limiter.limit("12/minute")
async def api_admin_retry_embed(user_id: str, request: Request):
    """Start prepare (embed, only_missing) on the student's current library."""
    call = await _begin_action(request, user_id, "retry-embed")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    try:
        quota.check_quota(user_id)
    except quota.QuotaExceeded as exc:
        return JSONResponse(
            status_code=507,
            content={"detail": sentence_for(exc), "quota": quota.usage_report(user_id)},
        )
    from app.routes.corpus import _run_create_embeddings
    from app.storage.libraries import get_active_library_id
    lib_id = get_active_library_id(user_id)
    # Same model the library's vectors were built with; "general" only when it has none yet.
    model = await core.run_in_thread(_stored_embedding_model, user_id, lib_id) or DEFAULT_EMBEDDING_MODEL
    # Bind the job to the student uid/library — never the admin session.
    if not core.start_user_job(
        user_id, lib_id, "embed", _run_create_embeddings,
        model=model, only_missing=True,
    ):
        return JSONResponse(
            status_code=409,
            content={"detail": "A prepare is already running in that library, or the account is at its job limit."},
        )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "retry-embed",
        reason=str(body.get("reason") or ""),
        new_value=f"embed only_missing library={lib_id}",
        ip=client_bucket(request),
    )
    return {"status": "started", "task": "embed", "library_id": lib_id}


@router.post("/api/admin/users/{user_id}/set-email")
@limiter.limit("12/minute")
async def api_admin_set_email(user_id: str, request: Request):
    """Replace the recovery email and send verification. Never auto-verifies."""
    call = await _begin_action(request, user_id, "set-email")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    email_error = validate_email(str(body.get("email") or ""))
    if email_error:
        return JSONResponse(status_code=400, content={"detail": email_error})
    if not mailer.is_configured():
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Email is not set up on this server.",
                "smtp_configured": False,
            },
        )
    email = core.user_db.normalize_email(str(body.get("email") or ""))
    old = rec.get("email") or ""
    try:
        token = core.user_db.start_email_verification(rec["username"], email)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    if not token:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    try:
        await run_in_thread(mailer.send_verification, email, rec["username"], token)
    except Exception:
        logger.exception("Helpdesk set-email failed for %s", rec["username"])
        return JSONResponse(
            status_code=502,
            content={"detail": "Saved, but the verification email could not be sent."},
        )
    fresh = core.user_db.get_by_id(user_id) or {}
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "set-email",
        reason=str(body.get("reason") or ""),
        old_value=old, new_value=email, ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "verify_sent", client_bucket(request), email,
    )
    return {
        "status": "sent",
        "emailed_to": email,
        "email": fresh.get("email") or email,
        "email_verified": bool(fresh.get("email_verified")),
        "smtp_configured": True,
    }


@router.post("/api/admin/users/{user_id}/quota-bump")
@limiter.limit("12/minute")
async def api_admin_quota_bump(user_id: str, request: Request):
    """Time-boxed per-account cap. Host default stays for everyone else."""
    call = await _begin_action(request, user_id, "quota-bump")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    raw_limit = body.get("limit_mb")
    if raw_limit is None:
        return JSONResponse(status_code=400, content={"detail": "limit_mb must be a whole number of megabytes."})
    try:
        limit_mb = int(raw_limit)
    except (TypeError, ValueError):
        return JSONResponse(status_code=400, content={"detail": "limit_mb must be a whole number of megabytes."})
    if limit_mb < 1 or limit_mb > _QUOTA_BUMP_MAX_MB:
        return JSONResponse(
            status_code=400,
            content={"detail": f"limit_mb must be between 1 and {_QUOTA_BUMP_MAX_MB}."},
        )
    until = _parse_quota_until(str(body.get("until") or ""))
    if not until:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "until must be a future UTC date (YYYY-MM-DD), "
                f"at most {_QUOTA_BUMP_MAX_DAYS} days from now.",
            },
        )
    old = f"{rec.get('quota_limit_mb') or ''} {rec.get('quota_limit_until') or ''}".strip()
    core.user_db.set_quota_override(user_id, limit_mb, until)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "quota-bump",
        reason=str(body.get("reason") or ""),
        old_value=old, new_value=f"{limit_mb}MB until {until}",
        ip=client_bucket(request),
    )
    return {
        "status": "ok",
        "quota": quota.usage_report(user_id),
    }


@router.post("/api/admin/users/{user_id}/delete-library")
@limiter.limit("12/minute")
async def api_admin_delete_library(user_id: str, request: Request):
    """Delete one named library. Never wipes the whole account."""
    call = await _begin_action(request, user_id, "delete-library")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    libs = list_libraries(user_id)
    library_id = str(body.get("library_id") or "").strip()
    typed_name = str(body.get("library_name") or "").strip()
    if not library_id or not typed_name:
        return JSONResponse(
            status_code=400,
            content={"detail": "library_id and library_name are required."},
        )
    match = next(
        (entry for entry in (libs.get("libraries") or []) if entry.get("id") == library_id),
        None,
    )
    if not match:
        return JSONResponse(status_code=404, content={"detail": "Library not found."})
    if (match.get("name") or "").strip() != typed_name:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Type {match.get('name') or 'the library name'} to confirm."},
        )
    blocked = _close_library_pipeline(user_id, library_id)
    if blocked:
        return blocked
    try:
        result = delete_library(user_id, library_id)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    used = quota.usage_bytes(user_id)
    core.user_db.set_storage_bytes(user_id, used)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "delete-library",
        reason=str(body.get("reason") or ""),
        old_value=typed_name, new_value=library_id,
        ip=client_bucket(request),
    )
    return {
        "status": "ok",
        "deleted_id": result.get("deleted_id"),
        "active_id": result.get("active_id"),
        "libraries": result.get("libraries") or [],
        "quota": quota.usage_report(user_id),
    }


@router.post("/api/admin/users/{user_id}/retry-fetch")
@limiter.limit("12/minute")
async def api_admin_retry_fetch(user_id: str, request: Request):
    """Re-run the last fetch for this account's current library."""
    call = await _begin_action(request, user_id, "retry-fetch")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    jobs = core.snapshot_jobs(user_id)
    last = (jobs.get("fetch") or {}).get("last_fetch") or {}
    if not last.get("query") or not last.get("sources"):
        return JSONResponse(
            status_code=400,
            content={"detail": "No previous fetch to retry on this account."},
        )
    try:
        quota.check_quota(user_id)
    except quota.QuotaExceeded as exc:
        return JSONResponse(
            status_code=507,
            content={"detail": sentence_for(exc), "quota": quota.usage_report(user_id)},
        )
    from app.routes.corpus import _run_multi_fetch
    from app.storage.libraries import get_active_library_id
    # The library the last fetch ran on (kept on the slot); the active one only for an old slot without it.
    lib_id = (jobs.get("fetch") or {}).get("library_id") or get_active_library_id(user_id)
    try:
        lib_id = owned_library_id(user_id, lib_id)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"detail": "The library that fetch ran on no longer exists."},
        )
    if not core.start_user_job(
        user_id, lib_id, "fetch", _run_multi_fetch,
        query=last["query"],
        sources=list(last["sources"]),
        max_results=int(last.get("max_results") or 20),
        email=last.get("email") or "",
        clear_first=bool(last.get("clear_first")),
    ):
        return JSONResponse(
            status_code=409,
            content={"detail": "A fetch is already running in that library, or the account is at its job limit."},
        )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "retry-fetch",
        reason=str(body.get("reason") or ""),
        new_value=f"fetch library={lib_id}",
        ip=client_bucket(request),
    )
    return {"status": "started", "task": "fetch", "library_id": lib_id}


@router.post("/api/admin/users/{user_id}/disable")
@limiter.limit("12/minute")
async def api_admin_disable(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "disable")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    message = helpdesk.sanitize_plain(str(body.get("message") or body.get("reason") or ""), limit=400)
    if len(message) < 3:
        return JSONResponse(
            status_code=400,
            content={"detail": "Write a short student-facing explanation."},
        )
    until_raw = str(body.get("until") or "").strip()
    if until_raw:
        until = _parse_quota_until(until_raw)
        if not until:
            return JSONResponse(
                status_code=400,
                content={"detail": "until must be a future UTC date (YYYY-MM-DD), at most 90 days."},
            )
    else:
        until = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
    old = rec.get("disabled_until") or ""
    helpdesk.set_disabled(core.user_db, user_id, until=until, message=message)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "disable",
        reason=str(body.get("reason") or ""),
        old_value=old, new_value=f"{until} {message[:80]}",
        ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "disable", client_bucket(request), admin["username"],
    )
    return {"status": "ok", "disabled_until": until, "disabled_message": message}


@router.post("/api/admin/users/{user_id}/enable")
@limiter.limit("12/minute")
async def api_admin_enable(user_id: str, request: Request):
    call = await _begin_action(request, user_id, "enable")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    old = rec.get("disabled_until") or ""
    helpdesk.clear_disabled(core.user_db, user_id)
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "enable",
        reason=str(body.get("reason") or ""),
        old_value=old, new_value="",
        ip=client_bucket(request),
    )
    core.user_db.record_auth_event(
        user_id, rec["username"], "enable", client_bucket(request), admin["username"],
    )
    return {"status": "ok"}


@router.post("/api/admin/users/{user_id}/view")
@limiter.limit("12/minute")
async def api_admin_start_view(user_id: str, request: Request):
    """Start a time-boxed read-only student view. Requires recent password."""
    call = await _begin_action(request, user_id, "view")
    if isinstance(call, JSONResponse):
        return call
    admin, rec, body = call.admin, call.rec, call.body
    user_id = rec["id"]
    password = str(body.get("password") or "")
    if not await core.password_confirms(request, admin["user_id"], password, "support-view"):
        return JSONResponse(
            status_code=403,
            content={"detail": "Re-enter your admin password to start student view."},
        )
    minutes = body.get("minutes") or helpdesk.SUPPORT_VIEW_MINUTES
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = helpdesk.SUPPORT_VIEW_MINUTES
    view = helpdesk.create_support_view(
        core.user_db,
        admin_id=admin["user_id"],
        admin_username=admin["username"],
        student_id=user_id,
        student_username=rec["username"],
        reason=str(body.get("reason") or ""),
        minutes=minutes,
        ip=client_bucket(request),
    )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "support-view-start",
        reason=str(body.get("reason") or ""),
        new_value=f"until {view['expires_at']}",
        ip=client_bucket(request),
    )
    response = JSONResponse({
        "status": "ok",
        "expires_at": view["expires_at"],
        "redirect": "/search",
    })
    response.set_cookie(
        core.SUPPORT_VIEW_COOKIE,
        view["token"],
        httponly=True,
        secure=core.COOKIE_SECURE,
        samesite="lax",
        max_age=int(view["minutes"]) * 60,
    )
    return response


@router.get("/api/admin/users/{user_id}/view-log")
@limiter.limit("20/minute")
async def api_admin_view_log(user_id: str, request: Request, view_id: str = ""):
    _admin, err = _require_admin(request)
    if err:
        return err
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(
            status_code=404, content={"detail": "Account not found"}
        )
    views = helpdesk.list_support_views_for_student(core.user_db, rec["id"], limit=10)
    chosen = next((v for v in views if v["id"] == view_id), views[0] if views else None)
    visits = helpdesk.list_support_visits(core.user_db, chosen["id"]) if chosen else []
    return {"views": views, "visits": visits}


@router.get("/api/admin/tickets")
@limiter.limit("30/minute")
async def api_admin_tickets(request: Request, status: str = ""):
    _admin, err = _require_admin(request)
    if err:
        return err
    if status not in ("", "all", *helpdesk.TICKET_STATUSES):
        return JSONResponse(status_code=400, content={"detail": "Unknown ticket status filter."})
    rows = helpdesk.list_tickets(core.user_db, status="" if status == "all" else status, limit=25)
    # `total` is this page (capped at 25); `open_total` is every open ticket, for the tab badge.
    return {
        "tickets": rows,
        "total": len(rows),
        "open_total": helpdesk.count_tickets(core.user_db, status="open"),
    }


@router.get("/api/admin/tickets/{ticket_id}")
@limiter.limit("30/minute")
async def api_admin_ticket_detail(ticket_id: str, request: Request):
    _admin, err = _require_admin(request)
    if err:
        return err
    rec = helpdesk.get_ticket(core.user_db, ticket_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Ticket not found"})
    return rec


@router.post("/api/admin/tickets/{ticket_id}/status")
@limiter.limit("30/minute")
async def api_admin_ticket_status(ticket_id: str, request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.get_ticket(core.user_db, ticket_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Ticket not found"})
    status = str(body.get("status") or "").strip()
    try:
        updated = helpdesk.set_ticket_status(core.user_db, ticket_id, status)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    core.user_db.add_support_action(
        rec["student_id"], admin["user_id"], admin["username"], "ticket-status",
        reason=str(body.get("reason") or ""),
        old_value=rec["status"], new_value=status,
        ip=client_bucket(request),
    )
    return {"status": "ok", "ticket": updated}


@router.post("/api/admin/tickets/{ticket_id}/reply")
@limiter.limit("20/minute")
async def api_admin_ticket_reply(ticket_id: str, request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.get_ticket(core.user_db, ticket_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Ticket not found"})
    try:
        reply = helpdesk.add_ticket_reply(
            core.user_db, ticket_id,
            author_id=admin["user_id"],
            author_username=admin["username"],
            author_role="admin",
            body=str(body.get("body") or ""),
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    helpdesk.set_ticket_status(core.user_db, ticket_id, "waiting_on_student")
    core.user_db.add_support_action(
        rec["student_id"], admin["user_id"], admin["username"], "ticket-reply",
        reason=str(body.get("reason") or ""),
        new_value=str(body.get("body") or "")[:80],
        ip=client_bucket(request),
    )
    emailed = False
    student = core.user_db.get_by_id(rec["student_id"])
    verified = core.user_db.get_verified_email((student or {}).get("username") or "")
    if verified and mailer.is_configured():
        try:
            await run_in_thread(mailer.send_support_reply, verified, rec["student_username"], str(body.get("body") or ""))
            emailed = True
        except Exception:
            logger.exception("Ticket reply email failed")
    return {"status": "ok", "reply": reply, "emailed": emailed}


@router.get("/api/admin/banner")
@limiter.limit("30/minute")
async def api_admin_banner_get(request: Request):
    _admin, err = _require_admin(request)
    if err:
        return err
    return {
        "draft": helpdesk.draft_banner(core.user_db),
        "published": helpdesk.published_banner(core.user_db),
    }


@router.post("/api/admin/banner")
@limiter.limit("20/minute")
async def api_admin_banner_save(request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    until = None
    if str(body.get("until") or "").strip():
        until = _parse_quota_until(str(body.get("until")))
        if not until:
            return JSONResponse(status_code=400, content={"detail": "until must be a future UTC date."})
    try:
        rec = helpdesk.save_banner_draft(
            core.user_db,
            body=str(body.get("body") or ""),
            expires_at=until,
            actor=admin["username"],
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "banner-save",
        reason=str(body.get("reason") or ""),
        new_value=rec["id"],
        ip=client_bucket(request),
    )
    return {"status": "ok", "banner": rec}


@router.post("/api/admin/banner/{notice_id}/publish")
@limiter.limit("20/minute")
async def api_admin_banner_publish(notice_id: str, request: Request):
    post = await _begin_post(request, confirm=BANNER_CONFIRM)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.publish_banner(core.user_db, notice_id, actor=admin["username"])
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Banner not found"})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "banner-publish",
        reason=str(body.get("reason") or ""),
        new_value=notice_id,
        ip=client_bucket(request),
    )
    return {"status": "ok", "banner": rec}


@router.post("/api/admin/banner/{notice_id}/disable")
@limiter.limit("20/minute")
async def api_admin_banner_disable(notice_id: str, request: Request):
    post = await _begin_post(request, confirm=BANNER_CONFIRM)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.disable_banner(core.user_db, notice_id, actor=admin["username"])
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Banner not found"})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "banner-disable",
        reason=str(body.get("reason") or ""),
        new_value=notice_id,
        ip=client_bucket(request),
    )
    return {"status": "ok", "banner": rec}


@router.post("/api/admin/banner/{notice_id}/rollback")
@limiter.limit("20/minute")
async def api_admin_banner_rollback(notice_id: str, request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.rollback_banner(
        core.user_db, notice_id, str(body.get("revision_id") or ""), actor=admin["username"],
    )
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Revision not found"})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "banner-rollback",
        reason=str(body.get("reason") or ""),
        new_value=str(body.get("revision_id") or ""),
        ip=client_bucket(request),
    )
    return {"status": "ok", "banner": rec}


@router.get("/api/admin/content")
@limiter.limit("30/minute")
async def api_admin_content_list(request: Request):
    _admin, err = _require_admin(request)
    if err:
        return err
    return {
        "keys": list(helpdesk.CONTENT_KEYS),
        "items": {key: helpdesk.get_site_content(core.user_db, key) for key in helpdesk.CONTENT_KEYS},
    }


@router.post("/api/admin/content/{key}")
@limiter.limit("20/minute")
async def api_admin_content_save(key: str, request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    if key not in helpdesk.CONTENT_KEYS:
        return JSONResponse(status_code=400, content={"detail": "Unknown content key."})
    raw = body.get("body")
    if not isinstance(raw, str):
        raw = json.dumps(raw)
    try:
        rec = helpdesk.set_site_content(core.user_db, key, raw, actor=admin["username"])
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": sentence_for(exc)})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "content-save",
        reason=str(body.get("reason") or ""),
        new_value=key,
        ip=client_bucket(request),
    )
    return {"status": "ok", "item": rec}


@router.post("/api/admin/content/{key}/rollback")
@limiter.limit("20/minute")
async def api_admin_content_rollback(key: str, request: Request):
    post = await _begin_post(request)
    if isinstance(post, JSONResponse):
        return post
    admin, body = post.admin, post.body
    rec = helpdesk.rollback_site_content(
        core.user_db, key, str(body.get("revision_id") or ""), actor=admin["username"],
    )
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Revision not found"})
    core.user_db.add_support_action(
        admin["user_id"], admin["user_id"], admin["username"], "content-rollback",
        reason=str(body.get("reason") or ""),
        new_value=key,
        ip=client_bucket(request),
    )
    return {"status": "ok", "item": rec}


@router.get("/api/admin/users/{user_id}/packet")
@limiter.limit("12/minute")
async def api_admin_packet(user_id: str, request: Request):
    """One-student support packet (status + notes + recent logs). Not a roster dump."""
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    rec, missing = _load_account(user_id)
    if missing or not rec:
        return missing or JSONResponse(
            status_code=404, content={"detail": "Account not found"}
        )
    user_id = rec["id"]
    used = quota.usage_bytes(user_id)
    report = quota.usage_report(user_id)
    notes = core.user_db.list_support_notes(user_id, limit=50)
    timeline = core.user_db.list_support_actions(user_id, limit=50)
    auth_ev = core.user_db.list_auth_events(user_id, limit=20)
    pub = _public(rec)
    lines = [
        f"LitSieve support packet for {pub['username']}",
        f"Prepared by {admin['username']}",
        f"id={pub['id']}",
        f"role={pub['role']} guest={pub['is_guest']}",
        f"email={pub['email'] or '-'} verified={pub['email_verified']}",
        f"created={pub['created_at']} locked={pub['locked']} locked_until={pub['locked_until'] or '-'}",
        f"last_login={pub['last_login_at'] or '-'} last_seen={pub['last_seen_at'] or '-'}",
        f"password_changed={pub['password_changed_at'] or '-'}",
        f"disk={report.get('used_mb')} MB of {report.get('limit_mb') or 'unlimited'} MB",
        "",
        "== Auth events ==",
    ]
    for ev in auth_ev:
        lines.append(f"{ev['created_at']} {ev['kind']} {ev['ip'] or ''} {ev['detail'] or ''}".rstrip())
    lines += ["", "== Support notes =="]
    for n in notes:
        lines.append(f"{n['created_at']} {n['admin_username']}: {n['body']}")
    lines += ["", "== Admin actions =="]
    for a in timeline:
        lines.append(
            f"{a['created_at']} {a['admin_username']} {a['action']} "
            f"reason={a['reason']} {a['old_value']}->{a['new_value']}"
        )
    core.user_db.add_support_action(
        user_id, admin["user_id"], admin["username"], "export-packet",
        reason="support packet",
        ip=client_bucket(request),
    )
    text = "\n".join(lines) + "\n"
    filename = f"support-{pub['username']}.txt"
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
