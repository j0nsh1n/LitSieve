"""Verifier tests: positive AND negative pair for every warn rule (no LLM, no I/O)."""


from app.services import reader_verify
from app.services.reader_verify import verify


def _check(report, check_id):
    return next(c for c in report["checks"] if c["check_id"] == check_id)


def _generated(**overrides):
    base = {
        "plain_summary": "Students slept 43 minutes longer after later start times.",
        "question_asked": "Does a sleep programme improve sleep?",
        "who_was_studied": "512 adolescents in secondary schools.",
        "what_was_found": (
            "Sleep rose by 43 minutes (95% CI 21 to 65); 34% reported better "
            "sleep (p < 0.01)."
        ),
        "what_it_does_not_show": (
            "The abstract alone cannot establish whether these findings apply to everyone."
        ),
        "stated_limitations": "Not reported in the abstract.",
        "glossary": [],
        "not_reported_fields": [],
    }
    base.update(overrides)
    return base


def test_full_clean_run_has_no_automatic_issues():
    abstract = (
        "Methods: In this randomised controlled trial, n = 512 participants were "
        "assigned to a sleep treatment or usual care. "
        "Results: Sleep rose 43 minutes per night (95% CI 21 to 65); 34% reported "
        "better sleep (p < 0.01). "
        "Conclusions: The treatment was associated with longer sleep."
    )
    generated = _generated(
        plain_summary=(
            "In this trial / experiment, the sleep treatment was associated with "
            "43 minutes more sleep."
        ),
        who_was_studied="512 participants in the treatment group.",
    )
    report = verify(abstract, "Sleep education trial", generated)
    assert report["status"] == "no_automatic_issues"
    # readability may skip; that must not count as a warning.
    assert all(c["outcome"] != "warn" for c in report["checks"])
    assert "checked_at" not in report


def test_numeric_missing_sample_size_warns():
    abstract = (
        "Methods: n = 512 adolescents were enrolled in a sleep programme. "
        "Results: Students slept 43 minutes longer per night (95% CI 21 to 65); "
        "34% reported better sleep (p < 0.01). "
        "Conclusions: Later start times were associated with longer sleep."
    )
    generated = _generated(
        plain_summary="Students slept 43 minutes longer.",
        who_was_studied="Adolescents in secondary schools.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "numeric_detail")
    assert chk["outcome"] == "warn"
    assert "1 number that does not appear" in chk["message"]
    assert chk["details"]["missing"] == ["n = 512"]


def test_numeric_unit_variant_matches():
    abstract = "A 43-minute increase in nightly sleep was recorded. The change was durable."
    generated = _generated(
        plain_summary="Students slept 43 minutes longer each night.",
        what_was_found="Sleep increased by 43 minutes.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "numeric_detail")
    assert chk["outcome"] == "pass"


def test_percentage_and_p_value_preserved():
    abstract = "About 34% of students improved (p < 0.01). The gain was steady."
    generated = _generated(
        plain_summary="34% of students improved.",
        what_was_found="The improvement reached 34% (p < 0.01).",
    )
    chk = _check(verify(abstract, "Sleep", generated), "numeric_detail")
    assert chk["outcome"] == "pass"


def test_bare_numbers_do_not_warn():
    abstract = "23 schools took part in 2021. Outcomes were tracked each term."
    generated = _generated(
        plain_summary="Schools took part in the study.",
        what_was_found="Outcomes were tracked across the school terms.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "numeric_detail")
    assert chk["outcome"] == "pass"
    assert "2021" in chk["details"]["years"]
    assert "23" in chk["details"]["bare_numbers"]


def test_ci_and_dose_preserved():
    abstract = "Caffeine fell by 20 mg per day (95% CI 10 to 30). The drop was sustained."
    generated = _generated(
        plain_summary="Caffeine intake fell by 20 mg per day.",
        what_was_found="The fall was 20 mg per day (95% CI 10 to 30).",
    )
    chk = _check(verify(abstract, "Caffeine", generated), "numeric_detail")
    assert chk["outcome"] == "pass"


def test_negation_loss_warns():
    abstract = (
        "Results: Sleep improved by 43 minutes per night. "
        "Conclusions: There was no significant difference in screen time."
    )
    generated = _generated(
        plain_summary="Students slept 43 minutes longer.",
        what_was_found="Screen time stayed at the same level.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "negation")
    assert chk["outcome"] == "warn"


def test_negation_preserved_passes():
    abstract = (
        "Results: Sleep improved by 43 minutes per night. "
        "Conclusions: There was no significant difference in screen time."
    )
    generated = _generated(
        plain_summary="Students slept 43 minutes longer.",
        what_was_found=(
            "Screen time showed no significant difference between the groups."
        ),
    )
    chk = _check(verify(abstract, "Sleep", generated), "negation")
    assert chk["outcome"] == "pass"


def test_bare_not_does_not_warn():
    abstract = (
        "Methods: Participants were not randomised to groups. "
        "Results: Sleep improved. "
        "Conclusions: The programme shows promise."
    )
    generated = _generated(
        plain_summary="Students slept longer.",
        what_was_found="Sleep improved in the programme group.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "negation")
    assert chk["outcome"] == "pass"


def test_uncertainty_upgrade_warns():
    abstract = "Sleep may improve with later start times. This was a small study."
    generated = _generated(
        plain_summary="Later starts help sleep.",
        what_was_found="The later start causes better sleep.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "uncertainty_language")
    assert chk["outcome"] == "warn"
    assert "causes" in chk["message"]


def test_uncertainty_preserved_passes():
    abstract = "Sleep may improve with later start times. This was a small study."
    generated = _generated(
        plain_summary="Sleep may improve with later start times.",
        what_was_found="Later starts might improve sleep in this small study.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "uncertainty_language")
    assert chk["outcome"] == "pass"


def test_shows_that_is_not_an_upgrade():
    abstract = (
        "Sleep quality was associated with later start times. Further study is needed."
    )
    generated = _generated(
        plain_summary="The study shows that sleep quality was associated with later start times.",
        what_was_found="More research is needed on sleep quality.",
    )
    chk = _check(verify(abstract, "Sleep", generated), "uncertainty_language")
    assert chk["outcome"] == "pass"


def test_word_boundary_no_false_positive():
    # Source with only "mayor" must not detect the "may" cue at all.
    src = "The mayor praised later starts. Sleep improved for participants."
    report = verify(
        src, "Sleep",
        _generated(plain_summary="Sleep improved.", what_was_found="Later starts helped."),
    )
    chk = _check(report, "uncertainty_language")
    assert chk["outcome"] == "pass"
    assert chk["details"]["source_cues"] == []

    # Generated "mayor" must not preserve a real "may" from the abstract.
    src2 = "Sleep may improve with later start times. Attendance was recorded."
    report2 = verify(
        src2, "Sleep",
        _generated(
            plain_summary="The mayor praised the scheme.",
            what_was_found="Later starts helped attendance.",
        ),
    )
    chk2 = _check(report2, "uncertainty_language")
    assert chk2["outcome"] == "warn"
    assert chk2["details"]["generated_cues"] == []


def test_study_type_omission_warns_only_when_confident():
    title = "A randomised controlled trial of sleep education"
    abstract = (
        "Adolescents were enrolled in a randomised controlled trial of a sleep "
        "education programme. Sleep improved in the intervention group."
    )
    generated = _generated(
        plain_summary="Students slept longer after the programme.",
        what_was_found="Sleep improved in the programme group.",
    )
    chk = _check(verify(abstract, title, generated), "study_design")
    assert chk["outcome"] == "warn"


def test_study_type_low_confidence_skipped():
    title = "A review of school sleep programmes"
    abstract = "We discuss studies of adolescent sleep. The evidence remains mixed."
    chk = _check(verify(abstract, title, _generated()), "study_design")
    assert chk["outcome"] == "skipped"


def test_readability_fk_grade_reasonable():
    generated = _generated(
        plain_summary=(
            "Researchers followed teenagers at several secondary schools for two "
            "school years to see whether later start times helped. Students in the "
            "programme slept about 43 minutes longer each night. The team measured "
            "sleep with wrist watches and compared the groups."
        ),
        what_was_found="Sleep rose by 43 minutes on average, and about a third of students reported better sleep.",
    )
    report = verify("n = 512 participants. Sleep improved.", "Sleep", generated)
    rk = report["readability"]
    grade = rk["flesch_kincaid_grade"]
    assert isinstance(grade, float)
    assert 0 < grade < 20
    assert rk["within_target_band"] == (8 <= grade <= 10)
    assert rk["dale_chall_score"] is None
    assert rk["target_band"] == "grades 8-10"
    assert rk["caveat"].startswith("Readability scores estimate")
    assert _check(report, "readability")["outcome"] == "pass"


def test_readability_skipped_without_sentences():
    empty = {key: "" for key in (
        "plain_summary", "question_asked", "who_was_studied", "what_was_found",
        "what_it_does_not_show", "stated_limitations",
    )}
    empty["glossary"] = []
    empty["not_reported_fields"] = []
    report = verify("Some abstract.", "Sleep", empty)
    rk = report["readability"]
    assert rk["flesch_kincaid_grade"] is None
    assert rk["within_target_band"] is None
    assert _check(report, "readability")["outcome"] == "skipped"


def test_status_precedence_warn_beats_skipped():
    title = "A review of school sleep programmes"
    abstract = "Methods: n = 512 participants were surveyed. Results: 34% improved."
    generated = _generated(
        plain_summary="Students improved by 34%.",
        who_was_studied="Adolescents.",
        what_was_found="34% improved.",
    )
    report = verify(abstract, title, generated)
    assert _check(report, "numeric_detail")["outcome"] == "warn"
    assert _check(report, "study_design")["outcome"] == "skipped"
    assert report["status"] == "needs_review"


def test_verifier_never_returns_error_severity():
    cases = [
        ("Some abstract about sleep. n = 40 participants.", _generated()),
        ("", _generated(plain_summary="", what_was_found="")),
        (
            "Later starts were associated with better sleep. n = 90 participants took part.",
            _generated(
                plain_summary="Later starts cause better sleep.",
                what_was_found="Later starts will make sleep better.",
            ),
        ),
    ]
    for abstract, generated in cases:
        report = verify(abstract, "T", generated)
        assert report["status"] in {
            "no_automatic_issues", "needs_review", "verification_incomplete",
        }
        for chk in report["checks"]:
            assert chk["severity"] in {"info", "warning"}
            assert chk["outcome"] in {"pass", "warn", "skipped"}


def test_verifier_exception_in_one_check_skips_that_check(monkeypatch):
    def _boom(ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(reader_verify, "_check_numeric_detail", _boom)
    abstract = (
        "Methods: In this randomised controlled trial, n = 512 participants were "
        "assigned to a sleep treatment or usual care. "
        "Results: Sleep rose 43 minutes per night (95% CI 21 to 65); 34% reported "
        "better sleep (p < 0.01). "
        "Conclusions: The treatment was associated with longer sleep."
    )
    generated = _generated(
        plain_summary=(
            "In this trial / experiment, the sleep treatment was associated with "
            "43 minutes more sleep."
        ),
        who_was_studied="512 participants in the treatment group.",
    )
    report = verify(abstract, "Sleep education trial", generated)
    chk = _check(report, "numeric_detail")
    assert chk["outcome"] == "skipped"
    assert chk["severity"] == "info"
    assert len(report["checks"]) == len(reader_verify.CHECK_ORDER)
    # a skipped non-optional check holds the status back from clean
    assert report["status"] == "verification_incomplete"
