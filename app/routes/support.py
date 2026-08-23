"""Student-facing help tickets, support-view exit, public site copy."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import core
from app.core import (
    csrf_failed,
    current_user,
    limiter,
)
from app.storage import helpdesk, quota
from app.storage.libraries import list_libraries

logger = logging.getLogger(__name__)

router = APIRouter()


def _ticket_context(request: Request, body: dict, user: dict) -> dict:
    _ctx = body.get("context")
    raw = _ctx if isinstance(_ctx, dict) else {}
    uid = user["user_id"]
    stats = {}
    try:
        from app.core import get_pipeline, release_pipeline
        p = get_pipeline(uid)
        try:
            stats = p.get_statistics() or {}
        finally:
            release_pipeline(uid)
    except Exception:
        logger.exception("Ticket stats failed")
    jobs = core.snapshot_jobs(uid)
    report = quota.usage_report(uid)
    libs = list_libraries(uid)
    last_error = ""
    for slot in jobs.values():
        if slot.get("error"):
            last_error = slot["error"]
            break
    return {
        "route": raw.get("route") or request.headers.get("referer") or "",
        "ui_mode": raw.get("ui_mode") or "",
        "app_version": "5.0.4",
        "user_agent": (raw.get("user_agent") or request.headers.get("user-agent") or "")[:160],
        "library_count": len((libs or {}).get("libraries") or []),
        "article_count": int(stats.get("total_articles") or 0),
        "embedding_count": int(stats.get("articles_with_embeddings") or 0),
        "quota_used_mb": report.get("used_mb"),
        "quota_limit_mb": report.get("limit_mb"),
        "job_fetch": (jobs.get("fetch") or {}).get("state"),
        "job_embed": (jobs.get("embed") or {}).get("state"),
        "last_error": last_error or raw.get("last_error") or "",
    }


@router.post("/api/support-view/exit")
@limiter.limit("30/minute")
async def api_support_view_exit(request: Request):
    user = current_user(request)
    view = (user or {}).get("support_view") if user else None
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if view and user:
        helpdesk.end_support_view(core.user_db, view["id"], reason="exit")
        core.user_db.add_support_action(
            user["user_id"], view.get("admin_username") or "", view.get("admin_username") or "",
            "support-view-end", reason=view.get("reason") or "exit",
            new_value="exit",
        )
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(core.SUPPORT_VIEW_COOKIE)
    return response


@router.get("/support-view/exit")
async def support_view_exit_page(request: Request):
    user = current_user(request)
    view = (user or {}).get("support_view") if user else None
    if view and user:
        helpdesk.end_support_view(core.user_db, view["id"], reason="exit")
        core.user_db.add_support_action(
            user["user_id"], view.get("admin_username") or "", view.get("admin_username") or "",
            "support-view-end", reason=view.get("reason") or "exit",
            new_value="exit",
        )
    response = RedirectResponse(url="/admin", status_code=302)
    response.delete_cookie(core.SUPPORT_VIEW_COOKIE)
    return response


@router.get("/api/site-content")
@limiter.limit("60/minute")
async def api_site_content(request: Request):
    return helpdesk.public_site_content(core.user_db)


@router.post("/api/tickets")
@limiter.limit("8/minute")
async def api_create_ticket(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if user.get("support_view"):
        return JSONResponse(status_code=403, content={"detail": "Student view is read-only."})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if user.get("is_guest"):
        return JSONResponse(
            status_code=400,
            content={"detail": "Guest demos cannot send help requests. Register for an account."},
        )
    try:
        body = await request.json()
        body = body if isinstance(body, dict) else {}
    except Exception:
        body = {}
    ctx = _ticket_context(request, body, user)
    try:
        ticket = helpdesk.create_ticket(
            core.user_db,
            student_id=user["user_id"],
            student_username=user["username"],
            body=str(body.get("body") or ""),
            context=ctx,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    core.user_db.add_support_action(
        user["user_id"], user["user_id"], user["username"], "ticket-open",
        reason="student help request",
        new_value=ticket["id"],
    )
    return {"status": "ok", "ticket": ticket}


@router.get("/api/tickets")
@limiter.limit("30/minute")
async def api_list_my_tickets(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    rows = helpdesk.list_tickets(core.user_db, student_id=user["user_id"], limit=25)
    return {"tickets": rows, "total": len(rows)}


@router.get("/api/tickets/{ticket_id}")
@limiter.limit("30/minute")
async def api_get_ticket(ticket_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    rec = helpdesk.get_ticket(core.user_db, ticket_id)
    if not rec or rec["student_id"] != user["user_id"]:
        if not (user.get("is_admin") and not user.get("support_view")):
            return JSONResponse(status_code=404, content={"detail": "Ticket not found"})
    return rec


@router.post("/api/tickets/{ticket_id}/reply")
@limiter.limit("20/minute")
async def api_reply_ticket(ticket_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if user.get("support_view"):
        return JSONResponse(status_code=403, content={"detail": "Student view is read-only."})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    rec = helpdesk.get_ticket(core.user_db, ticket_id)
    if not rec or rec["student_id"] != user["user_id"]:
        return JSONResponse(status_code=404, content={"detail": "Ticket not found"})
    try:
        body = await request.json()
        body = body if isinstance(body, dict) else {}
    except Exception:
        body = {}
    try:
        reply = helpdesk.add_ticket_reply(
            core.user_db, ticket_id,
            author_id=user["user_id"],
            author_username=user["username"],
            author_role="student",
            body=str(body.get("body") or ""),
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    helpdesk.set_ticket_status(core.user_db, ticket_id, "open")
    core.user_db.add_support_action(
        user["user_id"], user["user_id"], user["username"], "ticket-reply",
        reason="student reply", new_value=ticket_id,
    )
    return {"status": "ok", "reply": reply}
