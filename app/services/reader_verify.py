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

# Bump whenever check behaviour changes. Stale rows are served as current
# otherwise: v1 verdicts came from rules that warned on 8/8 faithful
# explanations, and a cached "Some details may need checking" chip would
# outlive the rules that produced it (audit 3.1).
CURRENT_VERIFIER_VERSION = "v2"

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

# Sections the MODEL authored. what_it_does_not_show is excluded on purpose: it
# is app copy (reader_mode._inject_app_copy supplies the fallback sentence, which
# itself contains "cannot establish"). Counting it as hedging made the
# uncertainty-loss rule vacuous — every explanation looked hedged because the app
# had hedged for it.
# Sections where the model makes claims about the paper. what_it_does_not_show is
# excluded from both the hedge and negation scans: the app injects its fallback
# there, and even model-authored boundary text is negative and hedged by
# definition, so counting it made both rules satisfiable for free.
CLAIM_FIELDS = (
    "plain_summary",
    "question_asked",
    "who_was_studied",
    "what_was_found",
    "stated_limitations",
)
HEDGE_SCAN_FIELDS = (
    "plain_summary",
    "question_asked",
    "who_was_studied",
    "what_was_found",
    "stated_limitations",
)

# Always required in the explanation; percent/duration are salience-filtered
# to the abstract's findings/conclusion sentences.
# Sample sizes and doses are few per abstract and define what was studied, so
# every one is required. p-values and confidence intervals come in bunches — an
# abstract with six p-values would otherwise force a plain-language explanation
# to recite all six, which warned on faithful explanations in the evaluation
# corpus. Only the first few are required; the rest are reported, not demanded.
ALWAYS_REQUIRED_KINDS = ("sample_size", "dose")
CAPPED_REQUIRED_KINDS = ("p_value", "ci")
# One. A results section routinely carries a headline statistic plus heterogeneity,
# subgroup and publication-bias diagnostics; demanding even two of them warned on
# explanations that correctly reported the headline and dropped the diagnostics.
CAPPED_REQUIRED_MAX = 1
# Quantities required from the conclusion sentence(s).
HEADLINE_MAX = 4
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


def _headline_text(abstract: str) -> str:
    """The abstract's conclusion only — where the paper states its headline.

    Separate from _conclusion_text (findings + conclusion) because salience by
    document order picked diagnostic statistics out of the results section and
    let the actual effect size be dropped without a warning (audit 1.1).
    """
    sections = parse_structured_abstract(abstract or "")
    if sections and (sections.get("conclusion") or "").strip():
        return sections["conclusion"]
    sentences = split_sentences(abstract or "")
    if sentences:
        return " ".join(sentences[-2:])
    return abstract or ""


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
    conclusion_tokens = reader_facts.extract_numbers(ctx["conclusion_text"])
    # Every quantity the conclusion states is required, including bare numbers
    # ("fell by 2.3 points"), which no required set covered before. A conclusion
    # carries one or two figures, so this is a short list — unlike the results
    # section, which is why the pool is the conclusion and not findings.
    # bare_number and year are excluded on purpose. A conclusion's bare digits are
    # as often a trial-registration id or a URL fragment as an effect size — the
    # caffeine fixture's conclusion carries "58864" from a registration link — and
    # _same_measure cannot match a unitless token anyway, so requiring them would
    # warn unconditionally. Consequence, stated rather than hidden: a headline
    # expressed as a bare number ("fell by 2.3 points") is still not required.
    headline_tokens = [
        t
        for t in reader_facts.extract_numbers(ctx["headline_text"])
        if t["kind"] not in ("bare_number", "year")
        and not (t["kind"] == "percent" and t["value"] in (90.0, 95.0, 99.0))
    ][:HEADLINE_MAX]
    required += headline_tokens
    for kind in CAPPED_REQUIRED_KINDS:
        required += [t for t in conclusion_tokens if t["kind"] == kind][:CAPPED_REQUIRED_MAX]
    salient = [
        t
        for t in conclusion_tokens
        if t["kind"] in ("percent", "duration")
        # 95% / 99% here are the confidence convention, not a finding.
        and not (t["kind"] == "percent" and t["value"] in (90.0, 95.0, 99.0))
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


# How a plain-language explanation actually names each design. Regex fragments,
# matched word-boundary against the generated prose. Keyed by study_type id from
# app/services/study_type.py.
DESIGN_SYNONYMS = {
    "synthesis": (
        r"meta[-\s]?analys[ie]s", r"systematic review", r"scoping review",
        r"umbrella review", r"pooled (?:analysis|studies|results)",
        r"combin\w+[^.]{0,40}stud(?:y|ies)", r"review of (?:the )?studies",
        r"pooled", r"earlier studies",
    ),
    "trial": (
        r"randomi[sz]ed", r"\brct\b", r"controlled trial", r"clinical trial",
        r"placebo", r"double[-\s]?blind", r"quasi[-\s]?experimental",
        r"put into groups by chance", r"assigned (?:at random|by chance)",
        r"control group", r"intervention (?:study|trial)", r"experiment",
    ),
    "observational": (
        r"observational", r"cohort", r"longitudinal", r"case[-\s]?control",
        r"followed (?:them )?over time", r"prospective", r"retrospective",
        r"pre[-\s]?post", r"single[-\s]?arm",
    ),
    "survey": (
        r"cross[-\s]?sectional", r"survey", r"questionnaire", r"snapshot",
        r"at one point in time", r"measured everyone once", r"comparative study",
    ),
    "qualitative": (
        r"qualitative", r"interview", r"focus group", r"open[-\s]?ended",
        r"content analysis", r"thematic",
    ),
    "methods": (r"protocol", r"study design paper", r"methods paper", r"pilot"),
    "narrative_review": (r"review", r"overview", r"summar[iy]", r"commentary"),
    "opinion": (r"commentary", r"editorial", r"opinion", r"perspective", r"argues"),
}


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
    # Match on how a person would actually name the design, not on the app's
    # display labels. Matching "Likely a review paper" / "Review / synthesis"
    # verbatim warned on essentially every explanation, because no plain-language
    # writer produces those strings — the evaluation corpus warned 10/12 on this
    # check alone before the synonym sets were added.
    synonyms = DESIGN_SYNONYMS.get(str(st.get("study_type") or ""), ())
    named = any(re.search(r"\b" + syn + r"\b", haystack) for syn in synonyms)
    if named or (label and label.casefold() in haystack) or (formal and formal.casefold() in haystack):
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
    # A negative result is stated wherever the result is stated. Scanning only
    # the conclusion missed "did not differ" and "non-significant" sitting in the
    # results of an unstructured abstract, so a lossy explanation passed.
    src_cues = reader_facts.extract_cues(ctx["source_abstract"])["negation"]
    gen_cues = reader_facts.extract_cues(ctx["claim_prose"])["negation"]
    details = {"source_cues": src_cues, "generated_cues": gen_cues}
    if not src_cues:
        return _check_outcome(
            "negation",
            "pass",
            "No negative findings wording in the abstract's conclusion.",
            details,
        )
    # Not ctx["prose"]: that includes what_it_does_not_show, which is a boundary
    # statement and therefore always phrased negatively ("does not show ..."), so
    # any explanation satisfied this rule for free while silently dropping the
    # abstract's actual negative finding (audit 1.2).
    if reader_facts.count_cues(ctx["claim_prose"], "negation") == 0:
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
    # Hedging anywhere in the explanation counts, not just in the findings
    # section, and any recognised hedge counts — not only the narrow source
    # vocabulary. Before this the check warned on explanations that hedged
    # correctly using different words.
    if not reader_facts.has_hedging(ctx["hedge_prose"]):
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
    # Three is the floor for a meaningful signal. With one or two named spans,
    # "most are missing" is noise — an explanation may legitimately not repeat
    # an instrument name or a database it was found in.
    if len(candidates) < 3:
        return _check_outcome(
            "entity_retention",
            "skipped",
            "Not enough distinct study details to check.",
            {"candidates": candidates},
        )
    haystack = ctx["prose"].casefold()
    missing = [c for c in candidates if c.casefold() not in haystack]
    details = {"missing": missing, "candidates": len(candidates)}
    # Warn only when NOTHING named in the abstract survived. A plain-language
    # explanation drops instrument and database names on purpose; dropping every
    # one is the signal that it may not be about this paper at all.
    if len(missing) < len(candidates):
        return _check_outcome(
            "entity_retention",
            "pass",
            "The key study details from the abstract appear in the explanation.",
            details,
        )
    return _check_outcome(
        "entity_retention",
        "warn",
        "None of the specific names from the abstract appear in the explanation.",
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
    # readability and entity_retention skip routinely on short or name-free
    # abstracts. Only a check that actually failed should downgrade the report,
    # or every clean explanation reads as "checks could not run fully".
    if any(
        c["outcome"] == "skipped"
        and c["check_id"] not in ("readability", "entity_retention")
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
        "headline_text": _headline_text(source_abstract or ""),
        "hedge_prose": _prose(generated, HEDGE_SCAN_FIELDS),
        "claim_prose": _prose(generated, CLAIM_FIELDS),
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
