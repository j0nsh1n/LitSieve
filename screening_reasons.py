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

# System-assigned reasons (UI should not offer these as free choices for bulk manual).
SYSTEM_REASONS = frozenset({"cluster", "duplicate"})


def normalize_reason(reason: Optional[str], default: str = "manual") -> str:
    """Return a known reason code, or default for unknown/empty values."""
    if not reason:
        return default
    key = str(reason).strip().lower().replace(" ", "_").replace("-", "_")
    if key in EXCLUSION_REASONS:
        return key
    return default


def reason_label(reason: Optional[str]) -> str:
    code = normalize_reason(reason)
    return EXCLUSION_REASONS.get(code, code)
