"""Schema + persistence tests for Reader Mode explanations (PR 2 slice)."""

import json

import pytest

from app.storage.database import ArticleDatabase

AUDIENCE = "high_school"
CONTENT = {
    "plain_summary": "Students slept longer.",
    "question_asked": "Does later school start improve sleep?",
    "glossary": [{"term": "cohort", "definition": "A group followed over time."}],
}
VERIFICATION = {
    "status": "no_automatic_issues",
    "checks": [],
    "verifier_version": "v1",
}


@pytest.fixture
def db(tmp_path):
    database = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    database.insert_articles([
        {
            "article_id": "A1",
            "source": "pubmed",
            "title": "A sleep study",
            "abstract": "Students slept more after later start times.",
        },
        {
            "article_id": "A2",
            "source": "pubmed",
            "title": "Another study",
            "abstract": "A second abstract about sleep.",
        },
    ])
    yield database
    database.close()


def _upsert(database, article_id="A1", audience=AUDIENCE, **overrides):
    kwargs = dict(
        article_id=article_id,
        source="pubmed",
        audience=audience,
        abstract_hash="hash-1",
        prompt_version="reader_v1",
        content=CONTENT,
        verification=VERIFICATION,
        provider="ollama",
        model="llama3.1",
    )
    kwargs.update(overrides)
    database.upsert_reader_explanation(**kwargs)


def test_table_created_on_fresh_database(tmp_path):
    database = ArticleDatabase(db_path=str(tmp_path / "t.db"))
    try:
        names = [
            row[0]
            for row in database.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        ]
        assert "reader_explanations" in names
    finally:
        database.close()


def test_migrate_recreates_dropped_table_on_existing_db(db):
    """An existing library file (articles already present) gets the table back."""
    db.conn.execute("DROP TABLE reader_explanations")
    db.conn.commit()
    db.migrate_schema()
    _upsert(db)
    assert db.get_reader_explanation("A1", "pubmed", AUDIENCE) is not None


def test_upsert_then_get_round_trips_json(db):
    _upsert(db)
    got = db.get_reader_explanation("A1", "pubmed", AUDIENCE)
    assert got is not None
    assert got["article_id"] == "A1"
    assert got["source"] == "pubmed"
    assert got["audience"] == AUDIENCE
    assert got["abstract_hash"] == "hash-1"
    assert got["prompt_version"] == "reader_v1"
    assert got["verifier_version"] == "v1"
    assert got["content"] == CONTENT
    assert got["verification"] == VERIFICATION
    assert got["provider"] == "ollama"
    assert got["model"] == "llama3.1"
    assert got["created_at"] is not None


def test_on_conflict_updates_same_key(db):
    _upsert(db)
    updated_content = dict(CONTENT, plain_summary="Rewritten summary.")
    _upsert(db, abstract_hash="hash-2", prompt_version="reader_v2", content=updated_content)

    rows = db.conn.execute("SELECT COUNT(*) FROM reader_explanations").fetchone()[0]
    assert rows == 1

    got = db.get_reader_explanation("A1", "pubmed", AUDIENCE)
    assert got["abstract_hash"] == "hash-2"
    assert got["prompt_version"] == "reader_v2"
    assert got["content"]["plain_summary"] == "Rewritten summary."
    # untouched columns survive the update
    assert got["model"] == "llama3.1"


def test_different_audience_is_a_different_row(db):
    _upsert(db, audience="high_school")
    _upsert(db, audience="general_reader", abstract_hash="hash-hs")
    rows = db.conn.execute(
        "SELECT audience FROM reader_explanations ORDER BY audience"
    ).fetchall()
    assert [r[0] for r in rows] == ["general_reader", "high_school"]
    assert db.get_reader_explanation("A1", "pubmed", "general_reader")["abstract_hash"] == "hash-hs"


def test_deleting_article_cascades_explanation(db):
    _upsert(db, article_id="A2")
    assert db.get_reader_explanation("A2", "pubmed", AUDIENCE) is not None
    with db._lock:
        db.conn.execute(
            "DELETE FROM articles WHERE article_id = ? AND source = ?",
            ("A2", "pubmed"),
        )
        db.conn.commit()
    assert db.get_reader_explanation("A2", "pubmed", AUDIENCE) is None


def test_get_returns_none_for_unknown_key(db):
    _upsert(db)
    assert db.get_reader_explanation("ZZZ", "pubmed", AUDIENCE) is None
    assert db.get_reader_explanation("A1", "pubmed", "unknown_audience") is None


def test_malformed_content_json_returns_none(db):
    _upsert(db)
    with db._lock:
        db.conn.execute(
            "UPDATE reader_explanations SET content_json = ? "
            "WHERE article_id = ? AND source = ? AND audience = ?",
            ("{not json", "A1", "pubmed", AUDIENCE),
        )
        db.conn.commit()
    assert db.get_reader_explanation("A1", "pubmed", AUDIENCE) is None


def test_malformed_verification_json_returns_none(db):
    _upsert(db)
    with db._lock:
        db.conn.execute(
            "UPDATE reader_explanations SET verification_json = ? "
            "WHERE article_id = ? AND source = ? AND audience = ?",
            (json.dumps({"status": "needs_review"})[:-2], "A1", "pubmed", AUDIENCE),
        )
        db.conn.commit()
    assert db.get_reader_explanation("A1", "pubmed", AUDIENCE) is None
