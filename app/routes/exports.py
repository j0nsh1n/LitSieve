"""Search-result, whole-library and screening-report exports."""

import csv
import io
import logging
import math
from typing import List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core import (
    csrf_failed,
    current_user,
    get_owned_pipeline,
    get_pipeline,
    limiter,
    release_pipeline,
    run_in_thread,
    server_error,
)
from app.schemas import (
    ExportSelectionRequest,
)
from app.services.citations import (
    article_doi,
    citation_model,
    collection_to_apa,
    collection_to_bibtex,
    collection_to_ris,
)
from app.utils import (
    build_screening_report,
    format_screening_report_txt,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_text(value) -> str:
    """Text cell for a spreadsheet: a leading = + - @ tab or CR gets a ' prefix (OWASP)."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_LEADERS):
        return "'" + text
    return text


def _csv_row(cells) -> list:
    """Neutralise every text cell; ints and floats we generated pass through."""
    return [c if isinstance(c, (int, float)) and not isinstance(c, bool) else _csv_text(c) for c in cells]


_CSV_EXTRA_HEADERS = ("Type", "DOI", "Container", "Publisher", "Open copy URL")


def _csv_extra(article: dict) -> list:
    """Type, DOI, container, publisher and open-copy URL, after the original columns."""
    model = citation_model(article)
    stored = article.get("work_type")
    container = article.get("container_title") or model.container
    return [
        stored if stored is not None else "",
        model.doi or "",
        container or "",
        model.publisher,
        model.open_copy_url or "",
    ]


def _txt_type_doi_lines(article: dict, indent: str) -> list:
    """Optional Type and DOI lines for TXT exports that already list fields."""
    lines = []
    stored = article.get("work_type")
    if stored:
        lines.append(f"{indent}Type: {stored}")
    doi = article_doi(article)
    if doi:
        lines.append(f"{indent}DOI: {doi}")
    return lines


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
            "Rank", "Similarity", "meaning_score", "word_bonus", "Title", "Year",
            "Journal", "Authors", "Source", "ID", "Cluster ID", "Cluster Label",
            *_CSV_EXTRA_HEADERS,
        ])
        for i, a in enumerate(results, 1):
            sim = a.get("similarity_score")
            meaning = a.get("semantic_score", a.get("meaning_score"))
            bonus = a.get("word_bonus")
            cells = _csv_row([
                i, "", "", "",
                a.get("title", ""), a.get("year", ""),
                a.get("journal", ""), "; ".join(a.get("authors") or []),
                a.get("source", ""), a.get("article_id", ""),
                a.get("cluster_id", ""), a.get("cluster_label", ""),
                *_csv_extra(a),
            ])
            # Our own number, not source text: written as is, even when negative.
            if isinstance(sim, (int, float)) and not isinstance(sim, bool):
                cells[1] = f"{sim:.3f}"
            if isinstance(meaning, (int, float)) and not isinstance(meaning, bool):
                cells[2] = f"{meaning:.3f}"
            if isinstance(bonus, (int, float)) and not isinstance(bonus, bool):
                cells[3] = f"{bonus:.3f}"
            writer.writerow(cells)
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
        lines.extend(_txt_type_doi_lines(a, "   "))
        if a.get("cluster_label"):
            lines.append(f"   Cluster: {a.get('cluster_label')}")
        lines.append("")
    return "\n".join(lines), "text/plain", "search_results.txt"


def _clean_score(value) -> Optional[float]:
    """A search score sent by the page: a finite float in [-1, 2], else ignored."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    if not math.isfinite(score) or score < -1.0 or score > 2.0:
        return None
    return score


def _clean_label(value) -> str:
    """A cluster label sent by the page: a short single-line string, else empty."""
    if not isinstance(value, str):
        return ""
    label = " ".join(value.split())
    return label if 0 < len(label) <= 200 else ""


@router.post("/api/export/selection")
@limiter.limit("30/minute")
async def api_export_selection(req: ExportSelectionRequest, request: Request, library_id: str = ""):
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
    try:
        p = get_owned_pipeline(uid, library_id or None)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid library"})
    try:
        def _load():
            known = p.db.get_all_articles_with_clusters()
            rows = []
            for key in items:
                art = known.get((key.article_id, key.source))
                if not art:
                    continue
                art = dict(art)
                score = _clean_score(key.similarity_score)
                if score is not None:
                    art["similarity_score"] = score
                meaning = _clean_score(key.meaning_score)
                if meaning is not None:
                    art["semantic_score"] = meaning
                bonus = _clean_score(key.word_bonus)
                if bonus is not None:
                    art["word_bonus"] = bonus
                label = _clean_label(key.cluster_label)
                if label and not art.get("cluster_label"):
                    art["cluster_label"] = label
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
        return server_error()
    finally:
        release_pipeline(uid, library_id or None)


def _library_rows_to_csv(rows: List[dict]) -> str:
    """CSV for GET /api/export/library?format=csv (includes Starred / Note columns)."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Year", "Journal", "Authors", "Source", "ID",
        "Cluster ID", "Cluster Label", "Excluded", "Exclusion Reason",
        "Starred", "Note",
        *_CSV_EXTRA_HEADERS,
    ])
    for a in rows:
        writer.writerow(_csv_row([
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
            *_csv_extra(a),
        ]))
    return output.getvalue()


def _build_library_export(db, scope: str, fmt: str):
    """Build (content, media_type, filename) for the library export; runs off the event loop."""
    rows = db.get_library_export_rows(scope=scope)
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
            lines.extend(_txt_type_doi_lines(a, "  "))
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
    return content, media_type, filename


@router.get("/api/export/library")
@limiter.limit("10/minute")
async def api_export_library(
    request: Request,
    scope: str = "all",
    format: str = "csv",
    library_id: str = "",
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
    try:
        p = get_owned_pipeline(uid, library_id or None)
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid library"})
    try:
        content, media_type, filename = await run_in_thread(_build_library_export, p.db, scope, fmt)
        return StreamingResponse(
            io.BytesIO(content.encode()),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        return server_error()
    finally:
        release_pipeline(uid, library_id or None)


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
        return server_error()
    finally:
        release_pipeline(uid)
