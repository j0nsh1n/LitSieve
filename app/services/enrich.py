"""Search-result enrichment shared by the search and cluster endpoints.

These shape rows that are about to be returned to the browser: PICO snippets,
the optional PICO ranking nudge, the user's private notes/stars, stored
extractive key points, and heuristic study-type tags.
"""

import logging
import re
from typing import List

from app.services.embeddings import PICOExtractor

logger = logging.getLogger(__name__)


def attach_pico(results: List[dict]) -> None:
    """Add structured PICO snippets (sentences) to each result."""
    for article in results:
        pico = PICOExtractor.extract_pico(article.get("abstract", ""))
        # Cap snippets so the UI stays readable.
        article["pico"] = {
            k: (v[:3] if isinstance(v, list) else v) for k, v in pico.items()
        }


def apply_pico_boost(results: List[dict], query_text: str) -> None:
    """Small re-rank boost when abstract PICO snippets overlap query terms."""
    q = (query_text or "").lower()
    # Pull meaningful tokens from a PICO-style or free-text query.
    tokens = [t for t in re.findall(r"[a-zA-Z]{4,}", q) if t not in {
        "population", "intervention", "comparison", "outcome", "with", "from",
        "that", "this", "have", "been", "were", "their", "about",
    }]
    if not tokens:
        return
    for a in results:
        base = float(a.get("similarity_score") or 0)
        blob = " ".join(
            " ".join(a.get("pico", {}).get(k) or [])
            for k in ("population", "intervention", "comparison", "outcome")
        ).lower()
        if not blob:
            blob = (a.get("abstract") or "").lower()
        hits = sum(1 for t in tokens if t in blob)
        # At most +0.08 so similarity still dominates.
        boost = min(0.08, 0.015 * hits)
        a["similarity_score"] = round(base + boost, 4)
        a["pico_boost"] = round(boost, 4)
    results.sort(key=lambda x: x.get("similarity_score") or 0, reverse=True)


def attach_notes(results: List[dict], p) -> None:
    notes = p.db.get_notes_map()
    for a in results:
        n = notes.get((a.get("article_id"), a.get("source"))) or {}
        a["note"] = n.get("note") or ""
        a["starred"] = bool(n.get("starred"))


def attach_key_points(results: List[dict], p) -> None:
    """Attach stored extractive bullets (may be empty list)."""
    kp = p.db.get_key_points_map()
    for a in results:
        bullets = kp.get((a.get("article_id"), a.get("source")))
        a["key_points"] = list(bullets) if bullets else []


def attach_study_types(results: List[dict]) -> None:
    """Heuristic study-type tags at search time (cheap; may be wrong)."""
    from app.content.ui_flags import get_ui_flags
    if not get_ui_flags().get("show_study_type_tags", True):
        return
    from app.services.study_type import attach_study_types
    attach_study_types(results)


def enrich_search_results(results: List[dict], p, *, query_text: str = "", pico_boost: bool = False) -> None:
    """Shared post-rank enrichment for search / seed / starred."""
    attach_pico(results)
    if pico_boost and query_text:
        apply_pico_boost(results, query_text)
    attach_notes(results, p)
    attach_key_points(results, p)
    attach_study_types(results)
