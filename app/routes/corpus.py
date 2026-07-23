"""Building the corpus: fetch, embeddings, clustering, duplicates, screening."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import core
from app.content.sample_corpus import get_sample_articles
from app.content.screening_reasons import normalize_reason
from app.core import (
    _ensure_progress,
    csrf_failed,
    current_user,
    get_pipeline,
    is_job_cancelled,
    limiter,
    release_pipeline,
    request_job_cancel,
    run_in_thread,
    server_error,
    start_user_job,
    update_progress,
)
from app.schemas import (
    ClusterRequest,
    ClusterScreeningRequest,
    CoverageRequest,
    DuplicateRequest,
    EmbeddingsRequest,
    MultiFetchRequest,
    ResolveDuplicatesRequest,
    SampleCorpusRequest,
    ScreeningRequest,
)
from app.services.enrich import attach_key_points
from app.utils import (
    coverage_suggestions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/progress")
async def api_progress(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    with core._progress_lock:
        p = _ensure_progress(user["user_id"])
        return {k: dict(v) for k, v in p.items()}


def _run_multi_fetch(p, *, query, sources, max_results, email, clear_first, uid):
    """Blocking multi-source fetch for sync wait= or background jobs."""
    update_progress(
        uid, 'fetch', done=0, total=len(sources),
        articles_so_far=0, message='Starting fetch…', cancel=False,
    )
    if clear_first:
        p.db.clear_all()
        p.invalidate_corpus_cache()

    def on_source_done(done, total, **extra):
        arts = extra.get('articles_so_far', 0)
        src = extra.get('source') or ''
        sc = extra.get('source_count', 0)
        kind = extra.get('error_kind')
        if kind and kind not in (None, 'no_results'):
            msg = f"{done}/{total} sources · {arts} papers · {src}: {kind}"
        else:
            msg = f"{done}/{total} sources · {arts} papers · last: {src} (+{sc})"
        update_progress(
            uid, 'fetch', done=done, total=total,
            articles_so_far=arts, message=msg,
        )

    results = p.fetch_articles_parallel(
        query=query,
        sources=sources,
        max_results=max_results,
        email=email or "user@example.com",
        progress_callback=on_source_done,
        cancel_check=lambda: is_job_cancelled(uid, 'fetch'),
    )
    p.invalidate_corpus_cache()
    total = sum(v['count'] for v in results.values())
    errors = {src: v['error'] for src, v in results.items() if v['error']}
    error_kinds = {
        src: v.get('error_kind')
        for src, v in results.items()
        if v.get('error_kind')
    }
    ok = {src: v['count'] for src, v in results.items() if not v['error']}
    cancelled = is_job_cancelled(uid, 'fetch')
    return {
        "status": "cancelled" if cancelled else "success",
        "total_fetched": total,
        "by_source": {src: v['count'] for src, v in results.items()},
        "ok_sources": ok,
        "errors": errors,
        "error_kinds": error_kinds,
        "cleared_first": clear_first,
        "cancelled": cancelled,
    }


@router.post("/api/fetch-articles-multi")
@limiter.limit("20/minute")
async def api_fetch_multi(req: MultiFetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    job_kwargs = dict(
        query=req.query,
        sources=req.sources,
        max_results=req.max_results,
        email=req.email,
        clear_first=req.clear_first,
        uid=uid,
    )
    if not req.wait:
        if not start_user_job(uid, 'fetch', _run_multi_fetch, **job_kwargs):
            return JSONResponse(
                status_code=409,
                content={"detail": "A fetch is already running"},
            )
        return JSONResponse(status_code=202, content={"status": "started"})

    p = get_pipeline(uid)
    update_progress(uid, 'fetch', active=True, done=0, total=len(req.sources),
                    result=None, error=None, cancel=False, articles_so_far=0)
    try:
        result = await run_in_thread(_run_multi_fetch, p, **job_kwargs)
        update_progress(uid, 'fetch', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, 'fetch', active=False, result=None, error=str(e))
        return server_error(e)
    finally:
        update_progress(uid, 'fetch', active=False)
        release_pipeline(uid)


@router.post("/api/jobs/{task}/cancel")
@limiter.limit("30/minute")
async def api_cancel_job(task: str, request: Request):
    """Request cancel for an active background job (fetch or embed)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if task not in ("fetch", "embed"):
        return JSONResponse(status_code=400, content={"detail": "Unknown task"})
    ok = request_job_cancel(user["user_id"], task)
    if not ok:
        return JSONResponse(
            status_code=409,
            content={"detail": f"No active {task} job to cancel"},
        )
    return {"status": "cancelling", "task": task}


def _run_create_embeddings(p, *, model, only_missing, uid):
    """Blocking embedding pass for sync wait= or background jobs."""
    update_progress(uid, 'embed', done=0, total=0)

    def on_batch_done(done, total):
        update_progress(uid, 'embed', done=done, total=total)

    # Engine swap happens inside create_embeddings under the pipeline lock.
    result = p.create_embeddings(
        model=model,
        progress_callback=on_batch_done,
        only_missing=only_missing,
    ) or {}
    stats = p.get_statistics()
    return {
        "status": "success",
        "articles_processed": stats["articles_with_embeddings"],
        "embeddings_created": result.get("embeddings_created", 0),
        "skipped_existing": result.get("skipped_existing", 0),
        "seconds": result.get("seconds", 0),
        "model": result.get("model") or model,
        "device": result.get("device") or "cpu",
    }


@router.post("/api/create-embeddings")
@limiter.limit("12/minute")
async def api_create_embeddings(req: EmbeddingsRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    job_kwargs = dict(model=req.model, only_missing=req.only_missing, uid=uid)
    if not req.wait:
        if not start_user_job(uid, 'embed', _run_create_embeddings, **job_kwargs):
            return JSONResponse(
                status_code=409,
                content={"detail": "A embed is already running"},
            )
        return JSONResponse(status_code=202, content={"status": "started"})

    p = get_pipeline(uid)
    update_progress(uid, 'embed', active=True, done=0, total=0, result=None, error=None)
    try:
        result = await run_in_thread(_run_create_embeddings, p, **job_kwargs)
        update_progress(uid, 'embed', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, 'embed', active=False, result=None, error=str(e))
        return server_error(e)
    finally:
        update_progress(uid, 'embed', active=False)
        release_pipeline(uid)


@router.post("/api/create-clusters")
async def api_create_clusters(req: ClusterRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = await run_in_thread(p.cluster_articles, n_clusters=req.n_clusters, method=req.method)
        # cluster_articles returns (labels, cluster_labels, by_cluster, resolved_n)
        # or None when there are no embeddings yet.
        resolved_n = result[3] if result else 0
        return {
            "status": "success",
            "clusters": p.db.get_all_clusters(),
            "resolved_n_clusters": resolved_n,
            "auto": req.n_clusters is None or req.n_clusters <= 0,
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.get("/api/clusters")
async def api_get_clusters(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        clusters = p.db.get_all_clusters()
        briefings = await run_in_thread(p.get_cluster_briefings)
        by_id = {b["cluster_id"]: b for b in briefings}
        for c in clusters:
            c["briefing"] = by_id.get(c["cluster_id"])
        return {"clusters": clusters}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.get("/api/clusters/{cluster_id}/articles")
async def api_get_cluster_articles(cluster_id: int, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        articles = p.db.get_articles_by_cluster(cluster_id)
        label = articles[0].get('cluster_label', f'Cluster {cluster_id}') if articles else f'Cluster {cluster_id}'
        attach_key_points(articles, p)
        for a in articles:
            a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": label, "articles": articles}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.get("/api/statistics")
async def api_statistics(request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        return p.get_statistics()
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/detect-duplicates")
async def api_detect_duplicates(req: DuplicateRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        duplicates = p.detect_duplicates(threshold=req.threshold)
        result = []
        for id1, id2, sim in duplicates[:50]:
            a1 = p.db.get_article_by_id(*id1)
            a2 = p.db.get_article_by_id(*id2)
            if a1 and a2:
                result.append({
                    "article1": {
                        "article_id": a1['article_id'], "source": a1['source'],
                        "title": a1.get('title', ''), "abstract": a1.get('abstract', ''),
                        "authors": a1.get('authors', []), "year": a1.get('year', ''),
                        "journal": a1.get('journal', ''),
                    },
                    "article2": {
                        "article_id": a2['article_id'], "source": a2['source'],
                        "title": a2.get('title', ''), "abstract": a2.get('abstract', ''),
                        "authors": a2.get('authors', []), "year": a2.get('year', ''),
                        "journal": a2.get('journal', ''),
                    },
                    "similarity": round(sim, 3),
                })
        return {"duplicates": result, "total": len(duplicates)}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/screening")
async def api_screening(req: ScreeningRequest, request: Request):
    """Exclude (screen out) or re-include specific articles."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        keys = [(item.article_id, item.source) for item in req.items]
        if req.action == "exclude":
            reason = normalize_reason(req.reason, default="manual")
            count = p.db.exclude_articles(keys, reason=reason)
        else:
            count = p.db.include_articles(keys)
            reason = None
        p.invalidate_corpus_cache()
        return {
            "status": "success",
            "action": req.action,
            "count": count,
            "reason": reason,
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/clusters/{cluster_id}/screening")
async def api_cluster_screening(cluster_id: int, req: ClusterScreeningRequest, request: Request):
    """Bulk exclude/include every article in a cluster (screening triage)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        keys = p.db.get_cluster_article_keys(cluster_id)
        if not keys:
            return JSONResponse(status_code=404, content={"detail": f"Cluster {cluster_id} has no articles"})
        if req.action == "exclude":
            reason = normalize_reason(req.reason, default="cluster")
            count = p.db.exclude_articles(keys, reason=reason)
        else:
            count = p.db.include_articles(keys)
            reason = None
        p.invalidate_corpus_cache()
        return {
            "status": "success",
            "action": req.action,
            "cluster_id": cluster_id,
            "count": count,
            "reason": reason,
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/load-sample-corpus")
@limiter.limit("6/minute")
async def api_load_sample_corpus(req: SampleCorpusRequest, request: Request):
    """Load the built-in demo paper set (no external API calls)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        if req.clear_first:
            p.db.clear_all()
        articles = get_sample_articles()
        stats = p.db.insert_articles(articles, dedupe=True)
        p.invalidate_corpus_cache()
        inserted = stats.get("inserted", 0) if isinstance(stats, dict) else 0
        return {
            "status": "success",
            "loaded": len(articles),
            "inserted": inserted,
            "updated": stats.get("updated", 0) if isinstance(stats, dict) else 0,
            "cleared_first": req.clear_first,
            "hint": "Prepare papers for search next (or it auto-runs after a normal fetch).",
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/resolve-duplicates")
async def api_resolve_duplicates(req: ResolveDuplicatesRequest, request: Request):
    """Auto-resolve duplicate groups: keep the best copy of each, exclude the rest."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        result = await run_in_thread(p.resolve_duplicates, threshold=req.threshold)
        return {"status": "success", **result}
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.post("/api/coverage")
async def api_coverage(req: CoverageRequest, request: Request):
    """Coverage map: what you have vs sources usually useful for your topics."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        stats = p.get_statistics()
        sources = stats.get("sources") or {}
        suggestions = coverage_suggestions(sources, req.topics or [])
        return {
            "sources": sources,
            "total_articles": stats.get("total_articles", 0),
            "suggestions": suggestions,
            "embedding_model": stats.get("embedding_model"),
            "missing_embeddings": stats.get("missing_embeddings"),
        }
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)
