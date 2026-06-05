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
