"""Evaluation corpus: the deterministic verifier against real abstracts.

Offline and fast — no LLM, no network. Fixtures in tests/fixtures/reader/ pair a
real PubMed abstract (fetched once from the public E-utilities API; PMID recorded
in each file) with a hand-written explanation.

Two kinds:

  faithful  an explanation that keeps the numbers, hedging, negatives and design.
            These must produce NO warnings. They are the warning-fatigue guard:
            a verifier that nags about correct work is worse than none, because
            students learn to dismiss the banner.

  degraded  the same abstract with exactly one thing broken, named in
            "seeded_defect". Exactly that check must warn, and no other.

The pairing is what makes this non-vacuous. Deleting a rule flips its degraded
fixture; loosening one until it never fires flips nothing here but is caught by
tests/test_reader_verify.py. Tightening a rule until it fires on everything
flips the faithful fixtures.

Expected outcomes were hand-labelled by reading each abstract against its
explanation. Do NOT regenerate them from verifier output to make this pass — if
the corpus disagrees, the verifier is the thing to fix.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.services.reader_verify import CHECK_ORDER, verify

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "reader"


def _load():
    files = sorted(FIXTURES.glob("*.json"))
    assert files, "no reader fixtures found"
    return [json.loads(f.read_text(encoding="utf-8")) for f in files]


CORPUS = _load()
IDS = [d["id"] for d in CORPUS]


def test_corpus_is_big_enough_and_balanced():
    """A corpus of only faithful cases cannot catch an over-tightened rule."""
    assert len(CORPUS) >= 12
    faithful = [d for d in CORPUS if d["variant"] == "faithful"]
    degraded = [d for d in CORPUS if d["variant"] == "degraded"]
    assert len(faithful) >= 8
    assert len(degraded) >= 6
    # Every degraded fixture names the single check it is meant to trip, and
    # every one of those checks is covered by at least one fixture.
    seeded = {d["seeded_defect"] for d in degraded}
    assert seeded == {"numeric_detail", "negation", "uncertainty_language", "study_design"}
    # Two of the degraded fixtures pin audit findings 1.2 and 1.3 specifically:
    # a negation loss masked by the model's own boundary sentence, and a hedge
    # loss where only precision qualifiers remain. Both passed before the fix.
    ids = {d["id"] for d in degraded}
    assert "sst_rct_negation_masked_by_boundary" in ids
    assert "dsst_meta_hedge_lost_precision_only" in ids


@pytest.mark.parametrize("doc", CORPUS, ids=IDS)
def test_fixture_matches_hand_labels(doc):
    report = verify(doc["abstract"], doc["provenance"]["title"], doc["generated"])
    got = {c["check_id"]: c["outcome"] for c in report["checks"]}
    for check_id, expected in doc["expected"].items():
        assert got.get(check_id) == expected, (
            f"{doc['id']}: {check_id} expected {expected}, got {got.get(check_id)}"
        )
    assert report["status"] == doc["expected_status"]


@pytest.mark.parametrize(
    "doc", [d for d in CORPUS if d["variant"] == "faithful"],
    ids=[d["id"] for d in CORPUS if d["variant"] == "faithful"],
)
def test_faithful_explanations_do_not_warn(doc):
    """Warning fatigue guard. A faithful explanation must come back clean."""
    report = verify(doc["abstract"], doc["provenance"]["title"], doc["generated"])
    warns = [c["check_id"] for c in report["checks"] if c["outcome"] == "warn"]
    assert warns == [], f"{doc['id']} warns on {warns} despite preserving the source"
    assert report["status"] == "no_automatic_issues"


@pytest.mark.parametrize(
    "doc", [d for d in CORPUS if d["variant"] == "degraded"],
    ids=[d["id"] for d in CORPUS if d["variant"] == "degraded"],
)
def test_degraded_explanations_warn_on_their_defect_only(doc):
    """Each degraded fixture trips exactly the check it was built to trip."""
    report = verify(doc["abstract"], doc["provenance"]["title"], doc["generated"])
    warns = sorted(c["check_id"] for c in report["checks"] if c["outcome"] == "warn")
    assert warns == [doc["seeded_defect"]], (
        f"{doc['id']}: expected only {doc['seeded_defect']} to warn, got {warns}"
    )
    assert report["status"] == "needs_review"


def test_warning_rate_on_faithful_corpus_is_zero():
    """Aggregate view: the number the corpus exists to hold down.

    If this ever needs relaxing, the honest fix is a less trigger-happy rule,
    not a higher threshold here.
    """
    faithful = [d for d in CORPUS if d["variant"] == "faithful"]
    warned = [
        d["id"]
        for d in faithful
        if any(
            c["outcome"] == "warn"
            for c in verify(d["abstract"], d["provenance"]["title"], d["generated"])["checks"]
        )
    ]
    assert not warned, f"{len(warned)}/{len(faithful)} faithful explanations warn: {warned}"


@pytest.mark.parametrize("doc", CORPUS, ids=IDS)
def test_every_check_reports_on_every_fixture(doc):
    """No check may silently vanish; a dropped rule shows up as a missing id."""
    report = verify(doc["abstract"], doc["provenance"]["title"], doc["generated"])
    assert [c["check_id"] for c in report["checks"]] == list(CHECK_ORDER)
    for c in report["checks"]:
        assert c["outcome"] in ("pass", "warn", "skipped")
        assert c["severity"] in ("info", "warning")
        assert c["severity"] != "error"


@pytest.mark.parametrize("doc", CORPUS, ids=IDS)
def test_fixture_provenance_is_recorded(doc):
    """Each abstract is traceable to a real record, not invented for the test."""
    prov = doc["provenance"]
    assert prov["source"] == "pubmed"
    assert prov["pmid"].isdigit()
    assert prov["title"].strip()
    assert len(doc["abstract"]) >= 400
