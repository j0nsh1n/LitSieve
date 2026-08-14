"""Phase 9 — destructive fetch should become reversible.

Step 1 is copy only. The wipe-on-failed-replace test is xfail until the
staging swap (Step 3) lands: clear_all() still runs before any source is
queried.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.content.sample_corpus import get_sample_articles
from app.fetchers.base import FetchError
from app.routes import corpus as corpus_routes
from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.database import ArticleDatabase

REPO = Path(__file__).resolve().parents[1]
DM = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")


def test_simple_start_fresh_copy_names_what_it_destroys():
    """Existing dialog — no new click. Message must match library-delete honesty."""
    fn = DM[
        DM.index("async function resolveSimpleFetchModeBeforeRequest") : DM.index(
            "async function doFetch"
        )
    ]
    assert "Start fresh" in fn
    assert "this cannot be undone" in fn.lower()
    for word in ("notes", "stars", "key points"):
        assert word in fn.lower(), word


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


@pytest.mark.xfail(
    reason=(
        "replace-fetch still calls clear_all() before any source is queried "
        "(Phase 9 Step 3 staging swap)"
    ),
    strict=True,
)
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

        assert p.db.get_statistics()["total_articles"] == before_total
        assert p.db.get_note(key[0], key[1])["note"] == "keep this note"
        assert p.db.get_note(key[0], key[1])["starred"] is True
        assert key in p.db.get_ai_key_points_keys()
    finally:
        p.close()
