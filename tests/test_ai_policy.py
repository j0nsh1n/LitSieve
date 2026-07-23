"""AI guardrails: opt-in, one paper at a time, never a silent bulk rewrite.

These are policy tests. If one starts failing, the fix is usually a product
decision, not a test edit.
"""

from __future__ import annotations

from pathlib import Path

from conftest import route_paths
from fastapi.testclient import TestClient

from app.main import app


def test_no_bulk_ai_library_routes():
    """No whole-library rewrite / bulk Q&A / evidence-grading endpoints."""
    paths = route_paths(app)
    forbidden = {
        "/api/ai/refine-library",
        "/api/ai/summarize-library",
        "/api/ai/ask-library",
        "/api/ai/bulk-refine",
        "/api/ai/evidence-grade",
        "/api/ai/rewrite-all",
        "/api/ai/grade-evidence",
    }
    assert not (paths & forbidden)
    # The per-article endpoints must exist (guards against a vacuous pass).
    assert "/api/ai/refine-article" in paths
    assert "/api/ai/ask-article" in paths
    # Long-lived "keep the model warm" sessions were removed on purpose:
    # the built-in service starts and stops around each single request.
    assert "/api/ai/session/begin" not in paths
    assert "/api/ai/session/end" not in paths


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


def test_ai_key_points_save_requires_auth():
    client = TestClient(app)
    r = client.post(
        "/api/ai/key-points",
        json={"article_id": "x", "source": "pubmed", "key_points": ["A finding."]},
    )
    assert r.status_code in (401, 403)


def test_account_ai_card_collapsed_by_default():
    """The Account AI panel is optional and must not be forced open."""
    html = (Path(__file__).resolve().parents[1] / "templates" / "account.html").read_text(
        encoding="utf-8"
    )
    assert 'id="ai-settings-section"' in html
    assert 'id="ai-settings-details"' in html
    assert "optional" in html.lower()
    assert "built-in" in html.lower() or "study aid" in html.lower()
    assert 'ai-settings-details" open' not in html
