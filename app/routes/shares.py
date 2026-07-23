"""Class share codes: create, list, revoke, preview, join (clone)."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import core
from app.core import (
    csrf_failed,
    current_user,
    limiter,
    run_in_thread,
    server_error,
)
from app.schemas import (
    ShareCreateRequest,
    ShareJoinRequest,
)
from app.storage import shares as shares_mod
from app.storage.libraries import (
    ensure_libraries,
    get_active_library_id,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/shares")
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
                share = core.user_db.create_share(
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


@router.get("/api/shares")
@limiter.limit("60/minute")
async def api_list_shares(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        items = core.user_db.list_shares_for_owner(user["user_id"])
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


@router.delete("/api/shares/{share_id}")
@limiter.limit("30/minute")
async def api_revoke_share(share_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        ok = core.user_db.revoke_share(share_id, user["user_id"])
        if not ok:
            existing = core.user_db.get_share_by_id(share_id)
            if existing and existing.get("owner_user_id") == user["user_id"]:
                return {"status": "success", "revoked": True, "already": True}
            return JSONResponse(status_code=404, content={"detail": "Share not found."})
        return {"status": "success", "revoked": True}
    except Exception as e:
        return server_error(e)


@router.get("/api/shares/preview")
@limiter.limit("30/minute")
async def api_preview_share(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    code = request.query_params.get("code") or ""
    try:
        preview = await run_in_thread(
            shares_mod.preview_share, core.user_db, user["user_id"], code
        )
        return preview
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@router.post("/api/shares/join")
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
            core.user_db,
            user["user_id"],
            user["username"],
            req.code,
        )
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
