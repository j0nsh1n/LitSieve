"""Question keyword and concept helper. No I/O. Tokens come from the input."""

from __future__ import annotations

import json
import re
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.services.question_concepts import (
    QuestionConcepts,
    question_concepts,
    question_keywords,
)

REPO = Path(__file__).resolve().parent.parent
BENCH_QUESTIONS = json.loads(
    (REPO / "tools" / "bench" / "questions.json").read_text(encoding="utf-8")
)["questions"]

Q1 = "What role did the U.S. government play in changing society during the Great Depression?"
Q2 = "How did New Deal policies affect African Americans during the Great Depression?"
Q3 = "How did British government evacuation policy affect children's schooling during the Second World War?"
Q4 = "How do later school start times affect sleep duration among adolescents?"
Q5 = "How does formative feedback affect secondary-school students' writing revision?"

BENCH_EXPECTED = {
    "Q1": {
        "text": Q1,
        "keywords": ["U.S.", "government", "changing", "society", "Great Depression"],
        "concepts": QuestionConcepts(
            actor=("U.S. government",),
            action=("changing",),
            outcome=("society",),
            population=(),
            period=("Great Depression",),
            place=("U.S.",),
        ),
    },
    "Q2": {
        "text": Q2,
        "keywords": ["New Deal", "policies", "affect", "African Americans", "Great Depression"],
        "concepts": QuestionConcepts(
            actor=("New Deal policies",),
            action=("affect",),
            outcome=(),
            population=("African Americans",),
            period=("Great Depression",),
            place=(),
        ),
    },
    "Q3": {
        "text": Q3,
        "keywords": [
            "British", "government", "evacuation", "policy", "affect",
            "children's", "schooling", "Second World War",
        ],
        "concepts": QuestionConcepts(
            actor=("British government evacuation policy",),
            action=("affect",),
            outcome=("schooling",),
            population=("children's",),
            period=("Second World War",),
            place=("British",),
        ),
    },
    "Q4": {
        "text": Q4,
        "keywords": [
            "later", "school", "start", "times", "affect",
            "sleep", "duration", "adolescents",
        ],
        "concepts": QuestionConcepts(
            actor=("later school start times",),
            action=("affect",),
            outcome=("sleep duration",),
            population=("adolescents",),
            period=(),
            place=(),
        ),
    },
    "Q5": {
        "text": Q5,
        "keywords": [
            "formative", "feedback", "affect", "secondary-school",
            "students'", "writing", "revision",
        ],
        "concepts": QuestionConcepts(
            actor=("formative feedback",),
            action=("affect",),
            outcome=("writing revision",),
            population=("secondary-school students'",),
            period=(),
            place=(),
        ),
    },
}

EXTRA_CASES = [
    (
        "New Deal African Americans",
        ["New Deal", "African Americans"],
        QuestionConcepts(),
    ),
    (
        "sleep",
        ["sleep"],
        QuestionConcepts(),
    ),
    (
        "",
        [],
        QuestionConcepts(),
    ),
    (
        "   ",
        [],
        QuestionConcepts(),
    ),
    (
        "Cómo afecta el sueño a los adolescentes",
        ["Cómo", "afecta", "el", "sueño", "los", "adolescentes"],
        QuestionConcepts(),
    ),
    (
        "How did the New Deal affect society?!?!",
        ["New Deal", "affect", "society"],
        QuestionConcepts(actor=("New Deal",), action=("affect",), outcome=("society",)),
    ),
    (
        "What is formative feedback in secondary schools?",
        ["formative", "feedback", "secondary", "schools"],
        QuestionConcepts(),
    ),
    (
        "What is the effect of later school start times on sleep duration among adolescents?",
        ["later", "school", "start", "times", "sleep", "duration", "adolescents"],
        QuestionConcepts(
            actor=("later school start times",),
            outcome=("sleep duration",),
            population=("adolescents",),
        ),
    ),
    (
        "How did tariffs affect trade during 1929–1939?",
        ["tariffs", "affect", "trade", "1929–1939"],
        QuestionConcepts(
            actor=("tariffs",),
            action=("affect",),
            outcome=("trade",),
            period=("1929–1939",),
        ),
    ),
    (
        "How did unemployment change in the 1930s?",
        ["unemployment", "change", "1930s"],
        QuestionConcepts(
            actor=("unemployment",),
            action=("change",),
            period=("1930s",),
        ),
    ),
    (
        "What impact did the New Deal have on unemployment?",
        ["New Deal", "unemployment"],
        QuestionConcepts(actor=("New Deal",), outcome=("unemployment",)),
    ),
    (
        "impact assessment",
        ["impact", "assessment"],
        QuestionConcepts(),
    ),
    (
        "How did X affect the greenhouse effect?",
        ["X", "affect", "greenhouse", "effect"],
        QuestionConcepts(
            actor=("X",),
            action=("affect",),
            outcome=("greenhouse effect",),
        ),
    ),
    (
        "How did X affect Y in adolescents?",
        ["X", "affect", "Y", "adolescents"],
        QuestionConcepts(
            actor=("X",),
            action=("affect",),
            outcome=("Y",),
            population=("adolescents",),
        ),
    ),
    (
        "How did X affect Y in adolescents during 1930s?",
        ["X", "affect", "Y", "adolescents", "1930s"],
        QuestionConcepts(
            actor=("X",),
            action=("affect",),
            outcome=("Y",),
            population=("adolescents",),
            period=("1930s",),
        ),
    ),
    (
        "How did X affect Y in Britain?",
        ["X", "affect", "Y", "Britain"],
        QuestionConcepts(
            actor=("X",),
            action=("affect",),
            outcome=("Y",),
            place=("Britain",),
        ),
    ),
    (
        "How does X affect us?",
        ["X", "affect", "us"],
        QuestionConcepts(
            actor=("X",),
            action=("affect",),
            outcome=("us",),
        ),
    ),
    (
        "US UK British",
        ["US", "UK", "British"],
        QuestionConcepts(place=("US", "UK", "British")),
    ),
    (
        "U.S. UK British",
        ["U.S.", "UK", "British"],
        QuestionConcepts(place=("U.S.", "UK", "British")),
    ),
    (
        "World War II Britain",
        ["World War II", "Britain"],
        QuestionConcepts(period=("World War II",), place=("Britain",)),
    ),
    (
        "Victorian era education",
        ["Victorian era", "education"],
        QuestionConcepts(period=("Victorian era",)),
    ),
]


def test_bench_questions_match_the_committed_set():
    assert [row["id"] for row in BENCH_QUESTIONS] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    for row in BENCH_QUESTIONS:
        assert row["text"] == BENCH_EXPECTED[row["id"]]["text"]


@pytest.mark.parametrize("qid", ["Q1", "Q2", "Q3", "Q4", "Q5"])
def test_bench_question_keywords_and_concepts(qid):
    expected = BENCH_EXPECTED[qid]
    assert question_keywords(expected["text"]) == expected["keywords"]
    assert question_concepts(expected["text"]) == expected["concepts"]


@pytest.mark.parametrize("question, keywords, concepts", EXTRA_CASES)
def test_extra_question_shapes(question, keywords, concepts):
    assert question_keywords(question) == keywords
    assert question_concepts(question) == concepts


def test_very_long_input_keeps_the_first_frame():
    long = Q2 * 20
    assert question_concepts(long) == question_concepts(Q2)
    first = question_keywords(Q2)
    assert question_keywords(long)[:len(first)] == first
    assert len(question_keywords(long)) > len(first)


def test_concepts_are_frozen():
    row = question_concepts(Q4)
    with pytest.raises(FrozenInstanceError):
        row.actor = ("nope",)


INVARIANT_QUESTIONS = [
    *(row["text"] for row in BENCH_QUESTIONS),
    *(case[0] for case in EXTRA_CASES),
    Q2 * 20,
    "How did X affect Y among Z during 1930s?",
    "What role did Congress play in recovery?",
    "US UK British",
    "1929-1939",
    "????",
    "affect change influence cause improve reduce increase",
    "the a of in role play impact effect during among",
]


# Independent of app.services.question_concepts._tokenize / _WORD.
_INDEPENDENT_TOKEN = re.compile(
    r"[A-Za-z](?:\.[A-Za-z])+\.?"
    r"|\d{4}\s*[–\-]\s*\d{4}"
    r"|\d{3,4}s"
    r"|[^\W\d_]+(?:['’\-][^\W\d_]+)*['’]?"
    r"|\d+"
)


def _independent_tokens(text: str) -> list[str]:
    return [match.group(0) for match in _INDEPENDENT_TOKEN.finditer(text or "")]


def _whole_tokens_from_question(phrase: str, question: str) -> bool:
    source = {token.casefold() for token in _independent_tokens(question)}
    parts = _independent_tokens(phrase)
    if not parts:
        return not (phrase or "").strip()
    return all(token.casefold() in source for token in parts)


@pytest.mark.parametrize("question", INVARIANT_QUESTIONS)
def test_every_output_token_comes_from_the_question(question):
    for phrase in question_keywords(question):
        assert _whole_tokens_from_question(phrase, question)
    concepts = question_concepts(question)
    for field in (
        concepts.actor, concepts.action, concepts.outcome,
        concepts.population, concepts.period, concepts.place,
    ):
        for phrase in field:
            assert _whole_tokens_from_question(phrase, question)


def test_invariant_rejects_partial_word_and_invented_word():
    question = "How does formative feedback affect sleep?"
    assert not _whole_tokens_from_question("form", question)
    assert not _whole_tokens_from_question("banana", question)
    assert _whole_tokens_from_question("formative", question)
    assert _whole_tokens_from_question("sleep", question)


def test_invariant_allows_scaffold_and_punctuation_removal():
    question = "How did the New, Deal affect society?"
    keywords = question_keywords(question)
    assert keywords == ["New Deal", "affect", "society"]
    for phrase in keywords:
        assert _whole_tokens_from_question(phrase, question)
    concepts = question_concepts(question)
    assert concepts.actor == ("New Deal",)
    assert concepts.action == ("affect",)
    assert concepts.outcome == ("society",)
    for phrase in (*concepts.actor, *concepts.action, *concepts.outcome):
        assert _whole_tokens_from_question(phrase, question)
