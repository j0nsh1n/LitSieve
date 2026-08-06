"""Optional at-rest database encryption (DB_ENCRYPTION_KEY + SQLCipher).

Encryption is opt-in; the default path must behave exactly as before, so these
tests cover both states and the failure modes that could destroy data.
"""

from __future__ import annotations

import os

import pytest

from app.storage import dbconn
from app.storage.database import ArticleDatabase

# CI always installs sqlcipher3-binary — fail hard there so encryption coverage
# cannot silently disappear. Locally, skip only if the optional package is missing.
if os.environ.get("CI"):
    import sqlcipher3 as sqlcipher  # noqa: F401
else:
    sqlcipher = pytest.importorskip(
        "sqlcipher3", reason="sqlcipher3-binary not installed (pip install -r requirements.txt)"
    )

ARTICLE = {
    "article_id": "1", "source": "pubmed", "title": "Confidential study title",
    "abstract": "A private abstract that must not appear in the raw file. " * 3,
    "year": "2024", "authors": ["Tester T"], "journal": "J",
}


def _seed(path, article=ARTICLE):
    db = ArticleDatabase(db_path=str(path))
    try:
        db.insert_articles([article], dedupe=False)
    finally:
        db.close()


def test_disabled_by_default_writes_plain_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    path = tmp_path / "plain.db"
    _seed(path)
    assert dbconn.encryption_enabled() is False
    assert path.read_bytes()[:16] == b"SQLite format 3\x00"
    assert dbconn.is_encrypted(str(path)) is False


def test_enabled_encrypts_contents_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv(dbconn.ENV_KEY, "a-test-key")
    path = tmp_path / "enc.db"
    _seed(path)

    raw = path.read_bytes()
    assert raw[:16] != b"SQLite format 3\x00"
    assert b"Confidential study title" not in raw
    assert dbconn.is_encrypted(str(path)) is True

    # Round-trips with the right key.
    db = ArticleDatabase(db_path=str(path))
    try:
        assert db.get_all_articles()[0]["title"] == "Confidential study title"
    finally:
        db.close()


def test_wrong_key_raises_instead_of_silently_creating_a_new_db(tmp_path, monkeypatch):
    monkeypatch.setenv(dbconn.ENV_KEY, "right-key")
    path = tmp_path / "enc.db"
    _seed(path)

    monkeypatch.setenv(dbconn.ENV_KEY, "wrong-key")
    with pytest.raises(dbconn.DatabaseKeyError):
        ArticleDatabase(db_path=str(path))


def test_plaintext_db_with_key_set_points_at_the_migration_tool(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    path = tmp_path / "plain.db"
    _seed(path)

    monkeypatch.setenv(dbconn.ENV_KEY, "a-test-key")
    with pytest.raises(dbconn.DatabaseKeyError) as exc:
        ArticleDatabase(db_path=str(path))
    assert "encrypt_databases.py" in str(exc.value)


def test_integrity_errors_covers_the_active_driver(monkeypatch):
    """sqlcipher3 has its own exception hierarchy.

    `except sqlite3.IntegrityError` stops matching the moment
    DB_ENCRYPTION_KEY is set, so a constraint violation would become an
    unhandled 500 only on encrypted deployments — exactly the config least
    likely to be exercised in testing.
    """
    import sqlite3

    from app.storage import dbconn

    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    plain = dbconn.integrity_errors()
    assert plain == (sqlite3.IntegrityError,)

    monkeypatch.setenv(dbconn.ENV_KEY, "k" * 32)
    keyed = dbconn.integrity_errors()
    assert sqlite3.IntegrityError in keyed
    assert len(keyed) == 2, f"sqlcipher IntegrityError not included: {keyed}"
    assert keyed[1] is not sqlite3.IntegrityError
