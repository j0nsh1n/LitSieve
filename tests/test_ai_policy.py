"""Phase R5: AI is opt-in, per-article only — no bulk library rewrite routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_no_bulk_ai_library_routes():
    """Guardrail: do not add silent whole-library AI rewrite endpoints."""
    paths = {getattr(r, "path", None) for r in app.routes}
    forbidden_substrings = (
        "/api/ai/summarize-library",
        "/api/ai/bulk",
        "/api/ai/rewrite-all",
        "/api/ai/grade-evidence",
    )
    for bad in forbidden_substrings:
        assert bad not in paths, f"unexpected bulk AI route: {bad}"


def test_ai_article_routes_exist_and_require_auth():
    client = TestClient(app)
    # Unauthenticated should not run the model.
    r = client.post(
        "/api/ai/refine-article",
        json={"article_id": "x", "source": "pubmed", "save_key_points": False},
    )
    assert r.status_code in (401, 403)
    r2 = client.post(
        "/api/ai/ask-article",
        json={"article_id": "x", "source": "pubmed", "question": "What was measured?"},
    )
    assert r2.status_code in (401, 403)


def test_finish_research_and_citation_guides_exist():
    client = TestClient(app)
    for slug in ("finish-your-research", "citation-quality"):
        r = client.get(f"/learn/{slug}")
        assert r.status_code == 200, slug
        assert "Starting point" in r.text or "starting point" in r.text.lower() or "peer" in r.text.lower()


def test_ai_key_points_save_requires_auth():
    client = TestClient(app)
    r = client.post(
        "/api/ai/key-points",
        json={"article_id": "x", "source": "pubmed", "key_points": ["A finding."]},
    )
    assert r.status_code in (401, 403)
