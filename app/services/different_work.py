"""Different-work suggestions for a starred paper with no open copy.

Stored embeddings and stored fields only. No network and no LLM.
"""

from __future__ import annotations

from typing import Any, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.services.question_concepts import QuestionConcepts
from app.services.work_types import normalize_doi
from app.utils import parse_year

OPEN_LISTED = "open_listed"
SUGGESTION_LIMIT = 3
# Cosine floor on stored MiniLM vectors. On frozen baseline_v1 (replay DBs
# under ~/HealthDatabaseAccess-scratch/bench/work/baseline_v1/):
# closest on-topic neighbors for Q1-Q3 sit about 0.51-0.67; history
# related-pair medians are about 0.37-0.42. Health/education neighbors are
# ~0.66-0.76 so the cap of 3 binds first. A labelled same-title preprint vs
# journal pair on Q1 was 0.86 (different DOIs); that is same-work via DOI or
# set-aside, not this floor. Below 0.45 the list is empty.
MIN_SIMILARITY = 0.45
FALLBACK_DIFFERENCE = "Different paper on a similar topic"

_CONCEPT_FIELDS = (
    "actor",
    "outcome",
    "population",
    "period",
    "place",
)


def work_doi(value: Any) -> Optional[str]:
    normalized = normalize_doi(value)
    if normalized:
        return normalized
    text = str(value or "").strip().lower()
    return text or None


def article_key(article: Mapping[str, Any]) -> Tuple[str, str]:
    return (str(article.get("article_id") or ""), str(article.get("source") or ""))


def difference_line(
    starred: Mapping[str, Any],
    other: Mapping[str, Any],
    concepts: Optional[QuestionConcepts] = None,
) -> str:
    """One short line of year, type, and concept differences."""
    parts: List[str] = []
    year_bit = _year_difference(starred, other)
    if year_bit:
        parts.append(year_bit)
    type_bit = _type_difference(starred, other)
    if type_bit:
        parts.append(type_bit)
    concept_bit = _concept_difference(starred, other, concepts)
    if concept_bit:
        parts.append(concept_bit)
    return "; ".join(parts) if parts else FALLBACK_DIFFERENCE


def pick_different_work(
    starred: Mapping[str, Any],
    ranked: Sequence[Mapping[str, Any]],
    *,
    min_similarity: float = MIN_SIMILARITY,
    limit: int = SUGGESTION_LIMIT,
    same_work_keys: Optional[Set[Tuple[str, str]]] = None,
) -> List[Mapping[str, Any]]:
    """Keep open, different-work neighbors above the cosine floor, closest first."""
    seed_key = article_key(starred)
    seed_doi = work_doi(starred.get("doi"))
    blocked = set(same_work_keys or ())
    blocked.add(seed_key)
    eligible: List[Mapping[str, Any]] = []
    for row in ranked:
        if not isinstance(row, Mapping):
            continue
        key = article_key(row)
        if key in blocked or key == ("", ""):
            continue
        other_doi = work_doi(row.get("doi"))
        if seed_doi and other_doi and seed_doi == other_doi:
            continue
        try:
            score = float(row.get("similarity_score") or 0)
        except (TypeError, ValueError):
            continue
        if score < min_similarity:
            continue
        url = _open_url(row)
        if not url:
            continue
        eligible.append(row)
        blocked.add(key)
    eligible.sort(
        key=lambda row: float(row.get("similarity_score") or 0),
        reverse=True,
    )
    return eligible[:limit]


def suggestion_public_dict(
    article: Mapping[str, Any], difference: str,
) -> Optional[dict]:
    url = _open_url(article)
    if not url:
        return None
    title = str(article.get("title") or "").strip() or "Untitled paper"
    return {
        "title": title,
        "url": url,
        "difference": difference or FALLBACK_DIFFERENCE,
    }


def _open_url(article: Mapping[str, Any]) -> str:
    access = article.get("access")
    if isinstance(access, Mapping):
        if str(access.get("state") or "") == OPEN_LISTED:
            url = str(access.get("url") or "").strip()
            if url.lower().startswith("http://") or url.lower().startswith("https://"):
                return url
        return ""
    return ""


def _year_difference(starred: Mapping[str, Any], other: Mapping[str, Any]) -> str:
    starred_year = parse_year(starred.get("year"))
    other_year = parse_year(other.get("year"))
    if not starred_year or not other_year or starred_year == other_year:
        return ""
    return f"{other_year} vs {starred_year}"


def _type_label(stored: Any) -> str:
    text = str(stored or "").strip().lower()
    if not text or text == "unknown":
        return ""
    return text.replace("-", " ")


def _type_difference(starred: Mapping[str, Any], other: Mapping[str, Any]) -> str:
    starred_type = _type_label(starred.get("work_type"))
    other_type = _type_label(other.get("work_type"))
    if not starred_type or not other_type or starred_type == other_type:
        return ""
    return f"{other_type} vs {starred_type}"


def _haystack(article: Mapping[str, Any]) -> str:
    return f"{article.get('title') or ''} {article.get('abstract') or ''}".casefold()


def _concept_phrases(concepts: Optional[QuestionConcepts]) -> List[str]:
    if concepts is None:
        return []
    phrases: List[str] = []
    seen: Set[str] = set()
    for field in _CONCEPT_FIELDS:
        for raw in getattr(concepts, field, ()) or ():
            phrase = str(raw or "").strip()
            key = phrase.casefold()
            if not phrase or key in seen:
                continue
            seen.add(key)
            phrases.append(phrase)
    return phrases


def _present(phrases: Iterable[str], haystack: str) -> List[str]:
    return [phrase for phrase in phrases if phrase.casefold() in haystack]


def _concept_difference(
    starred: Mapping[str, Any],
    other: Mapping[str, Any],
    concepts: Optional[QuestionConcepts],
) -> str:
    phrases = _concept_phrases(concepts)
    if not phrases:
        return ""
    starred_hits = _present(phrases, _haystack(starred))
    other_hits = _present(phrases, _haystack(other))
    starred_keys = {item.casefold() for item in starred_hits}
    other_keys = {item.casefold() for item in other_hits}
    only_other = [item for item in other_hits if item.casefold() not in starred_keys]
    only_starred = [item for item in starred_hits if item.casefold() not in other_keys]
    bits: List[str] = []
    if only_other:
        bits.append("covers " + ", ".join(only_other))
    if only_starred:
        bits.append("does not cover " + ", ".join(only_starred))
    return "; ".join(bits)
