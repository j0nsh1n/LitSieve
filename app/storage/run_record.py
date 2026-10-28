"""Private per-library record of Collect runs and Search questions.

Lives in the library database. Never stores contact email or API keys.
A failed write is logged and ignored so the student's request still succeeds.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

KEEP_ROWS = 50
RANKER_VERSION = "hybrid-0.7-0.3-v1"

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,})"
    r"|(?:api[_-]?key|ncbi_api_key|s2_api_key|openalex_api_key)\s*[=:]\s*[A-Za-z0-9_\-]{8,}",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub_secrets(value: Any) -> str:
    """Drop emails and API-key shaped strings from stored text."""
    text = "" if value is None else str(value)
    text = _EMAIL_RE.sub("[email]", text)
    return _KEY_RE.sub("[key]", text)


def json_text(value: Any) -> str:
    return scrub_secrets(json.dumps(value, ensure_ascii=False, default=str))


def _result_keys(rows: Iterable[Mapping[str, Any]]) -> list[list[str]]:
    keys: list[list[str]] = []
    for row in rows:
        aid = row.get("article_id")
        source = row.get("source")
        if aid is None or source is None:
            continue
        keys.append([str(aid), str(source)])
    return keys


def per_source_from_results(results: Optional[Mapping[str, Mapping[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not results:
        return out
    for src, row in results.items():
        elapsed = row.get("elapsed_s") or 0
        try:
            elapsed_s = round(float(elapsed), 3)
        except (TypeError, ValueError):
            elapsed_s = 0.0
        out[str(src)] = {
            "sent_query": scrub_secrets(row.get("sent_query") or ""),
            "inserted": int(row.get("inserted") or 0),
            "merged": int(row.get("merged") or 0),
            "skipped_duplicates": int(row.get("skipped_duplicates") or 0),
            "error_kind": row.get("error_kind"),
            "elapsed_s": elapsed_s,
        }
    return out


def begin_fetch_run(
    db,
    *,
    raw_input: str,
    sources: Sequence[str],
    topics: Optional[Sequence[str]] = None,
    areas: Optional[Sequence[str]] = None,
    mode: str,
    max_results: Optional[int],
    app_version: str,
) -> Optional[int]:
    try:
        return db.insert_fetch_run(
            started_at=utc_now(),
            raw_input=scrub_secrets(raw_input),
            sources=list(sources),
            topics=list(topics or []),
            areas=list(areas or []),
            mode=mode,
            max_results=max_results,
            app_version=app_version,
        )
    except Exception:
        logger.exception("Could not record fetch run start")
        return None


def finish_fetch_run(
    db,
    run_id: Optional[int],
    *,
    outcome: str,
    results: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> None:
    if run_id is None:
        return
    try:
        db.update_fetch_run(
            run_id,
            finished_at=utc_now(),
            outcome=str(outcome or "error"),
            per_source=per_source_from_results(results),
        )
    except Exception:
        logger.exception("Could not record fetch run finish")


def log_question(
    db,
    *,
    kind: str,
    question_text: str,
    filters: Optional[Mapping[str, Any]] = None,
    embedding_model: Optional[str] = None,
    result_rows: Iterable[Mapping[str, Any]] = (),
) -> None:
    try:
        db.insert_question_log(
            created_at=utc_now(),
            kind=kind,
            question_text=scrub_secrets(question_text),
            filters=dict(filters or {}),
            embedding_model=embedding_model,
            result_keys=_result_keys(result_rows),
        )
    except Exception:
        logger.exception("Could not record question log")
