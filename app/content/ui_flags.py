"""
Deployer / teacher UI feature flags (env-driven).

Classroom hosts can hide power-user surfaces without rebuilding the app.
Extractive key points always remain available when AI buttons are hidden.
"""

from __future__ import annotations

import os
from typing import Dict


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def ai_buttons_hidden() -> bool:
    """HIDE_AI_BUTTONS also switches the AI routes off (decided 2026-10-16)."""
    return _env_truthy("HIDE_AI_BUTTONS", "false")


def ai_off_response():
    """403 for an AI study-aid request while HIDE_AI_BUTTONS is on (audit 22.6)."""
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=403,
        content={"detail": "AI study aids are turned off on this server."},
    )


def get_ui_flags() -> Dict[str, bool]:
    """Public flags consumed by templates/JS and search enrichment.

    HIDE_STUDY_TYPE_TAGS=true  → no study-type badges on Search results
    HIDE_AI_BUTTONS=true       → no Refine/Ask/Explain on results (Account AI card stays)
    """
    return {
        "show_study_type_tags": not _env_truthy("HIDE_STUDY_TYPE_TAGS", "false"),
        "show_ai_buttons": not _env_truthy("HIDE_AI_BUTTONS", "false"),
    }
