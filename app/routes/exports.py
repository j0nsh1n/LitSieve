"""Search-result, whole-library and screening-report exports."""

import csv
import io
import logging
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

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
    ExportSelectionRequest,
)
from app.services.citations import collection_to_apa, collection_to_bibtex, collection_to_ris
from app.utils import (
    build_screening_report,
    format_screening_report_txt,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _format_ranked_export(results: List[dict], fmt: str):
    """Build download body for an ordered result list (search hits or selection)."""
    fmt = (fmt or "csv").lower().strip()
    if fmt == "ris":
        return collection_to_ris(results), "application/x-research-info-systems", "search_results.ris"
    if fmt == "bibtex":
        return collection_to_bibtex(results), "application/x-bibtex", "search_results.bib"
    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Rank", "Similarity", "Title", "Year", "Journal", "Authors",
            "Source", "ID", "Cluster ID", "Cluster Label",
        ])
        for i, a in enumerate(results, 1):
            writer.writerow([
                i, f"{a.get('similarity_score', 0):.3f}" if a.get("similarity_score") is not None else "",
                a.get("title", ""), a.get("year", ""),
                a.get("journal", ""), "; ".join(a.get("authors") or []),
                a.get("source", ""), a.get("article_id", ""),
                a.get("cluster_id", ""), a.get("cluster_label", ""),
            ])
        return output.getvalue(), "text/csv", "search_results.csv"
    # txt
    lines = []
    for i, a in enumerate(results, 1):
        sim = a.get("similarity_score")
        rank_bit = f"[{sim:.3f}] " if isinstance(sim, (int, float)) else ""
        lines.append(f"{i}. {rank_bit}{a.get('title', '')}")
        lines.append(f"   Year: {a.get('year', '')} | Journal: {a.get('journal', '')}")
        lines.append(f"   Authors: {'; '.join(a.get('authors') or [])}")
        lines.append(f"   Source: {a.get('source', '')} | ID: {a.get('article_id', '')}")
        if a.get("cluster_label"):
            lines.append(f"   Cluster: {a.get('cluster_label')}")
        lines.append("")
    return "\n".join(lines), "text/plain", "search_results.txt"


@router.post("/api/export/selection")
@limiter.limit("30/minute")
async def api_export_selection(req: ExportSelectionRequest, request: Request):
    """Export the exact ordered list of papers shown in Search (what you see is what you get)."""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if csrf_failed(request):
        return JSONResponse(status_code=403, content={"detail": "CSRF validation failed"})
    fmt = (req.format or "ris").lower().strip()
    if fmt not in ("csv", "txt", "ris", "bibtex"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    items = list(req.items or [])
    if not items:
        return JSONResponse(
            status_code=400,
            content={"detail": "No papers to export. Run a search first."},
        )
    if len(items) > 2000:
        return JSONResponse(status_code=400, content={"detail": "Too many papers (max 2000)."})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        def _load():
            rows = []
            for key in items:
                art = p.db.get_article_by_id(key.article_id, key.source)
                if art:
                    rows.append(art)
            return rows

        results = await run_in_thread(_load)
        if not results:
            return JSONResponse(
                status_code=400,
                content={"detail": "None of those papers were found in the active library."},
            )
        content, media_type, filename = _format_ranked_export(results, fmt)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


def _library_rows_to_csv(rows: List[dict]) -> str:
    """CSV for GET /api/export/library?format=csv (includes Starred / Note columns)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Year", "Journal", "Authors", "Source", "ID",
        "Cluster ID", "Cluster Label", "Excluded", "Exclusion Reason",
        "Starred", "Note",
    ])
    for a in rows:
        writer.writerow([
            a.get("title", ""),
            a.get("year", ""),
            a.get("journal", ""),
            "; ".join(a.get("authors") or []),
            a.get("source", ""),
            a.get("article_id", ""),
            a.get("cluster_id", ""),
            a.get("cluster_label", ""),
            "yes" if a.get("excluded") else "no",
            a.get("exclusion_reason", ""),
            "yes" if a.get("starred") else "no",
            a.get("note", ""),
        ])
    return output.getvalue()


@router.get("/api/export/library")
async def api_export_library(
    request: Request,
    scope: str = "all",
    format: str = "csv",
):
    """Export the collection with cluster membership and exclusion reasons.

    scope: all | included | excluded | starred
    format: csv | txt | ris | bibtex | apa
    """
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    if scope not in ("all", "included", "excluded", "starred"):
        return JSONResponse(status_code=400, content={"detail": "Invalid scope"})
    fmt = (format or "csv").lower().strip()
    if fmt not in ("csv", "txt", "ris", "bibtex", "apa"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        rows = p.db.get_library_export_rows(scope=scope)
        if fmt == "ris":
            content = collection_to_ris(rows)
            media_type = "application/x-research-info-systems"
            filename = "library.ris"
        elif fmt == "bibtex":
            content = collection_to_bibtex(rows)
            media_type = "application/x-bibtex"
            filename = "library.bib"
        elif fmt == "apa":
            content = collection_to_apa(rows)
            media_type = "text/plain"
            filename = "library_apa.txt"
        elif fmt == "txt":
            lines = []
            for a in rows:
                flag = "EXCLUDED" if a.get("excluded") else ("STARRED" if a.get("starred") else "INCLUDED")
                lines.append(f"[{flag}] {a.get('title', '')}")
                lines.append(
                    f"  Year: {a.get('year', '')} | Source: {a.get('source', '')} | "
                    f"ID: {a.get('article_id', '')}"
                )
                if a.get("cluster_label"):
                    lines.append(f"  Cluster: {a.get('cluster_label')}")
                if a.get("exclusion_reason"):
                    lines.append(f"  Exclusion reason: {a.get('exclusion_reason')}")
                if a.get("note"):
                    lines.append(f"  Note: {a.get('note')}")
                lines.append("")
            content = "\n".join(lines)
            media_type, filename = "text/plain", f"library_{scope}.txt"
        else:
            content = _library_rows_to_csv(rows)
            media_type, filename = "text/csv", f"library_{scope}.csv"
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)


@router.get("/api/screening-report")
async def api_screening_report(request: Request, format: str = "json"):
    """PRISMA-style screening accounting (read-only). format: json | txt"""
    user = current_user(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    fmt = (format or "json").lower().strip()
    if fmt not in ("json", "txt"):
        return JSONResponse(status_code=400, content={"detail": "Invalid format"})
    uid = user["user_id"]
    p = get_pipeline(uid)
    try:
        report = build_screening_report(p.db)
        if fmt == "txt":
            content = format_screening_report_txt(report)
            return StreamingResponse(
                io.BytesIO(content.encode()),
                media_type="text/plain",
                headers={
                    "Content-Disposition": "attachment; filename=screening_report.txt"
                },
            )
        return report
    except Exception as e:
        return server_error(e)
    finally:
        release_pipeline(uid)
