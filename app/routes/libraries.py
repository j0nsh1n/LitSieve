"""Multi-library workspace CRUD."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import core
from app.core import (
    csrf_failed,
    current_user,
    limiter,
    server_error,
)
from app.schemas import (
    LibraryCreateRequest,
    LibraryRenameRequest,
    LibrarySwitchRequest,
)
from app.storage.libraries import (
    create_library,
    delete_library,
    list_libraries,
    pipeline_cache_key,
    rename_library,
    set_active_library,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/libraries")
async def api_list_libraries(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        return list_libraries(user["user_id"])
    except Exception as e:
        return server_error(e)


@router.post("/api/libraries")
@limiter.limit("30/minute")
async def api_create_library(req: LibraryCreateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = create_library(user["user_id"], req.name)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@router.post("/api/libraries/switch")
@limiter.limit("60/minute")
async def api_switch_library(req: LibrarySwitchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = set_active_library(user["user_id"], req.library_id)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@router.patch("/api/libraries/{library_id}")
@limiter.limit("30/minute")
async def api_rename_library(library_id: str, req: LibraryRenameRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    try:
        result = rename_library(user["user_id"], library_id, req.name)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)


@router.delete("/api/libraries/{library_id}")
@limiter.limit("20/minute")
async def api_delete_library(library_id: str, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        # Refuse to delete while requests or background jobs still hold the
        # pipeline (jobs keep a reference until completion): closing the DB
        # under them would abort work or remove the file mid-write.
        key = pipeline_cache_key(uid, library_id)
        with core._pipelines_lock:
            if core._pipeline_refcounts.get(key, 0) > 0:
                return JSONResponse(
                    status_code=409,
                    content={
                        "detail": "This library is in use (an active job or "
                        "request). Wait for it to finish, then try again."
                    },
                )
            # Drop cached pipeline for this library before deleting files.
            pipe = core._pipelines.pop(key, None)
            pending = core._pending_close.pop(key, [])
        for p in [pipe, *pending]:
            if p is not None:
                try:
                    p.db.close()
                except Exception:
                    pass
        result = delete_library(uid, library_id)
        return {"status": "success", **result}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
