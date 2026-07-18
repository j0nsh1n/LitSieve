"""Tests for multi-discipline study-type heuristics."""

from study_type import attach_study_types, classify_study_type


def test_meta_analysis_is_synthesis():
    r = classify_study_type(
        title="A meta-analysis of classroom interventions",
        abstract="We conducted a meta-analysis of 40 studies.",
    )
    assert r["study_type"] == "synthesis"
    assert r["confidence"] >= 0.85
    assert r["confidence_band"] == "high"
    assert r["warning"] is None
    assert "abstract" in r["disclaimer"].lower()


def test_rct_is_trial():
    r = classify_study_type(
        title="Effect of drug X",
        abstract="In this randomized controlled trial, 200 patients were enrolled.",
    )
    assert r["study_type"] == "trial"
    assert r["confidence_band"] in ("high", "medium")


def test_qualitative():
    r = classify_study_type(
        title="Teacher experiences",
        abstract="This qualitative study used semi-structured interviews and thematic analysis.",
    )
    assert r["study_type"] == "qualitative"


def test_survey():
    r = classify_study_type(
        title="Student wellbeing",
        abstract="A cross-sectional survey of 1,200 undergraduates was administered online.",
    )
    assert r["study_type"] == "survey"


def test_unclear_short_text_has_warning():
    r = classify_study_type(title="x", abstract="")
    assert r["study_type"] == "unclear"
    assert r["warning"]
    assert r["confidence_band"] == "none"


def test_low_confidence_review_warns():
    # Bare "review" token is intentionally lowest confidence among review patterns.
    r = classify_study_type(
        title="Software notes",
        abstract="A brief review of package foo for systems programming.",
    )
    assert r["study_type"] == "narrative_review"
    assert r["confidence"] <= 0.45
    assert r["warning"]
    assert r["confidence_band"] == "low"


def test_attach_study_types_mutates_articles():
    arts = [
        {
            "title": "A systematic review of tutoring",
            "abstract": "This systematic review synthesizes 12 RCTs.",
        }
    ]
    attach_study_types(arts)
    assert arts[0]["study_type"] == "synthesis"
    assert arts[0]["study_type_label"]
    assert arts[0]["study_type_meaning"]
    assert arts[0]["study_type_label_formal"]
    assert "study_type_disclaimer" in arts[0]


def test_plain_language_labels_for_hs():
    r = classify_study_type(
        title="A meta-analysis of tutoring",
        abstract="We conducted a meta-analysis of 40 RCTs.",
    )
    assert "Likely" in r["study_type_label"]
    assert len(r["study_type_meaning"]) > 20
