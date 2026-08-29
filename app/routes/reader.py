"""Reader Mode: plain-language explanation of one abstract."""

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.core import (
    csrf_failed,
    current_user,
    get_pipeline,
    limiter,
    release_pipeline,
    run_in_thread,
    server_error,
)
from app.schemas import ReaderExplainRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _ai_unconfigured_detail() -> str:
    return (
        "AI is unavailable (not configured). Open Account → AI study aid and choose "
        "Built-in study aid or Cloud API key. Extractive key points still work."
    )


def _friendly_ai_unavailable(detail: str) -> str:
    low = (detail or "").lower()
    if "ollama" in low or "not running" in low or "not reachable" in low:
        return (
            "Built-in study aid is not ready (503). Try again in a moment, or switch "
            "to Cloud API key on Account. Extractive key points still work without AI."
        )
    return detail or "AI study aid unavailable."


def _normalise_audience(value: str) -> str:
    return "high_school" if value == "high_school" else "general_reader"


@router.post("/api/reader/explain")
@limiter.limit("6/minute")
async def api_reader_explain(req: ReaderExplainRequest, request: Request):
    """Generate or return a cached explanation of one abstract.

    Cache hits do not start the built-in study aid. Support-view POSTs are
    blocked by the read-only gate (this path is not in _ALLOWED_POST).
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from app.services.llm import LLMError, LLMUnavailable
        from app.services.reader_mode import explain_article

        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})

        def _work():
            return explain_article(
                p.db,
                article,
                req.audience,
                force_regenerate=bool(req.force_regenerate),
            )

        return await run_in_thread(_work)
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"detail": _friendly_ai_unavailable(str(e))})
    except LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception:
        return server_error()
    finally:
        release_pipeline(uid)


@router.get("/api/reader/explanation")
@limiter.limit("30/minute")
async def api_reader_get(
    request: Request,
    article_id: str = Query(min_length=1, max_length=256),
    source: str = Query(min_length=1, max_length=64),
    audience: str = Query(default="general_reader"),
):
    """Cache-only lookup. Never generates, never starts the study aid."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if audience not in ("high_school", "general_reader"):
        return JSONResponse(status_code=400, content={"detail": "Unknown reading level."})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from app.services.reader_mode import lookup_explanation

        article = p.db.get_article_by_id(article_id, source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})
        found = lookup_explanation(p.db, article, _normalise_audience(audience))
        if not found:
            return JSONResponse(status_code=404, content={"detail": "No saved explanation"})
        return found
    except Exception:
        return server_error()
    finally:
        release_pipeline(uid)
