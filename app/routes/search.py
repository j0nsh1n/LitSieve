"""Semantic search (text / PICO / seed / starred) plus per-article notes."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import (
    csrf_failed,
    current_user,
    get_pipeline,
    release_pipeline,
    run_in_thread,
    server_error,
)
from app.schemas import (
    NoteRequest,
    SearchRequest,
    SeedSearchRequest,
    StarredSearchRequest,
)
from app.services.enrich import (
    enrich_search_results,
)
from app.utils import (
    sort_articles,
)

logger = logging.getLogger(__name__)

router = APIRouter()














@router.post("/api/search")
async def api_search(req: SearchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        results = await run_in_thread(
            p.search_similar, req.query_text,
            top_k=req.top_k, source_filter=req.source_filter,
            cluster_filter=req.cluster_filter,
            year_min=req.year_min, year_max=req.year_max,
            lexical_boost=req.lexical_boost,
        )
        enrich_search_results(
            results, p, query_text=req.query_text, pico_boost=req.pico_boost,
        )
        sort_articles(results, req.sort_by)
        return {"results": results, "total": len(results)}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/search/seed")
async def api_search_seed(req: SeedSearchRequest, request: Request):
    """Find more papers like one you already have (by id or title fragment)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        data = await run_in_thread(
            p.search_by_seed, req.seed, req.top_k,
            req.source_filter, req.cluster_filter,
            req.year_min, req.year_max, req.lexical_boost,
        )
        results = data["results"]
        enrich_search_results(results, p)
        return {
            "seed": data["seed"],
            "results": results,
            "total": len(results),
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/search/starred")
async def api_search_starred(req: StarredSearchRequest, request: Request):
    """Rank papers near the centroid of your starred collection."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        data = await run_in_thread(
            p.search_from_starred,
            top_k=req.top_k,
            source_filter=req.source_filter,
            cluster_filter=req.cluster_filter,
            year_min=req.year_min,
            year_max=req.year_max,
        )
        results = data["results"]
        enrich_search_results(results, p)
        return {
            "results": results,
            "total": len(results),
            "seed_count": data["seed_count"],
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/notes")
async def api_upsert_note(req: NoteRequest, request: Request):
    """Save a private note and/or star flag on an article."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        note = p.db.upsert_note(req.article_id, req.source, note=req.note, starred=req.starred)
        return {"status": "success", "note": note}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.get("/api/notes")
async def api_get_note(request: Request, article_id: str = "", source: str = ""):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not article_id or not source:
        return JSONResponse(status_code=400, content={"detail": "article_id and source required"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return p.db.get_note(article_id, source)
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)
