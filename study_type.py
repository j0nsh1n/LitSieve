"""
Lightweight multi-discipline study-type tags (title + abstract heuristics).

Weaker and broader than clinical A–D evidence grading. Labels are educational
hints only — confidence can be low and patterns mis-fire. Always surface a
warning when confidence is not high.

Designed to run cheaply at search time (pure functions, no I/O).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Student-facing type id -> short label for badges.
STUDY_TYPE_LABELS: Dict[str, str] = {
    "synthesis": "Review / synthesis",
    "trial": "Trial / experiment",
    "observational": "Observational",
    "survey": "Survey / cross-sectional",
    "qualitative": "Qualitative",
    "methods": "Methods / theory",
    "narrative_review": "Narrative review",
    "opinion": "Opinion / commentary",
    "unclear": "Unclear type",
}

# Ordered most-specific first. (type_id, confidence, patterns)
_PATTERNS: List[Tuple[str, float, List[str]]] = [
    (
        "synthesis",
        0.9,
        [
            r"meta[-\s]?analysis",
            r"systematic review",
            r"scoping review",
            r"umbrella review",
        ],
    ),
    (
        "trial",
        0.88,
        [
            r"randomi[sz]ed controlled trial",
            r"\brct\b",
            r"randomi[sz]ed,?\s+double[-\s]?blind",
            r"placebo[-\s]?controlled",
            r"quasi[-\s]?experimental",
            r"controlled trial",
        ],
    ),
    (
        "trial",
        0.72,
        [
            r"randomi[sz]ed",
            r"\brandomly\s+(?:assigned|allocated)\b",
            r"experimental design",
            r"intervention group",
            r"treatment group",
        ],
    ),
    (
        "observational",
        0.85,
        [
            r"prospective cohort",
            r"retrospective cohort",
            r"cohort study",
            r"longitudinal study",
            r"case[-\s]?control",
        ],
    ),
    (
        "observational",
        0.7,
        [
            r"\bcohort\b",
            r"observational study",
            r"secondary (?:data )?analysis",
        ],
    ),
    (
        "survey",
        0.8,
        [
            r"cross[-\s]?sectional",
            r"prevalence survey",
            r"questionnaire survey",
            r"online survey",
            r"\bsurvey of\b",
            r"self[-\s]?report(?:ed)? survey",
        ],
    ),
    (
        "qualitative",
        0.82,
        [
            r"qualitative (?:study|research|analysis|interview)",
            r"semi[-\s]?structured interview",
            r"focus group",
            r"thematic analysis",
            r"grounded theory",
            r"ethnograph",
            r"phenomenolog",
        ],
    ),
    (
        "methods",
        0.75,
        [
            r"this (?:paper|article) (?:proposes|presents) a (?:method|framework|model)",
            r"methodological",
            r"simulation study",
            r"computational model",
            r"theoretical framework",
            r"proof of concept",
        ],
    ),
    (
        "narrative_review",
        0.55,
        [
            r"narrative review",
            r"literature review",
            r"state of the art",
            r"\breview article\b",
            r"\bin this review\b",
        ],
    ),
    (
        "opinion",
        0.6,
        [
            r"\beditorial\b",
            r"expert opinion",
            r"consensus statement",
            r"\bcommentary\b",
            r"\bperspective\b",
            r"letter to the editor",
        ],
    ),
    # Low-confidence catch-all "review" (often wrong for software reviews etc.)
    (
        "narrative_review",
        0.4,
        [r"\breview\b"],
    ),
]


def _confidence_band(confidence: float, type_id: str) -> str:
    if type_id == "unclear" or confidence <= 0:
        return "none"
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.55:
        return "medium"
    return "low"


def classify_study_type(
    title: Optional[str] = None,
    abstract: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Return a study-type tag from title+abstract heuristics.

    Fields:
      study_type, study_type_label, confidence (0-1), confidence_band,
      matched_phrase, warning (always set when band != high), disclaimer
    """
    text = f"{title or ''}. {abstract or ''}".strip()
    haystack = text.lower()
    if len(haystack) < 20:
        return _result(
            "unclear",
            0.0,
            None,
            extra_warning="Too little text to guess study type.",
        )

    for type_id, confidence, patterns in _PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, haystack, flags=re.IGNORECASE)
            if match:
                return _result(type_id, confidence, match.group(0))

    return _result("unclear", 0.0, None)


def _result(
    type_id: str,
    confidence: float,
    matched_phrase: Optional[str],
    extra_warning: Optional[str] = None,
) -> Dict[str, Any]:
    band = _confidence_band(confidence, type_id)
    label = STUDY_TYPE_LABELS.get(type_id, STUDY_TYPE_LABELS["unclear"])
    disclaimer = (
        "Automated guess from title and abstract only. Often incomplete or wrong. "
        "Not an evidence grade or quality score. Check the full paper."
    )
    if band == "high":
        warning = None
    elif band == "medium":
        warning = "Moderate confidence - treat this tag as a rough hint only."
    elif band == "low":
        warning = "Low confidence - this tag is often inaccurate for mixed or short abstracts."
    else:
        warning = "Could not classify study type from the available text."
    if extra_warning:
        warning = extra_warning if not warning else f"{warning} {extra_warning}"

    return {
        "study_type": type_id,
        "study_type_label": label,
        "confidence": round(float(confidence), 3),
        "confidence_band": band,
        "matched_phrase": matched_phrase,
        "warning": warning,
        "disclaimer": disclaimer,
    }


def attach_study_types(articles: List[dict]) -> None:
    """Mutate each article dict with study_type fields (search-time)."""
    for a in articles or []:
        info = classify_study_type(
            title=a.get("title"),
            abstract=a.get("abstract"),
        )
        a["study_type"] = info["study_type"]
        a["study_type_label"] = info["study_type_label"]
        a["study_type_confidence"] = info["confidence"]
        a["study_type_confidence_band"] = info["confidence_band"]
        a["study_type_matched"] = info["matched_phrase"]
        a["study_type_warning"] = info["warning"]
        a["study_type_disclaimer"] = info["disclaimer"]
