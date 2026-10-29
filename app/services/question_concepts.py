"""Split a student question into keywords and a few typed concept phrases.

Pure functions. No I/O, network, or model calls. Every output token must
already appear in the question; empty beats a guessed synonym.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PHRASES = (
    "second world war",
    "world war ii",
    "world war 2",
    "great depression",
    "victorian era",
    "african americans",
    "african american",
    "united states",
    "new deal",
    "cold war",
)

_ERA = frozenset({
    "great depression",
    "second world war",
    "world war ii",
    "world war 2",
    "cold war",
    "victorian era",
})

_SCAFFOLD = frozenset({
    "what", "how", "why", "which", "who", "when", "where", "whose",
    "did", "does", "do", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had",
    "the", "a", "an",
    "of", "in", "on", "at", "to", "for", "from", "by", "with", "as", "into",
    "role", "play", "played", "playing",
    "during", "among", "between", "within", "over",
    "that", "this", "these", "those",
    "and", "or", "but",
    "it", "its",
    "impact", "effect", "effects",
})

_RELATION = frozenset({
    "affect", "affects", "affected", "affecting",
    "change", "changes", "changed", "changing",
    "influence", "influences", "influenced", "influencing",
    "cause", "causes", "caused", "causing",
    "improve", "improves", "improved", "improving",
    "reduce", "reduces", "reduced", "reducing",
    "increase", "increases", "increased", "increasing",
    "decrease", "decreases", "decreased", "decreasing",
    "shape", "shapes", "shaped", "shaping",
})

_PLACES = frozenset({
    "u.s.", "u.s", "us", "usa", "uk", "united states",
    "britain", "british", "england", "english",
    "america", "american",
    "france", "french", "germany", "german",
    "canada", "canadian", "australia", "australian",
    "china", "chinese", "japan", "japanese",
    "india", "indian", "ireland", "irish",
    "scotland", "scottish", "wales", "welsh",
    "europe", "european", "italy", "italian",
    "spain", "spanish", "russia", "russian",
    "mexico", "mexican", "brazil", "brazilian",
    "africa", "african", "asia", "asian",
})

_POPULATION = frozenset({
    "african americans",
    "african american",
    "adolescents",
    "children",
    "students",
    "pupils",
    "patients",
    "workers",
    "women",
    "men",
    "youth",
    "teenagers",
    "americans",
})

_INTERROGATIVE = frozenset({
    "what", "how", "why", "which", "who", "when", "where",
})

_WORD = re.compile(
    r"U\.S\.?"
    r"|u\.s\.?"
    r"|\d{4}\s*[–\-]\s*\d{4}"
    r"|\d{3,4}s"
    r"|[^\W\d_]+(?:['’\-][^\W\d_]+)*['’]?"
    r"|[0-9]+",
)
_YEAR = re.compile(r"^(?:\d{3,4}s|\d{4}(?:\s*[–\-]\s*\d{4})?)$")
_POSSESSIVE_END = ("'s", "'", "\u2019s", "\u2019")


@dataclass(frozen=True)
class QuestionConcepts:
    actor: tuple[str, ...] = ()
    action: tuple[str, ...] = ()
    outcome: tuple[str, ...] = ()
    population: tuple[str, ...] = ()
    period: tuple[str, ...] = ()
    place: tuple[str, ...] = ()


def question_keywords(question: str) -> list[str]:
    """Content words in order, with question-frame scaffolding removed."""
    return [token for token in _tokenize(question) if not _is_scaffold(token)]


def question_concepts(question: str) -> QuestionConcepts:
    tokens = _tokenize(question)
    period = _matches(tokens, _is_period)
    place = _matches(tokens, _is_place)
    if not tokens or not _is_question_frame(tokens):
        return QuestionConcepts(period=period, place=place)
    actor, action, outcome, population = _parse_frame(tokens)
    return QuestionConcepts(
        actor=actor,
        action=action,
        outcome=outcome,
        population=population,
        period=period,
        place=place,
    )


def _tokenize(question: str) -> list[str]:
    words = [match.group(0) for match in _WORD.finditer(question or "")]
    if not words:
        return []
    folded = [word.casefold() for word in words]
    out: list[str] = []
    i = 0
    while i < len(words):
        merged = None
        for phrase in _PHRASES:
            parts = phrase.split()
            n = len(parts)
            if folded[i:i + n] == parts:
                merged = " ".join(words[i:i + n])
                out.append(merged)
                i += n
                break
        if merged is None:
            out.append(words[i])
            i += 1
    return out


def _is_scaffold(token: str) -> bool:
    if " " in token:
        return False
    folded = token.casefold()
    if folded in _RELATION:
        return False
    return folded in _SCAFFOLD


def _is_relation(token: str) -> bool:
    return token.casefold() in _RELATION


def _is_place(token: str) -> bool:
    return token.casefold() in _PLACES


def _is_period(token: str) -> bool:
    folded = token.casefold()
    if folded in _ERA:
        return True
    return bool(_YEAR.match(token.strip()))


def _is_question_frame(tokens: list[str]) -> bool:
    lower = [token.casefold() for token in tokens]
    if lower and lower[0] in _INTERROGATIVE:
        return True
    if "role" in lower and any(word in {"play", "played"} for word in lower):
        return True
    if any(word in {"effect", "effects", "impact"} for word in lower) and "of" in lower:
        return True
    return False


def _matches(tokens: list[str], pred) -> tuple[str, ...]:
    seen: list[str] = []
    found: set[str] = set()
    for token in tokens:
        if not pred(token):
            continue
        key = token.casefold()
        if key in found:
            continue
        found.add(key)
        seen.append(token)
    return tuple(seen)


def _idx(lower: list[str], *words: str, start: int = 0) -> int:
    wanted = set(words)
    for i in range(start, len(lower)):
        if lower[i] in wanted:
            return i
    return -1


def _phrase(tokens: list[str]) -> tuple[str, ...]:
    content = [token for token in tokens if not _is_scaffold(token)]
    if not content:
        return ()
    return (" ".join(content),)


def _is_population_span(tokens: list[str]) -> bool:
    content = [token for token in tokens if not _is_scaffold(token)]
    if not content:
        return False
    joined = " ".join(token.casefold() for token in content)
    if joined in _POPULATION:
        return True
    return len(content) == 1 and content[0].casefold() in _POPULATION


def _split_possessive(tokens: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    content = [token for token in tokens if not _is_scaffold(token)]
    poss = [
        i for i, token in enumerate(content)
        if token.endswith(_POSSESSIVE_END)
    ]
    if not poss:
        return None
    i = poss[-1]
    return _phrase(content[:i + 1]), _phrase(content[i + 1:])


def _split_y(tokens: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (outcome, population) for the Y span after a relation verb."""
    split = _split_possessive(tokens)
    if split is not None:
        population, outcome = split
        return outcome, population
    if _is_population_span(tokens):
        return (), _phrase(tokens)
    return _phrase(tokens), ()


def _setting_after_in(tokens: list[str], i: int) -> bool:
    if i >= len(tokens) or tokens[i].casefold() != "in":
        return False
    for token in tokens[i + 1:]:
        if _is_scaffold(token):
            continue
        return _is_place(token) or _is_period(token)
    return False


def _clause_end(tokens: list[str]) -> int:
    lower = [token.casefold() for token in tokens]
    for i, word in enumerate(lower):
        if word == "during":
            return i
        if _setting_after_in(tokens, i):
            return i
    return len(tokens)


def _tail_cut(tokens: list[str]) -> tuple[list[str], tuple[str, ...]]:
    """Cut Y at among/for/during/in-place. Return (y_tokens, population)."""
    lower = [token.casefold() for token in tokens]
    for i, word in enumerate(lower):
        if word in {"among", "for"}:
            pop_tokens = tokens[i + 1:_clause_end(tokens[i + 1:]) + i + 1]
            return tokens[:i], _phrase(pop_tokens)
        if word == "during":
            return tokens[:i], ()
        if _setting_after_in(tokens, i):
            return tokens[:i], ()
    return tokens, ()


def _parse_frame(tokens: list[str]) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...],
]:
    lower = [token.casefold() for token in tokens]
    role_i = _idx(lower, "role")
    play_i = _idx(lower, "play", "played")
    if role_i >= 0 and play_i > role_i:
        actor = _phrase(tokens[role_i + 1:play_i])
        rest_start = play_i + 1
        if rest_start < len(lower) and lower[rest_start] == "in":
            rest_start += 1
        y_tokens, population = _tail_cut(tokens[rest_start:])
        action, outcome, extra_pop = _role_y(y_tokens)
        return actor, action, outcome, extra_pop or population

    of_i = _idx(lower, "of")
    effect_i = _idx(lower, "effect", "effects", "impact")
    if effect_i >= 0 and of_i > effect_i:
        on_i = _idx(lower, "on", start=of_i + 1)
        if on_i <= of_i:
            return _phrase(tokens[of_i + 1:]), (), (), ()
        actor = _phrase(tokens[of_i + 1:on_i])
        y_tokens, population = _tail_cut(tokens[on_i + 1:])
        outcome, extra_pop = _split_y(y_tokens)
        return actor, (), outcome, extra_pop or population

    on_i = _idx(lower, "on")
    if effect_i >= 0 and on_i > effect_i:
        have_i = _idx(lower, "have", "has", "had", start=effect_i + 1)
        end_actor = have_i if have_i > effect_i else on_i
        actor = _phrase(tokens[effect_i + 1:end_actor])
        y_tokens, population = _tail_cut(tokens[on_i + 1:])
        outcome, extra_pop = _split_y(y_tokens)
        return actor, (), outcome, extra_pop or population

    rel_i = -1
    for i, token in enumerate(tokens):
        if _is_relation(token):
            rel_i = i
            break
    if rel_i < 0:
        return (), (), (), ()
    actor = _phrase(tokens[:rel_i])
    action = (tokens[rel_i],)
    y_tokens, population = _tail_cut(tokens[rel_i + 1:])
    outcome, extra_pop = _split_y(y_tokens)
    return actor, action, outcome, extra_pop or population


def _role_y(tokens: list[str]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    content = [token for token in tokens if not _is_scaffold(token)]
    if content and _is_relation(content[0]):
        return (content[0],), _phrase(content[1:]), ()
    outcome, population = _split_y(tokens)
    return (), outcome, population
