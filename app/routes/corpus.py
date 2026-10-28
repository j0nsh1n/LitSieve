"""Building the corpus: fetch, embeddings, clustering, duplicates, screening."""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import core
from app.content.sample_corpus import get_sample_articles
from app.content.screening_reasons import (
    SET_ASIDE_GROUP_ORDER,
    normalize_reason,
    set_aside_group_label,
)
from app.content.source_catalog import drop_retired_sources
from app.core import (
    account_jobs_full,
    csrf_failed,
    current_user,
    get_owned_pipeline,
    get_pipeline,
    is_job_cancelled,
    library_progress,
    limiter,
    release_pipeline,
    request_job_cancel,
    run_in_thread,
    server_error,
    start_user_job,
    try_begin_user_job,
    update_progress,
)
from app.errors import sentence_for
from app.schemas import (
    ClusterRequest,
    ClusterScreeningRequest,
    CoverageRequest,
    DuplicateRequest,
    EmbeddingsRequest,
    MultiFetchRequest,
    QuickScreenPreviewRequest,
    ResolveDuplicatesRequest,
    SampleCorpusRequest,
    ScreeningRequest,
)
from app.services import sample_embeddings
from app.services.enrich import attach_key_points
from app.services.pipeline import FETCHERS
from app.storage import quota
from app.storage.database import omit_null_metadata
from app.storage.libraries import owned_library_id
from app.storage.run_record import begin_fetch_run, finish_fetch_run, log_question
from app.utils import (
    coverage_suggestions,
)
from app.version import APP_VERSION

logger = logging.getLogger(__name__)

router = APIRouter()


# Each library has its own job slots; an account runs at most two at once (21.8).
ONE_FETCH = "A fetch is already running in this library. Wait for it to finish."
ONE_PREPARE = (
    "Papers are already being prepared in this library. Wait for it to finish."
)
ONE_CLUSTER = "Theme grouping is already running in this library."
ACCOUNT_FULL = (
    f"Your account is already running {core.MAX_JOBS_PER_ACCOUNT} jobs in "
    "other libraries. Wait for one to finish."
)


def _busy(uid: str, lib_id: str, task: str, detail: str) -> JSONResponse:
    """409 that names why the slot could not be claimed: this library, or the account."""
    own = core.job_worker_alive(uid, lib_id, task) or library_progress(uid, lib_id)[task].get("active")
    full = not own and account_jobs_full(uid)
    return JSONResponse(status_code=409, content={"detail": ACCOUNT_FULL if full else detail})


@router.get("/api/progress")
async def api_progress(request: Request, library_id: Optional[str] = None):
    """Job slots of one library: the page's, else the active one."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    try:
        lib_id = owned_library_id(user["user_id"], library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    snapshot = library_progress(user["user_id"], lib_id)
    sources = {}
    for src, row in (snapshot['fetch'].get('source_progress') or {}).items():
        item = dict(row)
        if item['state'] == 'running' and item.get('started_at') is not None:
            item['elapsed_seconds'] = max(0, time.time() - item['started_at'])
        sources[src] = item
    snapshot['fetch']['source_progress'] = sources
    return snapshot


def _run_multi_fetch(
    p, *, query, sources, max_results, email, clear_first, uid, lib_id,
    topics=None, areas=None,
):
    """Blocking multi-source fetch for sync wait= or background jobs."""
    # Live per-source narrative for the UI: only counts the API has produced.
    live_by_source: dict = {}
    live_status: dict = {}
    run_id = begin_fetch_run(
        p.db,
        raw_input=query,
        sources=list(sources),
        topics=topics,
        areas=areas,
        mode="replace" if clear_first else "append",
        max_results=max_results,
        app_version=APP_VERSION,
    )
    results = None
    outcome = "error"
    update_progress(
        uid, lib_id, 'fetch', done=0, total=len(sources),
        articles_so_far=0, message='Starting fetch…', cancel=False,
        sources=list(sources), by_source={}, source_status={},
        source_progress={
            src: {'state': 'queued', 'started_at': None, 'finished_at': None,
                  'elapsed_seconds': 0, 'error_kind': None}
            for src in sources
        },
    )
    reclaimable = 0
    if clear_first:
        reclaimable = quota.library_file_bytes(getattr(p.db, "db_path", "") or "")
        p.db.reset_staging_articles()

    def on_source_done(done, total, **extra):
        arts = extra.get('articles_so_far', 0)
        src = extra.get('source') or ''
        sc = extra.get('source_count', 0)
        kind = extra.get('error_kind')
        state = extra.get('source_state', 'done')
        if src:
            if state == 'done':
                live_by_source[src] = int(sc or 0)
            live_status[src] = (kind or 'ok') if state == 'done' else state
        if kind and kind not in (None, 'no_results'):
            msg = f"{done}/{total} sources · {arts} papers · {src}: {kind}"
        elif state == 'done':
            msg = f"{done}/{total} sources · {arts} papers · last: {src} (+{sc})"
        else:
            msg = f"{done}/{total} sources · {arts} papers · searching {src}"
        update_progress(
            uid, lib_id, 'fetch', done=done, total=total,
            articles_so_far=arts, message=msg,
            sources=list(sources),
            by_source=dict(live_by_source),
            source_status=dict(live_status),
            source_progress=extra.get('source_progress', {}),
        )

    actually_cleared = False
    try:
        try:
            results = p.fetch_articles_parallel(
                query=query,
                sources=sources,
                max_results=max_results,
                email=email or "",
                progress_callback=on_source_done,
                cancel_check=lambda: (
                    is_job_cancelled(uid, lib_id, 'fetch')
                    or quota.is_over_quota(uid, reclaimable=reclaimable)
                ),
                into_staging=bool(clear_first),
            )
            total = sum(v['count'] for v in results.values())
            user_cancel = is_job_cancelled(uid, lib_id, 'fetch')
            # Quota stop is not a user cancel. Do not swap a partial staging set
            # over the live library — keep what the student already has.
            hit_quota = quota.is_over_quota(uid, reclaimable=reclaimable)
            if clear_first:
                staged = p.db.count_staging_articles()
                if staged > 0 and not user_cancel and not hit_quota:
                    p.db.replace_from_staging()
                    actually_cleared = True
                    total = staged
                else:
                    p.db.drop_staging_articles()
                    if user_cancel or hit_quota:
                        total = 0
        except Exception:
            if clear_first:
                try:
                    p.db.drop_staging_articles()
                except Exception:
                    logger.exception("Could not drop staging after failed replace-fetch")
            raise

        p.invalidate_corpus_cache()
        assert results is not None
        errors = {src: v['error'] for src, v in results.items() if v['error']}
        error_kinds = {
            src: v.get('error_kind')
            for src, v in results.items()
            if v.get('error_kind')
        }
        ok = {src: v['count'] for src, v in results.items() if not v['error']}
        hit_quota = quota.is_over_quota(uid, reclaimable=reclaimable if not actually_cleared else 0)
        status, cancelled_flag = quota.fetch_finish_status(
            cancelled=is_job_cancelled(uid, lib_id, 'fetch'),
            hit_quota=hit_quota,
        )
        outcome = status
        return {
            "status": status,
            "quota_stopped": hit_quota,
            "quota": quota.usage_report(uid),
            "total_fetched": total,
            "by_source": {src: v['count'] for src, v in results.items()},
            "ok_sources": ok,
            "errors": errors,
            "error_kinds": error_kinds,
            "cleared_first": actually_cleared,
            "cancelled": cancelled_flag,
            "inserted": {src: v.get("inserted", v["count"]) for src, v in results.items()},
            "merged": {src: v.get("merged", 0) for src, v in results.items()},
            "skipped_duplicates": {
                src: v.get("skipped_duplicates", 0) for src, v in results.items()
            },
        }
    finally:
        finish_fetch_run(p.db, run_id, outcome=outcome, results=results)


@router.post("/api/fetch-articles-multi")
@limiter.limit("20/minute")
async def api_fetch_multi(req: MultiFetchRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    if core.is_guest_user(user):
        return core.guest_forbidden_response()
    uid = user["user_id"]
    try:
        lib_id = owned_library_id(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    # Saved preferences from before a source was retired may still list it.
    # Then: once each, in order, and only databases this server knows (21.5).
    req.sources = list(dict.fromkeys(drop_retired_sources(req.sources)))
    unknown = [src for src in req.sources if src not in FETCHERS]
    if unknown:
        return JSONResponse(
            status_code=400,
            content={"detail": f"Unknown database: {unknown[0]}. Pick from the list on Search."},
        )
    if not req.sources:
        return JSONResponse(
            status_code=400,
            content={"detail": "Pick at least one database to search."},
        )
    # Replace/clear_first must be allowed while over quota so students can
    # wipe the library and free disk; mid-fetch still stops if they go over again.
    if not req.clear_first:
        try:
            quota.check_quota(uid)
        except quota.QuotaExceeded as e:
            return JSONResponse(
                status_code=507,
                content={"detail": sentence_for(e), "quota": quota.usage_report(uid)},
            )
    job_kwargs = dict(
        query=req.query,
        sources=req.sources,
        max_results=req.max_results,
        email=req.email,
        clear_first=req.clear_first,
        topics=req.topics,
        areas=req.areas,
    )
    if not req.wait:
        if not start_user_job(uid, lib_id, 'fetch', _run_multi_fetch, **job_kwargs):
            return _busy(uid, lib_id, 'fetch', ONE_FETCH)
        return JSONResponse(status_code=202, content={"status": "started"})

    # Same per-user fetch slot as wait=False. Staging is library-wide; two
    # overlapping fetches (sync or background) would reset or mix staged rows.
    if not try_begin_user_job(
        uid, lib_id, 'fetch',
        total=len(req.sources),
        sources=list(req.sources),
        by_source={},
        source_status={},
        last_fetch={
            "query": req.query,
            "sources": list(req.sources),
            "max_results": req.max_results,
            "clear_first": bool(req.clear_first),
            "email": req.email or "",
        },
    ):
        return _busy(uid, lib_id, 'fetch', ONE_FETCH)
    try:
        p = get_pipeline(uid, lib_id)
        result = await run_in_thread(_run_multi_fetch, p, uid=uid, lib_id=lib_id, **job_kwargs)
        update_progress(uid, lib_id, 'fetch', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, lib_id, 'fetch', active=False, result=None, error=str(e))
        return server_error()
    finally:
        update_progress(uid, lib_id, 'fetch', active=False)
        release_pipeline(uid, lib_id)


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
    try:
        body = await request.json()
    except ValueError:
        body = {}
    raw_lib = body.get("library_id") if isinstance(body, dict) else None
    try:
        lib_id = owned_library_id(user["user_id"], raw_lib)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    ok = request_job_cancel(user["user_id"], lib_id, task)
    if not ok:
        return JSONResponse(
            status_code=409,
            content={"detail": f"No active {task} job to cancel"},
        )
    return {"status": "cancelling", "task": task}


class _EmbedCancelled(Exception):
    """Raised between batches when the student (or an admin) cancels a prepare."""


def _run_create_embeddings(p, *, model, only_missing, uid, lib_id):
    """Blocking embedding pass for sync wait= or background jobs."""
    update_progress(uid, lib_id, 'embed', done=0, total=0, cancel=False)

    def on_batch_done(done, total):
        update_progress(uid, lib_id, 'embed', done=done, total=total)
        # Read the cancel flag between batches: before, only fetch read it,
        # so cancelling a prepare did nothing (audit 21.1).
        if is_job_cancelled(uid, lib_id, 'embed'):
            raise _EmbedCancelled()

    # Engine swap happens inside create_embeddings under the pipeline lock.
    try:
        result = p.create_embeddings(
            model=model,
            progress_callback=on_batch_done,
            only_missing=only_missing,
        ) or {}
    except _EmbedCancelled:
        stats = p.get_statistics()
        return {
            "status": "cancelled",
            "articles_processed": stats["articles_with_embeddings"],
            "embeddings_created": 0,
            "message": "Preparing was cancelled. Nothing from this run was saved.",
        }
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
    try:
        lib_id = owned_library_id(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        quota.check_quota(uid)
    except quota.QuotaExceeded as e:
        return JSONResponse(status_code=507, content={"detail": sentence_for(e), "quota": quota.usage_report(uid)})
    job_kwargs = dict(model=req.model, only_missing=req.only_missing)
    if not req.wait:
        if not start_user_job(uid, lib_id, 'embed', _run_create_embeddings, **job_kwargs):
            return _busy(uid, lib_id, 'embed', ONE_PREPARE)
        return JSONResponse(status_code=202, content={"status": "started"})

    # Claim the slot like the background path: a sync embed used to mark the
    # slot active over a running job and then clear it in finally (21.3).
    if not try_begin_user_job(uid, lib_id, 'embed', done=0, total=0):
        return _busy(uid, lib_id, 'embed', ONE_PREPARE)
    try:
        p = get_pipeline(uid, lib_id)
    except Exception:
        update_progress(uid, lib_id, 'embed', active=False)
        return server_error()
    try:
        result = await run_in_thread(_run_create_embeddings, p, uid=uid, lib_id=lib_id, **job_kwargs)
        update_progress(uid, lib_id, 'embed', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, lib_id, 'embed', active=False, result=None, error=str(e))
        return server_error()
    finally:
        update_progress(uid, lib_id, 'embed', active=False)
        release_pipeline(uid, lib_id)


def _run_sample_prepare(p, *, model, only_missing, uid, lib_id):
    """Prepare the sample papers, then save their vectors for the next guest (21.9)."""
    result = _run_create_embeddings(p, model=model, only_missing=only_missing, uid=uid, lib_id=lib_id)
    if result.get("status") == "success" and result.get("embeddings_created"):
        try:
            sample_embeddings.save(p, model)
        except Exception:
            logger.warning("Could not save sample-paper vectors", exc_info=True)
    return result


def _run_create_clusters(p, *, uid, lib_id, n_clusters, method):
    def on_progress(done, total, message):
        update_progress(uid, lib_id, 'cluster', done=done, total=total, message=message)

    result = p.cluster_articles(n_clusters=n_clusters, method=method, progress_callback=on_progress)
    return {
        "status": "success", "clusters": p.db.get_all_clusters(),
        "resolved_n_clusters": result[3] if result else 0,
        "auto": n_clusters is None or n_clusters <= 0,
    }


@router.post("/api/create-clusters")
async def api_create_clusters(req: ClusterRequest, request: Request):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    uid = user["user_id"]
    try:
        lib_id = owned_library_id(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    kwargs = dict(n_clusters=req.n_clusters, method=req.method)
    if not req.wait:
        try:
            started = start_user_job(uid, lib_id, 'cluster', _run_create_clusters, **kwargs)
        except Exception:
            return server_error()
        if not started:
            return _busy(uid, lib_id, 'cluster', ONE_CLUSTER)
        return JSONResponse(status_code=202, content={"status": "started"})
    if not try_begin_user_job(uid, lib_id, 'cluster'):
        return _busy(uid, lib_id, 'cluster', ONE_CLUSTER)
    p = None
    try:
        p = get_pipeline(uid, lib_id)
        result = await run_in_thread(_run_create_clusters, p, uid=uid, lib_id=lib_id, **kwargs)
        update_progress(uid, lib_id, 'cluster', active=False, result=result, error=None)
        return result
    except Exception as e:
        update_progress(uid, lib_id, 'cluster', active=False, result=None, error=core.safe_error_text(e))
        return server_error()
    finally:
        if p is not None:
            release_pipeline(uid, lib_id)


@router.get("/api/clusters")
async def api_get_clusters(request: Request, library_id: Optional[str] = None):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        clusters = p.db.get_all_clusters()
        briefings = await run_in_thread(p.get_cluster_briefings)
        by_id = {b["cluster_id"]: b for b in briefings}
        for c in clusters:
            c["briefing"] = by_id.get(c["cluster_id"])
        return {"clusters": clusters}
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, library_id)


@router.get("/api/clusters/{cluster_id}/articles")
async def api_get_cluster_articles(
    cluster_id: int, request: Request, library_id: Optional[str] = None, include_abstract: bool = False,
):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        articles = p.db.get_articles_by_cluster(cluster_id)
        for article in articles:
            omit_null_metadata(article)
        label = articles[0].get('cluster_label', f'Cluster {cluster_id}') if articles else f'Cluster {cluster_id}'
        attach_key_points(articles, p)
        if not include_abstract:
            for a in articles:
                a.pop('abstract', None)
        return {"cluster_id": cluster_id, "cluster_label": label, "articles": articles}
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, library_id)


@router.get("/api/statistics")
async def api_statistics(request: Request, library_id: Optional[str] = None):
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        stats = p.get_statistics()
        # Storage usage is account-wide (all libraries), so the UI can warn
        # before a fetch is refused rather than after.
        stats["storage"] = quota.usage_report(uid)
        return stats
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, library_id)


@router.post("/api/detect-duplicates")
async def api_detect_duplicates(req: DuplicateRequest, request: Request):
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
        # Pairwise similarity over the library: off the event loop (21.4).
        duplicates = await run_in_thread(p.detect_duplicates, threshold=req.threshold)
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
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)


@router.post("/api/screening")
async def api_screening(req: ScreeningRequest, request: Request):
    """Exclude (screen out) or re-include specific articles."""
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
        return server_error()
    finally:
        release_pipeline(uid)


@router.get("/api/screening/excluded")
async def api_screening_excluded(
    request: Request, reason: Optional[str] = None, library_id: Optional[str] = None,
):
    """Papers set aside, with title, year, and reason.

    No ``reason`` (or ``all``) lists every reason, grouped, for the Simple
    Set aside list. ``reason=low_relevance`` is what Undo after Narrow it
    down, Start over, and Re-prepare ask for: they restore only that group.
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        code = None if not reason or reason == "all" else normalize_reason(reason, default="low_relevance")
        items = p.db.get_excluded_items(code)
        for item in items:
            omit_null_metadata(item)
            item["label"] = set_aside_group_label(item["reason"])
        counts: dict = {}
        for item in items:
            counts[item["reason"]] = counts.get(item["reason"], 0) + 1
        order = {r: i for i, r in enumerate(SET_ASIDE_GROUP_ORDER)}
        groups = [
            {"reason": r, "label": set_aside_group_label(r), "count": n}
            for r, n in sorted(counts.items(), key=lambda kv: order.get(kv[0], len(order)))
        ]
        return {
            "status": "success",
            "reason": code or "all",
            "count": len(items),
            "items": items,
            "groups": groups,
        }
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, library_id)


@router.post("/api/screening/quick-preview")
async def api_screening_quick_preview(req: QuickScreenPreviewRequest, request: Request):
    """Rank papers against a research question; return least-related for review.

    Read-only: never writes screening. Apply via POST /api/screening with
    reason=low_relevance after the student confirms the proposed set.
    """
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
        # Embedding a query can be heavy — keep it off the event loop.
        result = await run_in_thread(
            p.propose_low_relevance, req.query, req.fraction,
        )
        ranked = list(result.get("candidates") or []) + list(
            reversed(result.get("staying") or [])
        )
        log_question(
            p.db,
            kind="narrow_preview",
            question_text=req.query,
            filters={
                "sources": None,
                "clusters": None,
                "years": None,
                "lexical_boost": False,
                "pico_boost": False,
                "top_k": result.get("proposed_count"),
                "fraction": req.fraction,
            },
            embedding_model=p.embedding_model_name,
            result_rows=ranked,
        )
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)


@router.post("/api/clusters/{cluster_id}/screening")
async def api_cluster_screening(cluster_id: int, req: ClusterScreeningRequest, request: Request):
    """Bulk exclude/include every article in a cluster (screening triage)."""
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
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)


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
    if not req.clear_first:
        try:
            quota.check_quota(uid)
        except quota.QuotaExceeded as e:
            return JSONResponse(
                status_code=507,
                content={"detail": sentence_for(e), "quota": quota.usage_report(uid)},
            )
    try:
        p = get_owned_pipeline(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
    try:
        articles = get_sample_articles()
        if not articles:
            return JSONResponse(
                status_code=500,
                content={"detail": "Sample corpus is empty; collection left unchanged."},
            )
        if req.clear_first:
            p.db.clear_all()
        stats = p.db.insert_articles(articles, dedupe=True)
        p.invalidate_corpus_cache()
        sample_embeddings.restore(p)
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
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)


@router.post("/api/resolve-duplicates")
async def api_resolve_duplicates(req: ResolveDuplicatesRequest, request: Request):
    """Auto-resolve duplicate groups: keep the best copy of each, exclude the rest."""
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
        action = p.preview_duplicate_resolution if req.preview else p.resolve_duplicates
        result = await run_in_thread(action, threshold=req.threshold)
        return {"status": "success", **result}
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)


@router.post("/api/coverage")
async def api_coverage(req: CoverageRequest, request: Request):
    """Coverage map: what you have vs sources usually useful for your topics."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    uid = user["user_id"]
    try:
        p = get_owned_pipeline(uid, req.library_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": sentence_for(e)})
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
        return server_error()
    finally:
        release_pipeline(uid, req.library_id)
