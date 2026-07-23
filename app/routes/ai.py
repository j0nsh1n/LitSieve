"""Optional AI study aid: settings, refine, ask, key-point save."""

import logging

from fastapi import APIRouter, Request
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
from app.schemas import (
    AIArticleRequest,
    AIAskRequest,
    AISaveKeyPointsRequest,
    AISettingsUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/ai/settings")
async def api_ai_settings_get(request: Request):
    """Masked AI deploy settings for the Account page."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    from app.services.llm import public_ai_settings
    from app.services.llm import status as ai_status
    return {"settings": public_ai_settings(), "status": ai_status()}


@router.post("/api/ai/settings")
@limiter.limit("20/minute")
async def api_ai_settings_save(req: AISettingsUpdate, request: Request):
    """Save server-wide AI keys/models (user_data/ai_settings.json).

    Gated by AI_ALLOW_SETTINGS_WRITE (default true for single-teacher hosts).
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from app.services.llm import (
        ai_settings_write_allowed,
        public_ai_settings,
        save_ai_settings,
    )
    from app.services.llm import status as ai_status
    if not ai_settings_write_allowed():
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Saving AI settings is disabled on this server "
                    "(AI_ALLOW_SETTINGS_WRITE=false). Ask a teacher or deployer "
                    "to change env / ai_settings.json."
                )
            },
        )
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    if "llm_provider" in payload:
        prov = str(payload["llm_provider"]).strip().lower()
        if prov not in ("auto", "ollama", "openai", "anthropic"):
            return JSONResponse(
                status_code=400,
                content={"detail": "llm_provider must be auto, ollama, openai, or anthropic"},
            )
        payload["llm_provider"] = prov
    save_ai_settings(payload)
    return {
        "status": "success",
        "settings": public_ai_settings(),
        "status_detail": ai_status(),
    }


@router.post("/api/ai/ollama/start")
@limiter.limit("6/minute")
async def api_ai_ollama_start(request: Request):
    """Start local Ollama (detached), using OLLAMA_MODELS when set.

    Internal/ops endpoint: no UI caller (Refine/Ask auto-start). Gated by
    AI_ALLOW_SETTINGS_WRITE and AI_ALLOW_OLLAMA_CONTROL.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from app.services.llm import ai_settings_write_allowed, start_ollama
    from app.services.llm import status as ai_status
    if not ai_settings_write_allowed():
        return JSONResponse(
            status_code=403,
            content={"detail": "AI process control is disabled (AI_ALLOW_SETTINGS_WRITE=false)."},
        )
    ok, msg = await run_in_thread(start_ollama)
    return {
        "ok": ok,
        "message": msg,
        "status": ai_status(),
    }


@router.post("/api/ai/ollama/stop")
@limiter.limit("6/minute")
async def api_ai_ollama_stop(request: Request):
    """Stop Ollama server and model runners (frees VRAM).

    Internal/ops endpoint: no UI caller. Gated like /api/ai/ollama/start.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    from app.services.llm import ai_settings_write_allowed, stop_ollama
    from app.services.llm import status as ai_status
    if not ai_settings_write_allowed():
        return JSONResponse(
            status_code=403,
            content={"detail": "AI process control is disabled (AI_ALLOW_SETTINGS_WRITE=false)."},
        )
    ok, msg = await run_in_thread(stop_ollama)
    return {
        "ok": ok,
        "message": msg,
        "status": ai_status(),
    }


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


@router.post("/api/ai/refine-article")
@limiter.limit("8/minute")
async def api_ai_refine_article(req: AIArticleRequest, request: Request):
    """Optional LLM rewrite of summary/key points from the abstract only.

    Built-in mode: start local service → refine → stop when idle (ephemeral).
    Default corpus key points stay extractive. Never bulk-rewrites a library.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from app.services.llm import (
            LLMError,
            LLMUnavailable,
            is_configured,
            refine_article,
            run_with_ephemeral_builtin,
        )

        if not is_configured():
            return JSONResponse(status_code=503, content={"detail": _ai_unconfigured_detail()})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})
        existing = (p.db.get_key_points_map().get((req.article_id, req.source)) or [])

        def _work():
            return run_with_ephemeral_builtin(
                lambda: refine_article(
                    title=article.get("title") or "",
                    abstract=article.get("abstract") or "",
                    existing_key_points=existing,
                    source=req.source or "",
                    article_id=req.article_id or "",
                )
            )

        result = await run_in_thread(_work)
        if req.save_key_points and result.get("key_points"):
            p.db.insert_key_points({
                (req.article_id, req.source): result["key_points"],
            })
            result["saved"] = True
        else:
            result["saved"] = False
        result["article_id"] = req.article_id
        result["source"] = req.source
        result["label"] = "AI rewrite (from the abstract only — not extractive)"
        return result
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"detail": _friendly_ai_unavailable(str(e))})
    except LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/ai/key-points")
@limiter.limit("30/minute")
async def api_ai_save_key_points(req: AISaveKeyPointsRequest, request: Request):
    """Save the displayed AI key points for one article (explicit user action).

    Deliberately does not re-run the model: what the student approved is
    exactly what gets stored.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        points = [str(x).strip()[:500] for x in (req.key_points or []) if str(x).strip()]
        points = points[:6]
        if not points:
            return JSONResponse(status_code=400, content={"detail": "No key points to save."})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})
        p.db.insert_key_points({(req.article_id, req.source): points})
        return {"status": "success", "saved": True, "key_points": points}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/ai/ask-article")
@limiter.limit("8/minute")
async def api_ai_ask_article(req: AIAskRequest, request: Request):
    """Answer a question using only this paper's title + abstract (opt-in AI).

    Same lifecycle as Refine for built-in mode: start → answer → stop when idle.
    One paper per request — no whole-library Q&A.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        from app.services.llm import (
            LLMError,
            LLMUnavailable,
            ask_article,
            is_configured,
            run_with_ephemeral_builtin,
        )

        if not is_configured():
            return JSONResponse(status_code=503, content={"detail": _ai_unconfigured_detail()})
        article = p.db.get_article_by_id(req.article_id, req.source)
        if not article:
            return JSONResponse(status_code=404, content={"detail": "Article not found"})

        def _work():
            return run_with_ephemeral_builtin(
                lambda: ask_article(
                    question=req.question,
                    title=article.get("title") or "",
                    abstract=article.get("abstract") or "",
                    source=req.source or "",
                    article_id=req.article_id or "",
                )
            )

        result = await run_in_thread(_work)
        result["article_id"] = req.article_id
        result["source"] = req.source
        result["label"] = "AI answer (title + abstract only)"
        return result
    except LLMUnavailable as e:
        return JSONResponse(status_code=503, content={"detail": _friendly_ai_unavailable(str(e))})
    except LLMError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)
