"""Registration, login, logout, password reset/change, account deletion."""

import logging
import os
import shutil
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import core
from app.auth import (
    create_token,
    hash_password,
    validate_login_name,
    verify_password,
)
from app.core import (
    _evict_pipeline,
    _set_auth_cookies,
    csrf_failed,
    current_user,
    limiter,
    server_error,
    templates,
)
from app.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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


@router.get("/login")
async def login_page(request: Request):
    next_url = _safe_next_url(request.query_params.get("next"))
    if current_user(request):
        return RedirectResponse(url=next_url, status_code=302)
    return templates.TemplateResponse(
        request, "login.html",
        context={"error": "", "info": "", "next": next_url if next_url != "/data-management" else ""},
    )


@router.post("/login")
@limiter.limit("10/minute")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
):
    next_url = _safe_next_url(next or request.query_params.get("next"))
    username = username.strip().lower()
    user = core.user_db.get_by_username(username)
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


@router.get("/register")
async def register_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(request, "register.html", context={"error": "", "username": ""})


def _reset_codes_in_response() -> bool:
    """Classroom/self-host: show the reset code when DEBUG or explicit flag is set."""
    if os.getenv("RESET_CODES_IN_RESPONSE", "").strip().lower() in ("1", "true", "yes"):
        return True
    return os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes")


@router.get("/reset-password")
async def reset_password_page(request: Request):
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)
    return templates.TemplateResponse(
        request, "reset_password.html",
        context={"error": "", "info": "", "username": "", "reset_code": ""},
    )


@router.post("/reset-password/request")
@limiter.limit("5/minute")
async def reset_password_request(request: Request, username: str = Form(...)):
    """Issue a one-time reset code. Always looks successful (no user enum)."""
    username = (username or "").strip().lower()
    token = core.user_db.create_password_reset_token(username) if username else None
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


@router.post("/reset-password/confirm")
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
    ok, err = core.user_db.consume_password_reset_token(
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


@router.post("/register")
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
    elif error is None and core.user_db.get_by_username(username):
        error = "That login is already taken."

    if error:
        return templates.TemplateResponse(
            request, "register.html",
            context={"error": error, "username": username},
            status_code=400,
        )

    try:
        user = core.user_db.create_user(username, hash_password(password))
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


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return response


@router.post("/api/change-password")
async def api_change_password(req: ChangePasswordRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    record = core.user_db.get_by_id(user["user_id"])
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

    if not core.user_db.update_password(user["user_id"], hash_password(new_pw)):
        return JSONResponse(status_code=400, content={"detail": "Could not update password"})

    fresh = core.user_db.get_by_id(user["user_id"])
    token = create_token(
        fresh["id"], fresh["username"], fresh.get("token_version", 0),
    )
    response = JSONResponse(content={"status": "success"})
    _set_auth_cookies(response, token)
    return response


@router.post("/api/delete-account")
async def api_delete_account(req: DeleteAccountRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})

    uid = user["user_id"]
    # Re-verify the password before destroying anything.
    record = core.user_db.get_by_username(user["username"])
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
        from app.storage.libraries import user_dir as lib_user_dir
        udir = lib_user_dir(uid)
        if udir.is_dir():
            shutil.rmtree(udir)
        # 3. Delete the account record.
        core.user_db.delete_user(uid)
    except Exception as e:
        return server_error(e)

    # Clear auth cookies so the now-deleted session can't keep being used.
    response = JSONResponse(content={"status": "success"})
    response.delete_cookie("access_token")
    response.delete_cookie("csrf_token")
    return response
