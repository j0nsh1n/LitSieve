"""
Extractive key points from article abstracts (no LLM).

Every bullet is a real sentence from the abstract. Preferred path: structured
PubMed/Europe PMC headers (BACKGROUND/OBJECTIVE/METHODS/RESULTS/CONCLUSIONS).
Fallback: rank sentences by cosine similarity to the abstract centroid using
the already-loaded embedding model.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Minimum sentences before the centroid fallback is worth running (fewer would
# just restate the whole abstract).
MIN_SENTENCES_FOR_FALLBACK = 3
DEFAULT_TOP_K = 3

# Header token (uppercased, stripped of trailing colon) -> role for mapping.
# Multiple headers can map to the same role; first non-empty wins per role.
STRUCTURED_HEADERS = {
    "BACKGROUND": "background",
    "INTRODUCTION": "background",
    "OBJECTIVE": "aim",
    "OBJECTIVES": "aim",
    "AIM": "aim",
    "AIMS": "aim",
    "PURPOSE": "aim",
    "PURPOSES": "aim",
    "GOAL": "aim",
    "GOALS": "aim",
    "METHOD": "method",
    "METHODS": "method",
    "METHODOLOGY": "method",
    "MATERIALS AND METHODS": "method",
    "DESIGN": "method",
    "RESULT": "findings",
    "RESULTS": "findings",
    "FINDING": "findings",
    "FINDINGS": "findings",
    "OUTCOME": "findings",
    "OUTCOMES": "findings",
    "CONCLUSION": "conclusion",
    "CONCLUSIONS": "conclusion",
    "INTERPRETATION": "conclusion",
    "DISCUSSION": "conclusion",
}

# Preferred order of roles in the final bullet list.
ROLE_ORDER = ("aim", "method", "findings", "conclusion", "background")

# Match "HEADER:" at start of abstract or after sentence-ish break.
# Headers are typically ALL CAPS (or Title Case) followed by a colon.
_HEADER_RE = re.compile(
    r"(?:^|[\n\r]|[.!?]\s+)"
    r"("
    r"BACKGROUND|INTRODUCTION|"
    r"OBJECTIVES?|AIMS?|PURPOSES?|GOALS?|"
    r"METHODS?|METHODOLOGY|MATERIALS\s+AND\s+METHODS|DESIGN|"
    r"RESULTS?|FINDINGS?|OUTCOMES?|"
    r"CONCLUSIONS?|INTERPRETATION|DISCUSSION"
    r")"
    r"\s*:\s*",
    re.IGNORECASE,
)

# Sentence splitter: end punctuation + whitespace, or newlines. Keep it simple
# and deterministic (no NLTK dependency).
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def split_sentences(text: str) -> List[str]:
    """Split abstract into non-empty stripped sentences."""
    if not text or not text.strip():
        return []
    parts = _SENT_SPLIT_RE.split(text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def parse_structured_abstract(abstract: str) -> Optional[Dict[str, str]]:
    """
    If the abstract uses labeled sections (HEADER: body), return a map of
    role -> section text. Returns None when fewer than two labeled sections
    are found (unstructured abstracts).
    """
    if not abstract or not abstract.strip():
        return None

    matches = list(_HEADER_RE.finditer(abstract))
    if len(matches) < 2:
        return None

    sections: Dict[str, str] = {}
    for i, m in enumerate(matches):
        header = re.sub(r"\s+", " ", m.group(1).upper().strip())
        role = STRUCTURED_HEADERS.get(header)
        if not role:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(abstract)
        body = abstract[start:end].strip()
        # Drop a trailing header fragment if the next match started mid-chunk.
        body = body.strip(" \t\n\r.;")
        if not body:
            continue
        # First non-empty section wins per role.
        if role not in sections:
            sections[role] = body

    if len(sections) < 2:
        return None
    return sections


def _first_sentence(text: str) -> str:
    sents = split_sentences(text)
    if sents:
        return sents[0]
    return (text or "").strip()


def bullets_from_structured(sections: Dict[str, str], max_bullets: int = 4) -> List[str]:
    """Map structured sections to 3–4 bullets in a stable order."""
    bullets: List[str] = []
    for role in ROLE_ORDER:
        if role not in sections:
            continue
        sent = _first_sentence(sections[role])
        if sent and sent not in bullets:
            bullets.append(sent)
        if len(bullets) >= max_bullets:
            break
    return bullets


def rank_sentences_by_centroid(
    sentences: Sequence[str],
    embeddings: np.ndarray,
    top_k: int = DEFAULT_TOP_K,
) -> List[str]:
    """
    Rank sentences by cosine similarity to the mean embedding; return top_k
    in their original abstract order (not score order).
    """
    if not sentences or embeddings is None or len(embeddings) == 0:
        return []
    n = min(len(sentences), len(embeddings))
    if n == 0:
        return []
    vecs = np.asarray(embeddings[:n], dtype=np.float32)
    # L2-normalise so mean + cosine is well-defined.
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.maximum(norms, 1e-12)
    vecs = vecs / norms
    centroid = vecs.mean(axis=0)
    cnorm = float(np.linalg.norm(centroid))
    if cnorm > 0:
        centroid = centroid / cnorm
    scores = vecs @ centroid
    k = min(top_k, n)
    # Indices of top-k by score, then restore original order.
    top_idx = np.argsort(-scores)[:k]
    ordered = sorted(int(i) for i in top_idx)
    return [sentences[i] for i in ordered]


def extract_key_points_structured(abstract: str, max_bullets: int = 4) -> Optional[List[str]]:
    """Return structured-header bullets, or None if abstract is unstructured."""
    sections = parse_structured_abstract(abstract)
    if not sections:
        return None
    bullets = bullets_from_structured(sections, max_bullets=max_bullets)
    return bullets or None


def extract_key_points_centroid(
    abstract: str,
    encode_fn,
    top_k: int = DEFAULT_TOP_K,
) -> List[str]:
    """
    Fallback: embed each sentence, rank by similarity to abstract centroid.

    encode_fn: callable(list[str]) -> np.ndarray of shape (n, dim)
    """
    sentences = split_sentences(abstract)
    if len(sentences) < MIN_SENTENCES_FOR_FALLBACK:
        return []
    embeddings = encode_fn(list(sentences))
    if embeddings is None or len(embeddings) == 0:
        return []
    return rank_sentences_by_centroid(sentences, embeddings, top_k=top_k)


def extract_key_points(
    abstract: str,
    encode_fn=None,
    top_k: int = DEFAULT_TOP_K,
) -> List[str]:
    """
    Full extractive pipeline for one abstract.

    Uses structured headers when present; otherwise centroid ranking when
    encode_fn is provided. Returns [] when neither path yields bullets
    (short/empty abstract).
    """
    structured = extract_key_points_structured(abstract, max_bullets=max(top_k, 4))
    if structured:
        return structured[: max(top_k, 4)]
    if encode_fn is None:
        return []
    return extract_key_points_centroid(abstract, encode_fn, top_k=top_k)


def extract_key_points_batch(
    articles: Sequence[Dict],
    encode_fn=None,
    top_k: int = DEFAULT_TOP_K,
    progress_callback=None,
) -> Dict[Tuple[str, str], List[str]]:
    """
    Compute key points for many articles.

    Structured abstracts avoid embedding. For unstructured ones, sentences are
    collected and encoded in one batch for efficiency.
    """
    out: Dict[Tuple[str, str], List[str]] = {}
    # (key, list of sentences) for centroid path
    fallback: List[Tuple[Tuple[str, str], List[str]]] = []
    total = len(articles)

    for i, article in enumerate(articles):
        key = (article["article_id"], article["source"])
        abstract = article.get("abstract") or ""
        structured = extract_key_points_structured(abstract, max_bullets=max(top_k, 4))
        if structured:
            out[key] = structured[: max(top_k, 4)]
        else:
            sents = split_sentences(abstract)
            if len(sents) >= MIN_SENTENCES_FOR_FALLBACK and encode_fn is not None:
                fallback.append((key, sents))
            else:
                out[key] = []
        if progress_callback and (i + 1) % 50 == 0:
            progress_callback(i + 1, total)

    if fallback and encode_fn is not None:
        # Flatten all sentences, encode once, then slice per article.
        flat: List[str] = []
        spans: List[Tuple[Tuple[str, str], int, int]] = []
        for key, sents in fallback:
            start = len(flat)
            flat.extend(sents)
            spans.append((key, start, len(flat)))
        try:
            all_emb = np.asarray(encode_fn(flat), dtype=np.float32)
        except Exception as e:
            logger.warning("Key-point sentence encode failed: %s", e)
            for key, _sents in fallback:
                out[key] = []
            return out
        for key, start, end in spans:
            sents = flat[start:end]
            emb = all_emb[start:end]
            out[key] = rank_sentences_by_centroid(sents, emb, top_k=top_k)

    if progress_callback:
        progress_callback(total, total)
    return out
