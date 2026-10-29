#!/usr/bin/env python3
"""Offline check: can Laya sort each question's top 30 into relevance groups?

``run`` and ``run-f2`` score the dev split only. They do not read test-split
categories. ``score-test`` reads those categories once, for the setting
``run-f2`` already chose, and refuses a second pass.

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

Owner-standard F2 (``cell_f2b``, command ``run-f2``) asks up to four yes/no
questions. A concept slot with no phrase is not asked. The findings question
is always asked. Yes/no probabilities are independent.

    R  Does this paper report results about the outcome?
    A  Is this paper about the actor or exposure?
    C  Does it study a different population or place? Yes means a contradiction.
       Period is not part of this check. No stated population is not a contradiction.
    F  Does it report findings? No means it only describes a policy, method, or setting.

    rule outcome:
        answers when R is yes, F is not no, and C is not yes. A is not required.
        A missing R cannot be answers.
    rule actor:
        same as outcome, and A must be yes when A was asked.
    rule open:
        same as actor, but a missing R does not block answers.

    Then, for every rule: C yes is different. F no is how_why when the actor
    check passes or was not asked, and different when A is no. Anything still
    on the actor, or with the actor not asked, is context. The rest is different.

    python tools/eval_laya_groups.py run
    python tools/eval_laya_groups.py run-f2
    python tools/eval_laya_groups.py score-test
    python tools/eval_laya_groups.py run-ft --checkpoint DIR
    python tools/eval_laya_groups.py score-ft-test

``run-ft`` loads a local checkpoint and does not call the sidecar.
``score-ft-test`` reads the test split once.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import os
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
F2B_RULES: Tuple[str, ...] = ("outcome", "actor", "open")
F2B_INPUTS: Tuple[str, ...] = ("two", "full")
F2B_PHRASINGS: Tuple[str, ...] = ("p0", "p1", "avg")
HEALTH_EDU_TOPICS = frozenset({"health", "education"})
F2B_BUDGET = 300

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


def population_place_phrase(concepts: QuestionConcepts) -> str:
    """Population and place only. Period is not the owner's contradiction check."""
    return join_phrases(tuple(concepts.population) + tuple(concepts.place))


def f2b_slots(concepts: QuestionConcepts) -> List[Tuple[str, str]]:
    """Questions to ask. An empty concept slot is skipped. Findings is always asked."""
    slots: List[Tuple[str, str]] = []
    outcome = join_phrases(concepts.outcome)
    actor = join_phrases(concepts.actor)
    where = population_place_phrase(concepts)
    if outcome:
        slots.append(("R", outcome))
    if actor:
        slots.append(("A", actor))
    if where:
        slots.append(("C", where))
    slots.append(("F", ""))
    return slots


def f2b_batches_per_search(concepts: QuestionConcepts, phrasing: str) -> int:
    """Sidecar batches for one question's top 30. Averaging two phrasings doubles the calls."""
    checks = len(f2b_slots(concepts))
    if phrasing == "avg":
        return checks * 2
    return checks


def f2b_options(slot: str, target: str, phrasing: int) -> Dict[str, str]:
    """Two wordings. Phrasing 0 follows the owner's checks. Phrasing 1 says the same thing again."""
    second = int(phrasing) > 0
    if slot == "R":
        if not second:
            return {
                "yes": f"Yes. This paper reports results about {target}.",
                "no": f"No. This paper does not report results about {target}.",
            }
        return {
            "yes": f"Yes. The results in this paper are about {target}.",
            "no": f"No. The results in this paper are not about {target}.",
        }
    if slot == "A":
        if not second:
            return {
                "yes": f"Yes. This paper is about {target}.",
                "no": f"No. This paper is not about {target}.",
            }
        return {
            "yes": f"Yes. The actor or exposure in this paper is {target}.",
            "no": f"No. The actor or exposure in this paper is not {target}.",
        }
    if slot == "C":
        if not second:
            return {
                "yes": f"Yes. It studies a different population or place than {target}.",
                "no": f"No. It does not study a different population or place than {target}.",
            }
        return {
            "yes": f"Yes. Its population or place contradicts {target}.",
            "no": f"No. Its population or place does not contradict {target}.",
        }
    if slot != "F":
        raise ValueError(slot)
    if not second:
        return {
            "yes": "Yes. It reports findings.",
            "no": "No. It only describes a policy, a method, or a setting.",
        }
    return {
        "yes": "Yes. It reports findings, not only a description.",
        "no": "No. It states no findings and only describes a policy, method, or setting.",
    }


def f2b_instruction(question: str, slot: str, target: str) -> str:
    asked = f'A student asked "{question}".'
    if slot == "R":
        return f"{asked} Does this paper report results about {target}?"
    if slot == "A":
        return f"{asked} Is this paper about {target}?"
    if slot == "C":
        return (
            f"{asked} Does it study a different population or place than {target}? "
            "No stated population is not a contradiction."
        )
    return (
        f"{asked} Does it report findings, or only describe a policy, method, or setting?"
    )


def cell_f2b(flags: Mapping[str, bool], rule: str) -> str:
    """Map one boolean draw of the owner-standard questions to a group.

    ``flags`` holds only the questions that were asked. See the module docstring
    for the three rules. A missing population check is not a contradiction.
    """
    if rule not in F2B_RULES:
        raise ValueError(rule)
    if "C" in flags and flags["C"]:
        return "different"
    actor_ok = bool(flags["A"]) if "A" in flags else True
    findings_ok = bool(flags["F"]) if "F" in flags else True
    if rule == "open":
        outcome_ok = bool(flags["R"]) if "R" in flags else True
    else:
        outcome_ok = bool(flags["R"]) if "R" in flags else False
    answers_actor = actor_ok if rule in {"actor", "open"} else True
    if outcome_ok and findings_ok and answers_actor:
        return "answers"
    if "F" in flags and not flags["F"]:
        return "how_why" if actor_ok else "different"
    if actor_ok:
        return "context"
    return "different"


def combine_f2b(yes: Mapping[str, Optional[float]], rule: str) -> Dict[str, float]:
    """Turn P(yes) for the asked owner-standard questions into group probabilities.

    None, or a missing key, means that question was not asked. The values sum to 1
    when at least one question was asked, and to 0 when none were.
    """
    given: Dict[str, float] = {}
    for name in ("R", "A", "C", "F"):
        value = yes.get(name)
        if value is None:
            continue
        given[name] = _clip(float(value))
    totals = {group: 0.0 for group in GROUPS}
    if not given:
        return totals
    names = list(given)
    for bits in itertools.product((False, True), repeat=len(names)):
        flags = dict(zip(names, bits))
        cell = 1.0
        for name, bit in flags.items():
            probability = given[name]
            cell *= probability if bit else (1.0 - probability)
        totals[cell_f2b(flags, rule)] += cell
    return totals


def f2b_setting_id(inp: str, rule: str, phrasing: str) -> str:
    return f"f2b-{inp}-{rule}-{phrasing}"


def pick_f2b_key(row: Mapping[str, Any]) -> Tuple[float, ...]:
    """Stay under the harmful-error cap, then take the ndcg@10 gain. Macro-F1 breaks ties."""
    harm = row.get("harmful")
    harm_value = float(harm) if isinstance(harm, (int, float)) and not isinstance(harm, bool) else 1.0
    delta = row.get("d_ndcg")
    delta_value = float(delta) if isinstance(delta, (int, float)) and not isinstance(delta, bool) else -999.0
    f1 = row.get("macro_f1")
    f1_value = float(f1) if isinstance(f1, (int, float)) and not isinstance(f1, bool) else -1.0
    covered = row.get("coverage")
    covered_value = float(covered) if isinstance(covered, (int, float)) and not isinstance(covered, bool) else -1.0
    if harm_value <= HARM_CAP + 1e-12:
        return (1.0, delta_value, f1_value, covered_value)
    return (0.0, -harm_value, delta_value, f1_value)


def pick_f2b(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Pick on dev. A setting over the cap is used only when none are under it."""
    if not rows:
        raise ValueError("no settings to pick")
    return max(rows, key=pick_f2b_key)


def items_for_fold(records: Sequence[Mapping[str, Any]], held_out: str) -> List[dict]:
    """Dev rows for every question except the held-out one."""
    return [
        {"gold": row["gold"], "probs": row["probs"]}
        for row in records
        if row.get("qid") != held_out and row.get("gold") in GROUPS
    ]


def loo_predictions(
    records: Sequence[Mapping[str, Any]],
    qids: Sequence[str],
) -> Dict[str, Dict[str, str]]:
    """Fit thresholds on 14 questions and predict the 15th. The held-out gold is not in the fit."""
    out: Dict[str, Dict[str, str]] = {}
    for held in qids:
        tuned = tune_thresholds(items_for_fold(records, held))
        preds: Dict[str, str] = {}
        for row in records:
            if row.get("qid") != held:
                continue
            preds[str(row["key"])] = apply_thresholds(row["probs"], tuned.thresholds)
        out[held] = preds
    return out


def gate_verdict(
    *,
    dev_ndcg: Optional[float],
    dev_base: Optional[float],
    test_ndcg: Optional[float],
    test_base: Optional[float],
    test_harm: Optional[float],
    worse_questions: Sequence[str],
) -> str:
    """PASS only when every published condition holds. One miss is FAIL."""
    beats_dev = dev_ndcg is not None and dev_base is not None and dev_ndcg > dev_base
    beats_test = test_ndcg is not None and test_base is not None and test_ndcg > test_base
    harm_ok = test_harm is not None and test_harm <= HARM_CAP + 1e-12
    if beats_dev and beats_test and harm_ok and not list(worse_questions):
        return "PASS"
    return "FAIL"


def worse_question_ids(
    question_rows: Sequence[Mapping[str, Any]],
    topics: Mapping[str, str],
) -> List[str]:
    """Health and education questions whose group order is below today's order."""
    found: List[str] = []
    for row in question_rows:
        qid = str(row.get("question") or "")
        if topics.get(qid) not in HEALTH_EDU_TOPICS:
            continue
        delta = row.get("d_ndcg")
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta < 0:
            found.append(qid)
    return found


def claim_test_stamp(path: Path, chosen: str) -> bool:
    """Create the one-shot stamp. A second claim returns False and writes nothing."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"status": "started", "chosen": chosen}, handle)
    return True


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
    """Rank a calibrated candidate.

    A candidate under the harmful-error cap ranks by macro-F1. When none are
    under the cap, the lowest harmful-error rate wins, and macro-F1 breaks ties.
    """
    f1 = tuned.macro_f1 if tuned.macro_f1 is not None else -1.0
    harm = tuned.harmful if tuned.harmful is not None else 1.0
    covered = tuned.coverage if tuned.coverage is not None else -1.0
    accurate = tuned.accuracy if tuned.accuracy is not None else -1.0
    if tuned.eligible:
        return (1.0, f1, -harm, covered, accurate)
    return (0.0, -harm, f1, covered, accurate)


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
    if spec.form == "f2b":
        yes_cols: Dict[str, List[float]] = {}
        for slot, target in f2b_slots(concepts):
            options = f2b_options(slot, target, phrasing)
            rows = choose(
                f2b_instruction(str(question["text"]), slot, target),
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
            yes = {slot: values[index] for slot, values in yes_cols.items()}
            combined.append({"probs": combine_f2b(yes, spec.mode), "yes": yes})
        return combined
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
    if spec.form == "f2":
        return sum(len(f2_slots(question_concepts(str(q["text"])))) for q in questions)
    if spec.form == "f2b":
        return sum(len(f2b_slots(question_concepts(str(q["text"])))) for q in questions)
    return len(questions)


def load_questions(path: Path) -> List[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["questions"])


def load_results(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_label_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def gold_for(rows: Sequence[Mapping[str, str]], split: str) -> Dict[str, str]:
    """Primary labels for one split. The other split's categories are dropped."""
    by_labeller: Dict[str, List[Mapping[str, str]]] = {}
    for row in rows:
        name = (row.get("labeller") or "owner").strip() or "owner"
        by_labeller.setdefault(name, []).append(row)
    if not by_labeller:
        return {}
    chosen = "owner" if "owner" in by_labeller else sorted(by_labeller)[0]
    gold: Dict[str, str] = {}
    for row in by_labeller[chosen]:
        if (row.get("split") or "").strip().lower() != split:
            continue
        key = (row.get("key") or "").strip()
        group = category_to_group(str(row.get("category") or ""))
        if key and group:
            gold[key] = group
    return gold


def dev_gold_for(rows: Sequence[Mapping[str, str]]) -> Dict[str, str]:
    """Dev-split primary labels only. Test categories are dropped here."""
    return gold_for(rows, "dev")


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


def top_golds(prepared: Sequence[Mapping[str, Any]]) -> List[str]:
    """Dev groups for papers in the ranked top 30. Labels outside that list do not count."""
    found: List[str] = []
    for item in prepared:
        gold = item["gold"]
        for paper in item["papers"]:
            group = gold.get(paper["key"])
            if group:
                found.append(str(group))
    return found


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
    split: str = "dev",
) -> Dict[str, Any]:
    per = []
    for qrow in questions:
        qid = str(qrow["id"])
        hits = reorder_hits(qrow["rankings"]["lexical_on"], group_maps.get(qid, {}))
        fake = dict(qrow)
        fake["rankings"] = {"lexical_on": hits}
        per.append(scorer.score_question(fake, label_rows.get(qid, []), split, "lexical_on"))
    return {"questions": per, "ndcg@10": _mean([row.get("ndcg@10") for row in per]),
            "relevant@10": _mean([row.get("relevant@10") for row in per])}


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def ranking_deltas(
    rank_questions: Sequence[Mapping[str, Any]],
    baseline_questions: Sequence[Mapping[str, Any]],
) -> Dict[str, Dict[str, Optional[float]]]:
    """Per-question ndcg@10 and relevant@10, and the change from lexical_on.

    The overall mean is not a substitute. A gain on one question can cancel
    a loss on another.
    """
    base = {str(row.get("id")): row for row in baseline_questions}
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for row in rank_questions:
        qid = str(row.get("id"))
        origin = base.get(qid, {})
        ndcg = _as_float(row.get("ndcg@10"))
        rel = _as_float(row.get("relevant@10"))
        base_ndcg = _as_float(origin.get("ndcg@10"))
        base_rel = _as_float(origin.get("relevant@10"))
        out[qid] = {
            "ndcg@10": ndcg,
            "relevant@10": rel,
            "d_ndcg": None if ndcg is None or base_ndcg is None else ndcg - base_ndcg,
            "d_rel": None if rel is None or base_rel is None else rel - base_rel,
        }
    return out


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
        "| setting | question | n | coverage | accuracy | macro-F1 | harmful | ndcg@10 | rel@10 | d ndcg | d rel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in payload["question_rows"]:
        lines.append(
            "| {setting} | {question} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | "
            "{ndcg} | {rel} | {dndcg} | {drel} |".format(
                setting=row["setting"],
                question=row["question"],
                n=row["n"],
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                ndcg=_fmt(row.get("ndcg@10")),
                rel=_fmt(row.get("relevant@10"), 2),
                dndcg=_fmt(row.get("d_ndcg")),
                drel=_fmt(row.get("d_rel"), 2),
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
        deltas = ranking_deltas(rank["questions"], baseline_rank["questions"])
        for qid in qids:
            qrow = metric_row(sid, records, tuned, qid)
            qrow.update(deltas.get(qid, {}))
            question_rows.append(qrow)

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
    base_deltas = ranking_deltas(rank["questions"], baseline_rank["questions"])
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
        qrow = {
            "setting": baseline_row["setting"],
            "question": qid,
            "n": len(_classified(q_pairs)),
            "coverage": coverage(q_pairs),
            "accuracy": accuracy(q_pairs),
            "macro_f1": macro_f1(q_pairs),
            "harmful": harmful_rate(q_pairs),
            "harm_n": harm_n,
            "good_n": good_n,
        }
        qrow.update(base_deltas.get(qid, {}))
        question_rows.append(qrow)

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
        f1 = float(row["macro_f1"]) if isinstance(row.get("macro_f1"), float) else -1.0
        harm_value = float(harm) if isinstance(harm, float) else 1.0
        covered = float(row["coverage"]) if isinstance(row.get("coverage"), float) else -1.0
        if eligible:
            return (1.0, f1, -harm_value, covered)
        return (0.0, -harm_value, f1, covered)

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

    cached_n = sum(1 for entry in log if entry.get("cached"))
    skipped = ""
    if budget.stopped:
        skipped = f" Run stopped: {budget.reason}."
    budget_note = (
        f"Experiment budget was {budget.limit} new sidecar batches. "
        f"This run made {budget.used} new batches and reused {cached_n} cached batches. "
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


def average_yes(left: Mapping[str, float], right: Mapping[str, float]) -> Dict[str, float]:
    """Mean P(yes) per slot. Both phrasings ask the same slots."""
    slots = sorted(set(left) | set(right))
    return {slot: (float(left[slot]) + float(right[slot])) / 2.0 for slot in slots}


def _pairs_from(records: Sequence[Mapping[str, Any]], pred_of: Callable[[Mapping[str, Any]], str]) -> List[Tuple[str, str]]:
    pairs = []
    for row in records:
        gold = row.get("gold")
        if gold not in GROUPS and gold != "not_sorted":
            continue
        pairs.append((str(gold), pred_of(row)))
    return pairs


def _maps_from(
    records: Sequence[Mapping[str, Any]],
    pred_of: Callable[[Mapping[str, Any]], str],
) -> Dict[str, Dict[str, str]]:
    maps: Dict[str, Dict[str, str]] = {}
    for row in records:
        maps.setdefault(str(row["qid"]), {})[str(row["key"])] = pred_of(row)
    return maps


def summary_from_pairs(
    sid: str,
    pairs: Sequence[Tuple[str, str]],
    rank: Mapping[str, Any],
    baseline: Mapping[str, Any],
    cuts: str,
) -> Dict[str, Any]:
    harm_n, good_n = harmful_counts(pairs)
    harm = harmful_rate(pairs)
    base_ndcg = baseline.get("ndcg@10")
    base_rel = baseline.get("relevant@10")
    ndcg = rank.get("ndcg@10")
    rel = rank.get("relevant@10")
    return {
        "setting": sid,
        "n": len(_classified(pairs)),
        "coverage": coverage(pairs),
        "accuracy": accuracy(pairs),
        "macro_f1": macro_f1(pairs),
        "harmful": harm,
        "harm_n": harm_n,
        "good_n": good_n,
        "ndcg@10": ndcg,
        "relevant@10": rel,
        "d_ndcg": None if ndcg is None or base_ndcg is None else ndcg - base_ndcg,
        "d_rel": None if rel is None or base_rel is None else rel - base_rel,
        "cuts": cuts,
        "eligible": harm is not None and harm <= HARM_CAP + 1e-12,
    }


def question_summaries(
    sid: str,
    records: Sequence[Mapping[str, Any]],
    pred_of: Callable[[Mapping[str, Any]], str],
    rank: Mapping[str, Any],
    baseline: Mapping[str, Any],
    qids: Sequence[str],
) -> List[dict]:
    deltas = ranking_deltas(rank["questions"], baseline["questions"])
    by_q: Dict[str, List[Mapping[str, Any]]] = {}
    for row in records:
        by_q.setdefault(str(row["qid"]), []).append(row)
    out = []
    for qid in qids:
        pairs = _pairs_from(by_q.get(qid, []), pred_of)
        harm_n, good_n = harmful_counts(pairs)
        item = {
            "setting": sid,
            "question": qid,
            "n": len(_classified(pairs)),
            "coverage": coverage(pairs),
            "accuracy": accuracy(pairs),
            "macro_f1": macro_f1(pairs),
            "harmful": harmful_rate(pairs),
            "harm_n": harm_n,
            "good_n": good_n,
        }
        item.update(deltas.get(qid, {}))
        out.append(item)
    return out


def score_grouped(
    sid: str,
    records: Sequence[Mapping[str, Any]],
    pred_of: Callable[[Mapping[str, Any]], str],
    prepared: Sequence[Mapping[str, Any]],
    label_rows: Mapping[str, Sequence[Mapping[str, str]]],
    scorer: Any,
    baseline: Mapping[str, Any],
    split: str,
    cuts: str,
) -> Tuple[dict, List[dict]]:
    qids = [str(item["question"]["id"]) for item in prepared]
    rank = ranking_table(
        scorer,
        [item["qrow"] for item in prepared],
        label_rows,
        _maps_from(records, pred_of),
        split,
    )
    overall = summary_from_pairs(sid, _pairs_from(records, pred_of), rank, baseline, cuts)
    return overall, question_summaries(sid, records, pred_of, rank, baseline, qids)


def loo_summary_for(
    sid: str,
    records: Sequence[Mapping[str, Any]],
    prepared: Sequence[Mapping[str, Any]],
    label_rows: Mapping[str, Sequence[Mapping[str, str]]],
    scorer: Any,
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    """Fit on 14 dev questions, score the 15th, then pool those 15 scores."""
    qids = [str(item["question"]["id"]) for item in prepared]
    preds = loo_predictions(records, qids)

    def pred_of(row: Mapping[str, Any]) -> str:
        return preds.get(str(row["qid"]), {}).get(str(row["key"]), "not_sorted")

    overall, _questions = score_grouped(
        sid, records, pred_of, prepared, label_rows, scorer, baseline, "dev", "loo"
    )
    return overall


def loo_coverage_summary(
    sid: str,
    score_rows: Sequence[Mapping[str, Any]],
    prepared: Sequence[Mapping[str, Any]],
    label_rows: Mapping[str, Sequence[Mapping[str, str]]],
    scorer: Any,
    baseline: Mapping[str, Any],
) -> Dict[str, Any]:
    qids = [str(item["question"]["id"]) for item in prepared]
    fitted: Dict[str, Tuple[str, Dict[str, float]]] = {}
    for held in qids:
        items = [
            {"gold": row["gold"], "score": row["score"]}
            for row in score_rows
            if row["qid"] != held and row.get("gold") in GROUPS
        ]
        _tuned, floor, cuts = tune_coverage(items)
        fitted[held] = (floor, cuts)

    def pred_of(row: Mapping[str, Any]) -> str:
        floor, cuts = fitted[str(row["qid"])]
        return group_from_coverage(float(row["score"]), cuts, floor)

    overall, _questions = score_grouped(
        sid, score_rows, pred_of, prepared, label_rows, scorer, baseline, "dev", "loo"
    )
    return overall


def prepare_eval(
    questions: Sequence[Mapping[str, Any]],
    results: Mapping[str, Any],
    corpus: Path,
    labels_dir: Path,
) -> Tuple[List[dict], Dict[str, List[dict]]]:
    """Load papers and dev gold. Test categories are not stored on the papers."""
    by_id = {str(row["id"]): row for row in results["questions"]}
    prepared: List[dict] = []
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
        rows = load_label_rows(labels_dir / f"{qid}.csv")
        label_rows[qid] = rows
        concepts = question_concepts(str(question["text"]))
        prepared.append({
            "question": question,
            "qrow": qrow,
            "papers": papers,
            "gold": dev_gold_for(rows),
            "concepts": concepts,
            "missing_abstracts": missing,
        })
        print(
            f"{qid} top={len(hits)} dev={sum(1 for paper in papers if paper['key'] in prepared[-1]['gold'])} "
            f"missing_abstract={missing} checks={[slot for slot, _target in f2b_slots(concepts)]}",
            flush=True,
        )
    return prepared, label_rows


def _record(item: Mapping[str, Any], paper: Mapping[str, Any], probs: Mapping[str, float], yes: Optional[Mapping[str, float]] = None) -> dict:
    row = {
        "qid": item["question"]["id"],
        "key": paper["key"],
        "title": paper["title"],
        "gold": item["gold"].get(paper["key"]),
        "probs": probs,
    }
    if yes is not None:
        row["yes"] = dict(yes)
    return row


def fetch_f2b_yes(
    prepared: Sequence[Mapping[str, Any]],
    budget: Budget,
    cache: Dict[str, Any],
    cache_path: Path,
    url: str,
    log: List[dict],
) -> Optional[Dict[Tuple[str, int, str], List[Dict[str, float]]]]:
    """One batch per input, phrasing, question, and asked check. Rules are applied later."""
    table: Dict[Tuple[str, int, str], List[Dict[str, float]]] = {}
    for inp in F2B_INPUTS:
        for phrasing in (0, 1):
            for item in prepared:
                qid = str(item["question"]["id"])
                slots = f2b_slots(item["concepts"])
                texts = fit_states([
                    paper_text(paper["title"], paper["abstract"], inp) for paper in item["papers"]
                ])
                columns: Dict[str, List[float]] = {}
                for slot, target in slots:
                    options = f2b_options(slot, target, phrasing)
                    rows = cached_choice(
                        budget,
                        cache,
                        cache_path,
                        url,
                        f2b_instruction(str(item["question"]["text"]), slot, target),
                        options,
                        texts,
                        log,
                        f"f2b-{inp}-p{phrasing} {qid} {slot}",
                    )
                    if rows is None:
                        return None
                    columns[slot] = [
                        float(probs_from_choice(row, options).get("yes", 0.0)) for row in rows
                    ]
                table[(inp, phrasing, qid)] = [
                    {slot: columns[slot][index] for slot in columns}
                    for index in range(len(item["papers"]))
                ]
    return table


def records_for_rule(
    prepared: Sequence[Mapping[str, Any]],
    table: Mapping[Tuple[str, int, str], List[Dict[str, float]]],
    inp: str,
    rule: str,
    phrasing: str,
) -> List[dict]:
    records = []
    for item in prepared:
        qid = str(item["question"]["id"])
        if phrasing == "avg":
            yes_rows = [
                average_yes(left, right)
                for left, right in zip(table[(inp, 0, qid)], table[(inp, 1, qid)])
            ]
        else:
            index = 0 if phrasing == "p0" else 1
            yes_rows = table[(inp, index, qid)]
        for paper, yes in zip(item["papers"], yes_rows):
            records.append(_record(item, paper, combine_f2b(yes, rule), yes))
    return records


def fetch_f1_title(
    prepared: Sequence[Mapping[str, Any]],
    choose: Caller,
) -> Optional[List[dict]]:
    spec = Spec("f1", "title", "concepts", "p0")
    collected = []
    for item in prepared:
        texts = [paper_text(paper["title"], paper["abstract"], "title") for paper in item["papers"]]
        predicted = run_spec_on_question(spec, item["question"], item["concepts"], texts, choose)
        if predicted is None:
            return None
        for paper, row in zip(item["papers"], predicted):
            collected.append(_record(item, paper, row["probs"]))
    return collected


def _public_prob_records(records: Sequence[Mapping[str, Any]]) -> List[dict]:
    published = []
    for row in records:
        published.append({
            "qid": row["qid"],
            "key": row["key"],
            "probs": {group: float(row["probs"].get(group, 0.0)) for group in GROUPS},
        })
    return published


def _threshold_pred(thresholds: Mapping[str, float]) -> Callable[[Mapping[str, Any]], str]:
    def pred_of(row: Mapping[str, Any]) -> str:
        return apply_thresholds(row["probs"], thresholds)

    return pred_of


def _coverage_rows(prepared: Sequence[Mapping[str, Any]]) -> List[dict]:
    rows = []
    for item in prepared:
        qid = item["question"]["id"]
        for paper in item["papers"]:
            score = concept_coverage(item["concepts"], paper["title"], paper["abstract"])
            rows.append({
                "qid": qid,
                "key": paper["key"],
                "title": paper["title"],
                "gold": item["gold"].get(paper["key"]),
                "score": score,
            })
    return rows


def _slot_names(concepts: QuestionConcepts) -> str:
    labels = {"R": "outcome", "A": "actor", "C": "population/place", "F": "findings"}
    return " ".join(labels[slot] for slot, _target in f2b_slots(concepts))


def _harm_cell(row: Mapping[str, Any]) -> str:
    harm_n = row.get("harm_n")
    good_n = row.get("good_n")
    if harm_n == "" or good_n == "":
        return ""
    if harm_n is None or good_n is None:
        return ""
    return f"{harm_n}/{good_n}"


def render_round2(payload: Mapping[str, Any]) -> str:
    """Dev report. It does not contain a test-split score."""
    lines = [
        "# Laya relevance groups, owner-standard questions, dev split",
        "",
        "Dev labels only. This file does not score the test split. "
        "Thresholds were fit on these dev rows. Leave-one-question-out fits on 14 questions "
        "and scores the 15th.",
        "",
        "## Call budget",
        "",
        payload["budget_note"],
        "",
        "## Support",
        "",
        payload["support_note"],
        "",
        "## Checks asked",
        "",
        "Outcome, actor, and population or place are skipped when `question_concepts` leaves that slot empty. "
        "Period is not a contradiction check. Findings is always asked.",
        "",
        "| question | topic | checks |",
        "| --- | --- | --- |",
    ]
    for row in payload["slot_rows"]:
        lines.append(f"| {row['question']} | {row['topic']} | {row['checks']} |")
    lines.extend([
        "",
        "## Combination rules",
        "",
        "Yes and no are treated as independent. A missing check is not a no.",
        "",
        "Rule outcome: answers requires a yes on outcome results, a yes on findings when that question was asked, "
        "and no contradiction. The actor is not required. A question with no outcome phrase cannot be answers.",
        "",
        "Rule actor: same as outcome, and the actor question must be yes when it was asked.",
        "",
        "Rule open: same as actor, except a missing outcome phrase does not block answers.",
        "",
        "For every rule, a contradiction is different. Findings-no is how_why when the paper is about the actor "
        "or the actor was not asked, and different when the actor question is no. "
        "A paper that is not an answer and not a findings-no lands in context when it is about the actor "
        "or the actor was not asked. Otherwise it is different.",
        "",
        "Phrasing avg is the mean P(yes) of the two wordings, then the same rule. "
        "Title plus two abstract sentences is input `two`. The whole abstract is input `full`.",
        "",
        "## Full table",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | rel@10 | d ndcg | d rel | thresholds |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in payload["overall_rows"]:
        lines.append(
            "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm_cell} | "
            "{ndcg} | {rel} | {dndcg} | {drel} | {cuts} |".format(
                setting=row["setting"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                harm_cell=_harm_cell(row),
                ndcg=_fmt(row.get("ndcg@10")),
                rel=_fmt(row.get("relevant@10"), 2),
                dndcg=_fmt(row.get("d_ndcg")),
                drel=_fmt(row.get("d_rel"), 2),
                cuts=row.get("cuts") or "",
            )
        )
    lines.extend([
        "",
        "## Leave-one-question-out",
        "",
        "Thresholds for each row were fit without that row's question. "
        "The harmful-error rate pools the 15 held-out questions.",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | d ndcg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in payload["loo_rows"]:
        lines.append(
            "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm_cell} | {ndcg} | {dndcg} |".format(
                setting=row["setting"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                harm_cell=_harm_cell(row),
                ndcg=_fmt(row.get("ndcg@10")),
                dndcg=_fmt(row.get("d_ndcg")),
            )
        )
    lines.extend([
        "",
        "## Per question",
        "",
        "Coverage, accuracy, and macro-F1 for the chosen setting, F1 title-concepts, and concept coverage.",
        "",
        "| setting | question | n | coverage | accuracy | macro-F1 | harmful | ndcg@10 | rel@10 | d ndcg | d rel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in payload["question_rows"]:
        lines.append(
            "| {setting} | {question} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | "
            "{ndcg} | {rel} | {dndcg} | {drel} |".format(
                setting=row["setting"],
                question=row["question"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                ndcg=_fmt(row.get("ndcg@10")),
                rel=_fmt(row.get("relevant@10"), 2),
                dndcg=_fmt(row.get("d_ndcg")),
                drel=_fmt(row.get("d_rel"), 2),
            )
        )
    lines.extend([
        "",
        "## Latency",
        "",
        payload["latency_note"],
        "",
        "## Recommendation",
        "",
        payload["recommendation"],
        "",
    ])
    return "\n".join(lines)


def _recommend_dev(info: Mapping[str, Any]) -> str:
    chosen = info["chosen_row"]
    base = info["base_row"]
    f1 = info["f1_row"]
    loo = info["loo_chosen"]
    n = info["n_dev"]
    unsorted_n = info["unsorted_n"]
    sentences = []
    if info["dev_eligible"]:
        sentences.append(
            f"The chosen setting is {chosen['setting']}."
        )
        sentences.append(
            "On dev it was the setting at or under a 5% harmful-error rate with the largest gain "
            "in group-ordered ndcg@10."
        )
    else:
        sentences.append(
            f"No setting kept dev harmful errors at or below 5%. The chosen setting is {chosen['setting']}."
        )
        sentences.append(
            "The tie break was the lowest harmful-error rate, then the largest ndcg@10 gain."
        )
    sentences.append(
        f"It sorts {n - unsorted_n} of {n} dev papers and leaves {unsorted_n} unsorted. "
        f"Harmful errors were {_fmt(chosen.get('harmful'))} "
        f"({_harm_cell(chosen)}). "
        f"Dev ndcg@10 was {_fmt(chosen.get('ndcg@10'))} against today's {_fmt(info['today_ndcg'])} "
        f"and concept coverage's {_fmt(base.get('ndcg@10'))}."
    )
    sentences.append(
        f"Leave-one-question-out for that setting had harmful errors {_fmt(loo.get('harmful'))} "
        f"and ndcg@10 {_fmt(loo.get('ndcg@10'))} ({_fmt(loo.get('d_ndcg'))} vs today's order)."
    )
    sentences.append(
        f"F1 title-concepts had dev ndcg@10 {_fmt(f1.get('ndcg@10'))} "
        f"and harmful errors {_fmt(f1.get('harmful'))}."
    )
    sentences.append(
        f"One search sends {info['batches_full']} batches of 30 when every check is asked, "
        f"and {info['batches_min']} to {info['batches_max']} on these 15 questions. "
        f"Questions with only the findings check: {info['findings_only']}."
    )
    sentences.append("The test split is not scored in this file.")
    return " ".join(sentences)


def _recommend_final(dev: Mapping[str, Any], test: Mapping[str, Any]) -> str:
    """Eight sentences. The test numbers appear once, after the dev pick is fixed."""
    chosen = dev["chosen_row"]
    base = dev["base_row"]
    test_chosen = test["chosen"]
    test_base = test["coverage"]
    worse_text = ", ".join(test["worse"]) if test["worse"] else "none"
    if dev["dev_eligible"]:
        how_picked = (
            "the dev setting at or under a 5% harmful-error rate with the largest ndcg@10 gain"
        )
    else:
        how_picked = (
            "the lowest-harm fallback, because no dev setting stayed at or under a 5% harmful-error rate"
        )
    if test["verdict"] == "PASS":
        students = "The numbers clear the gate on this frozen set, and they are not a student-facing ranking change."
    else:
        students = "I would not put these groups in front of students, because the gate failed on the single test score."
    sentences = [
        f"The chosen setting is {chosen['setting']}, {how_picked}.",
        (
            f"Dev ndcg@10 was {_fmt(chosen.get('ndcg@10'))} against today's {_fmt(dev['today_ndcg'])} "
            f"and concept coverage's {_fmt(base.get('ndcg@10'))}, with harmful errors {_fmt(chosen.get('harmful'))} "
            f"and {dev['unsorted_n']} of {dev['n_dev']} papers left unsorted."
        ),
        (
            f"Leave-one-question-out had harmful errors {_fmt(dev['loo_chosen'].get('harmful'))} "
            f"and ndcg@10 {_fmt(dev['loo_chosen'].get('ndcg@10'))}."
        ),
        (
            f"The one test score had ndcg@10 {_fmt(test_chosen.get('ndcg@10'))} against concept coverage "
            f"{_fmt(test_base.get('ndcg@10'))} and today's {_fmt(test['today_ndcg'])}, with harmful errors "
            f"{_fmt(test_chosen.get('harmful'))} ({_harm_cell(test_chosen)}) and {test['unsorted_n']} of "
            f"{test_chosen.get('n')} papers left unsorted."
        ),
        f"Health and education questions behind today's test order: {worse_text}.",
        f"Gate verdict: {test['verdict']}.",
        (
            f"One search sends {dev['batches_full']} batches of 30 when every check is asked, "
            f"and {dev['findings_only']} ask only the findings check."
        ),
        students,
    ]
    return " ".join(sentences)


def _write_predictions(path: Path, records: Sequence[Mapping[str, Any]], thresholds: Mapping[str, float], splits: Mapping[Tuple[str, str], str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            gold = record.get("gold") if record.get("gold") else ""
            yes = record.get("yes") or {}
            handle.write(json.dumps({
                "qid": record["qid"],
                "key": record["key"],
                "title": record["title"],
                "split": splits.get((str(record["qid"]), str(record["key"])), ""),
                "gold_group": gold if gold else "",
                "pred_group": apply_thresholds(record["probs"], thresholds),
                "probabilities": {group: round(float(record["probs"].get(group, 0.0)), 4) for group in GROUPS},
                "yes": {slot: round(float(value), 4) for slot, value in yes.items()},
            }, ensure_ascii=False) + "\n")


def _split_index(label_rows: Mapping[str, Sequence[Mapping[str, str]]]) -> Dict[Tuple[str, str], str]:
    found: Dict[Tuple[str, str], str] = {}
    for qid, rows in label_rows.items():
        for row in rows:
            key = (row.get("key") or "").strip()
            if not key:
                continue
            found[(str(qid), key)] = (row.get("split") or "").strip().lower()
    return found


def execute_round2(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser()
    stamp = Path(str(out) + ".test-stamp.json")
    metrics_path = out.with_suffix(".json")
    if stamp.exists():
        print(f"refusing to refit after the test split was scored: {stamp}", flush=True)
        return 3
    if metrics_path.is_file():
        previous = json.loads(metrics_path.read_text(encoding="utf-8"))
        if isinstance(previous, dict) and previous.get("test"):
            print(f"refusing to refit after the test split was scored: {metrics_path}", flush=True)
            return 3
    questions = load_questions(Path(args.questions))
    results = load_results(Path(args.results))
    corpus = Path(args.corpus).expanduser()
    labels_dir = Path(args.labels).expanduser()
    cache_path = Path(args.cache).expanduser()
    cache = load_cache(cache_path)
    budget = Budget(int(args.budget))
    log: List[dict] = []
    prepared, label_rows = prepare_eval(questions, results, corpus, labels_dir)
    planned = sum(len(f2b_slots(item["concepts"])) for item in prepared) * len(F2B_INPUTS) * 2
    planned += len(prepared)
    print(f"planned new-or-cached batches {planned} budget {budget.limit}", flush=True)

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
            "f1-title-concepts-p0",
        )

    f1_records = fetch_f1_title(prepared, choose)
    if f1_records is None:
        print(f"stopped during f1-title-concepts-p0: {budget.reason}", flush=True)
        return 2
    table = fetch_f2b_yes(prepared, budget, cache, cache_path, args.laya_url, log)
    if table is None:
        print(f"stopped during f2b: {budget.reason}", flush=True)
        return 2
    print("loading eval_search for dev ranking scores", flush=True)
    scorer = _eval_search()
    qrows = [item["qrow"] for item in prepared]
    baseline_rank = ranking_table(scorer, qrows, label_rows, {}, "dev")

    store: Dict[str, List[dict]] = {"f1-title-concepts-p0": f1_records}
    for inp in F2B_INPUTS:
        for rule in F2B_RULES:
            for phrasing in F2B_PHRASINGS:
                sid = f2b_setting_id(inp, rule, phrasing)
                store[sid] = records_for_rule(prepared, table, inp, rule, phrasing)

    tuned_by: Dict[str, Tuned] = {}
    overall_by: Dict[str, dict] = {}
    for sid, records in store.items():
        items = [{"gold": row["gold"], "probs": row["probs"]} for row in records if row.get("gold") in GROUPS]
        tuned = tune_thresholds(items)
        tuned_by[sid] = tuned
        pred_of = _threshold_pred(tuned.thresholds)
        overall, _qrows = score_grouped(
            sid, records, pred_of, prepared, label_rows, scorer, baseline_rank, "dev", _fmt_cuts(tuned.thresholds)
        )
        overall_by[sid] = overall

    coverage_records = _coverage_rows(prepared)
    coverage_items = [
        {"gold": row["gold"], "score": row["score"]}
        for row in coverage_records
        if row.get("gold") in GROUPS
    ]
    _base_tuned, base_floor, base_cuts = tune_coverage(coverage_items)

    def coverage_pred(row: Mapping[str, Any]) -> str:
        return group_from_coverage(float(row["score"]), base_cuts, base_floor)

    coverage_sid = f"concept-coverage/{base_floor}"
    coverage_overall, coverage_questions = score_grouped(
        coverage_sid,
        coverage_records,
        coverage_pred,
        prepared,
        label_rows,
        scorer,
        baseline_rank,
        "dev",
        _fmt_cuts(base_cuts) + f" floor:{base_floor}",
    )
    f2b_rows = [overall_by[sid] for sid in overall_by if sid.startswith("f2b-")]
    chosen_row = dict(pick_f2b(f2b_rows))
    chosen = str(chosen_row["setting"])
    f1_row = overall_by["f1-title-concepts-p0"]
    ranked_ids = [str(row["setting"]) for row in sorted(f2b_rows, key=pick_f2b_key, reverse=True)]
    loo_ids = list(ranked_ids)
    loo_rows = []
    loo_by: Dict[str, dict] = {}
    for sid in loo_ids:
        print(f"loo {sid}", flush=True)
        summary = loo_summary_for(sid, store[sid], prepared, label_rows, scorer, baseline_rank)
        loo_by[sid] = summary
        loo_rows.append(summary)
    print(f"loo {coverage_sid}", flush=True)
    loo_coverage = loo_coverage_summary(
        coverage_sid, coverage_records, prepared, label_rows, scorer, baseline_rank
    )
    loo_by[coverage_sid] = loo_coverage
    loo_rows.append(loo_coverage)
    print("loo f1-title-concepts-p0", flush=True)
    loo_f1 = loo_summary_for(
        "f1-title-concepts-p0", store["f1-title-concepts-p0"], prepared, label_rows, scorer, baseline_rank
    )
    loo_by["f1-title-concepts-p0"] = loo_f1
    loo_rows.append(loo_f1)

    show_ids = [chosen, "f1-title-concepts-p0", coverage_sid]
    question_rows: List[dict] = []
    for sid in show_ids:
        if sid == coverage_sid:
            question_rows.extend(coverage_questions)
            continue
        pred_of = _threshold_pred(tuned_by[sid].thresholds)
        _overall, rows = score_grouped(
            sid, store[sid], pred_of, prepared, label_rows, scorer, baseline_rank, "dev", overall_by[sid]["cuts"]
        )
        question_rows.extend(rows)

    dev_golds = top_golds(prepared)
    support = support_counts(dev_golds)
    n_dev = sum(1 for gold in dev_golds if gold in GROUPS)
    chosen_pairs = _pairs_from(store[chosen], _threshold_pred(tuned_by[chosen].thresholds))
    unsorted_n = sum(1 for _gold, pred in _classified(chosen_pairs) if pred == "not_sorted")
    slot_rows = [
        {
            "question": str(item["question"]["id"]),
            "topic": str(item["question"].get("topic") or ""),
            "checks": _slot_names(item["concepts"]),
        }
        for item in prepared
    ]
    findings_only = ", ".join(
        row["question"] for row in slot_rows if row["checks"] == "findings"
    ) or "none"
    spec = parse_sid(chosen)
    phrasing = spec.phrasing if spec is not None else "p0"
    batch_counts = [
        f2b_batches_per_search(item["concepts"], phrasing) for item in prepared
    ]
    topics = {str(item["question"]["id"]): str(item["question"].get("topic") or "") for item in prepared}
    today = {
        "setting": "lexical_on",
        "n": n_dev,
        "coverage": None,
        "accuracy": None,
        "macro_f1": None,
        "harmful": None,
        "harm_n": "",
        "good_n": "",
        "ndcg@10": baseline_rank.get("ndcg@10"),
        "relevant@10": baseline_rank.get("relevant@10"),
        "d_ndcg": 0.0,
        "d_rel": 0.0,
        "cuts": "",
        "eligible": False,
    }
    overall_rows = [overall_by[sid] for sid in ranked_ids]
    overall_rows.append(f1_row)
    overall_rows.append(coverage_overall)
    overall_rows.append(today)
    dev_info = {
        "chosen_row": chosen_row,
        "base_row": coverage_overall,
        "f1_row": f1_row,
        "loo_chosen": loo_by[chosen],
        "n_dev": n_dev,
        "unsorted_n": unsorted_n,
        "today_ndcg": baseline_rank.get("ndcg@10"),
        "dev_eligible": bool(chosen_row.get("eligible")),
        "batches_full": f2b_batches_per_search(
            QuestionConcepts(actor=("a",), outcome=("o",), population=("p",)),
            phrasing,
        ),
        "batches_min": min(batch_counts) if batch_counts else 0,
        "batches_max": max(batch_counts) if batch_counts else 0,
        "findings_only": findings_only,
    }
    cached_n = sum(1 for entry in log if entry.get("cached"))
    budget_note = (
        f"Experiment budget was {budget.limit} new sidecar batches. "
        f"This run made {budget.used} new batches and reused {cached_n} cached batches. "
        f"Planned batches were {planned}: F1 title-concepts once per question, then two inputs "
        f"and two phrasings for each asked owner-standard check. The three rules reuse those answers."
    )
    support_note = (
        f"{n_dev} dev papers inside the top 30 enter the scores. "
        f"Unclassified gold is excluded. This slice has {support['not_sorted']} of those. "
        f"Answers {support['answers']}, how_why {support['how_why']}, "
        f"context {support['context']}, different {support['different']}. "
        f"Missing abstracts: {sum(item['missing_abstracts'] for item in prepared)}."
    )
    payload = {
        "budget_note": budget_note,
        "support_note": support_note,
        "slot_rows": slot_rows,
        "overall_rows": overall_rows,
        "loo_rows": loo_rows,
        "question_rows": question_rows,
        "latency_note": "Latency was not measured.",
        "recommendation": _recommend_dev(dev_info),
        "chosen": chosen,
        "paths": {
            "results": str(Path(args.results).expanduser()),
            "labels": str(labels_dir),
            "questions": str(Path(args.questions).expanduser()),
        },
        "topics": topics,
        "dev_info": {
            "chosen_row": chosen_row,
            "base_row": coverage_overall,
            "f1_row": f1_row,
            "loo_chosen": loo_by[chosen],
            "loo_f1": loo_f1,
            "loo_coverage": loo_coverage,
            "n_dev": n_dev,
            "unsorted_n": unsorted_n,
            "today_ndcg": baseline_rank.get("ndcg@10"),
            "dev_eligible": bool(chosen_row.get("eligible")),
            "batches_full": dev_info["batches_full"],
            "batches_min": dev_info["batches_min"],
            "batches_max": dev_info["batches_max"],
            "findings_only": findings_only,
            "phrasing": phrasing,
            "support": support,
        },
        "settings": {
            chosen: {
                "thresholds": tuned_by[chosen].thresholds,
                "records": _public_prob_records(store[chosen]),
            },
            "f1-title-concepts-p0": {
                "thresholds": tuned_by["f1-title-concepts-p0"].thresholds,
                "records": _public_prob_records(store["f1-title-concepts-p0"]),
            },
        },
        "coverage_fit": {
            "sid": coverage_sid,
            "cuts": base_cuts,
            "floor": base_floor,
            "records": [
                {"qid": row["qid"], "key": row["key"], "score": row["score"]}
                for row in coverage_records
            ],
        },
    }
    pred_dir = Path(args.pred_dir).expanduser()
    pred_path = pred_dir / f"{chosen}.jsonl"
    _write_predictions(pred_path, store[chosen], tuned_by[chosen].thresholds, _split_index(label_rows))
    print(f"wrote {pred_path}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_round2(payload), encoding="utf-8")
    metrics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {out}", flush=True)
    print(f"chose {chosen}", flush=True)

    if args.latency and spec is not None:
        item = prepared[0]
        texts = fit_states([
            paper_text(paper["title"], paper["abstract"], spec.inp) for paper in item["papers"]
        ])
        slot, target = f2b_slots(item["concepts"])[0]
        options = f2b_options(slot, target, 0)
        instructions = f2b_instruction(str(item["question"]["text"]), slot, target)
        measured = measure_latency(args.laya_url, instructions, options, texts)
        payload["latency_note"] = (
            f"Chosen setting `{chosen}`. Timed one batch of {len(texts)} on {item['question']['id']}, "
            f"check {slot}, input `{spec.inp}`, wording p0. "
            f"A search uses {dev_info['batches_min']} to {dev_info['batches_max']} such batches "
            f"({dev_info['batches_full']} when outcome, actor, population or place, and findings are all asked"
            + (" twice, once per wording" if phrasing == "avg" else "")
            + "). "
            + str(measured.get("detail") or "")
        )
        out.write_text(render_round2(payload), encoding="utf-8")
        metrics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(payload["latency_note"], flush=True)
    return 0


def _attach_gold(records: Sequence[Mapping[str, Any]], gold: Mapping[Tuple[str, str], str]) -> List[dict]:
    attached = []
    for row in records:
        copy = dict(row)
        copy["gold"] = gold.get((str(row["qid"]), str(row["key"])))
        attached.append(copy)
    return attached


def _test_gold(label_rows: Mapping[str, Sequence[Mapping[str, str]]]) -> Dict[Tuple[str, str], str]:
    found: Dict[Tuple[str, str], str] = {}
    for qid, rows in label_rows.items():
        for key, group in gold_for(rows, "test").items():
            found[(str(qid), key)] = group
    return found


def _render_test_section(test: Mapping[str, Any]) -> str:
    lines = [
        "## Test split",
        "",
        "Scored once, with the dev thresholds. The cuts were not fit again.",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | rel@10 | d ndcg | d rel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in test["overall_rows"]:
        lines.append(
            "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm_cell} | "
            "{ndcg} | {rel} | {dndcg} | {drel} |".format(
                setting=row["setting"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                harm_cell=_harm_cell(row),
                ndcg=_fmt(row.get("ndcg@10")),
                rel=_fmt(row.get("relevant@10"), 2),
                dndcg=_fmt(row.get("d_ndcg")),
                drel=_fmt(row.get("d_rel"), 2),
            )
        )
    lines.extend([
        "",
        "Per question for the chosen setting. Health and education rows decide the third gate.",
        "",
        "| setting | question | topic | n | coverage | accuracy | macro-F1 | harmful | ndcg@10 | d ndcg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in test["question_rows"]:
        lines.append(
            "| {setting} | {question} | {topic} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {ndcg} | {dndcg} |".format(
                setting=row["setting"],
                question=row["question"],
                topic=row.get("topic") or "",
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                ndcg=_fmt(row.get("ndcg@10")),
                dndcg=_fmt(row.get("d_ndcg")),
            )
        )
    lines.extend([
        "",
        "## Gate",
        "",
        test["gate_note"],
        "",
    ])
    return "\n".join(lines)


def _splice_test(text: str, section: str, recommendation: str) -> str:
    if "## Test split" in text:
        raise RuntimeError("test section already in the report")
    marker = "## Recommendation"
    block = section
    if marker not in text:
        return text.rstrip() + "\n\n" + block + "\n## Recommendation\n\n" + recommendation + "\n"
    head, _sep, _tail = text.partition(marker)
    return head + block + "\n## Recommendation\n\n" + recommendation + "\n"


def build_test_block(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Score the saved dev choice on the test split. Does not search new thresholds."""
    paths = payload["paths"]
    questions = load_questions(Path(paths["questions"]))
    results = load_results(Path(paths["results"]))
    labels_dir = Path(paths["labels"])
    by_id = {str(row["id"]): row for row in results["questions"]}
    prepared = []
    label_rows: Dict[str, List[dict]] = {}
    for question in questions:
        qid = str(question["id"])
        rows = load_label_rows(labels_dir / f"{qid}.csv")
        label_rows[qid] = rows
        prepared.append({"question": question, "qrow": by_id[qid], "papers": []})
    topics = {str(item["question"]["id"]): str(item["question"].get("topic") or "") for item in prepared}
    gold = _test_gold(label_rows)
    scorer = _eval_search()
    qrows = [item["qrow"] for item in prepared]
    baseline = ranking_table(scorer, qrows, label_rows, {}, "test")
    chosen = str(payload["chosen"])
    saved = payload["settings"][chosen]
    f1_saved = payload["settings"]["f1-title-concepts-p0"]
    coverage_fit = payload["coverage_fit"]
    chosen_records = _attach_gold(saved["records"], gold)
    f1_records = _attach_gold(f1_saved["records"], gold)
    coverage_records = _attach_gold(coverage_fit["records"], gold)
    cuts = coverage_fit["cuts"]
    floor = str(coverage_fit["floor"])

    def coverage_pred(row: Mapping[str, Any]) -> str:
        return group_from_coverage(float(row["score"]), cuts, floor)

    rows_out = []
    question_rows = []
    named = [
        (chosen, chosen_records, _threshold_pred(saved["thresholds"]), "dev thresholds"),
        ("f1-title-concepts-p0", f1_records, _threshold_pred(f1_saved["thresholds"]), "dev thresholds"),
        (
            str(coverage_fit["sid"]),
            coverage_records,
            coverage_pred,
            _fmt_cuts(cuts) + f" floor:{floor}",
        ),
    ]
    summaries = {}
    for sid, records, pred_of, cut_label in named:
        overall, per_q = score_grouped(
            sid, records, pred_of, prepared, label_rows, scorer, baseline, "test", cut_label
        )
        summaries[sid] = overall
        rows_out.append(overall)
        if sid == chosen:
            for row in per_q:
                row["topic"] = topics.get(str(row["question"]), "")
            question_rows = per_q
    today = {
        "setting": "lexical_on",
        "n": summaries[chosen]["n"],
        "coverage": None,
        "accuracy": None,
        "macro_f1": None,
        "harmful": None,
        "harm_n": "",
        "good_n": "",
        "ndcg@10": baseline.get("ndcg@10"),
        "relevant@10": baseline.get("relevant@10"),
        "d_ndcg": 0.0,
        "d_rel": 0.0,
        "cuts": "",
    }
    rows_out.append(today)
    worse = worse_question_ids(question_rows, topics)
    dev = payload["dev_info"]
    verdict = gate_verdict(
        dev_ndcg=_as_float(dev["chosen_row"].get("ndcg@10")),
        dev_base=_as_float(dev["base_row"].get("ndcg@10")),
        test_ndcg=_as_float(summaries[chosen].get("ndcg@10")),
        test_base=_as_float(summaries[str(coverage_fit["sid"])].get("ndcg@10")),
        test_harm=_as_float(summaries[chosen].get("harmful")),
        worse_questions=worse,
    )
    chosen_pairs = _pairs_from(chosen_records, _threshold_pred(saved["thresholds"]))
    unsorted_n = sum(1 for _gold, pred in _classified(chosen_pairs) if pred == "not_sorted")
    test_view = {
        "chosen": summaries[chosen],
        "coverage": summaries[str(coverage_fit["sid"])],
        "f1": summaries["f1-title-concepts-p0"],
        "today_ndcg": baseline.get("ndcg@10"),
        "worse": worse,
        "verdict": verdict,
        "unsorted_n": unsorted_n,
        "overall_rows": rows_out,
        "question_rows": question_rows,
    }
    beats_dev = "yes" if (
        _as_float(dev["chosen_row"].get("ndcg@10")) is not None
        and _as_float(dev["base_row"].get("ndcg@10")) is not None
        and _as_float(dev["chosen_row"].get("ndcg@10")) > _as_float(dev["base_row"].get("ndcg@10"))
    ) else "no"
    beats_test = "yes" if (
        _as_float(summaries[chosen].get("ndcg@10")) is not None
        and _as_float(summaries[str(coverage_fit["sid"])].get("ndcg@10")) is not None
        and _as_float(summaries[chosen].get("ndcg@10")) > _as_float(summaries[str(coverage_fit["sid"])].get("ndcg@10"))
    ) else "no"
    harm_ok = "yes" if (
        _as_float(summaries[chosen].get("harmful")) is not None
        and _as_float(summaries[chosen].get("harmful")) <= HARM_CAP + 1e-12
    ) else "no"
    gate_note = (
        f"Beats concept coverage on dev ndcg@10: {beats_dev}. "
        f"Beats concept coverage on test ndcg@10: {beats_test}. "
        f"Test harmful errors at or below 5%: {harm_ok}. "
        f"Health or education questions worse than today's test order: {', '.join(worse) if worse else 'none'}. "
        f"Verdict: {verdict}."
    )
    test_view["gate_note"] = gate_note
    recommendation = _recommend_final(dev, test_view)
    return {
        "markdown": _render_test_section(test_view),
        "recommendation": recommendation,
        "test": {
            "verdict": verdict,
            "gate_note": gate_note,
            "worse": worse,
            "chosen": summaries[chosen],
            "coverage": summaries[str(coverage_fit["sid"])],
            "f1": summaries["f1-title-concepts-p0"],
            "today_ndcg": baseline.get("ndcg@10"),
            "unsorted_n": unsorted_n,
            "question_rows": question_rows,
        },
    }


def execute_score_test(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser()
    metrics_path = out.with_suffix(".json")
    stamp = Path(str(out) + ".test-stamp.json")
    if not metrics_path.is_file():
        print(f"missing dev metrics {metrics_path}", flush=True)
        return 2
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    if payload.get("test"):
        print(f"test split already scored in {metrics_path}", flush=True)
        return 3
    if "## Test split" in out.read_text(encoding="utf-8"):
        print(f"test section already in {out}", flush=True)
        return 3
    chosen = str(payload.get("chosen") or "")
    if not chosen:
        print("dev run did not choose a setting", flush=True)
        return 2
    if not claim_test_stamp(stamp, chosen):
        print(f"test split already scored: {stamp}", flush=True)
        return 3
    try:
        block = build_test_block(payload)
        new_md = _splice_test(out.read_text(encoding="utf-8"), block["markdown"], block["recommendation"])
        new_payload = dict(payload)
        new_payload["test"] = block["test"]
        new_payload["recommendation"] = block["recommendation"]
        metrics_tmp = Path(str(metrics_path) + ".tmp")
        md_tmp = Path(str(out) + ".tmp")
        metrics_tmp.write_text(json.dumps(new_payload, indent=2), encoding="utf-8")
        md_tmp.write_text(new_md, encoding="utf-8")
        os.replace(md_tmp, out)
        os.replace(metrics_tmp, metrics_path)
    except Exception:
        if stamp.exists():
            stamp.unlink()
        raise
    print(f"wrote {out}", flush=True)
    print(f"gate {block['test']['verdict']}", flush=True)
    return 0


FT_SETTING = "ft-two-choice"
LAYA_PYTHON = Path.home() / ".local/share/laya-0.4.17/bin/python"
FT_INSTRUCTIONS = (
    "Which relevance group is this paper in? "
    "answers means it reports results on the question's outcome, and its population or place is not contradicted. "
    "how_why explains a mechanism or an implementation. "
    "context is experience, background, or setting. "
    "different is a related subject or incidental."
)
FT_CRITERIA = {
    "answers": "Reports results on the question's outcome, and its population or place is not contradicted.",
    "how_why": "Explains a mechanism or how something is implemented.",
    "context": "Experience, context, or background for the question.",
    "different": "Related subject or incidental to the question.",
}
# Published round-2 score. run-ft does not call that model again.
ROUND2_F2 = {
    "setting": "f2b-full-outcome-p0",
    "dev": {
        "n": 271, "coverage": 0.631, "accuracy": 0.485, "macro_f1": 0.354,
        "harmful": 0.050, "harm_n": "5/101", "ndcg@10": 0.431, "relevant@10": 3.07,
        "d_ndcg": 0.034, "d_rel": 0.27,
    },
    "test": {
        "n": 169, "coverage": 0.598, "accuracy": 0.386, "macro_f1": 0.277,
        "harmful": 0.052, "harm_n": "3/58", "ndcg@10": 0.418, "relevant@10": 1.80,
        "d_ndcg": -0.158, "d_rel": -0.60,
    },
}


def group_question() -> Dict[str, Any]:
    """The single choice question used to train and score the fine-tune."""
    return {"type": "choice", "instructions": FT_INSTRUCTIONS, "criteria": dict(FT_CRITERIA)}


def group_state(question: str, title: str, abstract: str) -> str:
    """State text: the question, the title, and the abstract span already chosen."""
    title_s = " ".join((title or "").split()) or "(no title)"
    abstract_s = " ".join((abstract or "").split())
    return f"Question: {question.strip()}\nTitle: {title_s}\nAbstract: {abstract_s}"


def ft_states(prepared: Sequence[Mapping[str, Any]]) -> List[dict]:
    """One state per top-30 paper. The abstract span is the first two sentences."""
    rows = []
    for item in prepared:
        question = str(item["question"]["text"])
        qid = str(item["question"]["id"])
        for paper in item["papers"]:
            lead = first_sentences(str(paper.get("abstract") or ""), 2)
            rows.append({
                "qid": qid,
                "key": str(paper.get("key") or ""),
                "state": group_state(question, str(paper.get("title") or ""), lead),
            })
    return rows


def rows_from_predict(results: Sequence[Mapping[str, Any]], question_id: str = "group") -> List[dict]:
    """Map ``Agent.predict_batch`` results to the choice-row shape the scorer uses."""
    rows = []
    for result in results:
        answers = result.get("answers") if isinstance(result, Mapping) else None
        answer = answers.get(question_id) if isinstance(answers, Mapping) else None
        if not isinstance(answer, Mapping):
            raise RuntimeError("local checkpoint returned no group answer")
        raw = answer.get("probabilities")
        probs = {}
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    probs[str(key)] = float(value)
        choice = answer.get("choice")
        rows.append({
            "choice": choice,
            "p": float(probs.get(str(choice), 0.0)),
            "probabilities": probs,
        })
    return rows


def answers_tag_precision(
    records: Sequence[Mapping[str, Any]], minimum: float = 0.8,
) -> Dict[str, Any]:
    """Precision of an answers tag when P(answers) is at least ``minimum``.

    Papers with no gold label are ignored. ``not_sorted`` gold counts as a miss.
    """
    flagged = []
    for row in records:
        gold = row.get("gold")
        if gold not in GROUPS and gold != "not_sorted":
            continue
        probability = float((row.get("probs") or {}).get("answers", 0.0))
        if probability + 1e-12 >= minimum:
            flagged.append(gold == "answers")
    count = len(flagged)
    hits = sum(1 for hit in flagged if hit)
    return {
        "precision": (hits / count) if count else None,
        "tp": hits,
        "flagged": count,
        "minimum": minimum,
    }


def predict_local(
    checkpoint: Path,
    states: Sequence[Mapping[str, Any]],
    batch_size: int = 8,
    latency_n: int = 30,
) -> Dict[str, Any]:
    """Score states with a local Laya checkpoint. Does not open a network port."""
    for key, value in (("HF_HUB_OFFLINE", "1"), ("TRANSFORMERS_OFFLINE", "1")):
        os.environ[key] = value
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from laya import load

    texts = [str(row["state"]) for row in states]
    questions = {"group": group_question()}
    started = time.perf_counter()
    agent = load(str(checkpoint))
    load_ms = (time.perf_counter() - started) * 1000.0
    latency: Dict[str, Any] = {
        "load_ms": round(load_ms, 1),
        "cold_ms": None,
        "warm_ms": [],
        "warm_median_ms": None,
        "batch": min(latency_n, len(texts)),
    }
    filled: List[Optional[dict]] = [None] * len(states)

    def fill(indexes: Sequence[int]) -> List[dict]:
        chunk = [texts[index] for index in indexes]
        predicted = agent.predict_batch(chunk, questions, batch_size=max(1, len(chunk)))
        mapped = rows_from_predict(predicted)
        if len(mapped) != len(indexes):
            raise RuntimeError("local checkpoint row count does not match states")
        for index, row in zip(indexes, mapped):
            filled[index] = row
        return mapped

    n_lat = min(latency_n, len(texts))
    if n_lat:
        fill(range(n_lat))
        latency["cold_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        warm = []
        for _ in range(5):
            tick = time.perf_counter()
            agent.predict_batch(list(texts[:n_lat]), questions, batch_size=n_lat)
            warm.append((time.perf_counter() - tick) * 1000.0)
        latency["warm_ms"] = [round(value, 1) for value in warm]
        latency["warm_median_ms"] = round(sorted(warm)[len(warm) // 2], 1)
    rest = list(range(n_lat, len(texts)))
    step = max(1, batch_size)
    for start in range(0, len(rest), step):
        fill(rest[start:start + step])
    packed = []
    for row, pred in zip(states, filled):
        if pred is None:
            raise RuntimeError("missing local prediction")
        packed.append({
            "qid": row["qid"],
            "key": row["key"],
            "choice": pred["choice"],
            "p": pred["p"],
            "probabilities": pred["probabilities"],
        })
    return {"checkpoint": str(checkpoint), "latency": latency, "rows": packed}


def _join_ft_records(
    prepared: Sequence[Mapping[str, Any]], predicted: Sequence[Mapping[str, Any]],
) -> List[dict]:
    by_pair = {(str(row["qid"]), str(row["key"])): row for row in predicted}
    records = []
    for item in prepared:
        qid = str(item["question"]["id"])
        for paper in item["papers"]:
            got = by_pair[(qid, str(paper["key"]))]
            probs = to_group_probs("choice", got.get("probabilities") or {})
            records.append(_record(item, paper, probs))
    return records


def _coverage_records(prepared: Sequence[Mapping[str, Any]]) -> Tuple[List[dict], str, Dict[str, float]]:
    records = []
    items = []
    for item in prepared:
        qid = str(item["question"]["id"])
        for paper in item["papers"]:
            score = concept_coverage(item["concepts"], paper["title"], paper["abstract"])
            gold = item["gold"].get(paper["key"])
            records.append({
                "qid": qid,
                "key": paper["key"],
                "gold": gold,
                "score": score,
                "probs": {},
            })
            if gold in GROUPS:
                items.append({"gold": gold, "score": score})
    _tuned, floor, cuts = tune_coverage(items)
    return records, floor, dict(cuts)


def _public_ft_records(records: Sequence[Mapping[str, Any]]) -> List[dict]:
    return [
        {
            "qid": str(row["qid"]),
            "key": str(row["key"]),
            "probs": {group: float(row["probs"].get(group, 0.0)) for group in GROUPS},
        }
        for row in records
    ]


def _public_coverage_records(records: Sequence[Mapping[str, Any]]) -> List[dict]:
    return [
        {"qid": str(row["qid"]), "key": str(row["key"]), "score": float(row["score"])}
        for row in records
    ]


def _table_line(row: Mapping[str, Any]) -> str:
    harm = row.get("harm_cell")
    if harm is None:
        harm = _harm_cell(row)
    return (
        "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm} | "
        "{ndcg} | {rel} | {dndcg} | {drel} |"
    ).format(
        setting=row.get("setting") or "",
        n="" if row.get("n") is None else row.get("n"),
        coverage=_fmt(row.get("coverage")),
        accuracy=_fmt(row.get("accuracy")),
        macro_f1=_fmt(row.get("macro_f1")),
        harmful=_fmt(row.get("harmful")),
        harm=harm or "",
        ndcg=_fmt(row.get("ndcg@10")),
        rel=_fmt(row.get("relevant@10"), 2),
        dndcg=_fmt(row.get("d_ndcg")),
        drel=_fmt(row.get("d_rel"), 2),
    )


def _reference_line(split: str) -> str:
    row = dict(ROUND2_F2[split])
    row["setting"] = ROUND2_F2["setting"] + " (round 2, not re-run)"
    row["harm_cell"] = row.pop("harm_n")
    row["good_n"] = ""
    return _table_line(row)


def render_ft_dev(payload: Mapping[str, Any]) -> str:
    info = payload["dev_info"]
    lines = [
        "# Fine-tuned Laya relevance groups",
        "",
        "Dev labels only. This file does not score the test split until score-ft-test runs.",
        "The fine-tune asks one choice question. Round 2's best setting is copied from the published dev table and is not re-run.",
        "",
        "## Dev",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | rel@10 | d ndcg | d rel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in info["overall_rows"]:
        lines.append(_table_line(row))
    lines.append(_reference_line("dev"))
    lines.extend([
        "",
        "## Leave-one-question-out",
        "",
        "Thresholds for the fine-tune and for concept coverage were fit without that row's question.",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | d ndcg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in info["loo_rows"]:
        lines.append(
            "| {setting} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {harm} | {ndcg} | {dndcg} |".format(
                setting=row["setting"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                harm=_harm_cell(row),
                ndcg=_fmt(row.get("ndcg@10")),
                dndcg=_fmt(row.get("d_ndcg")),
            )
        )
    lines.extend([
        "",
        "## Per question",
        "",
        "| setting | question | n | coverage | accuracy | macro-F1 | harmful | ndcg@10 | d ndcg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in info["question_rows"]:
        lines.append(
            "| {setting} | {question} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {ndcg} | {dndcg} |".format(
                setting=row["setting"],
                question=row["question"],
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                ndcg=_fmt(row.get("ndcg@10")),
                dndcg=_fmt(row.get("d_ndcg")),
            )
        )
    tag = info["tag_precision"]
    latency = info.get("latency") or {}
    lines.extend([
        "",
        "## Tag",
        "",
        (
            f"Dev precision of answers at P(answers) >= {tag['minimum']}: "
            f"{_fmt(tag.get('precision'))} ({tag['tp']}/{tag['flagged']})."
        ),
        "",
        "## Latency",
        "",
        (
            f"Cold wall time, including checkpoint load plus one batch of {latency.get('batch')}, "
            f"was {_fmt(latency.get('cold_ms'), 0)} ms. "
            f"Five warm runs of that batch: {', '.join(str(v) for v in latency.get('warm_ms') or [])} ms. "
            f"Median warm run {_fmt(latency.get('warm_median_ms'), 0)} ms."
        ),
        "",
        "## Recommendation",
        "",
        "Dev thresholds are fit. The test split is not scored in this file.",
        "",
    ])
    return "\n".join(lines)


def _run_checkpoint_predict(args: argparse.Namespace, states: Sequence[dict], out_path: Path) -> Dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = out_path.with_suffix(".states.json")
    state_path.write_text(json.dumps(states), encoding="utf-8")
    cmd = [
        "nice", "-n", "10", str(args.laya_python), str(Path(__file__).resolve()),
        "predict-local",
        "--checkpoint", str(args.checkpoint),
        "--states", str(state_path),
        "--out", str(out_path),
        "--batch-size", str(args.batch_size),
    ]
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["OMP_NUM_THREADS"] = "4"
    subprocess.check_call(cmd, env=env)
    return json.loads(out_path.read_text(encoding="utf-8"))


def execute_predict_local(args: argparse.Namespace) -> int:
    states = json.loads(Path(args.states).read_text(encoding="utf-8"))
    payload = predict_local(Path(args.checkpoint), states, batch_size=args.batch_size)
    Path(args.out).write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {args.out} rows={len(payload['rows'])}", flush=True)
    return 0


def execute_run_ft(args: argparse.Namespace) -> int:
    questions = load_questions(Path(args.questions))
    results = load_results(Path(args.results))
    prepared, label_rows = prepare_eval(
        questions, results, Path(args.corpus), Path(args.labels),
    )
    states = ft_states(prepared)
    pred_path = Path(args.predictions)
    if args.reuse_predictions and pred_path.is_file():
        predicted = json.loads(pred_path.read_text(encoding="utf-8"))
        if str(predicted.get("checkpoint") or "") != str(Path(args.checkpoint)):
            print("predictions file is for a different checkpoint; refusing to reuse", flush=True)
            return 2
    else:
        predicted = _run_checkpoint_predict(args, states, pred_path)
    records = _join_ft_records(prepared, predicted["rows"])
    items = [{"gold": row["gold"], "probs": row["probs"]} for row in records if row.get("gold") in GROUPS]
    tuned = tune_thresholds(items)
    print("loading eval_search for dev ranking scores", flush=True)
    scorer = _eval_search()
    qrows = [item["qrow"] for item in prepared]
    baseline = ranking_table(scorer, qrows, label_rows, {})
    pred_of = _threshold_pred(tuned.thresholds)
    overall, per_q = score_grouped(
        FT_SETTING, records, pred_of, prepared, label_rows, scorer, baseline, "dev",
        _fmt_cuts(tuned.thresholds),
    )
    loo = loo_summary_for(FT_SETTING, records, prepared, label_rows, scorer, baseline)
    cov_records, floor, cuts = _coverage_records(prepared)
    cov_sid = f"concept-coverage/{floor}"

    def cov_pred(row: Mapping[str, Any]) -> str:
        return group_from_coverage(float(row["score"]), cuts, floor)

    cov_overall, cov_q = score_grouped(
        cov_sid, cov_records, cov_pred, prepared, label_rows, scorer, baseline, "dev",
        _fmt_cuts(cuts) + f" floor:{floor}",
    )
    loo_cov = loo_coverage_summary(cov_sid, cov_records, prepared, label_rows, scorer, baseline)
    today = {
        "setting": "lexical_on",
        "n": overall["n"],
        "coverage": None,
        "accuracy": None,
        "macro_f1": None,
        "harmful": None,
        "harm_n": "",
        "good_n": "",
        "ndcg@10": baseline.get("ndcg@10"),
        "relevant@10": baseline.get("relevant@10"),
        "d_ndcg": 0.0,
        "d_rel": 0.0,
    }
    qids = [str(item["question"]["id"]) for item in prepared]
    payload = {
        "chosen": FT_SETTING,
        "checkpoint": str(Path(args.checkpoint)),
        "paths": {
            "questions": str(args.questions),
            "results": str(args.results),
            "labels": str(args.labels),
            "corpus": str(args.corpus),
        },
        "settings": {
            FT_SETTING: {
                "thresholds": {group: float(tuned.thresholds[group]) for group in GROUPS},
                "records": _public_ft_records(records),
            }
        },
        "coverage_fit": {
            "sid": cov_sid,
            "floor": floor,
            "cuts": {group: float(cuts[group]) for group in cuts},
            "records": _public_coverage_records(cov_records),
        },
        "dev_info": {
            "chosen_row": overall,
            "base_row": cov_overall,
            "overall_rows": [overall, cov_overall, today],
            "loo_rows": [loo, loo_cov],
            "question_rows": [row for row in per_q + cov_q if row["setting"] in {FT_SETTING, cov_sid}],
            "tag_precision": answers_tag_precision(records),
            "latency": predicted.get("latency") or {},
            "support": support_counts(top_golds(prepared)),
            "qids": qids,
            "cuts": _fmt_cuts(tuned.thresholds),
        },
        "round2_f2": ROUND2_F2,
        "test": None,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render_ft_dev(payload)
    out.write_text(text, encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {out}", flush=True)
    print(
        f"dev ndcg {_fmt(overall.get('ndcg@10'))} coverage {_fmt(cov_overall.get('ndcg@10'))} "
        f"harm {_fmt(overall.get('harmful'))}",
        flush=True,
    )
    return 0


def build_ft_test(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Score the saved fine-tune on the test split. Does not load a checkpoint."""
    paths = payload["paths"]
    questions = load_questions(Path(paths["questions"]))
    results = load_results(Path(paths["results"]))
    labels_dir = Path(paths["labels"])
    by_id = {str(row["id"]): row for row in results["questions"]}
    prepared = []
    label_rows: Dict[str, List[dict]] = {}
    for question in questions:
        qid = str(question["id"])
        rows = load_label_rows(labels_dir / f"{qid}.csv")
        label_rows[qid] = rows
        prepared.append({"question": question, "qrow": by_id[qid], "papers": []})
    topics = {str(item["question"]["id"]): str(item["question"].get("topic") or "") for item in prepared}
    gold = _test_gold(label_rows)
    scorer = _eval_search()
    qrows = [item["qrow"] for item in prepared]
    baseline = ranking_table(scorer, qrows, label_rows, {}, "test")
    chosen = str(payload["chosen"])
    saved = payload["settings"][chosen]
    thresholds = saved["thresholds"]
    ft_records = _attach_gold(saved["records"], gold)
    coverage = payload["coverage_fit"]
    cov_records = _attach_gold(coverage["records"], gold)
    cuts = coverage["cuts"]
    floor = str(coverage["floor"])
    cov_sid = str(coverage["sid"])

    def cov_pred(row: Mapping[str, Any]) -> str:
        return group_from_coverage(float(row["score"]), cuts, floor)

    ft_overall, ft_q = score_grouped(
        chosen, ft_records, _threshold_pred(thresholds), prepared, label_rows, scorer,
        baseline, "test", "dev thresholds",
    )
    cov_overall, _cov_q = score_grouped(
        cov_sid, cov_records, cov_pred, prepared, label_rows, scorer, baseline, "test",
        _fmt_cuts(cuts) + f" floor:{floor}",
    )
    for row in ft_q:
        row["topic"] = topics.get(str(row["question"]), "")
    today = {
        "setting": "lexical_on",
        "n": ft_overall["n"],
        "coverage": None,
        "accuracy": None,
        "macro_f1": None,
        "harmful": None,
        "harm_n": "",
        "good_n": "",
        "ndcg@10": baseline.get("ndcg@10"),
        "relevant@10": baseline.get("relevant@10"),
        "d_ndcg": 0.0,
        "d_rel": 0.0,
    }
    worse = worse_question_ids(ft_q, topics)
    dev = payload["dev_info"]
    verdict = gate_verdict(
        dev_ndcg=_as_float(dev["chosen_row"].get("ndcg@10")),
        dev_base=_as_float(dev["base_row"].get("ndcg@10")),
        test_ndcg=_as_float(ft_overall.get("ndcg@10")),
        test_base=_as_float(cov_overall.get("ndcg@10")),
        test_harm=_as_float(ft_overall.get("harmful")),
        worse_questions=worse,
    )
    tag = answers_tag_precision(ft_records)
    beats_dev = "yes" if (
        _as_float(dev["chosen_row"].get("ndcg@10")) is not None
        and _as_float(dev["base_row"].get("ndcg@10")) is not None
        and _as_float(dev["chosen_row"].get("ndcg@10")) > _as_float(dev["base_row"].get("ndcg@10"))
    ) else "no"
    beats_test = "yes" if (
        _as_float(ft_overall.get("ndcg@10")) is not None
        and _as_float(cov_overall.get("ndcg@10")) is not None
        and _as_float(ft_overall.get("ndcg@10")) > _as_float(cov_overall.get("ndcg@10"))
    ) else "no"
    harm_ok = "yes" if (
        _as_float(ft_overall.get("harmful")) is not None
        and _as_float(ft_overall.get("harmful")) <= HARM_CAP + 1e-12
    ) else "no"
    gate_note = (
        f"Beats concept coverage on dev ndcg@10: {beats_dev}. "
        f"Beats concept coverage on test ndcg@10: {beats_test}. "
        f"Test harmful errors at or below 5%: {harm_ok}. "
        f"Health or education questions worse than today's test order: {', '.join(worse) if worse else 'none'}. "
        f"Verdict: {verdict}."
    )
    test_view = {
        "overall_rows": [ft_overall, cov_overall, today],
        "question_rows": ft_q,
        "gate_note": gate_note,
        "tag_precision": tag,
        "verdict": verdict,
        "worse": worse,
        "chosen": ft_overall,
        "coverage": cov_overall,
        "today_ndcg": baseline.get("ndcg@10"),
    }
    lines = [
        "## Test split",
        "",
        "Scored once, with the dev thresholds. The cuts were not fit again. The checkpoint was not loaded again.",
        "",
        "| setting | n | coverage | accuracy | macro-F1 | harmful | harm n | ndcg@10 | rel@10 | d ndcg | d rel |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in test_view["overall_rows"]:
        lines.append(_table_line(row))
    lines.append(_reference_line("test"))
    lines.extend([
        "",
        "Per question for the chosen setting. Health and education rows decide the third gate.",
        "",
        "| setting | question | topic | n | coverage | accuracy | macro-F1 | harmful | ndcg@10 | d ndcg |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in ft_q:
        lines.append(
            "| {setting} | {question} | {topic} | {n} | {coverage} | {accuracy} | {macro_f1} | {harmful} | {ndcg} | {dndcg} |".format(
                setting=row["setting"],
                question=row["question"],
                topic=row.get("topic") or "",
                n=row.get("n") if row.get("n") is not None else "",
                coverage=_fmt(row.get("coverage")),
                accuracy=_fmt(row.get("accuracy")),
                macro_f1=_fmt(row.get("macro_f1")),
                harmful=_fmt(row.get("harmful")),
                ndcg=_fmt(row.get("ndcg@10")),
                dndcg=_fmt(row.get("d_ndcg")),
            )
        )
    lines.extend([
        "",
        (
            f"Test precision of answers at P(answers) >= {tag['minimum']}: "
            f"{_fmt(tag.get('precision'))} ({tag['tp']}/{tag['flagged']})."
        ),
        "",
        "## Gate",
        "",
        gate_note,
        "",
    ])
    recommendation = (
        f"The fine-tuned setting is {chosen}. "
        f"Dev ndcg@10 was {_fmt(dev['chosen_row'].get('ndcg@10'))} against concept coverage "
        f"{_fmt(dev['base_row'].get('ndcg@10'))}. "
        f"The one test score had ndcg@10 {_fmt(ft_overall.get('ndcg@10'))} against concept coverage "
        f"{_fmt(cov_overall.get('ndcg@10'))} and today's {_fmt(baseline.get('ndcg@10'))}, "
        f"with harmful errors {_fmt(ft_overall.get('harmful'))}. "
        f"Health and education questions behind today's test order: {', '.join(worse) if worse else 'none'}. "
        f"Gate verdict: {verdict}."
    )
    return {
        "markdown": "\n".join(lines) + "\n",
        "recommendation": recommendation,
        "test": {
            "verdict": verdict,
            "gate_note": gate_note,
            "worse": worse,
            "chosen": ft_overall,
            "coverage": cov_overall,
            "today_ndcg": baseline.get("ndcg@10"),
            "tag_precision": tag,
            "question_rows": ft_q,
        },
    }


def execute_score_ft_test(args: argparse.Namespace) -> int:
    out = Path(args.out).expanduser()
    metrics_path = out.with_suffix(".json")
    stamp = Path(str(out) + ".test-stamp.json")
    if not metrics_path.is_file():
        print(f"missing dev metrics {metrics_path}", flush=True)
        return 2
    if not out.is_file():
        print(f"missing dev report {out}", flush=True)
        return 2
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    if payload.get("test"):
        print(f"test split already scored in {metrics_path}", flush=True)
        return 3
    if "## Test split" in out.read_text(encoding="utf-8"):
        print(f"test section already in {out}", flush=True)
        return 3
    chosen = str(payload.get("chosen") or "")
    if not chosen:
        print("dev run did not choose a setting", flush=True)
        return 2
    if not claim_test_stamp(stamp, chosen):
        print(f"test split already scored: {stamp}", flush=True)
        return 3
    # The stamp stays even if a later step fails: the test labels have been read.
    block = build_ft_test(payload)
    new_md = _splice_test(out.read_text(encoding="utf-8"), block["markdown"], block["recommendation"])
    new_payload = dict(payload)
    new_payload["test"] = block["test"]
    new_payload["recommendation"] = block["recommendation"]
    metrics_tmp = Path(str(metrics_path) + ".tmp")
    md_tmp = Path(str(out) + ".tmp")
    metrics_tmp.write_text(json.dumps(new_payload), encoding="utf-8")
    md_tmp.write_text(new_md, encoding="utf-8")
    os.replace(md_tmp, out)
    os.replace(metrics_tmp, metrics_path)
    print(f"wrote {out}", flush=True)
    print(f"gate {block['test']['verdict']}", flush=True)
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
    f2 = sub.add_parser("run-f2", help="Owner-standard yes/no groups on the dev split")
    f2.add_argument("--corpus", default=str(scratch / "baseline_v2"))
    f2.add_argument("--results", default=str(scratch / "baseline_v2_results.json"))
    f2.add_argument("--labels", default=str(scratch / "labels_final_v2"))
    f2.add_argument("--questions", default=str(scratch / "v2" / "questions_all.json"))
    f2.add_argument("--out", default=str(scratch / "p25b_results.md"))
    f2.add_argument("--pred-dir", default=str(scratch / "p25b_predictions"))
    f2.add_argument("--cache", default=str(scratch / "p25b_cache.json"))
    f2.add_argument("--laya-url", default=LAYA_URL)
    f2.add_argument("--budget", type=int, default=F2B_BUDGET)
    f2.add_argument("--latency", action=argparse.BooleanOptionalAction, default=True)
    f2.set_defaults(func=execute_round2)
    score = sub.add_parser("score-test", help="Score the saved dev choice on the test split once")
    score.add_argument("--out", default=str(scratch / "p25b_results.md"))
    score.set_defaults(func=execute_score_test)
    ft = sub.add_parser("run-ft", help="Score a local checkpoint on the dev split")
    ft.add_argument("--checkpoint", required=True)
    ft.add_argument("--corpus", default=str(scratch / "baseline_v2"))
    ft.add_argument("--results", default=str(scratch / "baseline_v2_results.json"))
    ft.add_argument("--labels", default=str(scratch / "labels_final_v2"))
    ft.add_argument("--questions", default=str(scratch / "v2" / "questions_all.json"))
    ft.add_argument("--out", default=str(scratch / "p25c_results.md"))
    ft.add_argument("--predictions", default=str(scratch / "p25c_predictions.json"))
    ft.add_argument("--reuse-predictions", action="store_true")
    ft.add_argument("--laya-python", default=str(LAYA_PYTHON))
    ft.add_argument("--batch-size", type=int, default=8)
    ft.set_defaults(func=execute_run_ft)
    ft_score = sub.add_parser("score-ft-test", help="Score the fine-tune on the test split once")
    ft_score.add_argument("--out", default=str(scratch / "p25c_results.md"))
    ft_score.set_defaults(func=execute_score_ft_test)
    local = sub.add_parser("predict-local", help="Write group probabilities for a local checkpoint")
    local.add_argument("--checkpoint", required=True)
    local.add_argument("--states", required=True)
    local.add_argument("--out", required=True)
    local.add_argument("--batch-size", type=int, default=8)
    local.set_defaults(func=execute_predict_local)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
