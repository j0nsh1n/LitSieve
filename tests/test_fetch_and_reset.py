"""Tests for fetch helpers, insert dedupe, and password-reset flow."""


from app.auth import hash_password, verify_password
from app.fetchers.base import FetchError, HttpClient, classify_error
from app.storage.database import ArticleDatabase
from app.storage.user_db import UserDatabase
from app.utils import build_screening_report, format_screening_report_txt


def test_classify_error_kinds():
    assert classify_error(FetchError("x", kind="rate_limited")) == "rate_limited"
    assert classify_error(FetchError("x", kind="network")) == "network"
    assert "rate" in classify_error(Exception("HTTP 429 too many")).lower() or \
        classify_error(Exception("HTTP 429 too many")) == "rate_limited"


def test_http_client_backoff_parses_retry_after():
    # Unit: _backoff_sleep accepts Retry-After without raising.
    HttpClient._backoff_sleep(0, retry_after="0")
    HttpClient._backoff_sleep(0, retry_after="not-a-number")


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


def test_insert_articles_upsert_does_not_wipe_children(tmp_path):
    """ON CONFLICT DO UPDATE must not cascade-delete embeddings."""
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
        import numpy as np
        db.insert_embeddings({("1", "pubmed"): np.ones(4, dtype=np.float32)}, "general")
        # Upsert same key with new title
        art2 = dict(art, title="Title updated")
        db.insert_articles([art2], dedupe=False)
        ids, emb = db.get_all_embeddings()
        assert len(ids) == 1
        assert db.get_article_by_id("1", "pubmed")["title"] == "Title updated"
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
        ok, err = udb.consume_password_reset_token("alice", "not-the-token", hash_password("tpw-fixture-0002"))
        assert not ok
        # Good token works
        ok, err = udb.consume_password_reset_token("alice", token, hash_password("tpw-fixture-0002"))
        assert ok, err
        row = udb.get_by_username("alice")
        assert verify_password("tpw-fixture-0002", row["hashed_password"])
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
