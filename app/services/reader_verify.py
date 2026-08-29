"""
Deterministic verification of Reader Mode explanations (no LLM, no I/O).

Compares generated content against facts extracted from the source abstract
(reader_facts) and emits a VerificationReport-shaped dict. Every check is a
conservative warning; nothing here can establish correctness, so the status
vocabulary is deliberately limited to:

    no_automatic_issues | needs_review | verification_incomplete

Severity is "info" | "warning" only — never "error" — and the function never
raises: a check that blows up is marked skipped and the rest continue.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from app.services import reader_facts
from app.services.study_type import classify_study_type
from app.services.summarize import parse_structured_abstract, split_sentences

CURRENT_VERIFIER_VERSION = "v1"

STATUS_NO_ISSUES = "no_automatic_issues"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_INCOMPLETE = "verification_incomplete"

TARGET_BAND = "grades 8-10"
READABILITY_CAVEAT = "Readability scores estimate sentence and word complexity only."

# Prose sections compared against the abstract (glossary terms are definitional
# and are excluded from all prose joins, including readability).
PROSE_FIELDS = (
    "plain_summary",
    "question_asked",
    "who_was_studied",
    "what_was_found",
    "what_it_does_not_show",
    "stated_limitations",
)
FINDINGS_FIELDS = ("what_was_found", "plain_summary")

# Always required in the explanation; percent/duration are salience-filtered
# to the abstract's findings/conclusion sentences.
ALWAYS_REQUIRED_KINDS = ("sample_size", "p_value", "ci", "dose")
SALIENT_MAX = 3

CHECK_ORDER = (
    "numeric_detail",
    "study_design",
    "negation",
    "uncertainty_language",
    "entity_retention",
    "readability",
)

MAX_MESSAGE_LEN = 300


def _field(generated: Dict, name: str) -> str:
    value = (generated or {}).get(name)
    return str(value) if value else ""


def _prose(generated: Dict, fields: tuple) -> str:
    return " ".join(_field(generated, name) for name in fields).strip()


def _conclusion_text(abstract: str) -> str:
    """Findings/conclusion sentences of the abstract.

    Structured abstracts use their findings + conclusion sections; otherwise
    the last two sentences stand in.
    """
    sections = parse_structured_abstract(abstract or "")
    if sections:
        text = " ".join(
            sections.get(role, "") for role in ("findings", "conclusion") if sections.get(role)
        )
        if text.strip():
            return text
    sentences = split_sentences(abstract or "")
    if sentences:
        return " ".join(sentences[-2:])
    return abstract or ""


def _check_outcome(
    check_id: str, outcome: str, message: str, details: Optional[Dict] = None
) -> Dict:
    severity = "warning" if outcome == "warn" else "info"
    return {
        "check_id": check_id,
        "outcome": outcome,
        "severity": severity,
        "message": (message or "")[:MAX_MESSAGE_LEN],
        "details": details or {},
    }


def _same_measure(required: Dict, candidate: Dict) -> bool:
    """Value-normalised match within a unit class.

    43-minute equals 43 minutes; percentages match only percentages. A bare
    generated number satisfies a sample_size token (n= is notation, not
    meaning); dose/p_value/ci tokens must keep their unit class.
    """
    if required.get("value") != candidate.get("value"):
        return False
    if required.get("unit") == "%" or candidate.get("unit") == "%":
        return required.get("unit") == "%" and candidate.get("unit") == "%"
    if required["kind"] == "sample_size":
        return candidate["kind"] in ("sample_size", "bare_number")
    req_unit = required.get("unit")
    cand_unit = candidate.get("unit")
    return bool(req_unit) and bool(cand_unit) and req_unit == cand_unit


def _check_numeric_detail(ctx: Dict) -> Dict:
    abstract = ctx["source_abstract"]
    gen_tokens = reader_facts.extract_numbers(ctx["prose"])
    src_tokens = reader_facts.extract_numbers(abstract)

    required = [t for t in src_tokens if t["kind"] in ALWAYS_REQUIRED_KINDS]
    salient = [
        t
        for t in reader_facts.extract_numbers(ctx["conclusion_text"])
        if t["kind"] in ("percent", "duration")
    ][:SALIENT_MAX]

    seen: set = set()
    all_required: List[Dict] = []
    for tok in required + salient:
        key = (tok["kind"], tok["value"], tok.get("unit"), tok["surface"])
        if key not in seen:
            seen.add(key)
            all_required.append(tok)

    missing = [
        t["surface"]
        for t in all_required
        if not any(_same_measure(t, gen) for gen in gen_tokens)
    ]
    details = {
        "missing": missing,
        "checked": len(all_required),
        "bare_numbers": [t["surface"] for t in src_tokens if t["kind"] == "bare_number"],
        "years": [t["surface"] for t in src_tokens if t["kind"] == "year"],
    }
    if missing:
        count = len(missing)
        if count == 1:
            message = "The abstract mentions 1 number that does not appear in the explanation."
        else:
            message = (
                f"The abstract mentions {count} numbers that do not appear in the explanation."
            )
        return _check_outcome("numeric_detail", "warn", message, details)
    return _check_outcome(
        "numeric_detail",
        "pass",
        "Every key number from the abstract appears in the explanation.",
        details,
    )


def _check_study_design(ctx: Dict) -> Dict:
    st = classify_study_type(ctx["title"], ctx["source_abstract"])
    band = st.get("confidence_band")
    if band not in ("high", "medium") or st.get("study_type") == "unclear":
        return _check_outcome(
            "study_design",
            "skipped",
            "Study type was not determined confidently enough to check.",
            {"study_type": st.get("study_type"), "confidence_band": band},
        )
    label = str(st.get("study_type_label") or "")
    formal = str(st.get("study_type_label_formal") or "")
    haystack = ctx["prose"].casefold()
    if (label and label.casefold() in haystack) or (formal and formal.casefold() in haystack):
        return _check_outcome(
            "study_design",
            "pass",
            "The explanation reflects the study design.",
            {"label": label, "label_formal": formal},
        )
    return _check_outcome(
        "study_design",
        "warn",
        "The abstract suggests a specific study design, but the explanation does not say "
        "what kind of study it was.",
        {"label": label, "label_formal": formal},
    )


def _check_negation(ctx: Dict) -> Dict:
    src_cues = reader_facts.extract_cues(ctx["conclusion_text"])["negation"]
    gen_cues = reader_facts.extract_cues(ctx["findings_text"])["negation"]
    details = {"source_cues": src_cues, "generated_cues": gen_cues}
    if not src_cues:
        return _check_outcome(
            "negation",
            "pass",
            "No negative findings wording in the abstract's conclusion.",
            details,
        )
    if reader_facts.count_cues(ctx["findings_text"], "negation") == 0:
        return _check_outcome(
            "negation",
            "warn",
            "The abstract reports a negative finding, but the explanation does not mention one.",
            details,
        )
    return _check_outcome(
        "negation",
        "pass",
        "Negative findings from the abstract are reflected in the explanation.",
        details,
    )


def _check_uncertainty_language(ctx: Dict) -> Dict:
    src_cues = reader_facts.extract_cues(ctx["conclusion_text"])["uncertainty"]
    gen_cues = reader_facts.extract_cues(ctx["findings_text"])["uncertainty"]
    if not src_cues:
        return _check_outcome(
            "uncertainty_language",
            "pass",
            "No hedged wording in the abstract's conclusion to preserve.",
            {"source_cues": src_cues, "generated_cues": gen_cues},
        )
    reasons: List[str] = []
    term: Optional[str] = None
    if not gen_cues:
        reasons.append("lost")
    causal = reader_facts.extract_cues(ctx["findings_text"])["causal"]
    if causal:
        reasons.append("upgrade")
        term = causal[0]

    details = {
        "reasons": reasons,
        "term": term,
        "source_cues": src_cues,
        "generated_cues": gen_cues,
    }
    if "lost" in reasons and "upgrade" in reasons:
        message = (
            "The explanation both drops the abstract's cautious wording and uses stronger "
            f"language ({term})."
        )
    elif "lost" in reasons:
        message = "The abstract's cautious wording is not reflected in the explanation."
    elif "upgrade" in reasons:
        message = f"The explanation uses stronger language than the abstract ({term})."
    else:
        return _check_outcome(
            "uncertainty_language",
            "pass",
            "Cautious wording from the abstract was kept.",
            details,
        )
    return _check_outcome("uncertainty_language", "warn", message, details)


def _check_entity_retention(ctx: Dict) -> Dict:
    candidates = reader_facts.extract_pico_candidates(ctx["source_abstract"])
    if len(candidates) < 2:
        return _check_outcome(
            "entity_retention",
            "skipped",
            "Not enough distinct study details to check.",
            {"candidates": candidates},
        )
    haystack = ctx["prose"].casefold()
    missing = [c for c in candidates if c.casefold() not in haystack]
    details = {"missing": missing, "candidates": len(candidates)}
    if len(missing) * 2 > len(candidates):
        return _check_outcome(
            "entity_retention",
            "warn",
            "The explanation leaves out most of the study details from the abstract.",
            details,
        )
    return _check_outcome(
        "entity_retention",
        "pass",
        "The key study details from the abstract appear in the explanation.",
        details,
    )


def _count_syllables(word: str) -> int:
    """Vowel-group heuristic with silent trailing e, "le" endings, minimum 1."""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    if w.endswith("le") and w[-3] not in "aeiouy":
        return max(1, len(re.findall(r"[aeiouy]+", w[:-2])) + 1)
    if w.endswith("e"):
        w = w[:-1]
    return max(1, len(re.findall(r"[aeiouy]+", w)))


_WORD_SPLIT_RE = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


def _flesch_kincaid_grade(text: str) -> Optional[float]:
    sentences = split_sentences(text or "")
    words = _WORD_SPLIT_RE.findall(text or "")
    if not sentences or not words:
        return None
    syllables = sum(_count_syllables(w) for w in words)
    return (
        0.39 * (len(words) / len(sentences))
        + 11.8 * (syllables / len(words))
        - 15.59
    )


def _readability_report(prose: str) -> Dict:
    grade = _flesch_kincaid_grade(prose)
    if grade is None:
        return {
            "flesch_kincaid_grade": None,
            "dale_chall_score": None,
            "target_band": TARGET_BAND,
            "within_target_band": None,
            "caveat": READABILITY_CAVEAT,
        }
    return {
        "flesch_kincaid_grade": grade,
        "dale_chall_score": None,
        "target_band": TARGET_BAND,
        "within_target_band": 8 <= grade <= 10,
        "caveat": READABILITY_CAVEAT,
    }


def _check_readability(ctx: Dict) -> Dict:
    grade = _flesch_kincaid_grade(ctx["readability_prose"])
    if grade is None:
        return _check_outcome("readability", "skipped", "No generated text to measure.", {})
    return _check_outcome(
        "readability",
        "pass",
        f"Estimated reading level: grade {grade:.1f} (target: grades 8-10).",
        {"flesch_kincaid_grade": grade},
    )


def _derive_status(checks: List[Dict]) -> str:
    if any(c["outcome"] == "warn" for c in checks):
        return STATUS_NEEDS_REVIEW
    if any(
        c["outcome"] == "skipped" and c["check_id"] != "readability"
        for c in checks
    ):
        return STATUS_INCOMPLETE
    return STATUS_NO_ISSUES


def _context(source_abstract: str, title: str, generated: Dict) -> Dict:
    generated = dict(generated or {})
    prose = _prose(generated, PROSE_FIELDS)
    return {
        "source_abstract": source_abstract or "",
        "title": title or "",
        "prose": prose,
        "readability_prose": prose,
        "findings_text": _prose(generated, FINDINGS_FIELDS),
        "conclusion_text": _conclusion_text(source_abstract or ""),
    }


def _run_check(check_id: str, fn, ctx: Dict) -> Dict:
    try:
        return fn(ctx)
    except Exception:
        return _check_outcome(check_id, "skipped", "This check could not run.", {})


def verify(source_abstract: str, title: str, generated: dict) -> Dict:
    """Run the six checks and return a VerificationReport-shaped dict.

    Never raises: a failing check is skipped, and if verification itself
    cannot run the report comes back with every check skipped and status
    verification_incomplete. No checked_at stamp — orchestration adds time.
    """
    try:
        ctx = _context(source_abstract, title, generated)
        checks = [
            _run_check("numeric_detail", _check_numeric_detail, ctx),
            _run_check("study_design", _check_study_design, ctx),
            _run_check("negation", _check_negation, ctx),
            _run_check("uncertainty_language", _check_uncertainty_language, ctx),
            _run_check("entity_retention", _check_entity_retention, ctx),
            _run_check("readability", _check_readability, ctx),
        ]
        return {
            "status": _derive_status(checks),
            "checks": checks,
            "readability": _readability_report(ctx["readability_prose"]),
            "verifier_version": CURRENT_VERIFIER_VERSION,
        }
    except Exception:
        skipped = [_check_outcome(cid, "skipped", "This check could not run.", {}) for cid in CHECK_ORDER]
        return {
            "status": STATUS_INCOMPLETE,
            "checks": skipped,
            "readability": _readability_report(""),
            "verifier_version": CURRENT_VERIFIER_VERSION,
        }
