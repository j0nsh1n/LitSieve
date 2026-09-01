"""Cache behaviour for Reader Mode explanations."""

from __future__ import annotations

from app.services import reader_mode
from app.storage.database import ArticleDatabase

PAPER = {
    "article_id": "34567890",
    "source": "pubmed",
    "title": "Later school start times and adolescent sleep",
    "abstract": (
        "Methods: In this randomised controlled trial, n = 512 participants were "
        "assigned to a sleep treatment or usual care. Results: Sleep rose 43 minutes "
        "per night (95% CI 21 to 65); 34% reported better sleep (p < 0.01). "
        "Conclusions: The treatment was associated with longer sleep."
    ),
}


def _payload(**overrides):
    data = dict(
        plain_summary="In this trial / experiment, sleep rose by 43 minutes.",
        question_asked="Does a later start increase sleep?",
        who_was_studied="512 participants in a sleep treatment.",
        what_was_found=(
            "Sleep rose 43 minutes (95% CI 21 to 65); 34% reported better sleep "
            "(p < 0.01). The treatment was associated with longer sleep."
        ),
        what_it_does_not_show="The abstract alone cannot establish whether these findings apply to everyone.",
        stated_limitations="Not reported in the abstract.",
        glossary=[],
        not_reported_fields=["stated_limitations"],
        method="rules+llm",
        provider="openai",
    )
    data.update(overrides)
    return data


def _db(tmp_path):
    database = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    database.insert_articles([PAPER], dedupe=False)
    return database


def test_second_request_is_cached(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_gen(**kwargs):
        calls["n"] += 1
        return _payload()

    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(reader_mode, "generate_reader_explanation", fake_gen)
    db = _db(tmp_path)
    try:
        first = reader_mode.explain_article(db, PAPER, "general_reader")
        second = reader_mode.explain_article(db, PAPER, "general_reader")
        assert calls["n"] == 1
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["content"]["plain_summary"] == first["content"]["plain_summary"]
    finally:
        db.close()


def test_audience_change_is_a_miss(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_gen(**kwargs):
        calls["n"] += 1
        return _payload()

    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(reader_mode, "generate_reader_explanation", fake_gen)
    db = _db(tmp_path)
    try:
        reader_mode.explain_article(db, PAPER, "general_reader")
        reader_mode.explain_article(db, PAPER, "high_school")
        assert calls["n"] == 2
    finally:
        db.close()


def test_abstract_change_invalidates(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(
        reader_mode, "generate_reader_explanation",
        lambda **k: (calls.__setitem__("n", calls["n"] + 1) or _payload()),
    )
    db = _db(tmp_path)
    try:
        reader_mode.explain_article(db, PAPER, "general_reader")
        changed = dict(PAPER, abstract=PAPER["abstract"] + " Follow-up lasted two years.")
        reader_mode.explain_article(db, changed, "general_reader")
        assert calls["n"] == 2
    finally:
        db.close()


def test_prompt_version_bump_invalidates(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(
        reader_mode, "generate_reader_explanation",
        lambda **k: (calls.__setitem__("n", calls["n"] + 1) or _payload()),
    )
    db = _db(tmp_path)
    try:
        reader_mode.explain_article(db, PAPER, "general_reader")
        monkeypatch.setattr(reader_mode, "READER_PROMPT_VERSION", "reader_v2")
        reader_mode.explain_article(db, PAPER, "general_reader")
        assert calls["n"] == 2
    finally:
        db.close()


def test_verifier_version_bump_invalidates(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(
        reader_mode, "generate_reader_explanation",
        lambda **k: (calls.__setitem__("n", calls["n"] + 1) or _payload()),
    )
    db = _db(tmp_path)
    try:
        reader_mode.explain_article(db, PAPER, "general_reader")
        # Derive the "next" version instead of hardcoding one: this test asserted
        # a bump to "v2" and silently stopped testing anything the day the real
        # constant reached v2.
        bumped = reader_mode.CURRENT_VERIFIER_VERSION + "-next"
        assert bumped != reader_mode.CURRENT_VERIFIER_VERSION
        monkeypatch.setattr(reader_mode, "CURRENT_VERIFIER_VERSION", bumped)
        reader_mode.explain_article(db, PAPER, "general_reader")
        assert calls["n"] == 2
    finally:
        db.close()


def test_get_endpoint_never_generates(tmp_path, monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        reader_mode, "generate_reader_explanation",
        lambda **k: (calls.__setitem__("n", calls["n"] + 1) or _payload()),
    )
    db = _db(tmp_path)
    try:
        miss = reader_mode.lookup_explanation(db, PAPER, "general_reader")
        assert miss is None
        assert calls["n"] == 0
    finally:
        db.close()


def test_cache_write_failure_still_returns_content(tmp_path, monkeypatch):
    monkeypatch.setattr(reader_mode, "is_configured", lambda: True)
    monkeypatch.setattr(reader_mode, "run_with_ephemeral_builtin", lambda fn: fn())
    monkeypatch.setattr(reader_mode, "generate_reader_explanation", lambda **k: _payload())
    db = _db(tmp_path)
    try:
        def boom(*a, **k):
            raise RuntimeError("disk full")

        monkeypatch.setattr(db, "upsert_reader_explanation", boom)
        result = reader_mode.explain_article(db, PAPER, "general_reader")
        assert result["cached"] is False
        assert result["content"]["plain_summary"]
    finally:
        db.close()
