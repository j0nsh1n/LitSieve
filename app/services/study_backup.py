"""Frozen study-type backup classifier."""

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from scipy.special import softmax
from sklearn.feature_extraction.text import TfidfVectorizer

CUES = {
    "n_participants": r"\b(participants?|respondents?|patients|subjects|students|teachers|adults|children)\b",
    "n_equals": r"\bn\s*=\s*\d+|\b\d{2,}\s+(participants|patients|students|adults|children|respondents|women|men)\b",
    "stats": r"\bp\s*[<=]\s*0?\.\d|confidence interval|\bci\b|odds ratio|hazard ratio|regression|significant(ly)?\b",
    "randomised": r"random(ly|ized|ised|isation|ization)|controlled trial|\brct\b|placebo|double[- ]blind",
    "intervention": r"\bintervention\b|pre[- ]?test|post[- ]?test|pilot study|feasibility|effects? of .{0,40}(program|training|therapy|exercise)|\bweeks? of\b|experimental group|control group",
    "cohort": r"\bcohort\b|longitudinal|cross[- ]sectional|case[- ]control|retrospective|prospective|panel data|follow[- ]up|observational|secondary analysis",
    "survey": r"\bsurvey(ed|s)?\b|questionnaire|self[- ]report|likert|\brespondents\b",
    "qual": r"\binterview(s|ed)?\b|focus groups?|thematic|grounded theory|phenomenolog|ethnograph|lived experience|qualitative",
    "syst": r"systematic(ally)? (review|search)|meta[- ]analy|prisma|scoping review|databases? (were )?searched|pooled",
    "review": r"\breview(s|ed)?\b|overview|state of the art|literature|this (article|chapter|paper) (discusses|examines|explores|reviews|describes|summari[sz]es)",
    "method": r"\b(we|this paper) (propose|present|develop|introduce)|novel (method|model|framework|approach|algorithm)|\bframework\b|\bsimulation\b|\balgorithm\b|validation of|\bscale development\b|psychometric",
    "opinion": r"\b(commentary|editorial|perspective|viewpoint|essay|opinion|letter to|we argue|i argue|should\b|must\b|this essay)\b",
    "history": r"\b1[5-9]\d\ds?\b|archiv|\bcentury\b|historical",
    "lab": r"\bin vitro\b|\bmice\b|\brats\b|spectroscop|synthesi[sz]ed|\bcell lines?\b|microscop",
    "casereport": r"case report|\ba case of\b|case stud(y|ies)",
    "first_person": r"\b(we|our)\b",
    "future": r"\bwill\b",
}
CUE_RX = {k: re.compile(v, re.I) for k, v in CUES.items()}


def cues(texts):
    A = np.zeros((len(texts), len(CUE_RX) + 4))
    for i, t in enumerate(texts):
        for j, rx in enumerate(CUE_RX.values()):
            A[i, j] = min(len(rx.findall(t)), 3) / 3
        n = len(t)
        A[i, -4] = min(n, 2500) / 2500
        A[i, -3] = n < 300
        A[i, -2] = len(re.findall(r"\d+(?:\.\d+)?%?", t)) >= 5
        A[i, -1] = bool(re.search(r"\b(background|methods?|results?|conclusions?)\s*:", t, re.I))
    return csr_matrix(A)


@lru_cache(maxsize=1)
def _model():
    path = Path(__file__).resolve().parent.parent / "content" / "study_type_backup.npz"
    with np.load(path, allow_pickle=False) as data:
        values = {key: data[key] for key in data.files}
    vocab = {word: i for i, word in enumerate(values["vocabulary"].tolist())}
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), sublinear_tf=True, stop_words="english", vocabulary=vocab
    )
    vectorizer.idf_ = values["idf"]
    return values, vectorizer


def probabilities(texts, embeddings=None):
    values, vectorizer = _model()
    features = hstack([vectorizer.transform(texts), cues(texts)]).tocsr()
    text_p = softmax(features @ values["text_coef"].T + values["text_intercept"], axis=1)
    if embeddings is None:
        return values["classes"], text_p
    embed_p = softmax(
        np.asarray(embeddings) @ values["embed_coef"].T + values["embed_intercept"], axis=1
    )
    return values["classes"], (text_p + embed_p) / 2


def classify(texts, model=None):
    embeddings = None
    if model is not None:
        embeddings = model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    classes, probs = probabilities(texts, embeddings)
    threshold = 0.4 if embeddings is not None else 0.6
    result = []
    for row in probs:
        index = int(np.argmax(row))
        label, score = str(classes[index]), float(row[index])
        result.append((label, score) if label != "none_fit" and score >= threshold else None)
    return result
