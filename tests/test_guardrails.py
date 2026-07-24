"""Product guardrails — fail loudly if an invariant is dropped.

These tests protect the code by locking contracts that should not regress
silently when features are added, fixed, or removed. Prefer behavior and
route-surface asserts over brittle marketing-copy snapshots.

If a guardrail fails, either restore the invariant or deliberately update
this file *and* context.md in the same change (never delete a guardrail
to “make green” without a product decision).
"""

from __future__ import annotations

from pathlib import Path

from conftest import route_paths
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Deleted API surfaces (v4.1.1+). Do not re-add without an explicit product need.
# ---------------------------------------------------------------------------
DELETED_ROUTES = {
    "/api/search/export",
    "/api/clear-articles",
    "/api/fetch-articles",  # single-source; use fetch-articles-multi
    "/api/clusters/briefings",
    "/api/generate-key-points",
    "/api/ai/status",  # status is embedded in GET /api/ai/settings
    "/api/screening-reasons",
    "/api/ai/session/begin",
    "/api/ai/session/end",
    "/api/ai/refine-library",
    "/api/ai/summarize-library",
    "/api/ai/ask-library",
    "/api/ai/bulk-refine",
    "/api/ai/evidence-grade",
    "/api/ai/rewrite-all",
    "/api/ai/grade-evidence",
}


# Routes the product still depends on (vacuous-pass guard for route_paths itself).
REQUIRED_ROUTES = {
    "/api/libraries",
    "/api/libraries/switch",
    "/api/fetch-articles-multi",
    "/api/create-embeddings",
    "/api/export/selection",
    "/api/export/library",
    "/api/screening-report",
    "/api/search",
    "/api/ai/settings",
    "/api/ai/refine-article",
    "/api/ai/ask-article",
    "/api/ai/key-points",
    "/api/shares",
    "/api/shares/preview",
    "/api/shares/join",
    "/join",
    "/account",
}


def test_deleted_routes_stay_gone():
    paths = route_paths(app)
    resurrected = paths & DELETED_ROUTES
    assert not resurrected, f"Deleted surfaces reappeared: {sorted(resurrected)}"


def test_required_routes_still_present():
    """If this fails with an empty paths set, route_paths is broken — fix it."""
    paths = route_paths(app)
    assert len(paths) >= 30, f"route_paths returned too few routes: {len(paths)}"
    missing = REQUIRED_ROUTES - paths
    assert not missing, f"Required routes missing: {sorted(missing)}"


def test_mutating_share_endpoints_require_auth():
    client = TestClient(app)
    for method, path, body in (
        ("POST", "/api/shares", {"expires_days": 7}),
        ("POST", "/api/shares/join", {"code": "ABCD-EFGH"}),
        ("DELETE", "/api/shares/not-a-real-id", None),
    ):
        if method == "POST":
            r = client.post(path, json=body or {})
        else:
            r = client.delete(path)
        assert r.status_code in (401, 403), f"{method} {path} → {r.status_code}"


def test_library_endpoints_require_auth():
    client = TestClient(app)
    assert client.get("/api/libraries").status_code in (401, 403)
    assert client.post("/api/libraries", json={"name": "x"}).status_code in (401, 403)
    assert client.post(
        "/api/libraries/switch", json={"library_id": "x"}
    ).status_code in (401, 403)


def test_export_selection_requires_auth():
    client = TestClient(app)
    r = client.post(
        "/api/export/selection",
        json={"format": "ris", "articles": []},
    )
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# UI structure: multi-library primary; optional clone codes collapsed
# ---------------------------------------------------------------------------

def test_account_libraries_primary_clone_optional_collapsed():
    html = (REPO / "templates" / "account.html").read_text(encoding="utf-8")
    assert 'id="library-manage-list"' in html
    assert "Create library" in html
    # Clone codes live under collapsed advanced details — not a teacher console.
    assert 'id="library-clone-details"' in html
    assert "advanced-details" in html
    assert 'library-clone-details" open' not in html
    assert 'id="account-join-code"' in html
    assert "Library code" in html
    # Primary library card must not re-introduce class/teacher LMS pitch.
    primary = html.split('id="library-clone-details"')[0]
    assert "class code" not in primary.lower()
    assert "your teacher" not in primary.lower()


def test_join_page_uses_library_code_wording():
    html = (REPO / "templates" / "join.html").read_text(encoding="utf-8")
    assert "Library code" in html
    assert "class code from your teacher" not in html.lower()
    # Clone-only framing stays visible.
    assert "not live" in html.lower() or "own copy" in html.lower()


def test_user_facing_copy_code_errors_use_library_terminology():
    """API errors surface in the join UI — keep student-facing language consistent."""
    from app.storage import shares as shares_mod

    ok, msg = shares_mod.is_share_usable({"revoked_at": "2020-01-01T00:00:00Z"})
    assert ok is False
    assert "library code" in msg.lower()
    assert "share code" not in msg.lower()
    assert "student" not in msg.lower()


# ---------------------------------------------------------------------------
# Source / fetcher registry lock (cheap; catalog test is the deep check)
# ---------------------------------------------------------------------------

def test_pipeline_fetchers_nonempty_and_catalog_aligned():
    from app.content.source_catalog import SOURCE_CATALOG
    from app.services.pipeline import FETCHERS

    assert len(FETCHERS) >= 15
    # Full 1:1 lock lives in test_source_catalog; this is a cheap fail-closed check.
    assert set(FETCHERS.keys()) == set(SOURCE_CATALOG.keys())
