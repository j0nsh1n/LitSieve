"""Reader Mode orchestration: cache, generation, app-owned copy, verification."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.services import reader_facts
from app.services.llm import (
    LLMError,
    LLMUnavailable,
    generate_reader_explanation,
    is_configured,
    run_with_ephemeral_builtin,
)
from app.services.llm import provider as llm_provider
from app.services.reader_verify import CURRENT_VERIFIER_VERSION, verify
from app.services.study_type import classify_study_type
from app.services.summarize import parse_structured_abstract

logger = logging.getLogger(__name__)

READER_PROMPT_VERSION = "reader_v1"
AUDIENCES = ("high_school", "general_reader")
MIN_ABSTRACT_LEN = 40
NOT_REPORTED = "Not reported in the abstract."
FALLBACK_WHAT_IT_DOES_NOT_SHOW = (
    "The abstract alone cannot establish whether these findings apply to everyone."
)
LABEL = "AI explanation (from this abstract only — not medical advice)"
DISCLAIMER = (
    "This is an educational reading aid, not medical, legal, or professional "
    "advice. Always check the original paper."
)
PROSE_FIELDS = (
    "plain_summary",
    "question_asked",
    "who_was_studied",
    "what_was_found",
    "what_it_does_not_show",
    "stated_limitations",
)


def _active_model() -> Optional[str]:
    selected = llm_provider()
    if selected == "ollama":
        return (os.getenv("OLLAMA_MODEL") or "").strip() or None
    if selected == "openai":
        return (os.getenv("OPENAI_MODEL") or "").strip() or None
    if selected == "anthropic":
        return (os.getenv("LLM_MODEL") or "").strip() or None
    return None


def facts_block(title: str, abstract: str) -> str:
    """Deterministic facts fed to the model. No user identity, no library name."""
    lines: list[str] = []
    numbers = reader_facts.extract_numbers(abstract or "")
    if numbers:
        lines.append("Numbers:")
        for tok in numbers:
            lines.append(f"- {tok['kind']}: {tok['surface']}")
    cues = reader_facts.extract_cues(abstract or "")
    if cues["uncertainty"]:
        lines.append("Uncertainty cues: " + ", ".join(cues["uncertainty"]))
    if cues["negation"]:
        lines.append("Negation cues: " + ", ".join(cues["negation"]))
    info = classify_study_type(title or "", abstract or "")
    band = info.get("confidence_band")
    if band in ("high", "medium") and info.get("study_type") != "unclear":
        lines.append(
            f"Study type ({band} confidence): {info.get('study_type_label')} / "
            f"{info.get('study_type_label_formal')}"
        )
    sections = parse_structured_abstract(abstract or "")
    present = [role for role, text in (sections or {}).items() if text]
    if present:
        lines.append("Structured abstract sections: " + ", ".join(present))
    return "\n".join(lines)


def _inject_app_copy(content: Dict[str, Any]) -> Dict[str, Any]:
    """Fill empty prose; own the fallback sentence so the model does not author it."""
    out = dict(content or {})
    missing = [str(x) for x in (out.get("not_reported_fields") or []) if x]
    for field in PROSE_FIELDS:
        if field == "what_it_does_not_show":
            continue
        val = str(out.get(field) or "").strip()
        if not val:
            out[field] = NOT_REPORTED
            if field not in missing:
                missing.append(field)
        else:
            out[field] = val
    boundary = str(out.get("what_it_does_not_show") or "").strip()
    if not boundary or boundary == NOT_REPORTED:
        out["what_it_does_not_show"] = FALLBACK_WHAT_IT_DOES_NOT_SHOW
    else:
        out["what_it_does_not_show"] = boundary
    glossary = out.get("glossary") or []
    cleaned = []
    for entry in glossary:
        if not isinstance(entry, dict):
            continue
        term = str(entry.get("term") or "").strip()
        definition = str(entry.get("definition") or "").strip()
        if term and definition:
            cleaned.append({"term": term, "definition": definition})
    out["glossary"] = cleaned[:12]
    out["not_reported_fields"] = missing
    return out


def _cache_valid(row: Dict[str, Any], abstract_hash: str) -> bool:
    return (
        row.get("abstract_hash") == abstract_hash
        and row.get("prompt_version") == READER_PROMPT_VERSION
        and row.get("verifier_version") == CURRENT_VERIFIER_VERSION
    )


def _pack(
    *,
    article_id: str,
    source: str,
    audience: str,
    cached: bool,
    content: Dict[str, Any],
    verification: Dict[str, Any],
    provider: Optional[str],
    model: Optional[str] = None,
) -> Dict[str, Any]:
    body = {
        "article_id": article_id,
        "source": source,
        "audience": audience,
        "cached": cached,
        "content": content,
        "verification": verification,
        "label": LABEL,
        "disclaimer": DISCLAIMER,
        "provider": provider,
        "prompt_version": READER_PROMPT_VERSION,
    }
    if model:
        body["model"] = model
    return body


def lookup_explanation(db, article: Dict[str, Any], audience: str) -> Optional[Dict[str, Any]]:
    """Cache-only. Never generates. None on miss or stale hash/version."""
    audience = "high_school" if audience == "high_school" else "general_reader"
    abstract = (article.get("abstract") or "").strip()
    row = db.get_reader_explanation(
        article.get("article_id") or "",
        article.get("source") or "",
        audience,
    )
    if not row:
        return None
    if not _cache_valid(row, reader_facts.abstract_hash(abstract)):
        return None
    return _pack(
        article_id=row["article_id"],
        source=row["source"],
        audience=row["audience"],
        cached=True,
        content=row["content"],
        verification=row["verification"],
        provider=row.get("provider"),
        model=row.get("model"),
    )


def explain_article(
    db,
    article: Dict[str, Any],
    audience: str,
    *,
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """Generate or return a cached explanation for one library article."""
    audience = "high_school" if audience == "high_school" else "general_reader"
    article_id = article.get("article_id") or ""
    source = article.get("source") or ""
    title = article.get("title") or ""
    abstract = (article.get("abstract") or "").strip()
    if not abstract:
        raise LLMError("This abstract is empty, so it cannot be explained.")
    if len(abstract) < MIN_ABSTRACT_LEN:
        raise LLMError(
            "This abstract is too short to explain (a few sentences are needed)."
        )

    digest = reader_facts.abstract_hash(abstract)
    if not force_regenerate:
        row = db.get_reader_explanation(article_id, source, audience)
        if row and _cache_valid(row, digest):
            return _pack(
                article_id=article_id,
                source=source,
                audience=audience,
                cached=True,
                content=row["content"],
                verification=row["verification"],
                provider=row.get("provider"),
                model=row.get("model"),
            )

    if not is_configured():
        raise LLMUnavailable(
            "AI is unavailable (not configured). Open Account → AI study aid and choose "
            "Built-in study aid or Cloud API key. Extractive key points still work."
        )

    facts = facts_block(title, abstract)

    def _call():
        return generate_reader_explanation(
            title=title,
            abstract=abstract,
            audience=audience,
            source=source,
            article_id=article_id,
            facts_block=facts,
        )

    raw = run_with_ephemeral_builtin(_call)
    selected = raw.get("provider") or llm_provider()
    content = _inject_app_copy({
        key: value for key, value in raw.items() if key not in ("method", "provider")
    })
    verification = verify(abstract, title, content)
    verification["checked_at"] = datetime.now(timezone.utc).isoformat()
    model = _active_model()
    try:
        db.upsert_reader_explanation(
            article_id=article_id,
            source=source,
            audience=audience,
            abstract_hash=digest,
            prompt_version=READER_PROMPT_VERSION,
            content=content,
            verification=verification,
            provider=selected,
            model=model,
            verifier_version=CURRENT_VERIFIER_VERSION,
        )
    except Exception:
        logger.exception("reader explanation cache write failed")
    return _pack(
        article_id=article_id,
        source=source,
        audience=audience,
        cached=False,
        content=content,
        verification=verification,
        provider=selected,
        model=model,
    )
