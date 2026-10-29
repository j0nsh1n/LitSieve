"""Word-match scores for hybrid ranking. No I/O.

BM25 is scaled by the query's theoretical max (sum of idf·(k1+1)), not by
min-max on the shortlist (audit 19.1).
"""

from __future__ import annotations

import math
import re
from typing import List, Sequence, Tuple

from app.services.question_concepts import question_keywords

WORD_WEIGHT = 0.2
RANK_FORMULA = "blend"
RANK_METHOD = "bm25"
RANK_QUERY_KIND = "keywords"
BM25_K1 = 1.5
BM25_B = 0.75
_BM25_TOKEN = re.compile(r"(?u)\b\w\w+\b")


def lexical_query_text(query: str, kind: str = RANK_QUERY_KIND) -> str:
    if kind == "keywords":
        return " ".join(question_keywords(query))
    return query or ""


def tfidf_scores(query_text: str, docs: Sequence[str]) -> List[float]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity as sk_cosine

    if not docs:
        return []
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        mat = vec.fit_transform(list(docs))
        q = vec.transform([query_text or ""])
        return [float(x) for x in sk_cosine(q, mat).ravel().tolist()]
    except Exception:
        return [0.0] * len(docs)


def bm25_tokens(text: str) -> List[str]:
    return [m.group(0).casefold() for m in _BM25_TOKEN.finditer(text or "")]


def bm25_scores(
    query_text: str,
    docs: Sequence[str],
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> List[float]:
    n_docs = len(docs)
    if n_docs == 0:
        return []
    tokenized = [bm25_tokens(doc) for doc in docs]
    avgdl = sum(len(toks) for toks in tokenized) / n_docs
    df: dict[str, int] = {}
    for toks in tokenized:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    query_terms = list(dict.fromkeys(bm25_tokens(query_text)))
    if not query_terms:
        return [0.0] * n_docs
    idf = {
        term: math.log(1.0 + (n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
        for term in query_terms
    }
    max_score = sum(idf[term] * (k1 + 1.0) for term in query_terms)
    if max_score <= 0:
        return [0.0] * n_docs
    out: List[float] = []
    for toks in tokenized:
        tf_map: dict[str, int] = {}
        for term in toks:
            tf_map[term] = tf_map.get(term, 0) + 1
        dl = len(toks)
        score = 0.0
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf <= 0:
                continue
            denom = tf + k1 * (1.0 - b + b * dl / (avgdl or 1.0))
            score += idf[term] * (tf * (k1 + 1.0)) / denom
        out.append(min(1.0, max(0.0, score / max_score)))
    return out


def lexical_scores(
    query_text: str,
    docs: Sequence[str],
    method: str = RANK_METHOD,
) -> List[float]:
    if method == "bm25":
        return bm25_scores(query_text, docs)
    return tfidf_scores(query_text, docs)


def combine_rank_score(
    semantic: float,
    lexical: float,
    formula: str = RANK_FORMULA,
    weight: float = WORD_WEIGHT,
) -> Tuple[float, float]:
    """Return (sort score, semantic) so bonus ties break on meaning."""
    sem = float(semantic)
    lex = float(lexical)
    w = float(weight)
    if formula == "bonus":
        return (min(1.0, sem + w * lex), sem)
    return ((1.0 - w) * sem + w * lex, sem)


def word_bonus_value(
    semantic: float,
    lexical: float,
    formula: str = RANK_FORMULA,
    weight: float = WORD_WEIGHT,
) -> float:
    """Lexical term actually mixed in. Bonus formula also caps sem + bonus at 1."""
    bonus = float(weight) * float(lexical)
    if formula == "bonus":
        return min(bonus, max(0.0, 1.0 - float(semantic)))
    return bonus
