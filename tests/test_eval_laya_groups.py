"""Unit tests for Laya relevance-group mapping. No network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from app.services.question_concepts import QuestionConcepts

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "eval_laya_groups", REPO / "tools" / "eval_laya_groups.py"
)
ev = importlib.util.module_from_spec(_spec)
sys.modules["eval_laya_groups"] = ev
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(ev)


def test_category_to_group_covers_the_seven_labels():
    assert ev.category_to_group("direct_answer") == "answers"
    assert ev.category_to_group("mechanism_or_implementation") == "how_why"
    assert ev.category_to_group("experience_or_context") == "context"
    assert ev.category_to_group("background") == "context"
    assert ev.category_to_group("related_subject") == "different"
    assert ev.category_to_group("incidental") == "different"
    assert ev.category_to_group("unclassified") == "not_sorted"
    assert ev.category_to_group("not_a_label") is None


def test_f2_cells_at_the_corners():
    assert ev.combine_f2(1, 1, 1)["answers"] == pytest.approx(1)
    assert ev.combine_f2(1, 1, 0)["how_why"] == pytest.approx(1)
    assert ev.combine_f2(1, 0, 1)["context"] == pytest.approx(1)
    assert ev.combine_f2(0, 1, 1)["context"] == pytest.approx(1)
    assert ev.combine_f2(0, 0, 1)["context"] == pytest.approx(1)
    assert ev.combine_f2(1, 0, 0)["different"] == pytest.approx(1)
    assert ev.combine_f2(0, 1, 0)["different"] == pytest.approx(1)
    assert ev.combine_f2(0, 0, 0)["different"] == pytest.approx(1)


def test_f2_missing_slot_and_probability_sum():
    missing_outcome = ev.combine_f2(1, None, 1)
    assert missing_outcome["answers"] == pytest.approx(1)
    assert missing_outcome["how_why"] == pytest.approx(0)
    assert ev.combine_f2(1, None, 0)["different"] == pytest.approx(1)
    assert ev.combine_f2(0, None, 1)["context"] == pytest.approx(1)
    assert ev.combine_f2(1, 1, None)["answers"] == pytest.approx(1)
    assert ev.combine_f2(1, 0, None)["context"] == pytest.approx(1)
    assert ev.combine_f2(None, None, 1)["context"] == pytest.approx(1)
    assert ev.combine_f2(None, None, 0)["different"] == pytest.approx(1)
    assert ev.combine_f2(None, None, None) == {group: 0.0 for group in ev.GROUPS}
    soft = ev.combine_f2(0.9, 0.8, 0.3)
    assert sum(soft.values()) == pytest.approx(1.0)
    assert soft["how_why"] > soft["answers"]


def test_threshold_below_cutoff_is_not_sorted_never_different():
    probs = {"answers": 0.2, "how_why": 0.2, "context": 0.2, "different": 0.4}
    blocked = {group: 0.5 for group in ev.GROUPS}
    assert ev.apply_thresholds(probs, blocked) == "not_sorted"
    allowed = dict(blocked)
    allowed["different"] = 0.4
    assert ev.apply_thresholds(probs, allowed) == "different"
    answers = {"answers": 0.42, "how_why": 0.2, "context": 0.2, "different": 0.18}
    assert ev.apply_thresholds(answers, {"answers": 0.35, "how_why": 0.5, "context": 0.5, "different": 0.5}) == "answers"
    assert ev.apply_thresholds(answers, {"answers": 0.50, "how_why": 0.5, "context": 0.5, "different": 0.5}) == "not_sorted"


def test_metrics_drop_unclassified_and_count_harm():
    pairs = [
        ("not_sorted", "different"),
        ("answers", "answers"),
        ("answers", "different"),
        ("answers", "not_sorted"),
        ("how_why", "context"),
    ]
    assert ev.accuracy(pairs) == pytest.approx(1 / 3)
    assert ev.coverage(pairs) == pytest.approx(0.75)
    assert ev.harmful_rate(pairs) == pytest.approx(0.25)
    assert ev.harmful_counts(pairs) == (1, 4)
    # Both how_why rows in a slice that abstains produce F1 0, not a skipped class.
    abstain = [("how_why", "not_sorted"), ("how_why", "not_sorted")]
    assert ev.class_f1(abstain, "how_why") == 0.0
    assert ev.class_f1([("answers", "answers")], "how_why") is None


def test_dev_gold_ignores_test_rows():
    rows = [
        {"key": "a", "labeller": "panel", "category": "direct_answer", "split": "dev"},
        {"key": "b", "labeller": "panel", "category": "direct_answer", "split": "test"},
        {"key": "c", "labeller": "panel", "category": "unclassified", "split": "dev"},
        {"key": "d", "labeller": "owner", "category": "background", "split": "dev"},
        {"key": "a", "labeller": "owner", "category": "incidental", "split": "dev"},
        {"key": "e", "labeller": "owner", "category": "unclassified", "split": "dev"},
        {"key": "f", "labeller": "owner", "category": "direct_answer", "split": "test"},
    ]
    gold = ev.dev_gold_for(rows)
    assert gold == {"a": "different", "d": "context", "e": "not_sorted"}
    assert "b" not in gold
    assert "c" not in gold
    assert "f" not in gold


def test_concept_coverage_phrase_share():
    concepts = QuestionConcepts(
        actor=("later school start times",),
        outcome=("sleep duration",),
        population=("adolescents",),
    )
    full = "Later school start times and sleep duration in adolescents"
    assert ev.concept_coverage(concepts, full, "") == pytest.approx(1.0)
    assert ev.concept_coverage(concepts, "Adolescents and homework", "") == pytest.approx(1 / 3)
    assert ev.concept_coverage(concepts, "Volcano chemistry", "") == pytest.approx(0.0)
    us = QuestionConcepts(actor=("U.S. government",), outcome=("society",), population=())
    assert ev.concept_coverage(us, "US government and society", "") == pytest.approx(1.0)


def test_coverage_floor_can_stay_unsorted():
    cuts = {"answers": 0.67, "how_why": 0.51, "context": 0.34}
    assert ev.group_from_coverage(1.0, cuts, "not_sorted") == "answers"
    assert ev.group_from_coverage(0.5, cuts, "not_sorted") == "context"
    assert ev.group_from_coverage(0.0, cuts, "not_sorted") == "not_sorted"
    assert ev.group_from_coverage(0.0, cuts, "different") == "different"


def test_mock_laya_f1_and_f2_average():
    def caller(instructions, options, states):
        assert states == ["Paper one"]
        if "yes" in options:
            return [{"choice": "yes", "p": 0.8, "probabilities": {"yes": 0.8, "no": 0.2}}]
        return [{
            "choice": "answers",
            "p": 0.91,
            "probabilities": {"answers": 0.91, "how_why": 0.03, "context": 0.03, "different": 0.03},
        }]

    concepts = QuestionConcepts(
        actor=("later school start times",),
        outcome=("sleep duration",),
        population=("adolescents",),
    )
    question = {"id": "Q4", "text": "How do later school start times affect sleep duration among adolescents?"}
    f1 = ev.run_spec_on_question(ev.Spec("f1", "title", "concepts", "p0"), question, concepts, ["Paper one"], caller)
    assert f1 is not None
    assert f1[0]["probs"]["answers"] == pytest.approx(0.91)
    thresholds = {group: 0.5 for group in ev.GROUPS}
    assert ev.apply_thresholds(f1[0]["probs"], thresholds) == "answers"

    f2 = ev.run_spec_on_question(ev.Spec("f2", "title", "concepts", "p0"), question, concepts, ["Paper one"], caller)
    assert f2 is not None
    assert set(f2[0]["yes"]) == {"A", "O", "G"}
    store = {
        "f2-title-concepts-p0": [{
            "qid": "Q4", "key": "k", "title": "t", "gold": "answers",
            "probs": f2[0]["probs"], "yes": {"A": 0.8, "O": 0.8, "G": 0.2},
        }],
        "f2-title-concepts-p1": [{
            "qid": "Q4", "key": "k", "title": "t", "gold": "answers",
            "probs": f2[0]["probs"], "yes": {"A": 0.4, "O": 0.4, "G": 0.2},
        }],
    }
    ev.add_average_records(store)
    averaged = store["f2-title-concepts-avg"][0]
    assert averaged["yes"]["A"] == pytest.approx(0.6)
    assert averaged["probs"] == pytest.approx(ev.combine_f2(0.6, 0.6, 0.2))


def test_reorder_keeps_score_order_inside_a_group():
    hits = [
        {"key": "a", "rank": 1},
        {"key": "b", "rank": 2},
        {"key": "c", "rank": 3},
    ]
    ordered = ev.reorder_hits(hits, {"a": "different", "b": "answers", "c": "answers"})
    assert [hit["key"] for hit in ordered] == ["b", "c", "a"]
    assert [hit["rank"] for hit in ordered] == [1, 2, 3]
