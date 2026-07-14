import numpy as np
import pytest

from database import ArticleDatabase
from user_db import UserDatabase


@pytest.fixture
def article_db(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "articles.db"))
    yield db
    db.close()


@pytest.fixture
def user_db(tmp_path):
    db = UserDatabase(db_path=str(tmp_path / "users.db"))
    yield db
    db.conn.close()


def test_user_create_and_get(user_db):
    created = user_db.create_user("alice", "hashed-pw")
    assert created["username"] == "alice"

    fetched = user_db.get_by_username("alice")
    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["hashed_password"] == "hashed-pw"

    by_id = user_db.get_by_id(created["id"])
    assert by_id is not None
    assert by_id["username"] == "alice"


def test_duplicate_username_rejected(user_db):
    user_db.create_user("bob", "pw1")
    # The UNIQUE constraint (case-insensitive) must reject a second "bob",
    # including a different-case variant, as a clean ValueError rather than a
    # raw IntegrityError / 500.
    with pytest.raises(ValueError):
        user_db.create_user("bob", "pw2")
    with pytest.raises(ValueError):
        user_db.create_user("BOB", "pw3")


def test_users_get_distinct_ids(user_db):
    a = user_db.create_user("carol", "pw")
    b = user_db.create_user("dave", "pw")
    # Per-user data isolation depends on these ids being unique — they key the
    # per-user article database directory (user_data/<id>/articles.db).
    assert a["id"] != b["id"]


def test_delete_user(user_db):
    u = user_db.create_user("frank", "pw")
    assert user_db.get_by_username("frank") is not None

    assert user_db.delete_user(u["id"]) is True
    assert user_db.get_by_username("frank") is None
    # Deleting a non-existent id is a no-op that reports False.
    assert user_db.delete_user(u["id"]) is False


def test_article_db_uses_wal_journal(tmp_path):
    """Fresh ArticleDatabase connections enable WAL to reduce lock errors."""
    db = ArticleDatabase(db_path=str(tmp_path / "wal.db"))
    try:
        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        db.close()


def test_insert_and_get_all_articles(article_db):
    articles = [
        {
            "article_id": "1",
            "source": "pubmed",
            "title": "A study",
            "abstract": "Some abstract",
            "year": "2024",
            "authors": ["Doe J"],
            "journal": "Nature",
        },
        {
            # Missing optional fields should not raise (C3 fix).
            "article_id": "2",
            "source": "arxiv",
        },
    ]
    dropped = article_db.insert_articles(articles)
    assert dropped == 0

    stored = article_db.get_all_articles()
    assert len(stored) == 2
    ids = {a["article_id"] for a in stored}
    assert ids == {"1", "2"}


def test_get_embedding_model(article_db):
    article_db.insert_articles([
        {"article_id": "1", "source": "pubmed", "title": "t", "abstract": "a"},
    ])
    # No embeddings yet.
    assert article_db.get_embedding_model() is None

    article_db.insert_embeddings(
        {("1", "pubmed"): np.arange(8, dtype=np.float32)}, model_name="pubmedbert"
    )
    # Search must know which model built the vectors, to match query dimensions.
    assert article_db.get_embedding_model() == "pubmedbert"


def test_embeddings_roundtrip_without_pickle(article_db):
    article_db.insert_articles([
        {"article_id": "1", "source": "pubmed", "title": "t",
         "abstract": "a", "year": "2024", "authors": [], "journal": "j"},
    ])
    vec = np.arange(8, dtype=np.float32)
    article_db.insert_embeddings({("1", "pubmed"): vec}, model_name="general")

    ids, embeddings = article_db.get_all_embeddings()
    assert ids == [("1", "pubmed")]
    assert embeddings.shape == (1, 8)
    np.testing.assert_array_equal(embeddings[0], vec)


def test_update_password_bumps_token_version(user_db):
    u = user_db.create_user("pwuser", "hash-old")
    assert u["token_version"] == 0
    assert user_db.get_by_username("pwuser")["token_version"] == 0
    assert user_db.update_password(u["id"], "hash-new") is True
    row = user_db.get_by_id(u["id"])
    assert row["hashed_password"] == "hash-new"
    assert row["token_version"] == 1
    assert user_db.update_password(u["id"], "hash-newer") is True
    assert user_db.get_by_id(u["id"])["token_version"] == 2
