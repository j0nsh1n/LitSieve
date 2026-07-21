"""v3.8: sample corpus, APA export, expanded exclusion reasons."""

from citations import article_to_apa, collection_to_apa
from database import ArticleDatabase
from sample_corpus import SAMPLE_SOURCE, get_sample_articles
from screening_reasons import USER_SELECTABLE_REASONS, normalize_reason, reason_label
from utils import build_screening_report, format_screening_report_txt


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


def test_apa_export_basic():
    art = {
        "article_id": "10.1234/ex",
        "source": "crossref",
        "title": "An example study of widgets",
        "year": "2020",
        "authors": ["Rivera M", "Chen L"],
        "journal": "Demo Journal",
        "abstract": "x",
    }
    line = article_to_apa(art)
    assert "2020" in line
    assert "widgets" in line.lower()
    assert "Demo Journal" in line or "Demo" in line
    assert "doi.org" in line
    block = collection_to_apa([art, art])
    assert block.count("2020") == 2


def test_normalize_reason_codes():
    assert normalize_reason("off_topic") == "off_topic"
    assert normalize_reason("OFF-TOPIC") == "off_topic"
    assert normalize_reason("nope") == "manual"
    assert normalize_reason(None) == "manual"
    assert "Off topic" in reason_label("off_topic")
    assert "off_topic" in USER_SELECTABLE_REASONS


def test_exclusion_reason_in_report(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "r.db"))
    try:
        db.insert_articles([
            {
                "article_id": "1", "source": "pubmed", "title": "A",
                "abstract": "abs", "year": "2020", "authors": [], "journal": "",
            },
            {
                "article_id": "2", "source": "pubmed", "title": "B",
                "abstract": "abs", "year": "2020", "authors": [], "journal": "",
            },
        ], dedupe=False)
        db.exclude_articles([("1", "pubmed")], reason="off_topic")
        db.exclude_articles([("2", "pubmed")], reason="wrong_population")
        report = build_screening_report(db)
        assert report["excluded"]["off_topic"] == 1
        assert report["excluded"]["wrong_population"] == 1
        assert report["excluded"]["total"] == 2
        txt = format_screening_report_txt(report)
        assert "Off topic" in txt
        assert "Wrong population" in txt
    finally:
        db.close()
