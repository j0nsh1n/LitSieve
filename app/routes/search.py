"""Semantic search (text / PICO / seed / starred) plus per-article notes."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core import (
    csrf_failed,
    current_user,
    get_owned_pipeline,
    get_pipeline,
    release_pipeline,
    run_in_thread,
    server_error,
)
from app.errors import sentence_for
from app.schemas import (
    DifferentWorkRequest,
    NoteRequest,
    OtherCopiesRequest,
    SearchRequest,
    SeedSearchRequest,
    StarredSearchRequest,
)
from app.services.access import other_copies_payload
from app.services.enrich import (
    enrich_search_results,
)
from app.services.work_types import normalize_doi
from app.storage import quota
from app.storage.dbconn import integrity_errors
from app.storage.run_record import log_question
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
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        results = await run_in_thread(
            p.search_similar, req.query_text,
            top_k=req.top_k, source_filter=req.source_filter,
            cluster_filter=req.cluster_filter,
            year_min=req.year_min, year_max=req.year_max,
            lexical_boost=req.lexical_boost,
            work_type_filter=req.work_type_filter,
            free_to_read=req.free_to_read,
        )
        await run_in_thread(
            enrich_search_results,
            results, p, query_text=req.query_text, pico_boost=req.pico_boost,
        )
        sort_articles(results, req.sort_by)
        log_question(
            p.db,
            kind="search",
            question_text=req.query_text,
            filters={
                "sources": req.source_filter,
                "clusters": req.cluster_filter,
                "years": {"min": req.year_min, "max": req.year_max},
                "types": req.work_type_filter,
                "free_to_read": req.free_to_read,
                "lexical_boost": req.lexical_boost,
                "pico_boost": req.pico_boost,
                "top_k": req.top_k,
            },
            embedding_model=p.embedding_model_name,
            result_rows=results,
        )
        return {"results": results, "total": len(results)}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)


@router.post("/api/search/seed")
async def api_search_seed(req: SeedSearchRequest, request: Request):
    """Find more papers like one you already have (by id or title fragment)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        data = await run_in_thread(
            p.search_by_seed, req.seed, req.top_k,
            req.source_filter, req.cluster_filter,
            req.year_min, req.year_max, req.lexical_boost,
            req.include_seed, req.work_type_filter, req.free_to_read,
        )
        results = data["results"]
        await run_in_thread(enrich_search_results, results, p)
        log_question(
            p.db,
            kind="seed",
            question_text=req.seed,
            filters={
                "sources": req.source_filter,
                "clusters": req.cluster_filter,
                "years": {"min": req.year_min, "max": req.year_max},
                "types": req.work_type_filter,
                "free_to_read": req.free_to_read,
                "lexical_boost": req.lexical_boost,
                "pico_boost": False,
                "top_k": req.top_k,
            },
            embedding_model=p.embedding_model_name,
            result_rows=results,
        )
        return {
            "seed": data["seed"],
            "results": results,
            "total": len(results),
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)


@router.post("/api/search/starred")
async def api_search_starred(req: StarredSearchRequest, request: Request):
    """Rank papers near the centroid of your starred collection."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
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
            work_type_filter=req.work_type_filter,
            free_to_read=req.free_to_read,
        )
        results = data["results"]
        await run_in_thread(enrich_search_results, results, p)
        log_question(
            p.db,
            kind="starred",
            question_text="",
            filters={
                "sources": req.source_filter,
                "clusters": req.cluster_filter,
                "years": {"min": req.year_min, "max": req.year_max},
                "types": req.work_type_filter,
                "free_to_read": req.free_to_read,
                "lexical_boost": False,
                "pico_boost": False,
                "top_k": req.top_k,
            },
            embedding_model=p.embedding_model_name,
            result_rows=results,
        )
        return {
            "results": results,
            "total": len(results),
            "seed_count": data["seed_count"],
        }
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)


@router.post("/api/articles/other-copies")
async def api_other_copies(req: OtherCopiesRequest, request: Request):
    """Listed copies of starred papers with no open copy on this result page."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        keys = [(item.article_id, item.source) for item in req.articles]
        starred = p.db.get_starred_copy_fields(keys)
        dois: list[str] = []
        seen_doi = set()
        for row in starred.values():
            stored = str(row.get("doi") or "").strip()
            normalized = normalize_doi(row.get("doi"))
            for doi in (stored, normalized):
                if doi and doi not in seen_doi:
                    seen_doi.add(doi)
                    dois.append(doi)
        peers = p.db.get_copy_fields_for_dois(dois)
        return {"articles": other_copies_payload(
            starred, peers, trust_legacy=p.trust_legacy_access(),
        )}
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)


@router.post("/api/articles/different-work")
async def api_different_work(req: DifferentWorkRequest, request: Request):
    """Nearby open papers when a starred result has no open copy listed."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        keys = [(item.article_id, item.source) for item in req.articles]
        articles = await run_in_thread(
            p.suggest_different_work,
            keys,
            req.query_text,
            req.source_filter,
            req.cluster_filter,
            req.year_min,
            req.year_max,
            req.work_type_filter,
        )
        return {"articles": articles}
    except Exception as e:
        return server_error()
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
    try:
        p = get_owned_pipeline(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        current = p.db.get_note(req.article_id, req.source)
        if quota.would_increase_stored_text(current["note"], req.note):
            try:
                quota.check_quota(uid)
            except quota.QuotaExceeded as e:
                return JSONResponse(
                    status_code=507,
                    content={"detail": sentence_for(e), "quota": quota.usage_report(uid)},
                )
        note = p.db.upsert_note(req.article_id, req.source, note=req.note, starred=req.starred)
        return {"status": "success", "note": note}
    except integrity_errors():
        # notes.article_id is a foreign key, so starring a paper that is no
        # longer in this library raises rather than returning a row. That is
        # reachable from an ordinary stale tab -- a "replace" fetch or a
        # library switch changes every article id -- so it is the client's
        # view being out of date, not a server fault.
        return JSONResponse(
            status_code=404,
            content={"detail": "That paper is no longer in this library. "
                                "Refresh your results and try again."},
        )
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)


@router.get("/api/notes")
async def api_get_note(
    request: Request,
    article_id: str = "",
    source: str = "",
    library_id: str = "",
):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if not article_id or not source:
        return JSONResponse(status_code=400, content={"detail": "article_id and source required"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        return p.db.get_note(article_id, source)
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid)
