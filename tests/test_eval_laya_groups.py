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


def _probs(different: float, answers: float) -> dict:
    return {"answers": answers, "how_why": 0.0, "context": 0.0, "different": different}


def test_ineligible_thresholds_prefer_lower_harm():
    """The reproduced case: no cut meets the 5% cap, so harm outranks F1.

    Two gold answers at {different: .9, answers: .1} and {different: .6, answers: .4},
    plus twenty gold different rows at {different: .6, answers: .4}. All cuts at
    .35 put both answers in different (harm 1.0, macro-F1 10/21). Cuts that
    abstain on the .6 row leave harm at .5. The fallback must keep .5.
    """
    items = [
        {"gold": "answers", "probs": _probs(0.9, 0.1)},
        {"gold": "answers", "probs": _probs(0.6, 0.4)},
    ] + [{"gold": "different", "probs": _probs(0.6, 0.4)} for _ in range(20)]
    tuned = ev.tune_thresholds(items)
    assert tuned.eligible is False
    assert tuned.harmful == pytest.approx(0.5)
    assert tuned.macro_f1 == pytest.approx(0.0)
    assert tuned.thresholds == {
        "answers": 0.35,
        "how_why": 0.35,
        "context": 0.35,
        "different": 0.65,
    }
    high_f1 = ev.Tuned(
        thresholds={group: 0.35 for group in ev.GROUPS},
        macro_f1=10 / 21,
        accuracy=20 / 22,
        coverage=1.0,
        harmful=1.0,
        eligible=False,
    )
    assert ev._rank_key(tuned) > ev._rank_key(high_f1)


def test_ineligible_candidate_selection_prefers_lower_harm():
    mild = [
        {"gold": "answers", "probs": _probs(0.9, 0.1)},
        {"gold": "answers", "probs": _probs(0.6, 0.4)},
    ] + [{"gold": "different", "probs": _probs(0.6, 0.4)} for _ in range(20)]
    severe = [
        {"qid": "Q1", "key": f"a{i}", "gold": "answers", "probs": _probs(0.95, 0.05)}
        for i in range(2)
    ] + [
        {"qid": "Q1", "key": f"d{i}", "gold": "different", "probs": _probs(0.95, 0.05)}
        for i in range(20)
    ]
    mild_rows = [
        {"qid": "Q1", "key": f"m{i}", "gold": item["gold"], "probs": item["probs"]}
        for i, item in enumerate(mild)
    ]
    store = {"mild-two-concepts-p0": mild_rows, "severe-two-concepts-p0": severe}
    sid, tuned = ev._best_tuned(store, ["severe-two-concepts-p0", "mild-two-concepts-p0"])
    assert sid == "mild-two-concepts-p0"
    assert tuned.harmful == pytest.approx(0.5)
    assert ev.tune_thresholds(
        [{"gold": row["gold"], "probs": row["probs"]} for row in severe]
    ).harmful == pytest.approx(1.0)

    # Coverage uses the same key. An eligible abstaining floor beats a
    # higher-F1 floor that hides every good paper.
    coverage_items = [{"gold": "answers", "score": 0.0} for _ in range(2)]
    coverage_items += [{"gold": "different", "score": 0.0} for _ in range(20)]
    tuned_cov, floor, _cuts = ev.tune_coverage(coverage_items)
    assert tuned_cov.eligible is True
    assert tuned_cov.harmful == pytest.approx(0.0)
    assert floor == "not_sorted"
    hidden = ev.Tuned(
        thresholds={"answers": 1.01, "how_why": 1.01, "context": 1.01},
        macro_f1=10 / 21,
        accuracy=20 / 22,
        coverage=1.0,
        harmful=1.0,
        eligible=False,
    )
    assert ev._rank_key(tuned_cov) > ev._rank_key(hidden)


class _OrderScorer:
    def score_question(self, qrow, label_rows, split, ranking_name):
        assert split == "dev"
        assert ranking_name == "lexical_on"
        assert label_rows == []
        keys = [hit["key"] for hit in qrow["rankings"]["lexical_on"]]
        return {
            "id": qrow["id"],
            "ndcg@10": 1.0 if keys and str(keys[0]).startswith("r") else 0.2,
            "relevant@10": sum(1 for key in keys[:10] if str(key).startswith("r")),
        }


def test_per_question_ranking_keeps_a_loss_visible():
    questions = [
        {"id": "Q1", "rankings": {"lexical_on": [
            {"key": "x1", "rank": 1},
            {"key": "r1", "rank": 2},
        ]}},
        {"id": "Q2", "rankings": {"lexical_on": [
            {"key": "r2", "rank": 1},
            {"key": "x2", "rank": 2},
        ]}},
    ]
    scorer = _OrderScorer()
    baseline = ev.ranking_table(scorer, questions, {}, {})
    moved = ev.ranking_table(scorer, questions, {}, {
        "Q1": {"r1": "answers", "x1": "different"},
        "Q2": {"r2": "different", "x2": "answers"},
    })
    deltas = ev.ranking_deltas(moved["questions"], baseline["questions"])
    assert deltas["Q1"]["d_ndcg"] == pytest.approx(0.8)
    assert deltas["Q2"]["d_ndcg"] == pytest.approx(-0.8)
    assert ev._mean([deltas["Q1"]["d_ndcg"], deltas["Q2"]["d_ndcg"]]) == pytest.approx(0.0)
    assert moved["ndcg@10"] == pytest.approx(baseline["ndcg@10"])

    def question_row(setting: str, qid: str, fields: dict) -> dict:
        return {
            "setting": setting,
            "question": qid,
            "n": 2,
            "coverage": 1.0,
            "accuracy": 0.5,
            "macro_f1": 0.4,
            "harmful": 0.0,
            **fields,
        }

    rows = [
        question_row("s", qid, deltas[qid]) for qid in ("Q1", "Q2")
    ]
    base_deltas = ev.ranking_deltas(baseline["questions"], baseline["questions"])
    rows.extend(question_row("concept-coverage/not_sorted", qid, base_deltas[qid]) for qid in ("Q1", "Q2"))
    text = ev.render_report({
        "budget_note": "budget",
        "support_note": "support",
        "overall_rows": [{
            "setting": "s",
            "n": 4,
            "coverage": 1.0,
            "accuracy": 0.5,
            "macro_f1": 0.4,
            "harmful": 0.0,
            "harm_n": 0,
            "good_n": 2,
            "ndcg@10": moved["ndcg@10"],
            "relevant@10": moved["relevant@10"],
            "d_ndcg": 0.0,
            "d_rel": 0.0,
            "cuts": "",
        }],
        "question_rows": rows,
        "top5": [],
        "baseline_note": "base",
        "latency_note": "lat",
        "recommendation": "rec",
    })
    assert "| ndcg@10 | rel@10 | d ndcg | d rel |" in text
    def cells(line: str) -> list[str]:
        return [part.strip() for part in line.strip().strip("|").split("|")]

    q1 = cells(next(line for line in text.splitlines() if line.startswith("| s | Q1 |")))
    q2 = cells(next(line for line in text.splitlines() if line.startswith("| s | Q2 |")))
    base = cells(next(
        line for line in text.splitlines() if line.startswith("| concept-coverage/not_sorted | Q1 |")
    ))
    assert q1[-2:] == ["0.800", "0.00"]
    assert q2[-2:] == ["-0.800", "0.00"]
    assert base[-2:] == ["0.000", "0.00"]


def test_f2b_slots_skip_empty_concepts():
    assert [name for name, _target in ev.f2b_slots(QuestionConcepts())] == ["F"]
    period_only = QuestionConcepts(period=("Great Depression",))
    assert [name for name, _target in ev.f2b_slots(period_only)] == ["F"]
    adolescents = QuestionConcepts(population=("adolescents",))
    assert [name for name, _target in ev.f2b_slots(adolescents)] == ["C", "F"]
    place = QuestionConcepts(place=("U.S.",))
    assert [name for name, _target in ev.f2b_slots(place)] == ["C", "F"]
    full = QuestionConcepts(
        actor=("New Deal policies",),
        outcome=("employment",),
        population=("African Americans",),
        place=("the South",),
    )
    assert [name for name, _target in ev.f2b_slots(full)] == ["R", "A", "C", "F"]


def test_f2b_cells_at_the_corners():
    actor_no = {"R": 1.0, "A": 0.0, "C": 0.0, "F": 1.0}
    assert ev.combine_f2b(actor_no, "outcome")["answers"] == pytest.approx(1)
    assert ev.combine_f2b(actor_no, "actor")["different"] == pytest.approx(1)
    assert ev.combine_f2b({"F": 1.0}, "open")["answers"] == pytest.approx(1)
    assert ev.combine_f2b({"F": 1.0}, "outcome")["context"] == pytest.approx(1)
    contradicted = {"R": 1.0, "A": 1.0, "C": 1.0, "F": 1.0}
    for rule in ev.F2B_RULES:
        assert ev.combine_f2b(contradicted, rule)["different"] == pytest.approx(1)
    findings_no = {"R": 1.0, "A": 1.0, "C": 0.0, "F": 0.0}
    assert ev.combine_f2b(findings_no, "outcome")["how_why"] == pytest.approx(1)
    soft = ev.combine_f2b({"R": 0.7, "A": 0.4, "C": 0.2, "F": 0.8}, "actor")
    assert sum(soft.values()) == pytest.approx(1.0)
    missing_outcome = ev.combine_f2b({"A": 1.0, "F": 1.0}, "outcome")
    assert missing_outcome["answers"] == pytest.approx(0)
    assert missing_outcome["context"] == pytest.approx(1)
    assert ev.combine_f2b({"F": 1.0}, "open")["answers"] == pytest.approx(1)
    actor_missing_outcome = ev.combine_f2b({"A": 1.0, "F": 1.0}, "actor")
    assert actor_missing_outcome["answers"] == pytest.approx(0)
    assert actor_missing_outcome["context"] == pytest.approx(1)


def test_mock_laya_f2b_skips_empty_slots():
    calls = []

    def caller(instructions, options, states):
        calls.append(instructions)
        assert states == ["Paper"]
        assert set(options) == {"yes", "no"}
        return [{"choice": "yes", "p": 1.0, "probabilities": {"yes": 1.0, "no": 0.0}}]

    concepts = QuestionConcepts(actor=("New Deal policies",), population=("African Americans",))
    question = {
        "id": "Q2",
        "text": "How did New Deal policies affect African Americans during the Great Depression?",
    }
    rows = ev.run_spec_on_question(
        ev.Spec("f2b", "two", "actor", "p0"), question, concepts, ["Paper"], caller
    )
    assert rows is not None
    assert len(calls) == 3
    assert not any("report results about" in text for text in calls)
    assert set(rows[0]["yes"]) == {"A", "C", "F"}

    calls.clear()
    keyword = {"id": "Q15", "text": "microplastics drinking water human health"}
    rows = ev.run_spec_on_question(
        ev.Spec("f2b", "full", "outcome", "p0"), keyword, QuestionConcepts(), ["Paper"], caller
    )
    assert rows is not None
    assert len(calls) == 1
    assert "findings" in calls[0]
    assert rows[0]["probs"]["context"] == pytest.approx(1)


def test_loo_fit_does_not_see_the_held_out_question():
    q1 = [
        {"qid": "Q1", "key": f"d{i}", "gold": "different", "probs": _probs(0.9, 0.1)}
        for i in range(10)
    ]
    q2 = {"qid": "Q2", "key": "a", "gold": "answers", "probs": _probs(0.6, 0.4)}
    held = ev.loo_predictions(q1 + [q2], ["Q1", "Q2"])
    assert held["Q2"]["a"] == "different"
    joint = ev.tune_thresholds(
        [{"gold": row["gold"], "probs": row["probs"]} for row in q1 + [q2]]
    )
    assert joint.thresholds["different"] in (0.65, 0.80)
    assert ev.apply_thresholds(q2["probs"], joint.thresholds) == "not_sorted"


def test_pick_f2b_uses_harm_cap_then_ndcg():
    low_gain = {"setting": "low", "harmful": 0.0, "d_ndcg": -0.2, "macro_f1": 0.9, "coverage": 1.0}
    better = {"setting": "better", "harmful": 0.04, "d_ndcg": 0.1, "macro_f1": 0.2, "coverage": 0.5}
    huge = {"setting": "huge", "harmful": 0.5, "d_ndcg": 0.9, "macro_f1": 0.99, "coverage": 1.0}
    assert ev.pick_f2b([low_gain, better, huge])["setting"] == "better"
    milder = {"setting": "mild", "harmful": 0.2, "d_ndcg": -0.5, "macro_f1": 0.1, "coverage": 0.2}
    worse = {"setting": "worse", "harmful": 0.4, "d_ndcg": 0.8, "macro_f1": 0.9, "coverage": 1.0}
    assert ev.pick_f2b([worse, milder])["setting"] == "mild"


def test_gate_verdict_needs_every_condition():
    good = {
        "dev_ndcg": 0.5,
        "dev_base": 0.4,
        "test_ndcg": 0.5,
        "test_base": 0.4,
        "test_harm": 0.05,
        "worse_questions": (),
    }
    assert ev.gate_verdict(**good) == "PASS"
    assert ev.gate_verdict(**{**good, "test_harm": 0.06}) == "FAIL"
    assert ev.gate_verdict(**{**good, "worse_questions": ("Q4",)}) == "FAIL"
    assert ev.gate_verdict(**{**good, "dev_ndcg": 0.3}) == "FAIL"
    assert ev.gate_verdict(**{**good, "dev_ndcg": 0.4}) == "FAIL"
    assert ev.gate_verdict(**{**good, "test_ndcg": 0.4}) == "FAIL"


def test_worse_question_ids():
    rows = [
        {"question": "Q4", "d_ndcg": -0.01},
        {"question": "Q5", "d_ndcg": 0.0},
        {"question": "Q1", "d_ndcg": -0.5},
        {"question": "Q9", "d_ndcg": None},
    ]
    topics = {"Q4": "health", "Q5": "education", "Q1": "history", "Q9": "health"}
    assert ev.worse_question_ids(rows, topics) == ["Q4"]


def test_f2b_batches():
    full = QuestionConcepts(actor=("a",), outcome=("o",), population=("p",), place=("Europe",))
    assert ev.f2b_batches_per_search(full, "p0") == 4
    assert ev.f2b_batches_per_search(QuestionConcepts(), "avg") == 2


def test_test_stamp_blocks_a_second_claim(tmp_path):
    path = tmp_path / "p25b_results.md.test-stamp.json"
    assert ev.claim_test_stamp(path, "f2b-two-outcome-p0") is True
    assert ev.claim_test_stamp(path, "other") is False
    saved = path.read_text(encoding="utf-8")
    assert "f2b-two-outcome-p0" in saved
    assert "other" not in saved


def test_top_golds_ignore_labels_outside_the_top_30():
    prepared = [{
        "gold": {"in-top": "answers", "outside": "different", "blank": None},
        "papers": [{"key": "in-top"}, {"key": "unlabelled"}],
    }]
    assert ev.top_golds(prepared) == ["answers"]
    assert ev.support_counts(ev.top_golds(prepared))["answers"] == 1
    assert ev.support_counts(ev.top_golds(prepared))["different"] == 0


def test_splice_test_keeps_a_blank_line_before_the_recommendation():
    text = "# Title\n\n## Recommendation\n\nold\n"
    out = ev._splice_test(text, "## Test split\n\nscored\n", "Pick failed.")
    assert "\n\n## Recommendation\n\n" in out
    assert "old" not in out
    assert out.endswith("Pick failed.\n")
    assert "## Test split" in out


def test_group_state_uses_two_sentences_and_the_owner_definition():
    state = ev.group_state(
        "Does evening caffeine make it harder to fall asleep?",
        "Coffee intake and sleep latency",
        "Adults who drank coffee took longer to fall asleep. The delay was about twenty minutes.",
    )
    assert state.startswith("Question: Does evening caffeine")
    assert "Title: Coffee intake and sleep latency" in state
    assert "population or place is not contradicted" in ev.FT_INSTRUCTIONS
    assert set(ev.FT_CRITERIA) == set(ev.GROUPS)
    prepared = [{
        "question": {"id": "T1", "text": "How does vaping affect lung function?"},
        "papers": [{
            "key": "pubmed:1",
            "title": "Vaping study",
            "abstract": "First result sentence. Second sentence. Third sentence should drop.",
        }],
    }]
    rows = ev.ft_states(prepared)
    assert rows[0]["qid"] == "T1"
    assert "First result sentence. Second sentence." in rows[0]["state"]
    assert "Third sentence" not in rows[0]["state"]


def test_rows_from_predict_and_tag_precision():
    mapped = ev.rows_from_predict([{
        "answers": {
            "group": {
                "choice": "answers",
                "probabilities": {"answers": 0.91, "how_why": 0.03, "context": 0.03, "different": 0.03},
            }
        }
    }])
    assert mapped[0]["choice"] == "answers"
    assert mapped[0]["p"] == pytest.approx(0.91)
    records = [
        {"gold": "answers", "probs": {"answers": 0.91}},
        {"gold": "answers", "probs": {"answers": 0.85}},
        {"gold": "different", "probs": {"answers": 0.88}},
        {"gold": "not_sorted", "probs": {"answers": 0.95}},
        {"gold": "answers", "probs": {"answers": 0.5}},
        {"gold": None, "probs": {"answers": 0.99}},
    ]
    tag = ev.answers_tag_precision(records)
    assert tag["flagged"] == 4
    assert tag["tp"] == 2
    assert tag["precision"] == pytest.approx(0.5)


def test_run_ft_commands_do_not_use_the_sidecar():
    parser = ev.build_parser()
    dev = parser.parse_args(["run-ft", "--checkpoint", "/tmp/ft"])
    assert dev.func is ev.execute_run_ft
    assert dev.out.endswith("p25c_results.md")
    assert not hasattr(dev, "laya_url")
    held = parser.parse_args(["score-ft-test"])
    assert held.func is ev.execute_score_ft_test
    local = parser.parse_args([
        "predict-local", "--checkpoint", "/tmp/ft", "--states", "s.json", "--out", "o.json",
    ])
    assert local.func is ev.execute_predict_local


def test_run_f2_commands_are_wired():
    parser = ev.build_parser()
    dev = parser.parse_args(["run-f2"])
    assert dev.func is ev.execute_round2
    assert dev.out.endswith("p25b_results.md")
    assert dev.results.endswith("baseline_v2_results.json")
    assert dev.budget == ev.F2B_BUDGET
    assert dev.latency is True
    held = parser.parse_args(["score-test"])
    assert held.func is ev.execute_score_test
    assert held.out.endswith("p25b_results.md")
    screen = parser.parse_args(["run"])
    assert screen.func is ev.execute
    assert screen.budget == ev.EXPERIMENT_BUDGET


def test_reorder_keeps_score_order_inside_a_group():
    hits = [
        {"key": "a", "rank": 1},
        {"key": "b", "rank": 2},
        {"key": "c", "rank": 3},
    ]
    ordered = ev.reorder_hits(hits, {"a": "different", "b": "answers", "c": "answers"})
    assert [hit["key"] for hit in ordered] == ["b", "c", "a"]
    assert [hit["rank"] for hit in ordered] == [1, 2, 3]
