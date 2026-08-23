"""Operator change-and-ship console. Separate from student-support /admin."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import core
from app.auth import verify_password_async
from app.core import (
    COOKIE_SECURE,
    admin_forbidden_response,
    client_bucket,
    csrf_failed,
    current_user,
    is_admin_user,
    limiter,
    templates,
)
from app.operator import gitutil
from app.operator.runner import TIMEOUTS, run_action
from app.storage import ops_audit

logger = logging.getLogger(__name__)

router = APIRouter()

REAUTH_COOKIE = "ops_reauth"
REAUTH_TTL_DEFAULT = 10 * 60
REAUTH_TTL_MIN = 60
REAUTH_TTL_MAX = 8 * 60 * 60
REAUTH_TTL_CHOICES = (5, 10, 15, 30, 60, 120, 240, 480)  # minutes
HOLD_GRACE = 60  # leftover unlock after a held action; at least one minute
WRITE_ACTIONS = frozenset({"save_file", "commit", "deploy", "rollback", "revert_last"})

# Pause the unlock clock while Grok (or another held action) is in flight.
# user_id -> {action, remaining, until, started}
_unlock_holds: dict[str, dict] = {}


def _require_operator(request: Request):
    user = current_user(request)
    if not user:
        return None, JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not is_admin_user(user):
        return None, admin_forbidden_response()
    return user, None


def _reauth_secret() -> bytes:
    key = (os.getenv("SECRET_KEY") or "ops-dev-only").encode("utf-8")
    return key


def _parse_ttl_seconds(body: dict) -> Optional[int]:
    """Unlock window in seconds. Accepts minutes or ttl_seconds."""
    raw_minutes = body.get("minutes")
    raw_seconds = body.get("ttl_seconds")
    if raw_minutes is not None and raw_minutes != "":
        try:
            minutes = int(raw_minutes)
        except (TypeError, ValueError):
            return None
        seconds = minutes * 60
    elif raw_seconds is not None and raw_seconds != "":
        try:
            seconds = int(raw_seconds)
        except (TypeError, ValueError):
            return None
    else:
        return REAUTH_TTL_DEFAULT
    if seconds < REAUTH_TTL_MIN or seconds > REAUTH_TTL_MAX:
        return None
    return seconds


def _make_reauth(user_id: str, ttl: int) -> str:
    exp = str(int(time.time()) + int(ttl))
    payload = f"{user_id}:{exp}"
    mac = hmac.new(_reauth_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{mac}"


def _reauth_expiry(request: Request, user_id: str) -> int:
    """Unix expiry if the unlock cookie is valid, else 0."""
    raw = request.cookies.get(REAUTH_COOKIE) or ""
    parts = raw.split(":")
    if len(parts) != 3:
        return 0
    uid, exp, mac = parts
    if uid != user_id:
        return 0
    try:
        exp_i = int(exp)
    except ValueError:
        return 0
    if exp_i < int(time.time()):
        return 0
    expect = hmac.new(
        _reauth_secret(), f"{uid}:{exp}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(mac, expect):
        return 0
    return exp_i


def _hold_entry(user_id: str) -> Optional[dict]:
    hold = _unlock_holds.get(user_id)
    if not hold:
        return None
    if int(hold.get("until") or 0) < int(time.time()):
        _unlock_holds.pop(user_id, None)
        return None
    return hold


def _begin_unlock_hold(user_id: str, action: str, remaining: int, timeout: int) -> None:
    now = int(time.time())
    _unlock_holds[user_id] = {
        "action": action,
        "remaining": max(int(remaining), 1),
        "until": now + int(timeout) + 30,
        "started": now,
    }


def _finish_unlock_hold(user_id: str) -> Optional[int]:
    """End a hold. Returns remaining ttl to restore, or None if lock already cleared it."""
    hold = _unlock_holds.pop(user_id, None)
    if not hold:
        return None
    return max(int(hold.get("remaining") or 0), HOLD_GRACE)


def _clear_unlock_hold(user_id: str) -> None:
    _unlock_holds.pop(user_id, None)


def _set_reauth_cookie(response: JSONResponse, user_id: str, ttl: int) -> JSONResponse:
    response.set_cookie(
        REAUTH_COOKIE, _make_reauth(user_id, ttl),
        httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=ttl,
    )
    return response


def _reauth_ok(request: Request, user_id: str) -> bool:
    if _hold_entry(user_id):
        return True
    return _reauth_expiry(request, user_id) > 0


def _reauth_until(request: Request, user_id: str) -> int:
    hold = _hold_entry(user_id)
    if hold:
        return int(time.time()) + int(hold["remaining"])
    return _reauth_expiry(request, user_id)


async def _read_json(request: Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _need_reauth():
    return JSONResponse(
        status_code=403,
        content={"detail": "Re-enter your password before this action.", "reauth": True},
    )


@router.get("/ops")
async def ops_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if not is_admin_user(user):
        return RedirectResponse(url="/account", status_code=302)
    return templates.TemplateResponse(
        request, "ops.html", context={"active_page": "ops", "user": user}
    )


@router.post("/api/ops/reauth")
@limiter.limit("10/minute")
async def api_ops_reauth(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    body = await _read_json(request)
    password = str(body.get("password") or "")
    ttl = _parse_ttl_seconds(body)
    if ttl is None:
        return JSONResponse(
            status_code=400,
            content={
                "detail": f"Unlock duration must be 1–{REAUTH_TTL_MAX // 60} minutes.",
                "choices_minutes": list(REAUTH_TTL_CHOICES),
            },
        )
    row = core.user_db.get_by_id(user["user_id"])
    if not row or not await verify_password_async(password, row["hashed_password"]):
        return JSONResponse(status_code=403, content={"detail": "Password did not match."})
    until = int(time.time()) + ttl
    response = JSONResponse({"status": "ok", "ttl": ttl, "until": until})
    _set_reauth_cookie(response, user["user_id"], ttl)
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="ops-unlock", result="ok", detail=f"ttl={ttl}",
        ip=client_bucket(request),
    )
    return response


@router.post("/api/ops/lock")
@limiter.limit("20/minute")
async def api_ops_lock(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err or JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    _clear_unlock_hold(user["user_id"])
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="ops-lock", result="ok", ip=client_bucket(request),
    )
    response = JSONResponse({"status": "ok", "reauth": False})
    response.delete_cookie(REAUTH_COOKIE)
    return response


@router.get("/api/ops/status")
@limiter.limit("30/minute")
async def api_ops_status(request: Request):
    user, err = _require_operator(request)
    if err:
        return err
    try:
        gitutil.ensure_staging()
        diff = run_action("diff")
    except Exception as exc:
        logger.exception("ops status")
        return JSONResponse(status_code=503, content={"detail": str(exc)[:240]})
    return {
        "live_sha": diff.get("live_sha") or "",
        "staging_sha": diff.get("staging_sha") or "",
        "dirty": bool(diff.get("dirty")),
        "empty": bool(diff.get("empty")),
        "reauth": _reauth_ok(request, user["user_id"]) if user else False,
        "reauth_until": _reauth_until(request, user["user_id"]) if user else 0,
        "unlock_hold": ((_hold_entry(user["user_id"]) or {}).get("action") or "") if user else "",
        "reauth_choices_minutes": list(REAUTH_TTL_CHOICES),
        "reauth_default_minutes": REAUTH_TTL_DEFAULT // 60,
        "history": ops_audit.list_deploys(core.user_db, limit=15),
        "last_validate": ops_audit.get_state(core.user_db, "last_validate_ok") == "1",
        "grok": run_action(
            "grok_status",
            extra_env={"LITSIEVE_GROK_SESSION": ops_audit.get_state(core.user_db, "grok_session")},
        ),
    }


@router.get("/api/ops/files")
@limiter.limit("30/minute")
async def api_ops_files(request: Request):
    _user, err = _require_operator(request)
    if err:
        return err
    result = run_action("list_files")
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"detail": result.get("detail") or "list failed"})
    return result


@router.get("/api/ops/file")
@limiter.limit("30/minute")
async def api_ops_read(request: Request, path: str = ""):
    user, err = _require_operator(request)
    if err or not user:
        return err
    result = run_action("read_file", [path])
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="read_file", result="ok" if result.get("ok") else "fail",
        path=path, detail=result.get("detail") or "", ip=client_bucket(request),
    )
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"detail": result.get("detail") or "read failed"})
    return result


@router.post("/api/ops/file")
@limiter.limit("20/minute")
async def api_ops_save(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    body = await _read_json(request)
    rel = str(body.get("path") or "")
    content = str(body.get("content") if body.get("content") is not None else "")
    result = run_action("save_file", [rel], stdin=content.encode("utf-8"))
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="save_file", result="ok" if result.get("ok") else "fail",
        path=rel,
        before_hash=result.get("before_hash") or "",
        after_hash=result.get("after_hash") or "",
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    if result.get("ok"):
        ops_audit.set_state(core.user_db, "last_validate_ok", "0")
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"detail": result.get("detail") or "save failed"})
    return result


@router.get("/api/ops/diff")
@limiter.limit("30/minute")
async def api_ops_diff(request: Request):
    _user, err = _require_operator(request)
    if err:
        return err
    return run_action("diff")


@router.post("/api/ops/validate")
@limiter.limit("8/minute")
async def api_ops_validate(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    result = run_action("validate")
    ok = bool(result.get("ok"))
    ops_audit.set_state(core.user_db, "last_validate_ok", "1" if ok else "0")
    ops_audit.set_state(core.user_db, "last_validate_sha", result.get("sha") or "")
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="validate", result="ok" if ok else "fail",
        sha=result.get("sha") or "",
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    if not ok:
        return JSONResponse(status_code=400, content=result)
    return result


def _validate_blocks() -> Optional[JSONResponse]:
    if ops_audit.get_state(core.user_db, "last_validate_ok") != "1":
        return JSONResponse(
            status_code=400,
            content={"detail": "Validate must pass before commit or deploy."},
        )
    return None


@router.post("/api/ops/commit")
@limiter.limit("8/minute")
async def api_ops_commit(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    blocked = _validate_blocks()
    if blocked:
        return blocked
    body = await _read_json(request)
    message = str(body.get("message") or "").strip()
    result = run_action(
        "commit", [message],
        extra_env={"LITSIEVE_OPS_AUTHOR": user["username"]},
    )
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="commit", result="ok" if result.get("ok") else "fail",
        sha=result.get("sha") or "",
        message=result.get("message") or message,
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    if not result.get("ok"):
        return JSONResponse(status_code=400, content={"detail": result.get("detail") or "commit failed"})
    return result


@router.post("/api/ops/deploy")
@limiter.limit("6/minute")
async def api_ops_deploy(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    blocked = _validate_blocks()
    if blocked:
        return blocked
    body = await _read_json(request)
    if str(body.get("confirm") or "") != "DEPLOY":
        return JSONResponse(status_code=400, content={"detail": "Type DEPLOY to confirm."})
    diff = run_action("diff")
    if diff.get("empty"):
        return JSONResponse(status_code=400, content={"detail": "Review a non-empty diff before deploying."})
    sha = str(body.get("sha") or diff.get("staging_sha") or "")
    result = run_action("deploy", [sha])
    ok = bool(result.get("ok"))
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="deploy", result="ok" if ok else "fail",
        sha=result.get("sha") or sha,
        previous_sha=result.get("previous_sha") or "",
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    ops_audit.add_deploy(
        core.user_db,
        sha=result.get("sha") or sha,
        previous_sha=result.get("previous_sha") or "",
        actor_username=user["username"],
        result="ok" if ok else ("rolled_back" if result.get("rolled_back") else "failed"),
        detail=result.get("detail") or "",
    )
    if not ok:
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/ops/rollback")
@limiter.limit("6/minute")
async def api_ops_rollback(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    body = await _read_json(request)
    sha = str(body.get("sha") or "").strip()
    argv = [sha] if sha else []
    result = run_action("rollback", argv)
    ok = bool(result.get("ok"))
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="rollback", result="ok" if ok else "fail",
        sha=result.get("sha") or sha,
        previous_sha=result.get("previous_sha") or "",
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    ops_audit.add_deploy(
        core.user_db,
        sha=result.get("sha") or sha,
        previous_sha=result.get("previous_sha") or "",
        actor_username=user["username"],
        result="ok" if ok else "failed",
        detail=result.get("detail") or "",
    )
    if not ok:
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/ops/revert-last")
@limiter.limit("6/minute")
async def api_ops_revert_last(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    last = ops_audit.last_good_deploy(core.user_db)
    sha = (last or {}).get("previous_sha") or ""
    result = run_action("revert_last", [sha] if sha else [])
    ok = bool(result.get("ok"))
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="revert_last", result="ok" if ok else "fail",
        sha=result.get("sha") or sha,
        previous_sha=result.get("previous_sha") or "",
        detail=result.get("detail") or "",
        ip=client_bucket(request),
    )
    if not ok:
        return JSONResponse(status_code=400, content=result)
    return result


@router.post("/api/ops/grok")
@limiter.limit("6/minute")
async def api_ops_ask_grok(request: Request):
    user, err = _require_operator(request)
    if err or not user:
        return err
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not _reauth_ok(request, user["user_id"]):
        return _need_reauth()
    existing = _hold_entry(user["user_id"])
    if existing and existing.get("action") == "ask_grok":
        return JSONResponse(status_code=409, content={"detail": "Grok is already running."})
    body = await _read_json(request)
    prompt = str(body.get("prompt") or "").strip()
    rel = str(body.get("path") or "").strip()
    if len(prompt) < 3 or len(prompt) > 2000:
        return JSONResponse(
            status_code=400,
            content={"detail": "Prompt must be 3–2000 characters."},
        )
    argv = [prompt]
    if rel:
        argv.append(rel)
    sid = ops_audit.get_state(core.user_db, "grok_session")
    if not sid:
        sid = str(uuid.uuid4())
        ops_audit.set_state(core.user_db, "grok_session", sid)
    remaining = _reauth_expiry(request, user["user_id"]) - int(time.time())
    if remaining < 1:
        remaining = HOLD_GRACE
    _begin_unlock_hold(
        user["user_id"], "ask_grok", remaining, TIMEOUTS.get("ask_grok", 180),
    )
    try:
        result = run_action("ask_grok", argv, extra_env={"LITSIEVE_GROK_SESSION": sid})
    finally:
        ttl = _finish_unlock_hold(user["user_id"])
    ops_audit.add(
        core.user_db, actor_id=user["user_id"], actor_username=user["username"],
        action="ask_grok", result="ok" if result.get("ok") else "fail",
        path=rel, detail=(result.get("detail") or result.get("text") or "")[:240],
        ip=client_bucket(request),
    )
    if not result.get("ok"):
        response = JSONResponse(
            status_code=400, content={"detail": result.get("detail") or "Grok failed"}
        )
    else:
        response = JSONResponse(result)
    if ttl:
        _set_reauth_cookie(response, user["user_id"], ttl)
    return response


@router.get("/api/ops/audit")
@limiter.limit("30/minute")
async def api_ops_audit(request: Request):
    _user, err = _require_operator(request)
    if err:
        return err
    return {"entries": ops_audit.list_audit(core.user_db, limit=50)}
