"""Start over (option B): keep starred/noted papers; drop the rest."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import core
from app.core import (
    csrf_failed,
    current_user,
    get_pipeline,
    limiter,
    release_pipeline,
    server_error,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/api/start-over")
@limiter.limit("12/minute")
async def api_start_over(request: Request):
    """Start over (option B): keep starred/noted papers; drop the rest.

    Unlocks fetch in Simple mode by shrinking the library to annotated papers
    only. Guest accounts are read-only for this mutation.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if core.is_guest_user(user):
        return core.guest_forbidden_response()
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = p.db.keep_starred_and_noted()
        p.invalidate_corpus_cache()
        stats = p.get_statistics()
        return {
            "status": "success",
            "deleted": result.get("deleted", 0),
            "remaining": result.get("remaining", 0),
            "kept": result.get("kept", 0),
            "total_articles": stats.get("total_articles", 0),
            "starred": stats.get("starred", 0),
            "notes": stats.get("notes", 0),
        }
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)
