"""Unit tests for reader_facts extraction (deterministic, no I/O)."""

from app.services import reader_facts as facts


def test_normalise_collapses_whitespace_and_casefolds():
    assert facts.normalise("  A   B\t\nC  ") == "a b c"
    # NFKC folds the micro sign onto the greek mu
    assert facts.normalise("\u00b5g") == facts.normalise("\u03bcg")
    # punctuation is deliberately kept
    assert facts.normalise("Hello, world!") == "hello, world!"


def test_abstract_hash_stable_and_casefold():
    a = facts.abstract_hash("Patients  improved BY 43 minutes.")
    b = facts.abstract_hash("patients improved by 43 minutes.")
    assert a == b
    assert len(a) == 64
    assert a != facts.abstract_hash("patients improved by 44 minutes.")
    # punctuation matters: a change in punctuation must change the hash
    assert a != facts.abstract_hash("patients improved by 43 minutes,")


def test_extract_numbers_kinds_and_units():
    toks = facts.extract_numbers(
        "n = 1,024 adults; a 43-minute gain and 43 minutes per night (95% CI 21 to 65); "
        "34% better (p < 0.01); 20 mg caffeine; from 2019 to 2021"
    )
    by_kind = {}
    for t in toks:
        by_kind.setdefault(t["kind"], []).append(t)

    assert by_kind["sample_size"][0]["value"] == 1024.0
    assert by_kind["sample_size"][0]["unit"] == "n"

    durations = by_kind["duration"]
    assert all(t["value"] == 43.0 for t in durations)
    assert {t["surface"] for t in durations} == {"43-minute", "43 minutes"}
    assert all(t["unit"] == "minute" for t in durations), "unit class is singular"

    assert by_kind["ci"][0]["surface"] == "95% CI 21 to 65"
    assert by_kind["ci"][0]["value"] == 95.0

    assert by_kind["percent"][0]["value"] == 34.0
    assert by_kind["percent"][0]["unit"] == "%"

    assert by_kind["p_value"][0]["value"] == 0.01
    assert by_kind["p_value"][0]["unit"] == "p"

    assert by_kind["dose"][0]["value"] == 20.0
    assert by_kind["dose"][0]["unit"] == "mg"

    assert {t["value"] for t in by_kind["year"]} == {2019.0, 2021.0}


def test_extract_numbers_bare_number_token():
    toks = facts.extract_numbers("23 schools took part")
    assert len(toks) == 1
    assert toks[0]["kind"] == "bare_number"
    assert toks[0]["value"] == 23.0
    assert toks[0]["unit"] is None


def test_extract_numbers_first_match_wins_no_double_count():
    toks = facts.extract_numbers("95% CI 21 to 65")
    kinds = [t["kind"] for t in toks]
    assert kinds == ["ci"], "the CI span must be one ci token, not percent + bares"

    toks = facts.extract_numbers("43 minutes")
    kinds = [t["kind"] for t in toks]
    assert kinds == ["duration"], "the duration span must not also yield a bare number"


def test_cues_word_boundary_mayor_vs_may():
    cues = facts.extract_cues("The mayor praised the scheme.")
    assert cues["uncertainty"] == []
    assert facts.extract_cues("The mayor may act soon.")["uncertainty"] == ["may"]


def test_cues_word_boundary_no_substring_hits():
    # "not" inside "nothing" / "notice" must not fire anything
    assert facts.extract_cues("nothing changed, we noticed the result")["negation"] == []
    # multi-word cues still match
    assert "no significant" in facts.extract_cues("There was NO significant difference.")["negation"]
    assert "non-significant" in facts.extract_cues("the result was non-significant")["negation"]


def test_cues_tightened_lists_reject_overbroad_terms():
    # Bare "not", "without", "could", "will" and "shows that" are deliberately
    # not cues: they appear in almost every abstract.
    text = "The treatment group was not blinded and the study shows that outcomes changed. The paper will appear soon."
    cues = facts.extract_cues(text)
    assert cues["negation"] == []
    assert cues["uncertainty"] == []
    assert cues["causal"] == []


def test_causal_upgrades_match():
    cues = facts.extract_cues("This proves the drug causes harm.")
    assert set(cues["causal"]) == {"proves", "causes"}


def test_extract_pico_candidates_prefers_first_sentence_per_bucket():
    abstract = (
        "Patients were recruited first. Participants arrived later. "
        "The Sleep Education Program ran weekly. A second programme came later. "
        "Outcomes improved versus usual care."
    )
    cands = facts.extract_pico_candidates(abstract)
    joined = " ".join(cands).lower()
    # first matching sentence per bucket contributes; later matches do not
    assert "patients" in joined
    assert "Sleep Education Program" in joined or any(
        "sleep education program" in c for c in joined.split(", ")
    )
    # the second population / programme sentences must not add entities
    assert "arrived" not in joined
    assert "second" not in joined


def test_extract_pico_candidates_cap_at_8():
    names = ", ".join(f"Product {chr(65 + i)}x" for i in range(10))
    abstract = f"Patients received {names} in the treatment arm and improved."
    assert len(facts.extract_pico_candidates(abstract)) == 8


def test_extract_pico_candidates_empty():
    assert facts.extract_pico_candidates("The study looked at sleep.") == []
