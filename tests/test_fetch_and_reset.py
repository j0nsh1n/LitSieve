"""Tests for fetch helpers, insert dedupe, and password-reset flow."""

from conftest import TEST_PASSWORD_ALT

from app.auth import hash_password, verify_password
from app.fetchers import base as base_module
from app.fetchers.base import FetchError, HttpClient, classify_error
from app.storage.database import ArticleDatabase
from app.storage.user_db import UserDatabase
from app.utils import build_screening_report, format_screening_report_txt


def test_classify_error_kinds():
    """Kinds drive the per-source error badges, so they must be exact.

    (The old version OR'd two conditions where the second could never fail
    independently, so a wrong-but-rate-ish string would have passed.)
    """
    assert classify_error(FetchError("x", kind="rate_limited")) == "rate_limited"
    assert classify_error(FetchError("x", kind="network")) == "network"
    # A bare exception is classified by its text.
    assert classify_error(Exception("HTTP 429 too many")) == "rate_limited"
    assert classify_error(Exception("something unexpected")) == "error"


def _record_sleeps(monkeypatch):
    """Capture how long _backoff_sleep would have slept, without sleeping."""
    slept: list[float] = []
    monkeypatch.setattr(base_module.time, "sleep", lambda s: slept.append(s))
    return slept


def test_backoff_honours_retry_after(monkeypatch):
    """A server's Retry-After wins; ignoring it is how you get IP-blocked."""
    slept = _record_sleeps(monkeypatch)
    HttpClient._backoff_sleep(0, retry_after="7")
    assert slept == [7.0]


def test_backoff_caps_absurd_retry_after(monkeypatch):
    """A hostile or broken header must not park a job for hours."""
    slept = _record_sleeps(monkeypatch)
    HttpClient._backoff_sleep(0, retry_after="86400")
    assert slept == [60.0]


def test_backoff_falls_back_when_retry_after_is_garbage(monkeypatch):
    """Unparseable header -> exponential path, not a crash and not zero."""
    slept = _record_sleeps(monkeypatch)
    HttpClient._backoff_sleep(0, retry_after="not-a-number")
    assert len(slept) == 1
    assert 0.5 <= slept[0] <= 0.75, slept


def test_backoff_is_exponential_and_capped(monkeypatch):
    """~0.5, 1, 2, 4 … with jitter, flattening at 30s."""
    slept = _record_sleeps(monkeypatch)
    for attempt in range(5):
        HttpClient._backoff_sleep(attempt, retry_after=None)
    HttpClient._backoff_sleep(99, retry_after=None)

    for attempt in range(5):
        expected = 0.5 * (2 ** attempt)
        assert expected <= slept[attempt] <= expected + 0.25, (attempt, slept)
    assert slept[:-1] == sorted(slept[:-1]), "backoff must not shrink"
    assert 30.0 <= slept[-1] <= 30.25, f"cap not applied: {slept[-1]}"


def test_backoff_zero_retry_after_does_not_stall(monkeypatch):
    """Retry-After: 0 means retry now."""
    slept = _record_sleeps(monkeypatch)
    HttpClient._backoff_sleep(3, retry_after="0")
    assert slept == [0.0]


def test_backoff_ignores_negative_retry_after(monkeypatch):
    """Negative is nonsense; fall back rather than compute a negative sleep."""
    slept = _record_sleeps(monkeypatch)
    HttpClient._backoff_sleep(0, retry_after="-5")
    assert len(slept) == 1 and slept[0] >= 0.5, slept


def test_insert_articles_dedupes_cross_source_title(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "d.db"))
    try:
        a = {
            "article_id": "10.1/a",
            "source": "crossref",
            "title": "A Study of Widgets",
            "abstract": "Abstract text long enough.",
            "year": "2020",
            "authors": ["A"],
            "journal": "J",
        }
        b = {
            "article_id": "pmid1",
            "source": "pubmed",
            "title": "A Study of Widgets",  # same title
            "abstract": "Abstract text long enough.",
            "year": "2020",
            "authors": ["A"],
            "journal": "J",
        }
        r1 = db.insert_articles([a], dedupe=True)
        assert r1["inserted"] == 1
        r2 = db.insert_articles([b], dedupe=True)
        assert r2["skipped_duplicates"] == 1
        assert len(db.get_all_articles()) == 1
    finally:
        db.close()


def test_insert_articles_upsert_does_not_wipe_notes(tmp_path):
    """ON CONFLICT DO UPDATE must not cascade-delete notes/stars."""
    db = ArticleDatabase(db_path=str(tmp_path / "e.db"))
    try:
        art = {
            "article_id": "1",
            "source": "pubmed",
            "title": "Title",
            "abstract": "Abstract",
            "year": "2021",
            "authors": [],
            "journal": "J",
        }
        db.insert_articles([art], dedupe=False)
        db.upsert_note("1", "pubmed", note="keep me", starred=True)
        import numpy as np
        db.insert_embeddings({("1", "pubmed"): np.ones(4, dtype=np.float32)}, "general")
        db.insert_key_points({("1", "pubmed"): ["old extractive"]}, origin="extractive")
        art2 = dict(art, title="Title updated")
        stats = db.insert_articles([art2], dedupe=False)
        assert stats["stale_derived"] == 1
        ids, _emb = db.get_all_embeddings()
        assert ids == []
        assert ("1", "pubmed") not in db.get_key_points_keys()
        note = db.get_note("1", "pubmed")
        assert note["note"] == "keep me"
        assert note["starred"] is True
        assert db.get_article_by_id("1", "pubmed")["title"] == "Title updated"
    finally:
        db.close()


def test_insert_articles_same_text_keeps_embeddings(tmp_path):
    """Year/authors refresh must not drop vectors built from unchanged text."""
    db = ArticleDatabase(db_path=str(tmp_path / "e2.db"))
    try:
        art = {
            "article_id": "1",
            "source": "pubmed",
            "title": "Title",
            "abstract": "Abstract",
            "year": "2021",
            "authors": [],
            "journal": "J",
        }
        db.insert_articles([art], dedupe=False)
        import numpy as np
        db.insert_embeddings({("1", "pubmed"): np.ones(4, dtype=np.float32)}, "general")
        stats = db.insert_articles([dict(art, year="2022")], dedupe=False)
        assert stats["stale_derived"] == 0
        ids, _emb = db.get_all_embeddings()
        assert len(ids) == 1
    finally:
        db.close()


def test_insert_articles_keeps_ai_key_points_when_text_changes(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "e3.db"))
    try:
        art = {
            "article_id": "1",
            "source": "pubmed",
            "title": "Title",
            "abstract": "Abstract text that is long enough.",
            "year": "2021",
            "authors": [],
            "journal": "J",
        }
        db.insert_articles([art], dedupe=False)
        db.insert_key_points({("1", "pubmed"): ["student rewrite"]}, origin="ai")
        db.insert_articles([dict(art, abstract="A different abstract entirely.")], dedupe=False)
        assert db.get_key_points_origin_map().get(("1", "pubmed")) == "ai"
        assert db.get_key_points_map()[("1", "pubmed")] == ["student rewrite"]
    finally:
        db.close()


def test_year_counts_and_screening_report(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "y.db"))
    try:
        db.insert_articles([
            {
                "article_id": "1", "source": "pubmed", "title": "A",
                "abstract": "abs", "year": "2019", "authors": [], "journal": "",
            },
            {
                "article_id": "2", "source": "pubmed", "title": "B",
                "abstract": "abs", "year": "2019", "authors": [], "journal": "",
            },
            {
                "article_id": "3", "source": "arxiv", "title": "C",
                "abstract": "abs", "year": "2022", "authors": [], "journal": "",
            },
        ], dedupe=False)
        counts = db.get_year_counts()
        assert counts.get("2019") == 2
        assert counts.get("2022") == 1
        report = build_screening_report(db)
        assert report["by_year"]["2019"] == 2
        txt = format_screening_report_txt(report)
        assert "By year:" in txt
        assert "2019: 2" in txt
    finally:
        db.close()


def test_password_reset_flow(tmp_path):
    udb = UserDatabase(db_path=str(tmp_path / "u.db"))
    try:
        user = udb.create_user("alice", hash_password("oldpassword"))
        assert user["username"] == "alice"
        token = udb.create_password_reset_token("alice")
        assert token
        # Wrong token fails
        ok, err = udb.consume_password_reset_token("alice", "not-the-token", hash_password(TEST_PASSWORD_ALT))
        assert not ok
        # Good token works
        ok, err = udb.consume_password_reset_token("alice", token, hash_password(TEST_PASSWORD_ALT))
        assert ok, err
        row = udb.get_by_username("alice")
        assert verify_password(TEST_PASSWORD_ALT, row["hashed_password"])
        assert int(row["token_version"]) == 1
        # Reuse fails
        ok, err = udb.consume_password_reset_token("alice", token, hash_password("anotherpass1"))
        assert not ok
    finally:
        udb.conn.close()


def test_foreign_keys_pragma_on(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "fk.db"))
    try:
        row = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert int(row[0]) == 1
    finally:
        db.close()
