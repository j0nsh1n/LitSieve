"""Phases R5–R8 polish: AI coach defaults, guides, scale smoke, no bulk AI."""

from __future__ import annotations

import time

from conftest import route_paths
from fastapi.testclient import TestClient

from app.content.feature_guides import FEATURE_ORDER, get_guide, list_guides
from app.main import app
from app.storage.database import ArticleDatabase


def test_account_ai_card_collapsed_by_default():
    """R5: Account AI card is a collapsed <details>, with first-run optional note."""
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "templates" / "account.html").read_text(
        encoding="utf-8"
    )
    assert 'id="ai-settings-section"' in html
    assert 'id="ai-settings-details"' in html
    assert "optional" in html.lower()
    assert "built-in" in html.lower() or "study aid" in html.lower()
    # Must not force the outer AI panel open on first visit.
    assert 'id="ai-settings-details" open' not in html
    assert 'ai-settings-details" open' not in html


def test_no_bulk_ai_library_endpoints():
    """R5: refuse whole-library AI rewrite / bulk Q&A routes."""
    paths = route_paths(app)
    forbidden = {
        "/api/ai/refine-library",
        "/api/ai/summarize-library",
        "/api/ai/ask-library",
        "/api/ai/bulk-refine",
        "/api/ai/evidence-grade",
    }
    assert not (paths & forbidden)
    assert "/api/ai/refine-article" in paths
    assert "/api/ai/ask-article" in paths
    # Long-lived ask sessions removed — ephemeral start/stop only.
    assert "/api/ai/session/begin" not in paths
    assert "/api/ai/session/end" not in paths


def test_finish_research_and_citation_guides():
    """R7: college-adjacent guides exist with checklists."""
    assert "finish-your-research" in FEATURE_ORDER
    assert "citation-quality" in FEATURE_ORDER
    fin = get_guide("finish-your-research")
    cit = get_guide("citation-quality")
    assert fin and cit
    assert "school library" in (fin["summary"] + " ".join(fin["how_it_works"])).lower()
    assert "google scholar" in " ".join(fin["how_it_works"]).lower()
    assert fin.get("checklists")
    assert cit.get("checklists")
    titles = " ".join(b["title"] for b in cit["checklists"]).lower()
    assert "citation" in titles
    assert "appraisal" in titles or "signal" in titles
    # Weak appraisal must not claim clinical grades.
    body = " ".join(
        " ".join(b.get("checks") or []) + " " + (b.get("intro") or "")
        for b in cit["checklists"]
    ).lower()
    assert "not" in body and ("a–d" in body or "a-d" in body or "clinical" in body)

    client = TestClient(app)
    for slug in ("finish-your-research", "citation-quality"):
        r = client.get(f"/learn/{slug}")
        assert r.status_code == 200, slug
        assert get_guide(slug)["title"].split()[0] in r.text or get_guide(slug)["title"] in r.text
        assert "checklist" in r.text.lower() or "peer-reviewed" in r.text.lower()

    landing = client.get("/")
    assert landing.status_code == 200
    assert "/learn/finish-your-research" in landing.text
    assert "/learn/citation-quality" in landing.text


def test_list_guides_includes_r7():
    slugs = [g["slug"] for g in list_guides()]
    assert slugs[-2:] == ["finish-your-research", "citation-quality"] or (
        "finish-your-research" in slugs and "citation-quality" in slugs
    )


def test_scale_1k_articles_list_and_stats(tmp_path):
    """R8: 1k+ corpus list/statistics stay responsive after pagination design."""
    db = ArticleDatabase(db_path=str(tmp_path / "scale.db"))
    try:
        batch = []
        for i in range(1200):
            batch.append({
                "article_id": f"scale-{i}",
                "source": "pubmed" if i % 3 else "openalex",
                "title": f"Scale test paper {i} on climate and health outcomes",
                "abstract": (
                    f"Abstract {i}: this is a synthetic abstract used only for "
                    f"scale smoke testing of list and statistics paths. " * 2
                ),
                "year": str(2000 + (i % 25)),
                "authors": [f"Author {i % 40}"],
                "journal": "Journal of Scale Tests",
            })
            if len(batch) >= 200:
                db.insert_articles(batch)
                batch = []
        if batch:
            db.insert_articles(batch)

        t0 = time.perf_counter()
        all_articles = db.get_all_articles()
        stats_elapsed = time.perf_counter() - t0
        assert len(all_articles) >= 1200
        # Generous bound for CI; documents that 1k list is not multi-second.
        assert stats_elapsed < 5.0, f"get_all_articles too slow: {stats_elapsed:.2f}s"

        # Pagination UI uses page size 50 — ensure we can slice without error.
        page_size = 50
        pages = [
            all_articles[i : i + page_size]
            for i in range(0, len(all_articles), page_size)
        ]
        assert len(pages) >= 24
        assert sum(len(p) for p in pages) == len(all_articles)
    finally:
        db.close()
