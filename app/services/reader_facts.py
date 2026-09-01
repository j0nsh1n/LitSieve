"""
Deterministic fact extraction from abstracts for Reader Mode (no LLM, no I/O).

Pure string functions only: numeric tokens, cue phrases, entity candidates.
PICO keyword lists are deliberately duplicated from
app.services.embeddings.PICOExtractor — importing that module would pull in
numpy/sklearn/faiss/torch, and this module must stay loadable with no model.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Dict, List, Optional

from app.services.summarize import split_sentences

# Tightened cue lists (vs the plan): bare "not"/"without"/"could"/"limited",
# "shows that", "demonstrates that", "confirms", "leads to" and bare "will"
# are deliberately absent — they warn on almost every abstract.
NEGATION_CUES = (
    "did not", "does not", "no difference", "no significant",
    "failed to", "unable to", "did not differ", "non-significant",
    "nonsignificant", "no effect", "no evidence", "not associated",
    "not significantly",
)
UNCERTAINTY_CUES = (
    "may", "might", "suggests", "appears to", "associated with",
    "potential", "unclear", "further research", "further study",
    "preliminary", "possibly", "consistent with", "limited evidence",
)
CAUSAL_UPGRADES = (
    "causes", "caused", "causing", "proves", "proven",
    "guarantees", "will cause", "will increase", "will reduce",
    "will make",
)

# Hedging as a plain-language writer actually produces it. Precision qualifiers
# ("about", "roughly", "on average", "estimated") are deliberately NOT here: they
# describe a number's exactness, not confidence in a claim, and including them
# meant any explanation quoting "about 43 minutes" satisfied the hedge-loss rule
# while flatly asserting a causal claim (audit 1.3). Used ONLY on the
# generated side of the uncertainty "loss" test: the narrow UNCERTAINTY_CUES
# list above is for spotting caution in the source, and requiring the same
# vocabulary back out warned on well-hedged explanations that simply chose
# different words ("cannot establish" instead of "may").
HEDGE_MARKERS = (
    "cannot establish", "cannot show", "does not prove", "do not prove",
    "does not show", "did not find", "not prove", "no clear", "not clear",
    "tended to", "tend to", "seems", "seemed",
    "not enough", "cannot tell", "cannot say",
    # Real epistemic hedges a plain-language writer reaches for. UNCERTAINTY_CUES
    # only knows "further research"/"further study"; a writer is as likely to say
    # "more research is needed".
    "more research", "more study", "further work", "not certain", "hard to say",
    "rather than proof", "not proof", "only shows",
    "non-significant", "not significant", "smaller effect", "may not",
    "might not", "unable to say", "does not mean", "not by itself",
)

# Copied from PICOExtractor (app/services/embeddings.py) on purpose — see the
# module docstring. Keep in sync by hand; duplicate is intentional.
POPULATION_KEYWORDS = [
    'patients', 'participants', 'subjects', 'adults', 'children',
    'elderly', 'men', 'women', 'cohort', 'sample',
]

INTERVENTION_KEYWORDS = [
    'treatment', 'therapy', 'intervention', 'drug', 'medication',
    'procedure', 'surgery', 'training', 'program',
]

COMPARISON_KEYWORDS = [
    'versus', 'vs', 'compared', 'placebo', 'control', 'standard care',
]

OUTCOME_KEYWORDS = [
    'outcome', 'mortality', 'survival', 'efficacy', 'effectiveness',
    'improvement', 'reduction', 'increase', 'change',
]

# Ordered single pass; earlier alternatives win, so a "95% CI" span is one ci
# token (never a percent + bare numbers) and bare numbers only catch what no
# stronger kind claimed.
_NUMBER_TOKEN_RE = re.compile(
    r"""
    (?P<p_value>[Pp]\s*[=<>≤≥]\s*0?\.\d+)
    | (?P<ci>\d+\s*%\s*CI:?\s*-?\d+(?:\.\d+)?\s*(?:to|[-–,])\s*-?\d+(?:\.\d+)?|\[\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*\])
    | (?P<duration>\d+(?:\.\d+)?\s*-?\s*(?P<dunit>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|wks?|months?|mos?|years?|yrs?)\b)
    | (?P<sample_size>[nN]\s*=\s*\d[\d,]*)
    | (?P<dose>\d+(?:\.\d+)?\s*-?\s*(?P<dosunit>mg|kg|mcg|µg|μg|ml|mmHg|IU|g)\b)
    | (?P<percent>\d+(?:\.\d+)?\s*%)
    | (?P<year>\b(?:19|20)\d{2}\b)
    | (?P<bare_number>\b\d+(?:\.\d+)?\b)
    """,
    re.VERBOSE | re.IGNORECASE,
)

_P_VALUE_TAIL_RE = re.compile(r"(0?\.\d+)\s*$")
_CAP_SPAN_RE = re.compile(r"\b[A-Z][A-Za-z0-9-]+(?:\s+[A-Z][A-Za-z0-9-]+)+\b")


def normalise(text: str) -> str:
    """Strip, collapse internal whitespace, NFKC, casefold.

    Punctuation is kept on purpose: a hash that ignored punctuation would
    miss meaningful abstract edits.
    """
    collapsed = re.sub(r"\s+", " ", (text or "")).strip()
    return unicodedata.normalize("NFKC", collapsed).casefold()


def abstract_hash(text: str) -> str:
    """sha256 hex digest of normalise(text)."""
    return hashlib.sha256(normalise(text).encode("utf-8")).hexdigest()


def _first_number(surface: str) -> Optional[float]:
    m = re.search(r"-?\d[\d,]*\.?\d*", surface)
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def extract_numbers(text: str) -> List[Dict]:
    """Typed numeric tokens: {kind, value: float, unit, surface}.

    Comparison is value-normalised within a unit class (43-minute equals
    43 minutes); percentages only ever match percentages.
    """
    tokens: List[Dict] = []
    for m in _NUMBER_TOKEN_RE.finditer(text or ""):
        if m.group("p_value") is not None:
            kind = "p_value"
        elif m.group("ci") is not None:
            kind = "ci"
        elif m.group("duration") is not None:
            kind = "duration"
        elif m.group("sample_size") is not None:
            kind = "sample_size"
        elif m.group("dose") is not None:
            kind = "dose"
        elif m.group("percent") is not None:
            kind = "percent"
        elif m.group("year") is not None:
            kind = "year"
        else:
            kind = "bare_number"
        surface = m.group(kind).strip()
        unit: Optional[str] = None
        value: Optional[float] = None
        if kind == "p_value":
            tail = _P_VALUE_TAIL_RE.search(surface)
            value = float(tail.group(1)) if tail else None
            unit = "p"
        elif kind == "ci":
            value = _first_number(surface)
            unit = "ci"
        elif kind == "duration":
            value = _first_number(surface)
            unit = _DURATION_UNITS.get(
                m.group("dunit").lower().rstrip("s"), m.group("dunit").lower().rstrip("s")
            )
        elif kind == "sample_size":
            digits = surface.split("=", 1)[1].strip().replace(",", "")
            value = float(int(digits)) if digits else None
            unit = "n"
        elif kind == "dose":
            value = _first_number(surface)
            unit = m.group("dosunit").lower()
        elif kind == "percent":
            value = _first_number(surface)
            unit = "%"
        elif kind == "year":
            value = float(surface)
            unit = "year"
        else:  # bare_number
            value = float(surface)
        if value is None:
            continue
        tokens.append({
            "kind": kind,
            "value": value,
            "unit": unit,
            "surface": surface,
        })
    return tokens


_CUE_PATTERNS: Dict[str, tuple] = {
    "negation": tuple(
        (cue, re.compile(r"\b" + re.escape(normalise(cue)) + r"\b"))
        for cue in NEGATION_CUES
    ),
    "uncertainty": tuple(
        (cue, re.compile(r"\b" + re.escape(cue) + r"\b"))
        for cue in UNCERTAINTY_CUES
    ),
    "causal": tuple(
        (cue, re.compile(r"\b" + re.escape(cue) + r"\b"))
        for cue in CAUSAL_UPGRADES
    ),
}


def extract_cues(text: str) -> Dict[str, List[str]]:
    """Cue phrases present in text, word-boundary matched on casefolded text.

    Returns {negation: [...], uncertainty: [...], causal: [...]} listing each
    distinct cue found. Substring matching is forbidden ("may" must not match
    "mayor").
    """
    folded = normalise(text or "")
    out: Dict[str, List[str]] = {"negation": [], "uncertainty": [], "causal": []}
    for kind, patterns in _CUE_PATTERNS.items():
        for cue, pattern in patterns:
            if pattern.search(folded):
                out[kind].append(cue)
    return out


def count_cues(text: str, kind: str) -> int:
    """Total number of cue occurrences of one kind (negation|uncertainty|causal)."""
    folded = normalise(text or "")
    return sum(
        len(pattern.findall(folded))
        for _, pattern in _CUE_PATTERNS.get(kind, ())
    )


def extract_pico_candidates(abstract: str) -> List[str]:
    """Candidate entities (max 8) for the retention check.

    Per non-empty PICO bucket take the first matching sentence; from those
    sentences keep capitalised multi-word named spans (leading "The"/"A"
    stripped). Deduplicated (casefold), cap 8.
    """
    sentences = split_sentences(abstract or "")
    chosen: List[str] = []
    for keywords in (POPULATION_KEYWORDS, INTERVENTION_KEYWORDS,
                     COMPARISON_KEYWORDS, OUTCOME_KEYWORDS):
        for sent in sentences:
            low = (sent or "").lower()
            if any(kw in low for kw in keywords):
                if sent not in chosen:
                    chosen.append(sent)
                break

    candidates: List[str] = []
    seen: set = set()
    for sent in chosen:
        for span in _CAP_SPAN_RE.findall(sent):
            # Drop leading "The"/"A"/… so "The Sleep Education Program" is a
            # usable name, not junk. Keep multi-word proper spans only.
            words = span.split()
            while words and words[0].casefold() in _STOP_STARTERS:
                words.pop(0)
            if len(words) < 2:
                continue
            cleaned = " ".join(words)
            if _is_junk_candidate(cleaned):
                continue
            key = cleaned.casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(cleaned)
        if len(candidates) >= 8:
            break
    return candidates[:8]


# Abbreviated duration units map onto their spelled-out form so "69 min" in an
# abstract matches "69 minutes" in an explanation.
_DURATION_UNITS = {
    "sec": "second", "second": "second",
    "min": "minute", "minute": "minute",
    "hr": "hour", "hour": "hour",
    "day": "day",
    "wk": "week", "week": "week",
    "mo": "month", "month": "month",
    "yr": "year", "year": "year",
}


def has_hedging(text: str) -> bool:
    """True when text hedges at all, by either vocabulary.

    Deliberately generous: this backs a *warning* about lost caution, so a
    false negative (staying quiet) is cheaper than nagging a careful writer.
    """
    low = normalise(text or "")
    if not low:
        return False
    for _, pattern in _CUE_PATTERNS["uncertainty"]:
        if pattern.search(low):
            return True
    return any(marker in low for marker in HEDGE_MARKERS)


# Structured-abstract headers and sentence-initial fragments are not entities.
# Before this filter the corpus produced candidates like "MATERIALS AND METHODS",
# "Between T0" and "The GLM", which no plain-language explanation would repeat,
# so entity_retention warned on faithful explanations.
_SECTION_HEADERS = frozenset({
    "background", "objective", "objectives", "aim", "aims", "purpose",
    "methods", "method", "materials and methods", "results", "result",
    "conclusion", "conclusions", "findings", "design", "setting",
    "participants", "interventions", "intervention", "measurements",
    "background and objectives", "main outcome measures", "importance",
})
_STOP_STARTERS = frozenset({
    "the", "this", "these", "those", "a", "an", "we", "our", "their", "there",
    "between", "after", "before", "across", "during", "when", "while", "both",
    "for", "of", "in", "at", "on", "from", "given", "however", "although",
})


def _is_junk_candidate(span: str) -> bool:
    """True for section headers, stop-word-led fragments and bare short words."""
    text = " ".join((span or "").split())
    if not text:
        return True
    low = text.casefold()
    if low in _SECTION_HEADERS:
        return True
    # ALL-CAPS runs are structured-abstract headers, not named entities.
    if text.isupper() and len(text) > 3:
        return True
    words = low.split()
    if words and words[0] in _STOP_STARTERS:
        return True
    if len(words) == 1 and len(low) < 5:
        return True
    return False
