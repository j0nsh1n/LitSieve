"""Phase 9 — destructive fetch should become reversible.

Replace-fetch stages into staging_articles and swaps only when at least one
paper arrived. Notes / stars / saved AI key points stay on papers that come
back; papers that do not return (and their notes) are deleted.
"""

from __future__ import annotations

from pathlib import Path

from app.content.sample_corpus import get_sample_articles
from app.fetchers.base import FetchError
from app.routes import corpus as corpus_routes
from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.database import ArticleDatabase

REPO = Path(__file__).resolve().parents[1]
DM = (REPO / "static" / "js" / "simple_tools.js").read_text(encoding="utf-8") + "\n" + (
    REPO / "static" / "js" / "data_management.js"
).read_text(encoding="utf-8")


def test_simple_start_fresh_copy_names_what_it_destroys():
    """Existing dialog — no new click. Message must match library-delete honesty."""
    fn = DM[
        DM.index("async function resolveSimpleFetchModeBeforeRequest") : DM.index(
            "async function doFetch"
        )
    ]
    assert "Start fresh" in fn
    assert "come back" in fn.lower()
    for word in ("notes", "stars", "key points"):
        assert word in fn.lower(), word


def test_sample_corpus_loads_rows_before_clearing():
    """In-process sample list must exist before clear_all; empty list must not wipe."""
    src = (REPO / "app" / "routes" / "corpus.py").read_text(encoding="utf-8")
    fn = src[
        src.index("async def api_load_sample_corpus") : src.index(
            "async def api_resolve_duplicates"
        )
    ]
    assert fn.index("get_sample_articles()") < fn.index("clear_all()")
    assert "Sample corpus is empty" in fn


def test_advanced_replace_consequence_is_inline_not_a_modal():
    """Advanced: live line next to the radio. Simple already hides that row."""
    html = (REPO / "templates" / "data_management.html").read_text(encoding="utf-8")
    assert 'id="fetch-replace-consequence"' in html
    assert 'name="fetch-mode"' in html
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'html[data-mode="simple"] .form-row:has(input[name="fetch-mode"])' in css

    assert "function updateReplaceConsequence" in DM
    assert "fetch-replace-consequence" in DM
    # Must not introduce a confirm/choice around Advanced radios.
    vis = DM[
        DM.index("function updateReplaceConsequence") : DM.index(
            "function updatePrepareSectionVisibility"
        )
    ]
    assert "openSiteChoice" not in vis
    assert "openSiteConfirm" not in vis
    assert "notes" in vis and "stars" in vis and "key point" in vis


def test_statistics_exposes_note_star_and_ai_key_point_counts(tmp_path):
    db = ArticleDatabase(db_path=str(tmp_path / "stats.db"))
    try:
        arts = get_sample_articles()[:2]
        db.insert_articles(arts, dedupe=True)
        a, b = arts[0], arts[1]
        db.upsert_note(a["article_id"], a["source"], note="a note", starred=True)
        db.upsert_note(b["article_id"], b["source"], note="", starred=True)
        db.insert_key_points(
            {(a["article_id"], a["source"]): ["saved"]}, origin="ai"
        )
        db.insert_key_points(
            {(b["article_id"], b["source"]): ["auto"]}, origin="extractive"
        )
        st = db.get_statistics()
        assert st["notes"] == 1
        assert st["starred"] == 2
        assert st["ai_key_points"] == 1
        assert st["total_articles"] == 2
    finally:
        db.close()


class _FailingFetcher:
    SOURCE_NAME = "pubmed"

    def __init__(self, email=None, **kwargs):
        self.email = email

    def search_and_fetch(self, query, max_results=200):
        raise FetchError("network down", kind="network")


class _OnlyAFetcher:
    SOURCE_NAME = "pubmed"

    def __init__(self, email=None, **kwargs):
        self.email = email

    def search_and_fetch(self, query, max_results=200):
        return [
            {
                "article_id": "a1",
                "source": "pubmed",
                "title": "Paper A again",
                "abstract": "Returned on the new search.",
                "year": "2020",
                "authors": ["A"],
                "journal": "J",
            }
        ]


def _paper(aid, title):
    return {
        "article_id": aid,
        "source": "pubmed",
        "title": title,
        "abstract": f"Abstract for {title}",
        "year": "2020",
        "authors": ["A"],
        "journal": "J",
    }


def test_failed_replace_fetch_leaves_collection_intact(tmp_path, monkeypatch):
    """All sources error → library, notes, stars, and AI key points unchanged."""
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FailingFetcher)

    db_path = str(tmp_path / "articles.db")
    p = LiteratureSearchPipeline(db_path=db_path)
    try:
        articles = get_sample_articles()
        p.db.insert_articles(articles, dedupe=True)
        first = articles[0]
        key = (first["article_id"], first["source"])
        p.db.upsert_note(key[0], key[1], note="keep this note", starred=True)
        p.db.insert_key_points({key: ["student-saved bullet"]}, origin="ai")

        before_total = p.db.get_statistics()["total_articles"]
        assert before_total >= 10
        assert p.db.get_note(key[0], key[1])["note"] == "keep this note"
        assert p.db.get_note(key[0], key[1])["starred"] is True
        assert key in p.db.get_ai_key_points_keys()

        result = corpus_routes._run_multi_fetch(
            p,
            query="anything",
            sources=["pubmed"],
            max_results=5,
            email=None,
            clear_first=True,
            uid="phase9-user",
        )
        assert result["total_fetched"] == 0
        assert result["errors"]
        assert result["cleared_first"] is False
        assert p.db.count_staging_articles() == 0

        assert p.db.get_statistics()["total_articles"] == before_total
        assert p.db.get_note(key[0], key[1])["note"] == "keep this note"
        assert p.db.get_note(key[0], key[1])["starred"] is True
        assert key in p.db.get_ai_key_points_keys()
    finally:
        p.close()


def test_successful_replace_keeps_work_on_papers_that_return(tmp_path, monkeypatch):
    """Overlap keeps notes/stars/AI key points; gone papers (and their notes) drop."""
    import numpy as np

    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _OnlyAFetcher)

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "swap.db"))
    try:
        p.db.insert_articles([_paper("a1", "Paper A"), _paper("b1", "Paper B")], dedupe=False)
        p.db.upsert_note("a1", "pubmed", note="keep me", starred=True)
        p.db.upsert_note("b1", "pubmed", note="drop me", starred=True)
        p.db.insert_key_points({("a1", "pubmed"): ["saved A"]}, origin="ai")
        p.db.insert_key_points({("b1", "pubmed"): ["extractive B"]}, origin="extractive")
        p.db.exclude_articles([("a1", "pubmed")], reason="off_topic")
        p.db.insert_embeddings(
            {("a1", "pubmed"): np.array([1.0, 0.0], dtype=np.float32)},
            model_name="general",
        )

        result = corpus_routes._run_multi_fetch(
            p,
            query="new query",
            sources=["pubmed"],
            max_results=5,
            email=None,
            clear_first=True,
            uid="phase9-swap",
        )
        assert result["total_fetched"] == 1
        assert result["cleared_first"] is True
        assert p.db.count_staging_articles() == 0

        ids = {(a["article_id"], a["source"]) for a in p.db.get_all_articles()}
        assert ids == {("a1", "pubmed")}
        note_a = p.db.get_note("a1", "pubmed")
        assert note_a["note"] == "keep me"
        assert note_a["starred"] is True
        assert ("a1", "pubmed") in p.db.get_ai_key_points_keys()
        assert p.db.get_note("b1", "pubmed")["note"] == ""
        assert ("b1", "pubmed") not in p.db.get_ai_key_points_keys()
        assert ("a1", "pubmed") in p.db.get_excluded_keys()
        assert ("a1", "pubmed") in p.db.get_embedding_keys()
        titles = {a["title"] for a in p.db.get_all_articles()}
        assert "Paper A again" in titles
    finally:
        p.close()


def test_append_fetch_does_not_use_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _OnlyAFetcher)

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "append.db"))
    try:
        p.db.insert_articles([_paper("b1", "Paper B")], dedupe=False)
        p.db.upsert_note("b1", "pubmed", note="old note", starred=False)
        result = corpus_routes._run_multi_fetch(
            p,
            query="x",
            sources=["pubmed"],
            max_results=5,
            email=None,
            clear_first=False,
            uid="phase9-append",
        )
        assert result["cleared_first"] is False
        assert result["total_fetched"] >= 1
        ids = {(a["article_id"], a["source"]) for a in p.db.get_all_articles()}
        assert ("b1", "pubmed") in ids
        assert ("a1", "pubmed") in ids
        assert p.db.get_note("b1", "pubmed")["note"] == "old note"
        assert p.db.count_staging_articles() == 0
    finally:
        p.close()


def test_replace_quota_credit_ignores_live_library_size(tmp_path, monkeypatch):
    from app.storage import quota

    db_path = tmp_path / "lib" / "articles.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"x" * 2000)
    monkeypatch.setattr(quota, "limit_bytes", lambda: 100)
    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 2000)
    assert quota.is_over_quota("u") is True
    credit = quota.library_file_bytes(str(db_path))
    assert credit == 2000
    assert quota.is_over_quota("u", reclaimable=credit) is False
