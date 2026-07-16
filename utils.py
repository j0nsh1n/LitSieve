"""
Small shared helpers for sorting, source ranking, and coverage hints.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Higher = preferred when auto-resolving near-duplicates (tie-break after
# abstract length). Curated for a typical multi-source student corpus.
SOURCE_PRIORITY: Dict[str, int] = {
    "pubmed": 100,
    "europepmc": 90,
    "clinicaltrials": 85,
    "crossref": 80,
    "openalex": 75,
    "semanticscholar": 70,
    "doaj": 65,
    "arxiv": 60,
    "eric": 55,
    "core": 50,
    "zenodo": 45,
    "nasa_ads": 40,
}

# Topic id → sources that usually matter for classroom coverage checks.
# Mirrors the Data Management topic grid recommendations.
TOPIC_SOURCE_HINTS: Dict[str, List[str]] = {
    "health": ["pubmed", "europepmc", "clinicaltrials", "openalex", "semanticscholar"],
    "biology": ["pubmed", "europepmc", "openalex", "arxiv", "semanticscholar"],
    "chemistry": ["openalex", "arxiv", "semanticscholar", "crossref"],
    "physics": ["arxiv", "openalex", "semanticscholar", "nasa_ads"],
    "math": ["arxiv", "openalex", "semanticscholar"],
    "cs": ["arxiv", "openalex", "semanticscholar"],
    "earth": ["openalex", "semanticscholar", "nasa_ads", "zenodo"],
    "history": ["openalex", "semanticscholar", "eric", "crossref"],
    "economics": ["arxiv", "openalex", "semanticscholar", "eric"],
    "psychology": ["pubmed", "openalex", "semanticscholar", "eric"],
    "polisci": ["openalex", "semanticscholar", "eric"],
    "literature": ["openalex", "semanticscholar", "eric"],
    "education": ["eric", "openalex", "semanticscholar"],
}

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def parse_year(value: Any) -> int:
    """Extract a 4-digit publication year, or 0 if unknown/unparseable."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value if 1000 <= value <= 2100 else 0
    m = _YEAR_RE.search(str(value))
    return int(m.group(0)) if m else 0


def year_sort_key(article: Dict) -> int:
    """Numeric year for sorting (unknown years sort as 0)."""
    return parse_year(article.get("year"))


def sort_articles(results: List[Dict], sort_by: str) -> List[Dict]:
    """Sort a list of article dicts in place and return it."""
    if sort_by == "year":
        # Newest first; unknowns (0) sink to the bottom.
        results.sort(key=lambda a: year_sort_key(a), reverse=True)
    elif sort_by == "journal":
        results.sort(key=lambda a: (a.get("journal") or "").lower())
    elif sort_by == "title":
        results.sort(key=lambda a: (a.get("title") or "").lower())
    # "similarity" (default) keeps ranking order from search.
    return results


def source_priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source or "", 0)


def duplicate_quality_key(article: Optional[Dict], key: Tuple[str, str]) -> Tuple:
    """Rank a duplicate-group member for auto-resolve.

    Prefer the longest abstract (most useful record), then preferred source,
    then stable id fields so ties are deterministic.
    """
    article = article or {}
    abstract = article.get("abstract") or ""
    aid, src = key
    return (len(abstract), source_priority(src), src, aid)


def build_cluster_briefing(
    cluster_id: int,
    label: str,
    titles: List[str],
    years: List[Any],
    article_count: int,
    representative_title: Optional[str] = None,
) -> Dict:
    """Rule-based topic overview for a cluster (no LLM)."""
    parsed = [parse_year(y) for y in years]
    parsed = [y for y in parsed if y > 0]
    year_span = ""
    if parsed:
        lo, hi = min(parsed), max(parsed)
        year_span = str(lo) if lo == hi else f"{lo}-{hi}"

    clean_titles = [t.strip() for t in titles if t and t.strip()]
    # Prefer representative headline first, then other distinct titles.
    bullets: List[str] = []
    if representative_title and representative_title.strip():
        bullets.append(representative_title.strip())
    for t in clean_titles:
        if t not in bullets:
            bullets.append(t)
        if len(bullets) >= 4:
            break

    theme = (label or f"Cluster {cluster_id}").strip()
    summary = (
        f"{article_count} paper{'s' if article_count != 1 else ''}"
        + (f" spanning {year_span}" if year_span else "")
        + f". Theme keywords: {theme}."
    )
    return {
        "theme": theme,
        "summary": summary,
        "bullets": bullets,
        "year_span": year_span,
        "article_count": article_count,
    }


def coverage_suggestions(
    sources_present: Dict[str, int],
    topic_ids: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Suggest missing sources that usually matter for the selected topics."""
    topic_ids = topic_ids or []
    if not topic_ids:
        # Generic high-value sources if no topics chosen.
        recommended = ["pubmed", "openalex", "semanticscholar", "crossref"]
    else:
        recommended = []
        seen = set()
        for tid in topic_ids:
            for src in TOPIC_SOURCE_HINTS.get(tid, []):
                if src not in seen:
                    seen.add(src)
                    recommended.append(src)

    suggestions = []
    for src in recommended:
        if (sources_present.get(src) or 0) == 0:
            suggestions.append({
                "source": src,
                "reason": "Usually useful for your selected topic(s), but you have no articles from it yet.",
            })
    return suggestions[:6]


def build_screening_report(db) -> Dict[str, Any]:
    """PRISMA-style accounting of the current collection.

    Empty tables yield zeros naturally. Failures propagate so the endpoint
    can log and return 500 via server_error() — never mask them as empty data.
    """
    return db.build_screening_report_counts()


def format_screening_report_txt(report: Dict[str, Any]) -> str:
    """Plain-text screening report for download / on-screen panel (one source)."""
    total = int(report.get("total_articles") or 0)
    by_source = report.get("by_source") or {}
    if by_source:
        sources_str = "; ".join(f"{src}: {n}" for src, n in sorted(by_source.items()))
    else:
        sources_str = "(none)"
    excluded = report.get("excluded") or {}
    by_year = report.get("by_year") or {}
    if by_year:
        # Stable year order; unknown last.
        def _year_key(k: str):
            if k == "unknown":
                return (1, 0)
            try:
                return (0, -int(k))
            except ValueError:
                return (1, 0)
        years_str = "; ".join(
            f"{y}: {by_year[y]}" for y in sorted(by_year.keys(), key=_year_key)
        )
    else:
        years_str = "(none)"
    from screening_reasons import EXCLUSION_REASONS, reason_label

    lines = [
        f"SCREENING REPORT - {total} papers collected",
        f"Sources: {sources_str}",
        f"By year: {years_str}",
        f"Duplicates removed (kept best copy): {int(excluded.get('duplicate') or 0)}",
        f"Excluded as cluster triage: {int(excluded.get('cluster') or 0)}",
    ]
    # Remaining reason codes with non-zero counts (stable label order).
    for code in EXCLUSION_REASONS:
        if code in ("duplicate", "cluster"):
            continue
        n = int(excluded.get(code) or 0)
        if n:
            lines.append(f"Excluded ({reason_label(code)}): {n}")
    # Always show manual even if zero for continuity with older reports.
    if not int(excluded.get("manual") or 0):
        lines.append("Excluded (Manual): 0")
    lines.extend([
        f"INCLUDED in final set: {int(report.get('included') or 0)}",
        f"Starred: {int(report.get('starred') or 0)}",
        f"With embeddings: {int(report.get('with_embeddings') or 0)}",
        f"Clusters (excl. noise): {int(report.get('clusters') or 0)}",
        "Note: counts reflect the current collection state.",
        "",
    ])
    return "\n".join(lines)
