"""
Assignment hand-in pack helpers (Phase R3).

One zip for teachers: screening report + included-only CSV/RIS + short README
explaining notes/stars columns. Checklist targets are soft hints only.
"""

from __future__ import annotations

import csv
import io
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from citations import collection_to_ris
from study_type import classify_study_type
from utils import build_screening_report, format_screening_report_txt

HANDIN_README = """Assignment hand-in pack
=======================

This zip is for classroom hand-ins. It shows *process* and *what you kept*,
not a polished bibliography.

Contents
--------
1. screening_report.txt
   Counts: how many papers you collected, excluded (and why), and kept.
   Attach this when a teacher asks "show your screening work."

2. included_papers.csv
   Spreadsheet of papers still in your final set (not screened out).
   Columns include:
     - Title, Year, Journal, Authors, Source, ID
     - Cluster ID / Cluster Label (if you clustered)
     - Excluded / Exclusion Reason (should be empty for this file)
     - Starred  — yes if you bookmarked with ★ (private study flag)
     - Note     — your private note text, if any
   Teachers can sort/filter this log; stars and notes are optional process
   evidence, not grades.

3. included_papers.ris
   Same included set for Zotero / EndNote / Mendeley. Import here, then
   generate APA/MLA/Chicago in the manager for a final reference list.

Tips
----
- Scope is "included only" — screened-out duplicates and triage are out.
- CSV notes/stars stay in *your* library export; they are not shared when
  a teacher shares a class-code clone (notes/stars are not copied).
- This is a starting point over public databases, not a complete library search.
"""


def library_rows_to_csv(rows: List[dict]) -> str:
    """Same column layout as GET /api/export/library?format=csv."""
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


def build_assignment_zip(db) -> bytes:
    """Return zip bytes: report + included CSV + included RIS + README."""
    report = build_screening_report(db)
    report_txt = format_screening_report_txt(report)
    rows = db.get_library_export_rows(scope="included")
    csv_body = library_rows_to_csv(rows)
    ris_body = collection_to_ris(rows) if rows else ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("screening_report.txt", report_txt)
        zf.writestr("included_papers.csv", csv_body)
        zf.writestr("included_papers.ris", ris_body)
        zf.writestr("README_handin.txt", HANDIN_README)
    return buf.getvalue()


def evaluate_assignment_checklist(
    db,
    *,
    min_sources: int = 3,
    min_included: int = 5,
    require_review: bool = True,
) -> Dict[str, Any]:
    """Soft checklist against the included set. Never auto-fails hand-ins."""
    min_sources = max(0, int(min_sources))
    min_included = max(0, int(min_included))
    rows = db.get_library_export_rows(scope="included")
    n_included = len(rows)
    sources = sorted({(r.get("source") or "").strip() for r in rows if r.get("source")})
    n_sources = len(sources)

    review_ids = ("synthesis", "narrative_review")
    review_like = 0
    for r in rows:
        info = classify_study_type(title=r.get("title"), abstract=r.get("abstract"))
        if info.get("study_type") in review_ids:
            review_like += 1

    hints: List[Dict[str, Any]] = []

    ok_inc = n_included >= min_included if min_included else True
    hints.append({
        "id": "min_included",
        "ok": ok_inc,
        "label": f"At least {min_included} included papers",
        "detail": f"You have {n_included} in the included set.",
        "current": n_included,
        "target": min_included,
    })

    ok_src = n_sources >= min_sources if min_sources else True
    hints.append({
        "id": "min_sources",
        "ok": ok_src,
        "label": f"At least {min_sources} different sources",
        "detail": (
            f"You have {n_sources} source(s) among included papers"
            + (f" ({', '.join(sources)})" if sources else "")
            + "."
        ),
        "current": n_sources,
        "target": min_sources,
    })

    if require_review:
        ok_rev = review_like >= 1
        hints.append({
            "id": "has_review",
            "ok": ok_rev,
            "label": "At least 1 likely review / overview paper",
            "detail": (
                f"Heuristic found {review_like} included paper(s) that look like "
                "reviews or literature overviews (title+abstract guess only)."
            ),
            "current": review_like,
            "target": 1,
        })

    all_ok = all(h["ok"] for h in hints)
    return {
        "included": n_included,
        "unique_sources": n_sources,
        "sources": sources,
        "review_like_count": review_like,
        "starred_among_included": sum(1 for r in rows if r.get("starred")),
        "notes_among_included": sum(1 for r in rows if (r.get("note") or "").strip()),
        "targets": {
            "min_sources": min_sources,
            "min_included": min_included,
            "require_review": bool(require_review),
        },
        "hints": hints,
        "all_ok": all_ok,
        "soft": True,
        "message": (
            "All soft targets look met — still check your assignment rubric."
            if all_ok
            else "Some soft targets are not met yet — hints only, download still allowed."
        ),
    }
