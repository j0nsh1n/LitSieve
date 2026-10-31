"""
Lightweight multi-discipline study-type tags (title + abstract heuristics).

Weaker and broader than clinical A–D evidence grading. Labels are educational
hints only — confidence can be low and patterns mis-fire. Always surface a
warning when confidence is not high.

Designed to run cheaply at search time (pure functions, no I/O).

Default labels are plain-language for younger students, with a short
"what this means" line and the older formal name kept for tooltips.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# Student-facing type id -> short plain-language label (default UI).
STUDY_TYPE_LABELS: Dict[str, str] = {
    "synthesis": "Likely a review paper",
    "trial": "Likely an experiment or trial",
    "observational": "Likely an observational study",
    "survey": "Likely a survey",
    "qualitative": "Likely interviews / qualitative",
    "methods": "Likely methods or theory",
    "narrative_review": "Likely a literature overview",
    "opinion": "Likely opinion or commentary",
    "unclear": "Type unclear",
}

# Older / more formal names (tooltip / advanced).
STUDY_TYPE_FORMAL_LABELS: Dict[str, str] = {
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

# One-line "what this means" for younger grades.
STUDY_TYPE_MEANINGS: Dict[str, str] = {
    "synthesis": "Combines findings from many papers (for example a systematic review or meta-analysis).",
    "trial": "Tests something with groups (often with a control or random assignment).",
    "observational": "Watches people or events over time without assigning a treatment.",
    "survey": "Asks people questions at a point in time (questionnaire).",
    "qualitative": "Uses interviews, focus groups, or themes rather than large number tables.",
    "methods": "Proposes a method, model, framework, or simulation more than new field data.",
    "narrative_review": "Summarises a topic without a full systematic search protocol.",
    "opinion": "Commentary, editorial, or expert view rather than new primary data.",
    "unclear": "Title and abstract did not match a clear study-type pattern.",
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
      study_type, study_type_label (plain language), study_type_label_formal,
      study_type_meaning, confidence (0-1), confidence_band, matched_phrase,
      warning (always set when band != high), disclaimer
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
    formal = STUDY_TYPE_FORMAL_LABELS.get(type_id, STUDY_TYPE_FORMAL_LABELS["unclear"])
    meaning = STUDY_TYPE_MEANINGS.get(type_id, STUDY_TYPE_MEANINGS["unclear"])
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
        "study_type_label_formal": formal,
        "study_type_meaning": meaning,
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
        a["study_type_label_formal"] = info["study_type_label_formal"]
        a["study_type_meaning"] = info["study_type_meaning"]
        a["study_type_confidence"] = info["confidence"]
        a["study_type_confidence_band"] = info["confidence_band"]
        a["study_type_matched"] = info["matched_phrase"]
        a["study_type_warning"] = info["warning"]
        a["study_type_disclaimer"] = info["disclaimer"]
        a["study_type_source"] = "pattern"


# ---------------------------------------------------------------------------
# Laya as a switch (optional). The pattern tagger above stays first; only when
# it is unsure does a local Laya model pick among the same type ids, and its
# answer is used only when it is confident. Measured on the 28-paper sample
# library (2026-10-12): patterns alone tagged 11 papers (10 right); with this
# gate 13 papers, all right. Laya alone was right on only 15 of 28, so it never
# overrides a confident pattern and never shows a guess below LAYA_MIN_P.
# ---------------------------------------------------------------------------
PATTERN_KEEP = 0.75   # pattern confidence at or above this is kept as is
LAYA_MIN_P = 0.85     # Laya's answer is used only at or above this probability
_LAYA_TYPES = ["synthesis", "trial", "observational", "survey", "qualitative", "methods", "narrative_review", "opinion"]
_CACHE_MAX = 4096
_cache: "OrderedDict[str, Optional[Tuple[str, float]]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_key(a: dict) -> str:
    text = f"{a.get('title') or ''}\n{a.get('abstract') or ''}"
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()


def refine_study_types_with_laya(articles: List[dict], embedding_engine=None) -> int:
    """After attach_study_types: ask Laya (one batch) about papers the patterns were unsure of.

    Return how many tags Laya or the optional backup changed.
    """
    from app.services import laya_client

    laya_enabled = laya_client.enabled()
    if not laya_enabled and not _backup_enabled():
        return 0
    unsure = [a for a in articles or []
              if float(a.get("study_type_confidence") or 0) < PATTERN_KEEP
              and len(f"{a.get('title') or ''}{a.get('abstract') or ''}") >= 80]
    if not unsure:
        return 0
    if not laya_enabled:
        return _refine_with_backup(unsure, embedding_engine)
    keys = [_cache_key(a) for a in unsure]
    with _cache_lock:
        missing = [(k, a) for k, a in zip(keys, unsure) if k not in _cache]
    backup_changed = 0
    if missing:
        answers = laya_client.choice(
            "What kind of study is this paper?",
            {t: STUDY_TYPE_MEANINGS[t] for t in _LAYA_TYPES},
            [f"{a.get('title') or ''}. {a.get('abstract') or ''}" for _, a in missing],
        )
        if answers is None:
            if not _backup_enabled():
                return 0
            backup_changed = _refine_with_backup([a for _, a in missing], embedding_engine)
        else:
            with _cache_lock:
                for (k, _), ans in zip(missing, answers):
                    _cache[k] = (ans["choice"], ans["p"]) if ans["p"] >= LAYA_MIN_P else None
                    _cache.move_to_end(k)
                while len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
    changed = backup_changed
    for k, a in zip(keys, unsure):
        with _cache_lock:
            hit = _cache.get(k)
        if not hit:
            continue
        type_id, p = hit
        _apply_model_result(a, type_id, p, "laya")
        changed += 1
    return changed


def _apply_model_result(a: dict, type_id: str, p: float, source: str) -> None:
    info = _result(type_id, p, None)
    a["study_type"] = info["study_type"]
    a["study_type_label"] = info["study_type_label"]
    a["study_type_label_formal"] = info["study_type_label_formal"]
    a["study_type_meaning"] = info["study_type_meaning"]
    a["study_type_confidence"] = info["confidence"]
    a["study_type_confidence_band"] = info["confidence_band"]
    a["study_type_matched"] = None
    a["study_type_warning"] = info["warning"]
    a["study_type_disclaimer"] = info["disclaimer"]
    a["study_type_source"] = source


def _backup_enabled() -> bool:
    return os.getenv("LITSIEVE_STUDY_BACKUP", "").strip().lower() in {"1", "true", "yes", "on"}


def _refine_with_backup(articles: List[dict], engine) -> int:
    if not _backup_enabled():
        return 0
    try:
        from app.services.study_backup import classify
        model = None
        if (engine is not None and engine.model_name == "general"
                and engine.resolve_model_path("general") == "sentence-transformers/all-MiniLM-L6-v2"):
            model = engine.cached_model()
        texts = [f"{a.get('title') or ''}. {a.get('abstract') or ''}"[:4000] for a in articles]
        answers = classify(texts, model)
        changed = 0
        for article, answer in zip(articles, answers):
            if answer:
                _apply_model_result(article, answer[0], answer[1], "backup")
                changed += 1
        return changed
    except Exception:
        logging.getLogger(__name__).exception("Study type backup failed")
        return 0


def _clear_laya_cache_for_tests() -> None:
    with _cache_lock:
        _cache.clear()
