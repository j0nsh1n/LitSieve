"""Helpdesk console: one-student lookup, unblock, note, log.

Reuses ADMIN_USERNAMES / is_admin_user. Not a superadmin panel: no roster
export, no bulk delete, no promote/demote, no global settings.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from app import core
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
from app.services import mailer
from app.storage import quota
from app.storage.libraries import list_libraries

logger = logging.getLogger(__name__)

router = APIRouter()

_DESTRUCTIVE = frozenset({
    "revoke-sessions", "send-reset", "send-login-link", "cancel-job",
})


def _require_admin(request: Request):
    user = current_user(request)
    if not user:
        return None, JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not is_admin_user(user):
        return None, admin_forbidden_response()
    return user, None


def _public(rec: dict) -> dict:
    """Account fields safe for the helpdesk UI. Never includes password hashes."""
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
            else ("helpdesk" if core.is_admin_username(rec["username"]) else "student")
        ),
        "created_at": rec.get("created_at"),
        "locked": locked,
        "locked_until": rec.get("locked_until"),
        "failed_logins": int(rec.get("failed_logins") or 0),
        "last_login_at": rec.get("last_login_at"),
        "last_seen_at": rec.get("last_seen_at"),
        "password_changed_at": rec.get("password_changed_at"),
        "storage_bytes": int(rec.get("storage_bytes") or 0),
        "mfa": "not_available",
        "class_section": None,
        "display_name": rec["username"],
    }


async def _read_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _require_reason(body: dict, *, confirm: Optional[str] = None, username: str = "") -> Optional[JSONResponse]:
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


@router.get("/admin")
async def admin_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not is_admin_user(user):
        return RedirectResponse(url="/account", status_code=302)
    return templates.TemplateResponse(
        request, "admin.html", context={"active_page": "admin", "user": user}
    )


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
    if kind not in ("locked", "unverified", "quota", "errors"):
        return JSONResponse(status_code=400, content={"detail": "Unknown queue filter."})
    rows = core.user_db.queue_accounts(kind, limit=25)
    if kind == "quota":
        cap = quota.limit_bytes()
        if cap:
            rows = [r for r in rows if int(r.get("storage_bytes") or 0) >= cap]
        else:
            rows = []
    return {"filter": kind, "users": [_public(r) for r in rows], "total": len(rows)}


@router.get("/api/admin/users/{user_id}")
@limiter.limit("30/minute")
async def api_admin_user_detail(user_id: str, request: Request):
    _admin, err = _require_admin(request)
    if err:
        return err
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    used = quota.usage_bytes(user_id)
    core.user_db.set_storage_bytes(user_id, used)
    rec["storage_bytes"] = used
    report = quota.usage_report(user_id)
    libs = list_libraries(user_id)
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
    with core._progress_lock:
        jobs = {k: dict(v) for k, v in core._ensure_progress(user_id).items()}
    for slot in jobs.values():
        if slot.get("error"):
            last_job_error = slot.get("error")
    auth_ev = core.user_db.list_auth_events(user_id, limit=20)
    notes = core.user_db.list_support_notes(user_id, limit=50)
    timeline = core.user_db.list_support_actions(user_id, limit=50)
    return {
        **_public(rec),
        "quota": report,
        "libraries": libs,
        "statistics": {
            "total_articles": stats.get("total_articles", 0),
            "articles_with_embeddings": stats.get("articles_with_embeddings", 0),
            "starred": stats.get("starred", 0),
            "notes": stats.get("notes", 0),
        },
        "jobs": jobs,
        "last_error": last_job_error or (
            next((e["detail"] for e in auth_ev if e["kind"] in ("login_fail", "lockout")), None)
        ),
        "activity": auth_ev,
        "support_notes": notes,
        "timeline": timeline,
        "smtp_configured": mailer.is_configured(),
    }


@router.post("/api/admin/users/{user_id}/note")
@limiter.limit("30/minute")
async def api_admin_note(user_id: str, request: Request):
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    body = await _read_json(request)
    try:
        note = core.user_db.add_support_note(
            user_id, admin["user_id"], admin["username"], str(body.get("body") or ""),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
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
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    body = await _read_json(request)
    bad = _require_reason(body)
    if bad:
        return bad
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
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=rec["username"], username=rec["username"])
    if bad:
        return bad
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
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    body = await _read_json(request)
    bad = _require_reason(body)
    if bad:
        return bad
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
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    if rec.get("is_guest"):
        return JSONResponse(status_code=400, content={"detail": "Guest demos have no password."})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=rec["username"])
    if bad:
        return bad
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
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    if rec.get("is_guest"):
        return JSONResponse(status_code=400, content={"detail": "Guest demos cannot use a login link."})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=rec["username"])
    if bad:
        return bad
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


@router.post("/api/admin/users/{user_id}/reset-mfa")
@limiter.limit("12/minute")
async def api_admin_reset_mfa(user_id: str, request: Request):
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return JSONResponse(
        status_code=400,
        content={"detail": "This host does not use MFA or trusted devices."},
    )


@router.post("/api/admin/users/{user_id}/cancel-job")
@limiter.limit("30/minute")
async def api_admin_cancel_job(user_id: str, request: Request):
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
    body = await _read_json(request)
    bad = _require_reason(body, confirm=rec["username"])
    if bad:
        return bad
    task = str(body.get("task") or "").strip()
    if task not in ("fetch", "embed"):
        return JSONResponse(status_code=400, content={"detail": "task must be fetch or embed"})
    ok = request_job_cancel(user_id, task)
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


@router.get("/api/admin/users/{user_id}/packet")
@limiter.limit("12/minute")
async def api_admin_packet(user_id: str, request: Request):
    """One-student support packet (status + notes + recent logs). Not a roster dump."""
    admin, err = _require_admin(request)
    if err or not admin:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    rec = core.user_db.get_by_id(user_id)
    if not rec:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})
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
        f"mfa={pub['mfa']}",
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
