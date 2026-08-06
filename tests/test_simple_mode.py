"""Simple / Advanced UI mode — structural guardrails (Phase 5).

Simple mode is a client preference (localStorage.uiMode + data-mode on <html>).
These tests lock the contracts that are easy to break silently: theme-init
must set mode pre-paint, the nav must renumber without gaps when Clusters is
hidden, and hidden source checkboxes must still participate in fetch.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import route_paths
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def test_theme_init_sets_data_mode_before_paint():
    """theme-init must apply data-mode synchronously in <head> (no flash)."""
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    tag = re.search(r"<script[^>]*theme-init\.js[^>]*>", base)
    assert tag, "base.html no longer loads theme-init.js"
    assert "defer" not in tag.group(0), tag.group(0)
    assert "async" not in tag.group(0), tag.group(0)
    assert "type=\"module\"" not in tag.group(0).lower(), tag.group(0)
    head = base.split("</head>")[0]
    assert "theme-init.js" in head, "theme-init.js must be in <head>"

    init = (REPO / "static" / "js" / "theme-init.js").read_text(encoding="utf-8")
    assert "uiMode" in init
    assert "data-mode" in init
    assert "localStorage.getItem('uiMode')" in init or 'localStorage.getItem("uiMode")' in init
    # Must never load as module / deferred itself.
    assert "type=\"module\"" not in init
    assert "no defer" in init.lower() or "Must stay a plain blocking" in init


def test_mode_toggle_replaces_reading_mode():
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="mode-toggle"' in base
    assert "reading-toggle" not in base
    assert "readingMode" not in (REPO / "static" / "js" / "theme-init.js").read_text(
        encoding="utf-8"
    )
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "setUiMode" in common
    assert "isSimpleMode" in common
    assert "reading-toggle" not in common
    assert "setReadingMode" not in common


def test_simple_nav_steps_are_contiguous():
    """Simple mode hides Clusters; remaining steps must be 1, 2, 3 with no gap."""
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    # Workflow tuples: (key, label, href, tip, simple_step)
    rows = re.findall(
        r'\(\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"(\d*)"\s*\)',
        base,
    )
    assert rows, "base.html workflow must include simple_step as 5th tuple field"
    by_key = dict(rows)
    assert "clusters" in by_key, by_key
    assert by_key["clusters"] == "", "Clusters has no Simple step number (hidden)"
    visible = [by_key[k] for k in ("data_management", "statistics", "search")]
    assert visible == ["1", "2", "3"], f"Simple steps must be contiguous 1-3, got {visible}"

    # data-step-simple attributes drive the JS renumberer.
    assert 'data-step-simple="{{ simple_step }}"' in base or 'data-step-simple="' in base
    assert "nav-step-{{ key }}" in base or "nav-step-" in base

    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert "display: none" in css


def test_hidden_source_grid_still_submits_checked_sources():
    """Guard the 'hidden control still submits' trap.

    Simple mode CSS-hides the source grid; fetch must still read every checked
    checkbox (no :visible / offsetParent filter). Topics auto-check sources.
    """
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert "source-option-grid" in css
    # Hide via display on the section, not by disabling inputs.
    hide_block = re.search(
        r'html\[data-mode="simple"\][^{]*source-option-grid[^{]*\{[^}]+\}',
        css,
        re.DOTALL,
    )
    assert hide_block, "Simple mode must hide the source grid via CSS"
    assert "display:" in hide_block.group(0)
    assert "pointer-events: none" not in hide_block.group(0)

    dm_js = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")
    # doFetch source collection — must not filter by visibility.
    assert "source-option-grid input[type=\"checkbox\"]:checked" in dm_js or (
        "source-option-grid input[type='checkbox']:checked" in dm_js
    )
    assert "offsetParent" not in dm_js
    assert ":visible" not in dm_js
    assert "updateRecommendedSources" in dm_js
    # Auto-check when topics selected.
    assert "checkbox.checked = recommended.has(sourceId)" in dm_js


def test_register_seeds_simple_mode_cookie(tmp_path, monkeypatch):
    """Brand-new accounts get ui_mode_seed=simple; login alone must not."""
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": "newstudent1",
            "password": "tpw-fixture-0001",
            "password_confirm": "tpw-fixture-0001",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.cookies.get("ui_mode_seed") == "simple"

    # Logout then login of an "existing" account must not re-seed Simple.
    client.post("/logout", follow_redirects=False)
    # Clear client cookie jar seed so we only see what login sets.
    client.cookies.clear()
    r2 = client.post(
        "/login",
        data={"username": "newstudent1", "password": "tpw-fixture-0001"},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)
    assert r2.cookies.get("ui_mode_seed") in (None, "")


def test_clusters_route_still_exists():
    """Simple mode removes Clusters from the nav only — URL must still work."""
    paths = route_paths(app)
    assert "/clusters" in paths


def test_simple_prepare_section_is_optional_and_gated():
    """Simple mode: prepare is un-numbered, optional, and only shown with papers."""
    html = (REPO / "templates" / "data_management.html").read_text(encoding="utf-8")
    assert 'id="prepare-section"' in html
    assert "Optional: re-prepare for search" in html
    assert "prepare-heading-simple" in html
    assert "<strong>Optional.</strong>" in html or "Optional." in html
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert "prepare-heading-advanced" in css
    assert "prepare-heading-simple" in css
    dm = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")
    assert "updatePrepareSectionVisibility" in dm
    assert "forceShow" in dm


def test_simple_mode_renumbers_fetch_not_advanced():
    """Simple: Fetch is step 2 (sources hidden). Advanced keeps Fetch as step 3."""
    html = (REPO / "templates" / "data_management.html").read_text(encoding="utf-8")
    assert "dm-step-simple" in html
    assert "dm-step-advanced" in html
    assert "2. Fetch Articles" in html
    assert "3. Fetch Articles" in html
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    # Simple hides advanced labels; Advanced hides simple labels — no cross-bleed.
    assert 'html[data-mode="simple"] .dm-step-advanced' in css
    assert 'html:not([data-mode="simple"]) .dm-step-simple' in css


def test_fetch_auto_chains_to_prepare():
    """After a successful fetch, prepare starts without a second click (all modes).

    Zero papers / cancelled / quota must not start prepare.
    """
    dm = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")
    assert "fromAutoChain" in dm
    assert "Getting your papers ready" in dm
    # Auto-chain is not gated on Simple mode only.
    chain_block = dm[dm.find("fetchedOk") : dm.find("async function doCreateEmbeddings")]
    assert "fromAutoChain" in chain_block
    assert "isSimpleMode" not in chain_block
    # Guard: do not auto-start on empty fetch.
    assert "total_fetched" in dm
    # Must still go through the job API (never inline embed work in the page).
    assert "/api/create-embeddings" in dm
    assert "waitForJob" in dm


def test_low_relevance_is_system_reason_not_user_selectable():
    from app.content.screening_reasons import (
        EXCLUSION_REASONS,
        SYSTEM_REASONS,
        USER_SELECTABLE_REASONS,
        normalize_reason,
        reason_label,
    )

    assert "low_relevance" in EXCLUSION_REASONS
    assert "low_relevance" in SYSTEM_REASONS
    assert "low_relevance" not in USER_SELECTABLE_REASONS
    assert normalize_reason("low_relevance") == "low_relevance"
    assert "Low relevance" in reason_label("low_relevance")


def test_screening_report_includes_low_relevance_counts(tmp_path):
    from app.storage.database import ArticleDatabase
    from app.utils import build_screening_report, format_screening_report_txt

    db = ArticleDatabase(db_path=str(tmp_path / "lr.db"))
    try:
        db.insert_articles(
            [
                {
                    "article_id": "1",
                    "source": "pubmed",
                    "title": "A",
                    "abstract": "abs",
                    "year": "2020",
                    "authors": [],
                    "journal": "",
                },
                {
                    "article_id": "2",
                    "source": "pubmed",
                    "title": "B",
                    "abstract": "abs",
                    "year": "2020",
                    "authors": [],
                    "journal": "",
                },
            ],
            dedupe=False,
        )
        db.exclude_articles([("1", "pubmed")], reason="low_relevance")
        report = build_screening_report(db)
        assert report["excluded"]["low_relevance"] == 1
        txt = format_screening_report_txt(report)
        assert "Low relevance" in txt
    finally:
        db.close()


def test_quick_screen_preview_does_not_exclude(tmp_path):
    """Preview ranks only — apply is a separate POST /api/screening call."""
    import numpy as np

    from app.services.pipeline import LiteratureSearchPipeline

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "qs.db"))
    try:
        arts = [
            {
                "article_id": str(i),
                "source": "pubmed",
                "title": f"Title {i}",
                "abstract": f"abstract {i}",
                "year": "2020",
                "authors": [],
                "journal": "J",
            }
            for i in range(8)
        ]
        p.db.insert_articles(arts, dedupe=False)
        # Orthogonal-ish vectors so ranking is deterministic-ish.
        emb = {
            (str(i), "pubmed"): np.eye(8, dtype=np.float32)[i]
            for i in range(8)
        }
        p.db.insert_embeddings(emb, model_name="general")
        p.embedding_engine.embed_query = (  # type: ignore[method-assign]
            lambda _t: np.eye(8, dtype=np.float32)[0]
        )
        before = set(p.db.get_excluded_keys())
        result = p.propose_low_relevance("diabetes adolescents", fraction=0.25)
        after = set(p.db.get_excluded_keys())
        assert before == after, "preview must never write screening"
        assert result["total_ranked"] == 8
        assert result["proposed_count"] >= 1
        assert result["proposed_count"] < 8
        assert len(result["candidates"]) == result["proposed_count"]
        # Least similar to e0 should not include paper 0 (most similar).
        ids = {c["article_id"] for c in result["candidates"]}
        assert "0" not in ids
    finally:
        p.close()


def test_quick_screen_apply_and_reinclude_low_relevance(tmp_path):
    from app.storage.database import ArticleDatabase

    db = ArticleDatabase(db_path=str(tmp_path / "qs2.db"))
    try:
        db.insert_articles(
            [
                {
                    "article_id": "x",
                    "source": "pubmed",
                    "title": "X",
                    "abstract": "a",
                    "year": "2021",
                    "authors": [],
                    "journal": "",
                }
            ],
            dedupe=False,
        )
        n = db.exclude_articles([("x", "pubmed")], reason="low_relevance")
        assert n == 1
        assert ("x", "pubmed") in set(db.get_excluded_keys())
        n2 = db.include_articles([("x", "pubmed")])
        assert n2 == 1
        assert ("x", "pubmed") not in set(db.get_excluded_keys())
    finally:
        db.close()


def test_clean_up_page_and_quick_screen_ui_present():
    html = (REPO / "templates" / "statistics.html").read_text(encoding="utf-8")
    assert "Clean up" in html
    assert "quick-screen" in html
    assert "Preview suggestions" in html
    assert "cleanup-work" in html
    assert "empty-state-actions" in html
    js = (REPO / "static" / "js" / "statistics.js").read_text(encoding="utf-8")
    assert "/api/screening/quick-preview" in js
    assert "low_relevance" in js
    assert "doQuickScreenPreview" in js
    assert "doQuickScreenApply" in js
    assert "updateCleanupWorkVisibility" in js
    # Apply is a separate call from preview.
    assert js.index("quick-preview") < js.index("action: 'exclude'") or (
        "action: 'exclude'" in js and "low_relevance" in js
    )
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert ".empty-state-card > .info-text" in css


def test_search_not_relevant_button_uses_off_topic():
    """Per-card Not relevant screens out with off_topic and offers undo."""
    js = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "not-relevant-btn" in js
    assert "Not relevant" in js
    assert "off_topic" in js
    assert "replaceCardWithUndo" in js
    assert "undo-not-relevant" in js
    # Uses the shared screening endpoint (not a one-off API).
    assert "/api/screening" in js


def test_search_simple_subtitle_and_work_gate():
    """Simple mode drops Step 4 of 4; search UI stays hidden until papers are ready."""
    html = (REPO / "templates" / "search.html").read_text(encoding="utf-8")
    assert "search-sub-simple" in html
    assert "search-sub-advanced" in html
    assert "Step 4 of 4" in html  # Advanced only
    assert "search-work" in html
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'html[data-mode="simple"] .search-sub-advanced' in css
    assert 'html:not([data-mode="simple"]) .search-sub-simple' in css
    js = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert "updateSearchWorkVisibility" in js
    assert "articles_with_embeddings" in js
