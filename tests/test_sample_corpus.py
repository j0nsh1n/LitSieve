"""The built-in demo corpus used for first-run / no-API-key classroom demos."""

from app.content.sample_corpus import SAMPLE_SOURCE, get_sample_articles
from app.storage.database import ArticleDatabase


def test_sample_corpus_shape():
    arts = get_sample_articles()
    assert len(arts) >= 15
    for a in arts:
        assert a["source"] == SAMPLE_SOURCE
        assert a["article_id"]
        assert a["title"]
        assert a["abstract"] and len(a["abstract"]) > 40
        assert a["year"]


def test_load_sample_into_db(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "s.db"))
    try:
        stats = db.insert_articles(get_sample_articles(), dedupe=True)
        assert stats["inserted"] == len(get_sample_articles())
        assert db.get_statistics()["total_articles"] == len(get_sample_articles())
        assert db.get_statistics()["sources"].get(SAMPLE_SOURCE) == len(get_sample_articles())
    finally:
        db.close()
