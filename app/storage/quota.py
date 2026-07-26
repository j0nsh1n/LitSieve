"""Per-account storage cap.

Registration is open and a single fetch can pull thousands of abstracts, each
of which later grows a 384-float embedding. Without a ceiling, one enthusiastic
account (or a bot) can fill the disk for everyone on a small Render / HF box.

The cap is measured in **bytes actually on disk** under ``user_data/<uid>/``
rather than an article count, because that is the resource that runs out and it
covers articles, embeddings, clusters and notes across *all* of a user's
libraries at once.

Set ``MAX_USER_STORAGE_MB=0`` to disable (useful for a single-user local run).
"""

from __future__ import annotations

import logging
import math
import os

from app.storage.libraries import user_dir

logger = logging.getLogger(__name__)

DEFAULT_MAX_MB = 500
ENV_KEY = "MAX_USER_STORAGE_MB"


class QuotaExceeded(RuntimeError):
    """Raised when an account is at or over its storage ceiling."""

    def __init__(self, used_bytes: int, limit_bytes: int):
        self.used_bytes = used_bytes
        self.limit_bytes = limit_bytes
        super().__init__(
            f"Storage limit reached ({mb(used_bytes)} MB of {mb(limit_bytes)} MB). "
            "Delete a library or screen out papers you do not need, then try again."
        )


def mb(num_bytes: int) -> float:
    return round(num_bytes / (1024 * 1024), 1)


def limit_bytes() -> int:
    """Configured ceiling in bytes; 0 means unlimited.

    Only finite, non-negative numbers are accepted. ``inf`` / NaN / negatives
    fall back to the default (negatives used to become 0 and silently disable
    the cap). Explicit ``0`` still means unlimited.
    """
    raw = (os.getenv(ENV_KEY) or "").strip()
    if not raw:
        return DEFAULT_MAX_MB * 1024 * 1024
    try:
        value = float(raw)
    except (ValueError, OverflowError):
        logger.warning("%s=%r is not a number; using default %d MB", ENV_KEY, raw, DEFAULT_MAX_MB)
        return DEFAULT_MAX_MB * 1024 * 1024
    if not math.isfinite(value) or value < 0:
        logger.warning("%s=%r is invalid; using default %d MB", ENV_KEY, raw, DEFAULT_MAX_MB)
        return DEFAULT_MAX_MB * 1024 * 1024
    return int(value) * 1024 * 1024


def usage_bytes(user_id: str) -> int:
    """Total bytes under the account's data directory (all libraries)."""
    root = user_dir(user_id)
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            # File vanished mid-walk (a job rotating a WAL, say) — skip it.
            continue
    return total


def usage_report(user_id: str) -> dict:
    """Usage numbers for the UI. ``limit_mb`` is 0 when the cap is disabled."""
    used = usage_bytes(user_id)
    cap = limit_bytes()
    return {
        "used_mb": mb(used),
        "limit_mb": mb(cap) if cap else 0,
        "percent": round(used / cap * 100, 1) if cap else 0.0,
        "over_limit": bool(cap) and used >= cap,
    }


def check_quota(user_id: str) -> None:
    """Raise :class:`QuotaExceeded` when the account is at/over its ceiling."""
    cap = limit_bytes()
    if not cap:
        return
    used = usage_bytes(user_id)
    if used >= cap:
        raise QuotaExceeded(used, cap)


def is_over_quota(user_id: str) -> bool:
    """Boolean form for use inside a running job (never raises)."""
    try:
        check_quota(user_id)
        return False
    except QuotaExceeded:
        return True
    except Exception:
        logger.exception("Quota check failed for %s; allowing the operation", user_id)
        return False


def fetch_finish_status(*, cancelled: bool, hit_quota: bool) -> tuple[str, bool]:
    """Map job end conditions to API status + cancelled flag.

    Quota stop is not a user cancel: status becomes ``quota_stopped`` and
    ``cancelled`` stays False so the UI can show a storage message.
    """
    if hit_quota:
        return "quota_stopped", False
    if cancelled:
        return "cancelled", True
    return "success", False
