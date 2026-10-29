#!/usr/bin/env python3
"""Offline check: can Laya sort each question's top 30 into relevance groups?

Dev split only. This tool never reads test-split categories into a score.
The held-out test split stays for a later, single scoring pass.

Groups, from the seven label categories:

    direct_answer                         -> answers
    mechanism_or_implementation           -> how_why
    experience_or_context, background     -> context
    related_subject, incidental           -> different
    unclassified                          -> not_sorted

``not_sorted`` is also what we predict when a group's probability is below
its dev-set threshold. A low score never becomes ``different``.

F2 combination rule (yes/no answers treated as independent):

    Asked actor (A), outcome (O), and setting (G = population, period, or place):
        A and O and G        -> answers
        A and O, not G       -> how_why
        G, but not both A and O -> context
        anything else       -> different
    A and O, setting not asked:
        both yes -> answers; exactly one -> context; neither -> different
    One concept plus setting, outcome or actor not asked:
        both yes -> answers; setting only -> context; otherwise -> different
    Only one question asked:
        yes -> context; no -> different
    A slot with no phrase is not asked, and how_why stays empty unless A, O, and G
    were all asked.

Concept-coverage baseline: share of the non-empty actor, outcome, and population
phrases whose words all appear in the title and abstract. Bands on that share
are cut on the dev split.

    python tools/eval_laya_groups.py run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.services.question_concepts import QuestionConcepts, question_concepts

GROUPS: Tuple[str, ...] = ("answers", "how_why", "context", "different")
GROUP_SORT = {"answers": 0, "how_why": 1, "context": 2, "not_sorted": 3, "different": 4}
CATEGORY_TO_GROUP = {
    "direct_answer": "answers",
    "mechanism_or_implementation": "how_why",
    "experience_or_context": "context",
    "background": "context",
    "related_subject": "different",
    "incidental": "different",
    "unclassified": "not_sorted",
}
THRESHOLD_GRID = (0.35, 0.50, 0.65, 0.80)
COVERAGE_GRID = (0.34, 0.51, 0.67, 1.01)
MAX_TEXT = 4000
EXPERIMENT_BUDGET = 54
LAYA_URL = "http://127.0.0.1:7880"
CALL_TIMEOUT_S = 180.0
HARM_CAP = 0.05

_WORD = re.compile(
    r"U\.S\.?"
    r"|u\.s\.?"
    r"|[^\W\d_]+(?:['’\-][^\W\d_]+)*['’]?"
    r"|[0-9]+",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

Caller = Callable[[str, Dict[str, str], Sequence[str]], List[dict]]


def category_to_group(category: str) -> Optional[str]:
    """Map one label category to a relevance group. Unknown categories return None."""
    return CATEGORY_TO_GROUP.get((category or "").strip())


def _clip(p: float) -> float:
    value = float(p)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def cell_group(flags: Mapping[str, bool]) -> str:
    """Map one boolean outcome of the F2 questions to a group.

    See the module docstring for the full rule. ``flags`` contains only the
    questions that were asked.
    """
    keys = set(flags)

    def yes(name: str) -> bool:
        return bool(flags.get(name))

    if keys == {"A", "O", "G"}:
        if yes("A") and yes("O") and yes("G"):
            return "answers"
        if yes("A") and yes("O"):
            return "how_why"
        if yes("G"):
            return "context"
        return "different"
    if keys == {"A", "O"}:
        if yes("A") and yes("O"):
            return "answers"
        if yes("A") or yes("O"):
            return "context"
        return "different"
    if keys == {"A", "G"} or keys == {"O", "G"}:
        first = "A" if "A" in keys else "O"
        if yes(first) and yes("G"):
            return "answers"
        if yes("G"):
            return "context"
        return "different"
    if len(keys) == 1:
        return "context" if yes(next(iter(keys))) else "different"
    return "different"


def combine_f2(
    p_actor: Optional[float],
    p_outcome: Optional[float],
    p_setting: Optional[float],
) -> Dict[str, float]:
    """Turn up to three P(yes) values into group probabilities that sum to 1.

    None means that question was not asked. An empty concept list returns zeros.
    """
    given: Dict[str, float] = {}
    if p_actor is not None:
        given["A"] = _clip(p_actor)
    if p_outcome is not None:
        given["O"] = _clip(p_outcome)
    if p_setting is not None:
        given["G"] = _clip(p_setting)
    totals = {group: 0.0 for group in GROUPS}
    if not given:
        return totals
    names = list(given)
    for bits in itertools.product((False, True), repeat=len(names)):
        flags = dict(zip(names, bits))
        cell = 1.0
        for name, bit in flags.items():
            p = given[name]
            cell *= p if bit else (1.0 - p)
        totals[cell_group(flags)] += cell
    return totals


def apply_thresholds(probs: Mapping[str, float], thresholds: Mapping[str, float]) -> str:
    """Pick the most probable group. Below that group's threshold, return not_sorted.

    A paper is never moved to ``different`` just because the winning group was
    too uncertain. Ties prefer answers, then how_why, then context, then different.
    """
    best: Optional[str] = None
    best_key: Optional[Tuple[float, int]] = None
    for index, group in enumerate(GROUPS):
        p = float(probs.get(group, 0.0))
        key = (p, -index)
        if best_key is None or key > best_key:
            best_key = key
            best = group
    if best is None:
        return "not_sorted"
    if float(probs.get(best, 0.0)) < float(thresholds.get(best, 1.0)):
        return "not_sorted"
    return best


def average_probs(rows: Sequence[Mapping[str, float]]) -> Dict[str, float]:
    """Mean probability per group. Missing keys count as 0."""
    if not rows:
        return {group: 0.0 for group in GROUPS}
    out = {}
    n = float(len(rows))
    for group in GROUPS:
        out[group] = sum(float(row.get(group, 0.0)) for row in rows) / n
    return out


def _classified(pairs: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    return [(gold, pred) for gold, pred in pairs if gold in GROUPS]


def coverage(pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    rows = _classified(pairs)
    if not rows:
        return None
    return sum(1 for _, pred in rows if pred != "not_sorted") / len(rows)


def accuracy(pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    rows = [(gold, pred) for gold, pred in _classified(pairs) if pred != "not_sorted"]
    if not rows:
        return None
    return sum(1 for gold, pred in rows if gold == pred) / len(rows)


def class_f1(pairs: Sequence[Tuple[str, str]], group: str) -> Optional[float]:
    """F1 on rows whose prediction is a real group.

    Gold ``not_sorted`` (unclassified) is already outside ``pairs`` via
    ``_classified``. If every gold row for this group was left unsorted, and
    the group was never predicted, F1 is 0 when the class exists and None when
    the slice has no such gold at all.
    """
    classified = _classified(pairs)
    support = sum(1 for gold, _ in classified if gold == group)
    sorted_rows = [(gold, pred) for gold, pred in classified if pred != "not_sorted"]
    tp = sum(1 for gold, pred in sorted_rows if gold == group and pred == group)
    fp = sum(1 for gold, pred in sorted_rows if pred == group and gold != group)
    fn = sum(1 for gold, pred in sorted_rows if gold == group and pred != group)
    if tp + fp + fn == 0:
        if support == 0:
            return None
        return 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def macro_f1(pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    scores = [class_f1(pairs, group) for group in GROUPS]
    used = [score for score in scores if score is not None]
    if not used:
        return None
    return sum(used) / len(used)


def harmful_rate(pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    """Share of gold answers and how_why put in ``different``.

    ``not_sorted`` is not this error. None when the slice has no such gold.
    """
    good = [(gold, pred) for gold, pred in pairs if gold in {"answers", "how_why"}]
    if not good:
        return None
    return sum(1 for _, pred in good if pred == "different") / len(good)


def harmful_counts(pairs: Sequence[Tuple[str, str]]) -> Tuple[int, int]:
    good = [pred for gold, pred in pairs if gold in {"answers", "how_why"}]
    return sum(1 for pred in good if pred == "different"), len(good)


@dataclass(frozen=True)
class Tuned:
    thresholds: Dict[str, float]
    macro_f1: Optional[float]
    accuracy: Optional[float]
    coverage: Optional[float]
    harmful: Optional[float]
    eligible: bool


def _rank_key(tuned: Tuned) -> Tuple[float, ...]:
    return (
        1.0 if tuned.eligible else 0.0,
        tuned.macro_f1 if tuned.macro_f1 is not None else -1.0,
        -(tuned.harmful if tuned.harmful is not None else 1.0),
        tuned.coverage if tuned.coverage is not None else -1.0,
        tuned.accuracy if tuned.accuracy is not None else -1.0,
    )


def tune_thresholds(items: Sequence[Mapping[str, Any]]) -> Tuned:
    """Search per-group thresholds on these dev items.

    ``items`` are ``{"gold": group, "probs": {group: p}}``. The objective is
    macro-F1 among thresholds whose harmful-error rate is at most 5%. If none
    qualify, keep the lowest harmful rate, then the best macro-F1.
    """
    best: Optional[Tuned] = None
    for combo in itertools.product(THRESHOLD_GRID, repeat=len(GROUPS)):
        thresholds = dict(zip(GROUPS, combo))
        pairs = [
            (str(item["gold"]), apply_thresholds(item["probs"], thresholds))
            for item in items
        ]
        harm = harmful_rate(pairs)
        tuned = Tuned(
            thresholds=thresholds,
            macro_f1=macro_f1(pairs),
            accuracy=accuracy(pairs),
            coverage=coverage(pairs),
            harmful=harm,
            eligible=harm is not None and harm <= HARM_CAP + 1e-12,
        )
        if best is None or _rank_key(tuned) > _rank_key(best):
            best = tuned
    if best is None:
        return Tuned({group: 0.5 for group in GROUPS}, None, None, None, None, False)
    return best


def content_words(text: str) -> List[str]:
    """Words for the coverage baseline. Dots and possessives are folded away."""
    out: List[str] = []
    for raw in _WORD.findall(text or ""):
        token = raw.casefold().replace(".", "")
        for suffix in ("'s", "\u2019s", "'", "\u2019"):
            if token.endswith(suffix) and len(token) > len(suffix) + 1:
                token = token[: -len(suffix)]
                break
        for part in token.split("-"):
            if part:
                out.append(part)
    return out


def _phrase_present(phrases: Sequence[str], hay: set[str]) -> Optional[bool]:
    if not phrases:
        return None
    needed = content_words(" ".join(phrases))
    if not needed:
        return None
    return all(word in hay for word in needed)


def concept_coverage(concepts: QuestionConcepts, title: str, abstract: str) -> float:
    """Share of non-empty actor, outcome, and population phrases found in the text.

    A phrase counts only when every one of its words appears. Period and place
    are not part of this baseline. An empty concept list scores 0.
    """
    hay = set(content_words(f"{title}\n{abstract}"))
    slots: List[float] = []
    for slot in (concepts.actor, concepts.outcome, concepts.population):
        present = _phrase_present(slot, hay)
        if present is None:
            continue
        slots.append(1.0 if present else 0.0)
    if not slots:
        return 0.0
    return sum(slots) / len(slots)


def group_from_coverage(score: float, cuts: Mapping[str, float], floor: str) -> str:
    """Map a coverage share to a group. ``cuts`` are answers >= how_why >= context."""
    if score >= float(cuts["answers"]):
        return "answers"
    if score >= float(cuts["how_why"]):
        return "how_why"
    if score >= float(cuts["context"]):
        return "context"
    return floor


def tune_coverage(items: Sequence[Mapping[str, Any]]) -> Tuple[Tuned, str, Dict[str, float]]:
    """Cut the coverage share on dev. The floor is either not_sorted or different."""
    best: Optional[Tuple[Tuned, str, Dict[str, float]]] = None
    levels = COVERAGE_GRID
    for floor in ("not_sorted", "different"):
        for triple in itertools.product(levels, repeat=3):
            answers_t, how_t, context_t = triple
            if not (answers_t >= how_t >= context_t):
                continue
            cuts = {"answers": answers_t, "how_why": how_t, "context": context_t}
            pairs = [
                (str(item["gold"]), group_from_coverage(float(item["score"]), cuts, floor))
                for item in items
            ]
            harm = harmful_rate(pairs)
            tuned = Tuned(
                thresholds=dict(cuts),
                macro_f1=macro_f1(pairs),
                accuracy=accuracy(pairs),
                coverage=coverage(pairs),
                harmful=harm,
                eligible=harm is not None and harm <= HARM_CAP + 1e-12,
            )
            if best is None or _rank_key(tuned) > _rank_key(best[0]):
                best = (tuned, floor, cuts)
    assert best is not None
    return best


def first_sentences(text: str, n: int = 2) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    parts = [part for part in _SENTENCE.split(cleaned) if part]
    return " ".join(parts[:n])


def paper_text(title: str, abstract: str, variant: str) -> str:
    title_s = " ".join((title or "").split()) or "(no title)"
    abstract_s = " ".join((abstract or "").split())
    if variant == "title":
        body = title_s
    elif variant == "two":
        lead = first_sentences(abstract_s, 2)
        body = f"{title_s}\n\n{lead}" if lead else title_s
    else:
        body = f"{title_s}\n\n{abstract_s}" if abstract_s else title_s
    return body[:MAX_TEXT]


def join_phrases(phrases: Sequence[str]) -> str:
    parts = [part.strip() for part in phrases if part and str(part).strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " or " + parts[-1]


def setting_phrases(concepts: QuestionConcepts) -> Tuple[str, ...]:
    return tuple(concepts.population) + tuple(concepts.period) + tuple(concepts.place)


def f2_slots(concepts: QuestionConcepts) -> List[Tuple[str, str]]:
    slots: List[Tuple[str, str]] = []
    actor = join_phrases(concepts.actor)
    outcome = join_phrases(concepts.outcome)
    setting = join_phrases(setting_phrases(concepts))
    if actor:
        slots.append(("A", actor))
    if outcome:
        slots.append(("O", outcome))
    if setting:
        slots.append(("G", setting))
    return slots


def _lead(question: str, concepts: QuestionConcepts, mode: str) -> str:
    if mode == "raw":
        return f'A student asked "{question}".'
    actor = join_phrases(concepts.actor) or "the subject they named"
    outcome = join_phrases(concepts.outcome) or "the outcome they named"
    setting = join_phrases(setting_phrases(concepts)) or "the people, time, or place they named"
    return (
        f"A student is asking about {actor}. "
        f"The outcome they care about is {outcome}. "
        f"The people, time, or place are {setting}."
    )


def f1_options(concepts: QuestionConcepts, phrasing: int) -> Dict[str, str]:
    actor = join_phrases(concepts.actor) or "the subject"
    outcome = join_phrases(concepts.outcome) or "the outcome"
    setting = join_phrases(setting_phrases(concepts)) or "the setting"
    if phrasing == 0:
        return {
            "answers": "It answers the question with evidence about the relationship.",
            "how_why": "It explains how or why the relationship works, rather than reporting the result.",
            "context": "It is background or context for the people, the period, the place, or the wider subject.",
            "different": "It answers a different question.",
        }
    if phrasing == 1:
        return {
            "answers": f"Direct evidence on whether {actor} changes {outcome} for {setting}.",
            "how_why": f"How {actor} brings about {outcome}. This is the mechanism, not the result itself.",
            "context": (
                f"Scene-setting on {actor} or {setting} that does not answer the effect on {outcome}."
            ),
            "different": f"A different subject from {actor} and {outcome}.",
        }
    return {
        "answers": "A student could cite this paper as an answer.",
        "how_why": "A student could cite this paper to explain the mechanism.",
        "context": "A student could cite this paper only to set the scene.",
        "different": "A student who cited this paper would be off the question.",
    }


def f3_options(phrasing: int) -> Dict[str, str]:
    tables = (
        {
            "analysis": "An analysis of this relationship.",
            "how": "How it works.",
            "background": "Background or context.",
            "different": "A different question.",
        },
        {
            "analysis": "It reports the effect the question asks about.",
            "how": "It explains the process behind that effect.",
            "background": "It describes the setting around the topic.",
            "different": "It is about something else.",
        },
        {
            "analysis": "It measures or reviews the relationship itself.",
            "how": "It accounts for the mechanism or the implementation.",
            "background": "It gives history, experience, or surrounding facts.",
            "different": "It is not the student's question.",
        },
    )
    return dict(tables[phrasing])


F3_TO_GROUP = {
    "analysis": "answers",
    "how": "how_why",
    "background": "context",
    "different": "different",
}


def f2_options(target: str, phrasing: int) -> Dict[str, str]:
    if phrasing == 0:
        return {
            "yes": f"Yes. This paper is about {target}.",
            "no": f"No. This paper is not about {target}.",
        }
    if phrasing == 1:
        return {
            "yes": f"Yes. The paper's main subject includes {target}.",
            "no": f"No. The paper's main subject does not include {target}.",
        }
    return {
        "yes": f"Yes. The paper discusses {target}.",
        "no": f"No. The paper discusses a subject other than {target}.",
    }


def instruction_for(question: str, concepts: QuestionConcepts, mode: str, form: str) -> str:
    lead = _lead(question, concepts, mode)
    if form == "f2":
        return lead + " Decide whether the statement in the options is true of this paper."
    if form == "f3":
        return lead + " Choose the role of this paper for that question."
    return lead + " Choose the group that best fits this paper."


def probs_from_choice(row: Mapping[str, Any], options: Mapping[str, str]) -> Dict[str, float]:
    raw = row.get("probabilities") if isinstance(row, Mapping) else None
    probs = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if key in options and isinstance(value, (int, float)):
                probs[str(key)] = _clip(float(value))
    if not probs and row.get("choice") in options:
        probs[str(row["choice"])] = _clip(float(row.get("p") or 0.0))
    return probs


def to_group_probs(form: str, probs: Mapping[str, float]) -> Dict[str, float]:
    if form == "f3":
        out = {group: 0.0 for group in GROUPS}
        for key, value in probs.items():
            group = F3_TO_GROUP.get(key)
            if group:
                out[group] += float(value)
        return out
    out = {group: float(probs.get(group, 0.0)) for group in GROUPS}
    return out


@dataclass(frozen=True)
class Spec:
    form: str
    inp: str
    mode: str
    phrasing: str

    @property
    def sid(self) -> str:
        return f"{self.form}-{self.inp}-{self.mode}-{self.phrasing}"

    @property
    def phrasing_index(self) -> Optional[int]:
        if self.phrasing.startswith("p") and self.phrasing[1:].isdigit():
            return int(self.phrasing[1:])
        return None


def fit_states(states: Sequence[str], limit: int = 180_000) -> List[str]:
    """Keep a 30-paper batch under the sidecar's body cap."""
    texts = [text[:MAX_TEXT] for text in states]
    raw = sum(len(text) for text in texts)
    if raw <= limit:
        return texts
    per = max(200, limit // max(1, len(texts)))
    return [text[:per] for text in texts]


def _cache_key(instructions: str, options: Mapping[str, str], states: Sequence[str]) -> str:
    payload = json.dumps(
        {"instructions": instructions, "options": options, "states": list(states)},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def post_choice(
    url: str,
    instructions: str,
    options: Mapping[str, str],
    states: Sequence[str],
    timeout: float = CALL_TIMEOUT_S,
) -> Tuple[List[dict], float]:
    """POST one batch. Returns (results, wall_ms). Raises on a bad response."""
    body = json.dumps(
        {
            "instructions": instructions,
            "options": dict(options),
            "states": list(states),
            "state_key": "text",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/choice",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc
    wall_ms = (time.perf_counter() - started) * 1000.0
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != len(states):
        raise RuntimeError("malformed choice response")
    for row in results:
        if not isinstance(row, dict) or row.get("choice") not in options:
            raise RuntimeError("malformed choice row")
    return results, wall_ms


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self.failures = 0
        self.stopped = False
        self.reason = ""

    def room(self, cost: int) -> bool:
        return (not self.stopped) and self.used + cost <= self.limit


def load_cache(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "entries": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("entries", {})
    return data


def save_cache(path: Path, cache: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache), encoding="utf-8")


def cached_choice(
    budget: Budget,
    cache: Dict[str, Any],
    cache_path: Path,
    url: str,
    instructions: str,
    options: Mapping[str, str],
    states: Sequence[str],
    log: List[dict],
    label: str,
) -> Optional[List[dict]]:
    """One batch, cache first. Two failures in a row stop the run."""
    if budget.stopped:
        return None
    key = _cache_key(instructions, options, states)
    hit = cache["entries"].get(key)
    if isinstance(hit, dict) and isinstance(hit.get("results"), list):
        log.append({"label": label, "cached": True, "n": len(states), "ms": hit.get("ms")})
        return hit["results"]
    if budget.used + 1 > budget.limit:
        budget.stopped = True
        budget.reason = "budget"
        return None
    last_error = "unknown"
    for _attempt in range(2):
        try:
            results, wall_ms = post_choice(url, instructions, options, states)
        except RuntimeError as exc:
            last_error = str(exc)
            budget.failures += 1
            print(f"laya fail {budget.failures} {label}: {last_error}", flush=True)
            if budget.failures >= 2:
                budget.stopped = True
                budget.reason = last_error
                return None
            continue
        budget.failures = 0
        budget.used += 1
        cache["entries"][key] = {"results": results, "ms": round(wall_ms, 1), "n": len(states)}
        save_cache(cache_path, cache)
        log.append({"label": label, "cached": False, "n": len(states), "ms": round(wall_ms, 1)})
        print(
            f"call {budget.used}/{budget.limit} {label} n={len(states)} {wall_ms:.0f} ms",
            flush=True,
        )
        return results
    budget.stopped = True
    budget.reason = last_error
    return None


def _phrasing_index(spec: Spec) -> int:
    return spec.phrasing_index if spec.phrasing_index is not None else 0


def run_spec_on_question(
    spec: Spec,
    question: Mapping[str, Any],
    concepts: QuestionConcepts,
    texts: Sequence[str],
    choose: Caller,
) -> Optional[List[dict]]:
    """Return one ``{probs, yes}`` row per paper, or None if a call failed.

    ``yes`` is present for F2 and holds P(yes) per asked slot. Averaging
    phrasings uses those values, then ``combine_f2``, because the combination
    is not linear.
    """
    phrasing = _phrasing_index(spec)
    if spec.form == "f2":
        yes_cols: Dict[str, List[float]] = {}
        for slot, target in f2_slots(concepts):
            options = f2_options(target, phrasing)
            rows = choose(
                instruction_for(str(question["text"]), concepts, spec.mode, "f2"),
                options,
                texts,
            )
            if rows is None:
                return None
            yes_cols[slot] = []
            for row in rows:
                probs = probs_from_choice(row, options)
                yes_cols[slot].append(float(probs.get("yes", 0.0)))
        combined = []
        for index in range(len(texts)):
            yes = {
                slot: values[index]
                for slot, values in yes_cols.items()
            }
            combined.append({
                "probs": combine_f2(
                    yes.get("A"),
                    yes.get("O"),
                    yes.get("G"),
                ),
                "yes": yes,
            })
        return combined
    if spec.form == "f3":
        options = f3_options(phrasing)
    else:
        options = f1_options(concepts, phrasing)
    rows = choose(
        instruction_for(str(question["text"]), concepts, spec.mode, spec.form),
        options,
        texts,
    )
    if rows is None:
        return None
    return [{"probs": to_group_probs(spec.form, probs_from_choice(row, options))} for row in rows]


def spec_cost(questions: Sequence[Mapping[str, Any]], spec: Spec) -> int:
    if spec.phrasing == "avg":
        return 0
    if spec.form != "f2":
        return len(questions)
    return sum(len(f2_slots(question_concepts(str(q["text"])))) for q in questions)


def load_questions(path: Path) -> List[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["questions"])


def load_results(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_label_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def dev_gold_for(rows: Sequence[Mapping[str, str]]) -> Dict[str, str]:
    """Dev-split primary labels only. Test categories are dropped here."""
    by_labeller: Dict[str, List[Mapping[str, str]]] = {}
    for row in rows:
        name = (row.get("labeller") or "owner").strip() or "owner"
        by_labeller.setdefault(name, []).append(row)
    if not by_labeller:
        return {}
    chosen = "owner" if "owner" in by_labeller else sorted(by_labeller)[0]
    gold: Dict[str, str] = {}
    for row in by_labeller[chosen]:
        if (row.get("split") or "").strip().lower() != "dev":
            continue
        key = (row.get("key") or "").strip()
        group = category_to_group(str(row.get("category") or ""))
        if key and group:
            gold[key] = group
    return gold


def load_abstracts(corpus: Path, qid: str) -> Tuple[Dict[Tuple[str, str], dict], Dict[str, dict]]:
    by_pair: Dict[Tuple[str, str], dict] = {}
    by_doi: Dict[str, dict] = {}
    qdir = corpus / qid
    if not qdir.is_dir():
        return by_pair, by_doi
    for path in sorted(qdir.glob("*.json")):
        if path.name in {"report.json", "manifest.json"}:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        for article in payload:
            if not isinstance(article, dict):
                continue
            source = str(article.get("source") or "")
            aid = str(article.get("article_id") or "")
            if source and aid:
                by_pair[(source, aid)] = article
            doi = str(article.get("doi") or "").strip().lower()
            if doi:
                by_doi[doi] = article
    return by_pair, by_doi


def hit_text_fields(
    hit: Mapping[str, Any],
    by_pair: Mapping[Tuple[str, str], Mapping[str, Any]],
    by_doi: Mapping[str, Mapping[str, Any]],
) -> Tuple[str, str]:
    article = by_pair.get((str(hit.get("source") or ""), str(hit.get("article_id") or "")))
    if article is None:
        article = by_doi.get(str(hit.get("doi") or "").strip().lower())
    title = str(hit.get("title") or "")
    abstract = ""
    if article is not None:
        abstract = str(article.get("abstract") or "")
        if not title:
            title = str(article.get("title") or "")
    return title, abstract


def support_counts(golds: Iterable[str]) -> Dict[str, int]:
    counts = {group: 0 for group in (*GROUPS, "not_sorted")}
    for gold in golds:
        if gold in counts:
            counts[gold] += 1
    return counts


def pairs_for(
    records: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, float],
    qid: Optional[str] = None,
) -> List[Tuple[str, str]]:
    pairs = []
    for record in records:
        if qid is not None and record["qid"] != qid:
            continue
        gold = record.get("gold")
        if gold not in GROUPS and gold != "not_sorted":
            continue
        pairs.append((str(gold), apply_thresholds(record["probs"], thresholds)))
    return pairs


def metric_row(
    sid: str,
    records: Sequence[Mapping[str, Any]],
    tuned: Tuned,
    qid: Optional[str] = None,
) -> Dict[str, Any]:
    pairs = pairs_for(records, tuned.thresholds, qid)
    harm_n, good_n = harmful_counts(pairs)
    return {
        "setting": sid,
        "question": qid or "OVERALL",
        "n": len(_classified(pairs)),
        "coverage": coverage(pairs),
        "accuracy": accuracy(pairs),
        "macro_f1": macro_f1(pairs),
        "harmful": harmful_rate(pairs),
        "harm_n": harm_n,
        "good_n": good_n,
        "eligible": (harmful_rate(pairs) is not None and harmful_rate(pairs) <= HARM_CAP + 1e-12)
        if qid is None
        else tuned.eligible,
        "thresholds": tuned.thresholds,
    }


def add_average_records(
    store: Dict[str, List[dict]],
) -> None:
    """Average phrasings of the same formulation, input, and question mode.

    F1 and F3 average group probabilities. F2 averages P(yes) on each slot,
    then applies ``combine_f2``.
    """
    grouped: Dict[Tuple[str, str, str], List[str]] = {}
    for sid in list(store):
        spec = parse_sid(sid)
        if spec is None or spec.phrasing == "avg":
            continue
        grouped.setdefault((spec.form, spec.inp, spec.mode), []).append(sid)
    for (form, inp, mode), sids in grouped.items():
        phrased = [sid for sid in sids if sid.endswith(("-p0", "-p1", "-p2"))]
        if len(phrased) < 2:
            continue
        by_key: Dict[Tuple[str, str], List[dict]] = {}
        meta: Dict[Tuple[str, str], dict] = {}
        for sid in phrased:
            for record in store[sid]:
                ident = (record["qid"], record["key"])
                by_key.setdefault(ident, []).append(record)
                meta[ident] = record
        if any(len(rows) != len(phrased) for rows in by_key.values()):
            continue
        averaged = []
        for ident, rows in by_key.items():
            base = meta[ident]
            if form == "f2" and all(isinstance(row.get("yes"), dict) for row in rows):
                slots = sorted({slot for row in rows for slot in row["yes"]})
                yes = {
                    slot: sum(float(row["yes"].get(slot, 0.0)) for row in rows) / len(rows)
                    for slot in slots
                }
                probs = combine_f2(yes.get("A"), yes.get("O"), yes.get("G"))
                averaged.append({**base, "probs": probs, "yes": yes})
            else:
                averaged.append({**base, "probs": average_probs([row["probs"] for row in rows])})
        store[f"{form}-{inp}-{mode}-avg"] = averaged


def parse_sid(sid: str) -> Optional[Spec]:
    parts = sid.split("-")
    if len(parts) != 4:
        return None
    return Spec(*parts)


def _eval_search():
    spec = importlib.util.spec_from_file_location("eval_search", REPO_ROOT / "tools" / "eval_search.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules["eval_search"] = module
    spec.loader.exec_module(module)
    return module


def reorder_hits(hits: Sequence[Mapping[str, Any]], groups: Mapping[str, str]) -> List[dict]:
    def sort_key(hit: Mapping[str, Any]) -> Tuple[int, int]:
        group = groups.get(str(hit.get("key") or ""), "not_sorted")
        return (GROUP_SORT.get(group, 3), int(hit.get("rank") or 0))

    ordered = sorted(hits, key=sort_key)
    return [{**dict(hit), "rank": index} for index, hit in enumerate(ordered, start=1)]


def groups_from_records(
    records: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, float],
) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for record in records:
        out.setdefault(record["qid"], {})[record["key"]] = apply_thresholds(
            record["probs"], thresholds
        )
    return out


def ranking_table(
    scorer: Any,
    questions: Sequence[Mapping[str, Any]],
    label_rows: Mapping[str, Sequence[Mapping[str, str]]],
    group_maps: Mapping[str, Mapping[str, str]],
) -> Dict[str, Any]:
    per = []
    for qrow in questions:
        qid = str(qrow["id"])
        hits = reorder_hits(qrow["rankings"]["lexical_on"], group_maps.get(qid, {}))
        fake = dict(qrow)
        fake["rankings"] = {"lexical_on": hits}
        per.append(scorer.score_question(fake, label_rows.get(qid, []), "dev", "lexical_on"))
    return {"questions": per, "ndcg@10": _mean([row.get("ndcg@10") for row in per]),
            "relevant@10": _mean([row.get("relevant@10") for row in per])}


def _mean(values: Iterable[Any]) -> Optional[float]:
    nums = [float(value) for value in values if isinstance(value, (int, float))]
    if not nums:
        return None
    return sum(nums) / len(nums)


def _fmt(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _fmt_cuts(thresholds: Mapping[str, float]) -> str:
    return " ".join(f"{group[0]}:{thresholds[group]:.2f}" for group in GROUPS if group in thresholds)


def render_report(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Laya relevance groups on the dev split",
        "",
        "Dev labels only. Test-split categories were not scored. "
        "Thresholds were chosen on these same dev rows, so the figures are fit to a small set.",
        "",
        "## Call budget",
        "",
        payload["budget_note"],
        "",
        "## Support",
        "",
        payload["support_note"],
        "",
        "## Full table",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | rel@10 | d ndcg | d rel | thresholds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["overall_rows"]:
        if row.get("good_n") in ("", None):
            harm_cell = ""
        else:
            harm_cell = f"{row.get('harm_n')}/{row.get('good_n')}"
        lines.append(
            "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm_cell} | "
            "{ndcg} | {rel} | {dndcg} | {drel} | {cuts} |".format(
                setting=row["setting"],
                n=row["n"],
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                harm_cell=harm_cell,
                ndcg=_fmt(row.get("ndcg@10")),
                rel=_fmt(row.get("relevant@10"), 2),
                dndcg=_fmt(row.get("d_ndcg")),
                drel=_fmt(row.get("d_rel"), 2),
                cuts=row.get("cuts", ""),
            )
        )
    lines.extend([
        "",
        "## Per question",
        "",
        "| setting | question | n | coverage | accuracy | macro-F1 | harmful |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in payload["question_rows"]:
        lines.append(
            "| {setting} | {question} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} |".format(
                setting=row["setting"],
                question=row["question"],
                n=row["n"],
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
            )
        )
    lines.extend(["", "## Top 5 at a harmful-error rate of 5% or less", ""])
    if payload["top5"]:
        for index, row in enumerate(payload["top5"], start=1):
            lines.append(
                f"{index}. `{row['setting']}` macro-F1 {_fmt(row.get('macro_f1'))}, "
                f"harmful {_fmt(row.get('harmful'))}, coverage {_fmt(row.get('coverage'))}, "
                f"ndcg@10 {_fmt(row.get('ndcg@10'))} ({_fmt(row.get('d_ndcg'))} vs today's order)."
            )
    else:
        lines.append("No setting stayed at or under a 5% harmful-error rate.")
    lines.extend([
        "",
        "## Concept-coverage baseline",
        "",
        payload["baseline_note"],
        "",
        "## Latency",
        "",
        payload["latency_note"],
        "",
        "## F2 rule",
        "",
        "Yes/no probabilities are treated as independent. "
        "Actor plus outcome plus setting is answers. "
        "Actor plus outcome without the setting is how_why. "
        "The setting without both actor and outcome is context. "
        "The remaining cells are different. "
        "A missing concept is not asked. "
        "how_why is only used when all three were asked. "
        "Phrasing averages use the mean P(yes) for each F2 question, then this rule. "
        "F1 and F3 average the group probabilities.",
        "",
        "## Recommendation",
        "",
        payload["recommendation"],
        "",
    ])
    return "\n".join(lines)


def recommend(payload: Mapping[str, Any]) -> str:
    top = payload["top5"]
    base = payload["baseline_row"]
    support = payload["support"]
    n = payload["n_dev_scored"]
    sentences = [
        f"The dev slice inside the top 30 is {n} labelled papers "
        f"({support['answers']} answers, {support['how_why']} how_why, "
        f"{support['context']} context, {support['different']} different).",
        "how_why has two papers, so that class moves macro-F1 a lot and should not be read as stable.",
    ]
    if not top:
        sentences.append(
            "No Laya setting kept the harmful-error rate at 5% or less, "
            "so none is good enough to show students."
        )
    else:
        best = top[0]
        base_f1 = base.get("macro_f1")
        best_f1 = best.get("macro_f1")
        beats = (
            best_f1 is not None
            and base_f1 is not None
            and best_f1 > base_f1
            and (best.get("harmful") or 1) <= HARM_CAP
        )
        sentences.append(
            f"The strongest eligible setting is {best['setting']} "
            f"with macro-F1 {_fmt(best_f1)} and harmful-error {_fmt(best.get('harmful'))} "
            f"at coverage {_fmt(best.get('coverage'))}."
        )
        sentences.append(
            f"Concept coverage, cut on the same dev rows, has macro-F1 {_fmt(base_f1)} "
            f"and harmful-error {_fmt(base.get('harmful'))}."
        )
        if beats and (best.get("coverage") or 0) >= 0.5 and (best_f1 or 0) >= 0.55:
            sentences.append(
                "That is better than the lexical baseline on this dev slice, "
                "but the same rows chose the thresholds, and the test split is still untouched."
            )
            sentences.append(
                "I would not put the groups in front of students yet. "
                "A later single test-split score, on a larger label set, has to clear the same harmful-error cap."
            )
        else:
            sentences.append(
                "I would not put these groups in front of students. "
                "The eligible settings are weak, sparse, or both, on a dev set that also chose the thresholds."
            )
    sentences.append(
        "Reordering the top 30 by group uses today's score inside each group. "
        "The ndcg@10 and relevant@10 columns are `tools/eval_search.py` on `--split dev`."
    )
    return " ".join(sentences[:8])


def laya_unit_state() -> str:
    try:
        completed = subprocess.run(
            ["systemctl", "--user", "is-active", "litsieve-laya.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error:{exc}"
    return (completed.stdout or completed.stderr or "").strip() or "unknown"


def wait_for_idle() -> bool:
    """Wait until the sidecar process exits. Do not hit /health. That would wake it."""
    print("waiting for litsieve-laya.service to go inactive", flush=True)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = laya_unit_state()
        print(f"laya unit {state}", flush=True)
        if state == "inactive":
            return True
        time.sleep(15)
    return False


def measure_latency(
    url: str,
    instructions: str,
    options: Mapping[str, str],
    states: Sequence[str],
) -> Dict[str, Any]:
    idle = wait_for_idle()
    note: Dict[str, Any] = {"idle": idle, "n": len(states)}
    if not idle:
        note["cold_ms"] = None
        note["warm_ms"] = []
        note["detail"] = "The shared sidecar did not idle out within 15 minutes, so cold latency was not measured."
        return note
    try:
        _rows, cold_ms = post_choice(url, instructions, options, states)
    except RuntimeError as exc:
        note["cold_ms"] = None
        note["warm_ms"] = []
        note["detail"] = f"Cold batch failed: {exc}"
        return note
    warm: List[float] = []
    for _ in range(5):
        try:
            _rows, wall_ms = post_choice(url, instructions, options, states)
        except RuntimeError as exc:
            note["cold_ms"] = round(cold_ms, 1)
            note["warm_ms"] = [round(value, 1) for value in warm]
            note["detail"] = f"Warm batch failed after {len(warm)} runs: {exc}"
            return note
        warm.append(wall_ms)
    ordered = sorted(warm)
    median = ordered[len(ordered) // 2]
    note["cold_ms"] = round(cold_ms, 1)
    note["warm_ms"] = [round(value, 1) for value in warm]
    note["warm_median_ms"] = round(median, 1)
    note["detail"] = (
        f"Cold wall time after an idle exit was {note['cold_ms']:.0f} ms "
        f"for one batch of {len(states)}. "
        f"Five warm runs were {', '.join(f'{value:.0f}' for value in note['warm_ms'])} ms. "
        f"The median warm run was {note['warm_median_ms']:.0f} ms."
    )
    return note


def _best_tuned(store: Mapping[str, List[dict]], sids: Sequence[str]) -> Tuple[str, Tuned]:
    best_sid = sids[0]
    best: Optional[Tuned] = None
    for sid in sids:
        items = [
            {"gold": row["gold"], "probs": row["probs"]}
            for row in store[sid]
            if row.get("gold") in GROUPS
        ]
        tuned = tune_thresholds(items)
        if best is None or _rank_key(tuned) > _rank_key(best):
            best = tuned
            best_sid = sid
    assert best is not None
    return best_sid, best


def execute(args: argparse.Namespace) -> int:
    questions = load_questions(Path(args.questions))
    results = load_results(Path(args.results))
    by_id = {str(row["id"]): row for row in results["questions"]}
    corpus = Path(args.corpus).expanduser()
    labels_dir = Path(args.labels).expanduser()
    cache_path = Path(args.cache).expanduser()
    cache = load_cache(cache_path)
    budget = Budget(int(args.budget))
    log: List[dict] = []
    prepared = []
    label_rows: Dict[str, List[dict]] = {}
    for question in questions:
        qid = str(question["id"])
        qrow = by_id[qid]
        hits = list(qrow["rankings"]["lexical_on"])
        by_pair, by_doi = load_abstracts(corpus, qid)
        papers = []
        missing = 0
        for hit in hits:
            title, abstract = hit_text_fields(hit, by_pair, by_doi)
            if not abstract:
                missing += 1
            papers.append({
                "key": str(hit.get("key") or ""),
                "title": title,
                "abstract": abstract,
                "rank": hit.get("rank"),
            })
        gold = dev_gold_for(load_label_rows(labels_dir / f"{qid}.csv"))
        label_rows[qid] = load_label_rows(labels_dir / f"{qid}.csv")
        concepts = question_concepts(str(question["text"]))
        prepared.append({
            "question": question,
            "qrow": qrow,
            "hits": hits,
            "papers": papers,
            "gold": gold,
            "concepts": concepts,
            "missing_abstracts": missing,
        })
        print(
            f"{qid} top={len(hits)} dev={sum(1 for p in papers if p['key'] in gold)} "
            f"missing_abstract={missing} slots={f2_slots(concepts)}",
            flush=True,
        )

    store: Dict[str, List[dict]] = {}

    def choose_factory(label: str) -> Caller:
        def choose(instructions: str, options: Dict[str, str], states: Sequence[str]) -> Any:
            return cached_choice(
                budget,
                cache,
                cache_path,
                args.laya_url,
                instructions,
                options,
                fit_states(states),
                log,
                label,
            )
        return choose

    def run_spec(spec: Spec) -> bool:
        if spec.sid in store:
            return True
        cost = spec_cost(questions, spec)
        if not budget.room(cost):
            print(f"skip {spec.sid}, budget {budget.used}/{budget.limit} needs {cost}", flush=True)
            return False
        collected: List[dict] = []
        for item in prepared:
            texts = [
                paper_text(paper["title"], paper["abstract"], spec.inp)
                for paper in item["papers"]
            ]
            label = f"{spec.sid} {item['question']['id']}"
            predicted = run_spec_on_question(
                spec,
                item["question"],
                item["concepts"],
                texts,
                choose_factory(label),
            )
            if predicted is None:
                print(f"stopped during {spec.sid}: {budget.reason}", flush=True)
                return False
            for paper, row in zip(item["papers"], predicted):
                gold = item["gold"].get(paper["key"])
                collected.append({
                    "qid": item["question"]["id"],
                    "key": paper["key"],
                    "title": paper["title"],
                    "gold": gold,
                    "probs": row["probs"],
                    "yes": row.get("yes"),
                })
        store[spec.sid] = collected
        return True

    screen_ids = []
    for form in ("f1", "f3", "f2"):
        spec = Spec(form, "two", "concepts", "p0")
        if not run_spec(spec):
            break
        screen_ids.append(spec.sid)
    winner = None
    if screen_ids and not budget.stopped:
        winner, _tuned = _best_tuned(store, screen_ids)
        form = winner.split("-")[0]
        print(f"screen winner {winner}", flush=True)
        if form == "f2":
            run_spec(Spec("f2", "full", "concepts", "p0"))
            if not budget.stopped:
                run_spec(Spec("f2", "two", "raw", "p0"))
            done_inputs = [
                sid for sid in store
                if sid.startswith("f2-") and sid.endswith("-concepts-p0")
            ]
            best_input_sid, _best = _best_tuned(store, done_inputs) if done_inputs else (winner, None)
            best_inp = best_input_sid.split("-")[1]
            if not budget.stopped:
                run_spec(Spec("f2", "title", "concepts", "p0"))
            if not budget.stopped:
                run_spec(Spec("f2", best_inp, "concepts", "p1"))
            if not budget.stopped:
                run_spec(Spec("f2", best_inp, "concepts", "p2"))
        else:
            run_spec(Spec(form, "title", "concepts", "p0"))
            if not budget.stopped:
                run_spec(Spec(form, "full", "concepts", "p0"))
            input_sids = [
                sid for sid in store
                if sid.startswith(f"{form}-") and sid.endswith("-concepts-p0")
            ]
            best_input_sid, _best = _best_tuned(store, input_sids)
            best_inp = best_input_sid.split("-")[1]
            if not budget.stopped:
                run_spec(Spec(form, best_inp, "raw", "p0"))
            if not budget.stopped:
                run_spec(Spec(form, best_inp, "concepts", "p1"))
            if not budget.stopped:
                run_spec(Spec(form, best_inp, "concepts", "p2"))
            raw_sid = f"{form}-{best_inp}-raw-p0"
            concept_sid = f"{form}-{best_inp}-concepts-p0"
            present = [sid for sid in (concept_sid, raw_sid) if sid in store]
            best_mode_sid, _mode = _best_tuned(store, present)
            if best_mode_sid.endswith("-raw-p0") and not budget.stopped:
                run_spec(Spec(form, best_inp, "raw", "p1"))
                if not budget.stopped:
                    run_spec(Spec(form, best_inp, "raw", "p2"))
            others = [sid.split("-")[0] for sid in screen_ids if not sid.startswith(form + "-")]
            for other in others:
                if budget.stopped:
                    break
                if spec_cost(questions, Spec(other, "full", "concepts", "p0")) > 5:
                    continue
                run_spec(Spec(other, "full", "concepts", "p0"))
    add_average_records(store)

    dev_items_gold = []
    for item in prepared:
        for paper in item["papers"]:
            gold = item["gold"].get(paper["key"])
            if gold in GROUPS:
                dev_items_gold.append((item, paper, gold))
    support = support_counts(gold for _item, _paper, gold in dev_items_gold)
    n_dev = len(dev_items_gold)

    coverage_items = []
    coverage_by_key: Dict[Tuple[str, str], float] = {}
    for item, paper, gold in (
        (item, paper, item["gold"].get(paper["key"]))
        for item in prepared
        for paper in item["papers"]
    ):
        score = concept_coverage(item["concepts"], paper["title"], paper["abstract"])
        coverage_by_key[(item["question"]["id"], paper["key"])] = score
        if gold in GROUPS:
            coverage_items.append({"gold": gold, "score": score})
    base_tuned, base_floor, base_cuts = tune_coverage(coverage_items)

    print("loading eval_search for dev ranking scores", flush=True)
    scorer = _eval_search()
    baseline_rank = ranking_table(scorer, [item["qrow"] for item in prepared], label_rows, {})
    base_ndcg = baseline_rank["ndcg@10"]
    base_rel = baseline_rank["relevant@10"]

    tuned_by_sid: Dict[str, Tuned] = {}
    overall_rows = []
    question_rows = []
    qids = [str(item["question"]["id"]) for item in prepared]

    def add_setting(sid: str, records: List[dict], tuned: Tuned, group_maps: Mapping[str, Mapping[str, str]]) -> None:
        rank = ranking_table(scorer, [item["qrow"] for item in prepared], label_rows, group_maps)
        overall = metric_row(sid, records, tuned)
        overall["ndcg@10"] = rank["ndcg@10"]
        overall["relevant@10"] = rank["relevant@10"]
        overall["d_ndcg"] = None if rank["ndcg@10"] is None or base_ndcg is None else rank["ndcg@10"] - base_ndcg
        overall["d_rel"] = None if rank["relevant@10"] is None or base_rel is None else rank["relevant@10"] - base_rel
        overall["cuts"] = _fmt_cuts(tuned.thresholds)
        overall["eligible"] = bool(tuned.eligible)
        overall_rows.append(overall)
        for qid in qids:
            question_rows.append(metric_row(sid, records, tuned, qid))

    for sid, records in store.items():
        items = [{"gold": row["gold"], "probs": row["probs"]} for row in records if row.get("gold") in GROUPS]
        tuned = tune_thresholds(items)
        tuned_by_sid[sid] = tuned
        maps = groups_from_records(records, tuned.thresholds)
        add_setting(sid, records, tuned, maps)

    base_records = []
    base_maps: Dict[str, Dict[str, str]] = {}
    for item in prepared:
        qid = item["question"]["id"]
        base_maps[qid] = {}
        for paper in item["papers"]:
            score = coverage_by_key[(qid, paper["key"])]
            pred = group_from_coverage(score, base_cuts, base_floor)
            base_maps[qid][paper["key"]] = pred
            base_records.append({
                "qid": qid,
                "key": paper["key"],
                "title": paper["title"],
                "gold": item["gold"].get(paper["key"]),
                "probs": {},
                "pred": pred,
                "score": score,
            })
    # Baseline metrics use the coverage group directly, not Laya thresholds.
    base_pairs = [
        (row["gold"], row["pred"])
        for row in base_records
        if row.get("gold") in GROUPS or row.get("gold") == "not_sorted"
    ]
    base_tuned_view = Tuned(
        thresholds=base_cuts,
        macro_f1=macro_f1(base_pairs),
        accuracy=accuracy(base_pairs),
        coverage=coverage(base_pairs),
        harmful=harmful_rate(base_pairs),
        eligible=base_tuned.eligible,
    )
    rank = ranking_table(scorer, [item["qrow"] for item in prepared], label_rows, base_maps)
    baseline_row = {
        "setting": f"concept-coverage/{base_floor}",
        "n": len(_classified(base_pairs)),
        "coverage": base_tuned_view.coverage,
        "accuracy": base_tuned_view.accuracy,
        "macro_f1": base_tuned_view.macro_f1,
        "harmful": base_tuned_view.harmful,
        "harm_n": harmful_counts(base_pairs)[0],
        "good_n": harmful_counts(base_pairs)[1],
        "ndcg@10": rank["ndcg@10"],
        "relevant@10": rank["relevant@10"],
        "d_ndcg": None if rank["ndcg@10"] is None or base_ndcg is None else rank["ndcg@10"] - base_ndcg,
        "d_rel": None if rank["relevant@10"] is None or base_rel is None else rank["relevant@10"] - base_rel,
        "cuts": _fmt_cuts(base_cuts) + f" floor:{base_floor}",
        "eligible": bool(base_tuned.eligible),
        "question": "OVERALL",
    }
    overall_rows.append(baseline_row)
    for qid in qids:
        q_pairs = [
            (row["gold"], row["pred"])
            for row in base_records
            if row["qid"] == qid and (row.get("gold") in GROUPS or row.get("gold") == "not_sorted")
        ]
        harm_n, good_n = harmful_counts(q_pairs)
        question_rows.append({
            "setting": baseline_row["setting"],
            "question": qid,
            "n": len(_classified(q_pairs)),
            "coverage": coverage(q_pairs),
            "accuracy": accuracy(q_pairs),
            "macro_f1": macro_f1(q_pairs),
            "harmful": harmful_rate(q_pairs),
            "harm_n": harm_n,
            "good_n": good_n,
        })

    # Today's order, so the table shows the unreordered scores as a reference row.
    today = {
        "setting": "lexical_on",
        "n": n_dev,
        "coverage": None,
        "accuracy": None,
        "macro_f1": None,
        "harmful": None,
        "harm_n": "",
        "good_n": "",
        "ndcg@10": base_ndcg,
        "relevant@10": base_rel,
        "d_ndcg": 0.0,
        "d_rel": 0.0,
        "cuts": "",
        "eligible": False,
        "question": "OVERALL",
    }
    overall_rows.append(today)

    def sort_key(row: Mapping[str, Any]) -> Tuple[float, ...]:
        harm = row.get("harmful")
        eligible = bool(row.get("eligible")) and row["setting"] not in {"lexical_on"}
        return (
            1.0 if eligible else 0.0,
            float(row["macro_f1"]) if isinstance(row.get("macro_f1"), float) else -1.0,
            -(float(harm) if isinstance(harm, float) else 1.0),
            float(row["coverage"]) if isinstance(row.get("coverage"), float) else -1.0,
        )

    laya_rows = [row for row in overall_rows if row["setting"] in store]
    top5 = [row for row in sorted(laya_rows, key=sort_key, reverse=True) if row.get("eligible")][:5]
    best3 = sorted(laya_rows, key=sort_key, reverse=True)[:3]

    pred_dir = Path(args.pred_dir).expanduser()
    pred_dir.mkdir(parents=True, exist_ok=True)
    for row in best3:
        sid = row["setting"]
        tuned = tuned_by_sid[sid]
        path = pred_dir / f"{sid}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for record in store[sid]:
                gold = record.get("gold") if record.get("gold") else ""
                # Test rows have gold None. Leave the field empty so this file cannot score them.
                handle.write(json.dumps({
                    "qid": record["qid"],
                    "key": record["key"],
                    "title": record["title"],
                    "gold_group": gold if gold else "",
                    "pred_group": apply_thresholds(record["probs"], tuned.thresholds),
                    "probabilities": {g: round(float(record["probs"].get(g, 0.0)), 4) for g in GROUPS},
                }, ensure_ascii=False) + "\n")
        print(f"wrote {path}", flush=True)

    latency_note = "Latency was not measured."
    if args.latency and best3 and not budget.stopped:
        best = best3[0]
        spec = parse_sid(best["setting"])
        if spec is None or spec.phrasing == "avg":
            # Average has no single prompt. Time the p0 call of the same input and mode.
            base_sid = best["setting"].rsplit("-", 1)[0] + "-p0" if spec and spec.phrasing == "avg" else best["setting"]
            spec = parse_sid(base_sid) or spec
        if spec is not None:
            item = prepared[0]
            texts = fit_states([
                paper_text(paper["title"], paper["abstract"], spec.inp)
                for paper in item["papers"]
            ])
            phrasing = _phrasing_index(spec)
            concepts = item["concepts"]
            if spec.form == "f2":
                slot, target = f2_slots(concepts)[0]
                options = f2_options(target, phrasing)
                instructions = instruction_for(str(item["question"]["text"]), concepts, spec.mode, "f2")
                latency_note = (
                    f"Best setting `{best['setting']}`. "
                    f"Timed the first F2 question ({slot}, {target}) on {item['question']['id']} "
                    f"with input `{spec.inp}`."
                )
            elif spec.form == "f3":
                options = f3_options(phrasing)
                instructions = instruction_for(str(item["question"]["text"]), concepts, spec.mode, "f3")
                latency_note = (
                    f"Best setting `{best['setting']}`. "
                    f"Timed one F3 batch on {item['question']['id']} with input `{spec.inp}`."
                )
            else:
                options = f1_options(concepts, phrasing)
                instructions = instruction_for(str(item["question"]["text"]), concepts, spec.mode, "f1")
                latency_note = (
                    f"Best setting `{best['setting']}`. "
                    f"Timed one F1 batch on {item['question']['id']} with input `{spec.inp}`."
                )
            measured = measure_latency(args.laya_url, instructions, options, texts)
            latency_note = latency_note + " " + str(measured.get("detail") or "")
            payload_latency = measured
        else:
            payload_latency = {}
    else:
        payload_latency = {}
        if budget.stopped:
            latency_note = f"Latency was skipped because the run stopped ({budget.reason})."

    fresh = sum(1 for entry in log if not entry.get("cached"))
    cached_n = sum(1 for entry in log if entry.get("cached"))
    skipped = ""
    if budget.stopped:
        skipped = f" Run stopped: {budget.reason}."
    budget_note = (
        f"Experiment budget was {budget.limit} new sidecar batches. "
        f"This run made {budget.used} new batches and reused {cached_n} cached batches "
        f"({fresh} logged network or cache lookups). "
        f"Screened F1, F3, and F2 on title plus two abstract sentences, concept wording, phrasing p0. "
        f"The screen winner was `{winner or 'none'}`. "
        "F2 asks one yes/no batch per concept slot, so a winning F2 spends the rest of the budget on "
        "the full abstract and the raw question before title-only and extra phrasings. "
        "A winning F1 or F3 also runs title-only, the full abstract, the raw question, "
        "and two more phrasings, then one full-abstract pass for the other cheap formulation."
        + skipped
    )
    support_note = (
        f"{n_dev} dev papers inside the top 30 enter the scores. "
        f"Unclassified gold would be excluded. This slice has {support['not_sorted']} of those. "
        f"Answers {support['answers']}, how_why {support['how_why']}, "
        f"context {support['context']}, different {support['different']}. "
        f"Missing abstracts: {sum(item['missing_abstracts'] for item in prepared)}."
    )
    baseline_note = (
        f"`{baseline_row['setting']}` uses actor, outcome, and population only. "
        f"A phrase matches when every word is in the title or abstract. "
        f"Cuts are {baseline_row['cuts']}. "
        f"macro-F1 {_fmt(baseline_row.get('macro_f1'))}, "
        f"harmful {_fmt(baseline_row.get('harmful'))}, "
        f"coverage {_fmt(baseline_row.get('coverage'))}, "
        f"accuracy {_fmt(baseline_row.get('accuracy'))}. "
        f"ndcg@10 {_fmt(baseline_row.get('ndcg@10'))} against today's {_fmt(base_ndcg)}."
    )
    payload = {
        "budget_note": budget_note,
        "support_note": support_note,
        "overall_rows": overall_rows,
        "question_rows": question_rows,
        "top5": top5,
        "baseline_note": baseline_note,
        "baseline_row": baseline_row,
        "latency_note": latency_note,
        "support": support,
        "n_dev_scored": n_dev,
        "calls": budget.used,
        "winner": winner,
        "latency": payload_latency,
        "log": log,
    }
    payload["recommendation"] = recommend(payload)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(payload), encoding="utf-8")
    metrics_path = out.with_suffix(".json")
    slim = dict(payload)
    slim.pop("log", None)
    metrics_path.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}", flush=True)
    print(f"wrote {metrics_path}", flush=True)
    if budget.stopped and budget.reason != "budget":
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Run the dev-split Laya group experiment")
    scratch = Path.home() / "HealthDatabaseAccess-scratch" / "bench"
    run.add_argument("--corpus", default=str(scratch / "baseline_v1"))
    run.add_argument("--results", default=str(scratch / "baseline_v1b_results.json"))
    run.add_argument("--labels", default=str(scratch / "labels_final"))
    run.add_argument("--questions", default=str(REPO_ROOT / "tools" / "bench" / "questions.json"))
    run.add_argument("--out", default=str(scratch / "p25a_results.md"))
    run.add_argument("--pred-dir", default=str(scratch / "p25a_predictions"))
    run.add_argument("--cache", default=str(scratch / "p25a_cache.json"))
    run.add_argument("--laya-url", default=LAYA_URL)
    run.add_argument("--budget", type=int, default=EXPERIMENT_BUDGET)
    run.add_argument("--latency", action=argparse.BooleanOptionalAction, default=True)
    run.set_defaults(func=execute)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
