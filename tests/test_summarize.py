"""Tests for extractive key points (structured parser + centroid fallback)."""

import numpy as np
import pytest

from summarize import (
    bullets_from_structured,
    extract_key_points,
    extract_key_points_batch,
    extract_key_points_centroid,
    extract_key_points_structured,
    parse_structured_abstract,
    rank_sentences_by_centroid,
    split_sentences,
)


STRUCTURED = (
    "BACKGROUND: Smoking is a major risk factor for cardiovascular disease. "
    "OBJECTIVE: To evaluate whether nicotine replacement reduces events. "
    "METHODS: We conducted a randomized trial of 1200 adults over 2 years. "
    "RESULTS: The intervention group had 30 percent fewer hospitalizations. "
    "CONCLUSIONS: Nicotine replacement is associated with fewer cardiac events."
)


def test_split_sentences_basic():
    sents = split_sentences("First sentence. Second one! Third?")
    assert sents == ["First sentence.", "Second one!", "Third?"]


def test_parse_structured_abstract_roles():
    sections = parse_structured_abstract(STRUCTURED)
    assert sections is not None
    assert "aim" in sections
    assert "method" in sections
    assert "findings" in sections
    assert "conclusion" in sections
    assert "evaluate whether nicotine" in sections["aim"].lower()
    assert "randomized trial" in sections["method"].lower()


def test_parse_unstructured_returns_none():
    plain = (
        "This abstract has no section headers at all. "
        "It just narrates findings about diabetes and exercise. "
        "Patients improved after twelve weeks of walking."
    )
    assert parse_structured_abstract(plain) is None


def test_structured_bullets_are_real_sentences():
    bullets = extract_key_points_structured(STRUCTURED)
    assert bullets is not None
    assert 3 <= len(bullets) <= 4
    # Every bullet must appear verbatim in the abstract (extractive guarantee).
    for b in bullets:
        assert b in STRUCTURED


def test_bullets_from_structured_order():
    sections = {
        "background": "Background text here.",
        "aim": "Aim text here.",
        "method": "Method text here.",
        "findings": "Findings text here.",
        "conclusion": "Conclusion text here.",
    }
    bullets = bullets_from_structured(sections, max_bullets=4)
    assert bullets[0] == "Aim text here."
    assert "Method text here." in bullets
    assert "Findings text here." in bullets
    assert "Conclusion text here." in bullets
    # Background is last preference and dropped when max is 4 with four better roles.
    assert "Background text here." not in bullets


def test_rank_sentences_by_centroid_original_order():
    # Three one-hot axes: sentence 0 and 2 are near the mean of a set that
    # also has a middle outlier along a different axis when we craft carefully.
    sentences = ["alpha", "beta", "gamma"]
    # Make alpha and gamma identical and strong; beta orthogonal.
    emb = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    top = rank_sentences_by_centroid(sentences, emb, top_k=2)
    # Top-2 by score are alpha and gamma; returned in original order.
    assert top == ["alpha", "gamma"]


def test_centroid_fallback_skips_short_abstracts():
    short = "Only one sentence here."
    called = []

    def encode(texts):
        called.append(texts)
        return np.ones((len(texts), 4), dtype=np.float32)

    assert extract_key_points_centroid(short, encode) == []
    assert called == []


def test_centroid_fallback_uses_encode_fn():
    # Three on-theme sentences + one off-theme so the centroid leans on-theme.
    abstract = (
        "Alpha covers the main theme of glucose control. "
        "Beta is a digression about parking lots near the hospital. "
        "Gamma also discusses glucose and insulin response. "
        "Delta again examines glucose levels after meals."
    )
    # Fake encoder: on-theme sentences share a vector; digression is orthogonal.
    def encode(texts):
        rows = []
        for t in texts:
            if "glucose" in t.lower() or "insulin" in t.lower():
                rows.append([1.0, 0.0, 0.0])
            else:
                rows.append([0.0, 1.0, 0.0])
        return np.array(rows, dtype=np.float32)

    bullets = extract_key_points_centroid(abstract, encode, top_k=2)
    assert len(bullets) == 2
    # Both selected bullets should be on-theme; original abstract order.
    assert all("glucose" in b.lower() or "insulin" in b.lower() for b in bullets)
    assert bullets[0].startswith("Alpha")
    for b in bullets:
        assert b in abstract


def test_extract_key_points_prefers_structured():
    def boom(_texts):
        raise AssertionError("encode should not run for structured abstracts")

    bullets = extract_key_points(STRUCTURED, encode_fn=boom)
    assert len(bullets) >= 3
    for b in bullets:
        assert b in STRUCTURED


def test_batch_mixed_structured_and_fallback():
    # Majority on-theme so centroid ranking prefers asthma sentences.
    plain = (
        "Sentence one about asthma inhalers and adherence. "
        "Sentence two about weather patterns in the region. "
        "Sentence three also covers asthma inhalers and children. "
        "Sentence four returns to asthma education programs."
    )
    articles = [
        {"article_id": "1", "source": "pubmed", "abstract": STRUCTURED},
        {"article_id": "2", "source": "arxiv", "abstract": plain},
        {"article_id": "3", "source": "pubmed", "abstract": "Too short."},
    ]

    def encode(texts):
        rows = []
        for t in texts:
            if "asthma" in t.lower():
                rows.append([1.0, 0.0])
            else:
                rows.append([0.0, 1.0])
        return np.array(rows, dtype=np.float32)

    out = extract_key_points_batch(articles, encode_fn=encode, top_k=2)
    assert ("1", "pubmed") in out
    assert len(out[("1", "pubmed")]) >= 3
    assert len(out[("2", "arxiv")]) == 2
    assert all("asthma" in b.lower() for b in out[("2", "arxiv")])
    assert out[("3", "pubmed")] == []


def test_key_points_roundtrip_in_db(tmp_path):
    from database import ArticleDatabase

    db = ArticleDatabase(db_path=str(tmp_path / "kp.db"))
    try:
        db.insert_articles(
            [
                {
                    "article_id": "x1",
                    "source": "pubmed",
                    "title": "T",
                    "abstract": STRUCTURED,
                    "year": "2020",
                    "authors": ["A"],
                    "journal": "J",
                }
            ]
        )
        n = db.insert_key_points({("x1", "pubmed"): ["Bullet one.", "Bullet two."]})
        assert n == 1
        m = db.get_key_points_map()
        assert m[("x1", "pubmed")] == ["Bullet one.", "Bullet two."]
        assert ("x1", "pubmed") in db.get_key_points_keys()
    finally:
        db.close()
