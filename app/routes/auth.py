"""Registration, login, logout, password reset/change, account deletion, guest demo."""

import logging
import os
import secrets
import shutil
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import core
from app.auth import (
    create_token,
    hash_password_async,
    validate_email,
    validate_new_username,
    verify_password_async,
)
from app.core import (
    _evict_pipeline,
    _set_auth_cookies,
    csrf_failed,
    current_user,
    get_pipeline,
    limiter,
    release_pipeline,
    run_in_thread,
    server_error,
    templates,
)
from app.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    SetEmailRequest,
)
from app.services import mailer

logger = logging.getLogger(__name__)


def _guest_auto_prepare_enabled() -> bool:
    """Production default is on; tests set GUEST_AUTO_PREPARE=0 so they stay fast."""
    raw = (os.getenv("GUEST_AUTO_PREPARE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _start_guest_prepare(uid: str) -> None:
    """Kick off embeddings so /guest lands on Search, not an empty collect form."""
    if not uid or not _guest_auto_prepare_enabled():
        return
    try:
        from app.routes.corpus import _run_create_embeddings
        core.start_user_job(
            uid, "embed", _run_create_embeddings,
            model="general", only_missing=True, uid=uid,
        )
    except Exception:
        logger.exception("Guest auto-prepare failed to start for %s", uid)

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
    ip = core.client_bucket(request)
    if user and core.user_db.is_disabled(user):
        msg = (user.get("disabled_message") or "").strip() or (
            "This account is temporarily disabled. Ask your teacher if you need it turned back on."
        )
        core.user_db.record_auth_event(
            user["id"], user["username"], "login_fail", ip, "disabled"
        )
        return templates.TemplateResponse(
            request, "login.html",
            context={"error": msg, "info": "", "next": next if next else ""},
            status_code=400,
        )
    if user and core.user_db.is_locked(user):
        core.user_db.record_auth_event(
            user["id"], user["username"], "login_fail", ip, "locked"
        )
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": "This account is locked after too many failed sign-ins. "
                         "Ask your teacher to unlock it, or wait 15 minutes.",
                "info": "",
                "next": next if next else "",
            },
            status_code=400,
        )
    if not user or not await verify_password_async(password, user["hashed_password"]):
        core.user_db.record_login_failure(username, ip)
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": "Invalid username or password",
                "info": "",
                "next": next if next else "",
            },
            status_code=400,
        )
    core.user_db.record_login_success(user["id"], ip)
    token = create_token(
        user["id"], user["username"], user.get("token_version", 0),
    )
    response = RedirectResponse(url=next_url, status_code=302)
    _set_auth_cookies(response, token)
    return response


@router.get("/login/once")
@limiter.limit("10/minute")
async def login_once(request: Request, token: str = ""):
    """Consume a short-lived emailed one-time login link."""
    rec = core.user_db.consume_one_time_login(token or "")
    if not rec:
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": "That sign-in link is invalid or has expired. Ask for a new one.",
                "info": "",
                "next": "",
            },
            status_code=400,
        )
    if core.user_db.is_disabled(rec):
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": (rec.get("disabled_message") or "").strip()
                or "This account is temporarily disabled.",
                "info": "",
                "next": "",
            },
            status_code=400,
        )
    if core.user_db.is_locked(rec):
        return templates.TemplateResponse(
            request, "login.html",
            context={
                "error": "This account is locked. Ask your teacher to unlock it first.",
                "info": "",
                "next": "",
            },
            status_code=400,
        )
    core.user_db.record_login_success(rec["id"], core.client_bucket(request))
    core.user_db.record_auth_event(
        rec["id"], rec["username"], "otl_used", core.client_bucket(request), ""
    )
    jwt_token = create_token(
        rec["id"], rec["username"], rec.get("token_version", 0),
    )
    response = RedirectResponse(url="/search", status_code=302)
    _set_auth_cookies(response, jwt_token)
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
    entered = (username or "").strip().lower()
    # People type whichever they remember. A *verified* address identifies the
    # account too; an unverified one must not (anyone can type any address).
    username = entered
    if entered and "@" in entered and not core.user_db.get_by_username(entered):
        by_email = core.user_db.get_by_verified_email(entered)
        if by_email:
            username = by_email["username"]
    token = core.user_db.create_password_reset_token(username) if username else None
    if token:
        logger.info("Password reset code issued for %s", username)
    info = (
        "If that login exists, a reset code was created. "
        "Enter it below with a new password."
    )
    reset_code = ""
    # Preferred delivery: email the code to a *verified* address. An unverified
    # address is ignored — nobody has proved they control it, so mailing a reset
    # code there would be a takeover vector.
    verified_email = core.user_db.get_verified_email(username) if token else None
    emailed = False
    if token and verified_email and mailer.is_configured():
        try:
            await run_in_thread(mailer.send_password_reset, verified_email, username, token)
            emailed = True
            info = (
                "If that login exists and has a verified email, a reset code is "
                "on its way. Enter it below with a new password."
            )
        except Exception:
            # Do not reveal that the account exists; fall through to the
            # on-screen path if that is enabled for this host.
            logger.exception("Reset email failed for %s", username)

    if token and not emailed and _reset_codes_in_response():
        # Self-hosted / DEBUG: surface the code so hosts without SMTP still work.
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
        username, token, await hash_password_async(password),
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
    # New accounts get a plain handle; an optional recovery email is added
    # later from Account and must be verified. Older email-shaped logins are
    # grandfathered by validate_login_name at sign-in.
    error = validate_new_username(username)

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
        user = core.user_db.create_user(username, await hash_password_async(password))
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
    response = RedirectResponse(url="/search", status_code=302)
    _set_auth_cookies(response, token)
    # One-shot seed: theme-init reads this when localStorage.uiMode is unset,
    # sets Simple mode for brand-new accounts, then clears the cookie.
    # Existing accounts never get this cookie (login path only sets auth).
    response.set_cookie(
        "ui_mode_seed",
        "simple",
        httponly=False,
        secure=core.COOKIE_SECURE,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


async def _start_guest_session(request: Request) -> RedirectResponse:
    """Create a throwaway guest account, load sample papers, log them in.

    Guests cannot fetch from real databases (server-enforced). Sample corpus
    only — enough to try prepare → screen → search → export.
    Accounts and their libraries are deleted after core.GUEST_MAX_AGE_MINUTES.
    """
    # Sweep expired demos whenever someone starts a new one.
    try:
        core.purge_expired_guests()
    except Exception:
        logger.exception("purge_expired_guests before guest start failed")

    # Already signed in: just go to the app (do not replace a real account).
    # Expired guests already returned None from current_user above path.
    if current_user(request):
        return RedirectResponse(url="/data-management", status_code=302)

    from app.content.sample_corpus import get_sample_articles

    username = f"guest_{secrets.token_hex(4)}"
    # Unusable password (never shown); guests sign in only via /guest.
    hashed = await hash_password_async(secrets.token_urlsafe(32))
    try:
        user = core.user_db.create_user(username, hashed, is_guest=True)
    except ValueError:
        # Extremely unlikely collision on token_hex; one retry.
        username = f"guest_{secrets.token_hex(5)}"
        user = core.user_db.create_user(username, hashed, is_guest=True)

    uid = user["id"]
    # Load demo papers into their private library (no external APIs).
    p = get_pipeline(uid)
    try:
        articles = get_sample_articles()
        p.db.clear_all()
        p.db.insert_articles(articles, dedupe=False)
        p.invalidate_corpus_cache()
    except Exception:
        logger.exception("Guest sample load failed for %s", uid)
        # Still let them in; they can use "Load sample papers" on DM.
    finally:
        release_pipeline(uid)

    _start_guest_prepare(uid)

    token = create_token(
        user["id"], user["username"], user.get("token_version", 0),
    )
    response = RedirectResponse(url="/search", status_code=302)
    # Cookies expire with the demo window so browsers drop the session too.
    _set_auth_cookies(
        response, token, max_age=core.GUEST_MAX_AGE_MINUTES * 60,
    )
    # Guests start in Simple mode (same seed as new registrations).
    response.set_cookie(
        "ui_mode_seed",
        "simple",
        httponly=False,
        secure=core.COOKIE_SECURE,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@router.get("/guest")
@limiter.limit("12/minute")
async def guest_start_get(request: Request):
    """Link-friendly entry: Try the demo without creating an account."""
    return await _start_guest_session(request)


@router.post("/guest")
@limiter.limit("12/minute")
async def guest_start_post(request: Request):
    """Form POST entry (same as GET /guest)."""
    return await _start_guest_session(request)



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
    if not record or not await verify_password_async(req.current_password, record["hashed_password"]):
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

    if not core.user_db.update_password(user["user_id"], await hash_password_async(new_pw)):
        return JSONResponse(status_code=400, content={"detail": "Could not update password"})

    fresh = core.user_db.get_by_id(user["user_id"])
    if not fresh:
        return JSONResponse(status_code=400, content={"detail": "Could not update password"})
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
    if not record or not await verify_password_async(req.password, record["hashed_password"]):
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


# --- Optional recovery email -------------------------------------------------
# Username is the login. An email is optional, added here, and only usable for
# password recovery once verified. The whole section is inert when SMTP is not
# configured — without a way to send the link, "verified" would be meaningless.


def _email_state(user_row) -> dict:
    """Non-secret email state for the Account UI."""
    email = (user_row or {}).get("email")
    verified = bool((user_row or {}).get("email_verified"))
    return {
        "email": email or "",
        "verified": verified,
        "pending": bool(email) and not verified,
        "sending_configured": mailer.is_configured(),
    }


@router.get("/api/account/email")
async def api_get_email(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    row = core.user_db.get_by_id(user["user_id"])
    state = _email_state(row)
    # Grandfathered accounts: the login itself looks like an address, so offer
    # to claim it rather than making them retype it.
    login = (row or {}).get("username") or ""
    state["login_looks_like_email"] = "@" in login
    state["suggested_email"] = login if "@" in login else ""
    return state


@router.post("/api/account/email")
@limiter.limit("6/minute")
async def api_set_email(req: SetEmailRequest, request: Request):
    """Set/replace the recovery email and send a verification link."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not mailer.is_configured():
        return JSONResponse(
            status_code=503,
            content={"detail": "Email is not set up on this server, so an address "
                               "cannot be verified. Ask the person running it to "
                               "configure SMTP."},
        )

    row = core.user_db.get_by_username(user["username"])
    if not row or not await verify_password_async(req.current_password, row["hashed_password"]):
        return JSONResponse(status_code=400, content={"detail": "Incorrect password"})

    error = validate_email(req.email)
    if error:
        return JSONResponse(status_code=400, content={"detail": error})

    email = core.user_db.normalize_email(req.email)
    try:
        token = core.user_db.start_email_verification(row["username"], email)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    if not token:
        return JSONResponse(status_code=404, content={"detail": "Account not found"})

    try:
        await run_in_thread(mailer.send_verification, email, row["username"], token)
    except Exception:
        logger.exception("Verification email failed for %s", row["username"])
        return JSONResponse(
            status_code=502,
            content={"detail": "Saved, but the verification email could not be sent. "
                               "Try 'Resend' in a moment."},
        )
    return {"status": "sent", **_email_state(core.user_db.get_by_id(user["user_id"]))}


@router.post("/api/account/email/resend")
@limiter.limit("4/minute")
async def api_resend_verification(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if not mailer.is_configured():
        return JSONResponse(status_code=503, content={"detail": "Email is not set up on this server."})

    row = core.user_db.get_by_id(user["user_id"])
    email = (row or {}).get("email")
    if not row or not email:
        return JSONResponse(status_code=400, content={"detail": "No email on this account yet."})
    if row.get("email_verified"):
        return {"status": "already_verified", **_email_state(row)}

    token = core.user_db.start_email_verification(row["username"], email)
    try:
        await run_in_thread(mailer.send_verification, email, row["username"], token)
    except Exception:
        logger.exception("Resend failed for %s", row["username"])
        return JSONResponse(status_code=502, content={"detail": "Could not send the email just now."})
    return {"status": "sent", **_email_state(core.user_db.get_by_id(user["user_id"]))}


@router.delete("/api/account/email")
@limiter.limit("6/minute")
async def api_delete_email(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    core.user_db.clear_email(user["user_id"])
    return {"status": "removed", **_email_state(core.user_db.get_by_id(user["user_id"]))}


@router.get("/verify-email")
async def verify_email_page(request: Request, token: str = ""):
    """Confirm an address from the emailed link.

    Public on purpose: the token is the proof, and the person clicking may be
    reading mail in a browser where they are not signed in.
    """
    ok, error, username = core.user_db.confirm_email_verification(token)
    if ok:
        logger.info("Email verified for %s", username)
    return templates.TemplateResponse(
        request, "verify_email.html",
        context={"ok": ok, "error": error, "username": username or ""},
        status_code=200 if ok else 400,
    )
