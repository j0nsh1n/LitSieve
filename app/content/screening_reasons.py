"""
Screening exclusion reason codes (classroom-friendly PRISMA-style labels).

Legacy codes (manual, cluster, duplicate) are kept for compatibility.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# code -> short student-facing label
EXCLUSION_REASONS: Dict[str, str] = {
    "manual": "Manual",
    "cluster": "Cluster triage",
    "duplicate": "Duplicate copy",
    "off_topic": "Off topic",
    "wrong_population": "Wrong population",
    "wrong_study_type": "Wrong study type",
    "language": "Language",
    "insufficient_info": "Insufficient abstract / info",
    "other": "Other",
    # System-suggested (Quick screen): least similar to the research question.
    "low_relevance": "Low relevance (suggested)",
}

# Reasons students may pick in the UI (not auto-set by the system).
USER_SELECTABLE_REASONS: List[str] = [
    "off_topic",
    "wrong_population",
    "wrong_study_type",
    "language",
    "insufficient_info",
    "manual",
    "other",
]

# System-assigned reasons (UI must not offer these as free student choices).
SYSTEM_REASONS = frozenset({"cluster", "duplicate", "low_relevance"})


def normalize_reason(reason: Optional[str], default: str = "manual") -> str:
    """Return a known reason code, or default for unknown/empty values.

    Accepts spaces or hyphens (``Wrong population`` / ``OFF-TOPIC``) and maps
    them to the stable underscore codes in EXCLUSION_REASONS.
    """
    if not reason:
        return default
    key = str(reason).strip().lower().replace(" ", "_").replace("-", "_")
    return key if key in EXCLUSION_REASONS else default


def reason_label(reason: Optional[str]) -> str:
    """Student-facing label for a reason code (unknown → normalized default)."""
    return EXCLUSION_REASONS.get(normalize_reason(reason), "Manual")


# Plain-words group names for the Simple "Set aside" list. The report keeps the
# PRISMA labels above; a student reading the list needs to know which button
# put the paper there.
_SET_ASIDE_GROUP_LABELS: Dict[str, str] = {
    "low_relevance": "Set aside by Narrow it down",
    "off_topic": "Marked not relevant",
    "duplicate": "Duplicate copies",
    "cluster": "Set aside with a theme group",
    "manual": "Set aside by hand",
    "insufficient_info": "Too little information",
}

# Groups in the order the list shows them: the ones a student did last first,
# then the system's.
SET_ASIDE_GROUP_ORDER: List[str] = [
    "off_topic",
    "low_relevance",
    "duplicate",
    "cluster",
    "manual",
    "wrong_population",
    "wrong_study_type",
    "language",
    "insufficient_info",
    "other",
]


def set_aside_group_label(reason: Optional[str]) -> str:
    """Group heading for the Set aside list, in plain words."""
    code = normalize_reason(reason)
    return _SET_ASIDE_GROUP_LABELS.get(code, EXCLUSION_REASONS.get(code, "Set aside"))
