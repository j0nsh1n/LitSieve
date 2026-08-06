"""Simple / Advanced UI mode — structural + dual-mode guardrails (Phase 5).

Simple mode is a client preference (localStorage.uiMode + data-mode on <html>).
These tests lock contracts that are easy to break silently:

* theme-init sets mode pre-paint (no flash)
* Simple and Advanced each get the right labels / visibility (no cross-bleed)
* Hidden source checkboxes still submit when the grid is CSS-hidden
* Fetch auto-chains prepare; Quick screen preview never auto-excludes
* Both modes keep capability reachability (Clusters URL, Advanced controls in DOM)
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import TEST_PASSWORD, route_paths
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pre-paint + toggle (both modes)
# ---------------------------------------------------------------------------


def test_theme_init_sets_data_mode_before_paint():
    """theme-init must apply data-mode synchronously in <head> (no flash)."""
    base = _read("templates", "base.html")
    tag = re.search(r"<script[^>]*theme-init\.js[^>]*>", base)
    assert tag, "base.html no longer loads theme-init.js"
    assert "defer" not in tag.group(0), tag.group(0)
    assert "async" not in tag.group(0), tag.group(0)
    assert "type=\"module\"" not in tag.group(0).lower(), tag.group(0)
    head = base.split("</head>")[0]
    assert "theme-init.js" in head, "theme-init.js must be in <head>"

    init = _read("static", "js", "theme-init.js")
    assert "uiMode" in init
    assert "data-mode" in init
    assert "localStorage.getItem('uiMode')" in init or 'localStorage.getItem("uiMode")' in init
    # Default Advanced when unset (existing accounts); seed cookie for new accounts.
    assert "advanced" in init
    assert "ui_mode_seed" in init
    assert "type=\"module\"" not in init
    assert "no defer" in init.lower() or "Must stay a plain blocking" in init


def test_mode_toggle_replaces_reading_mode():
    """Reading mode is retired; Simple/Advanced toggle owns the slot."""
    base = _read("templates", "base.html")
    assert 'id="mode-toggle"' in base
    assert "reading-toggle" not in base
    assert "readingMode" not in _read("static", "js", "theme-init.js")
    common = _read("static", "js", "common.js")
    assert "setUiMode" in common
    assert "isSimpleMode" in common
    assert "updateNavStepNumbers" in common
    assert "reading-toggle" not in common
    assert "setReadingMode" not in common
    css = _read("static", "css", "style.css")
    assert "data-reading" not in css
    assert ".mode-toggle" in css


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
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.cookies.get("ui_mode_seed") == "simple"

    client.post("/logout", follow_redirects=False)
    client.cookies.clear()
    r2 = client.post(
        "/login",
        data={"username": "newstudent1", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)
    assert r2.cookies.get("ui_mode_seed") in (None, "")


# ---------------------------------------------------------------------------
# Nav: Simple contiguous 1–3; Advanced keeps four steps including Clusters
# ---------------------------------------------------------------------------


def test_simple_nav_steps_are_contiguous():
    """Simple mode hides Clusters; remaining steps must be 1, 2, 3 with no gap."""
    base = _read("templates", "base.html")
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
    # Advanced step indices still 1–4 on the same workflow loop.
    assert "data-step-advanced" in base
    assert 'data-step-simple="{{ simple_step }}"' in base or 'data-step-simple="' in base

    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert "nav-flow-arrow-before-clusters" in css

    # Nav label is Clean up (not Duplicates).
    assert "Clean up" in base
    assert re.search(r'"statistics"\s*,\s*"Clean up"', base)


def test_advanced_nav_keeps_clusters_and_four_steps():
    """Advanced must still list Clusters; CSS only hides it under data-mode=simple."""
    base = _read("templates", "base.html")
    assert "nav-step-clusters" in base or "nav-step-{{ key }}" in base
    assert "/clusters" in base
    assert "Clusters" in base
    css = _read("static", "css", "style.css")
    # Advanced is the default when not simple — clusters rule is simple-only.
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert "html:not([data-mode=\"simple\"]) .nav-step-clusters" not in css


def test_clusters_route_still_exists():
    """Simple mode removes Clusters from the nav only — URL must still work."""
    paths = route_paths(app)
    assert "/clusters" in paths
    assert "/statistics" in paths
    assert "/search" in paths
    assert "/data-management" in paths


# ---------------------------------------------------------------------------
# Data Management: dual labels + hide surfaces + source submit trap
# ---------------------------------------------------------------------------


def test_simple_css_hides_power_surfaces_not_controls_from_dom():
    """Simple mode hides via CSS; Advanced surfaces stay in the HTML templates."""
    css = _read("static", "css", "style.css")
    for needle in (
        "source-option-grid",
        "coverage-bars",
        "nav-step-clusters",
        "sim-badge",
        "seed-input-panel",
    ):
        assert needle in css, f"Simple hide rule missing target: {needle}"

    # Sources / advanced options still exist in templates for Advanced + submit.
    dm = _read("templates", "data_management.html")
    assert 'id="source-option-grid"' in dm
    assert 'id="embedding-model"' in dm
    assert "Choose Sources" in dm or "source-option-grid" in dm

    search = _read("templates", "search.html")
    assert 'value="seed"' in search
    assert "lexical-boost" in search
    assert "lib-export-scope" in search


def test_hidden_source_grid_still_submits_checked_sources():
    """Guard the 'hidden control still submits' trap (both modes use same fetch JS)."""
    css = _read("static", "css", "style.css")
    hide_block = re.search(
        r'html\[data-mode="simple"\][^{]*source-option-grid[^{]*\{[^}]+\}',
        css,
        re.DOTALL,
    )
    assert hide_block, "Simple mode must hide the source grid via CSS"
    assert "display:" in hide_block.group(0)
    assert "pointer-events: none" not in hide_block.group(0)

    dm_js = _read("static", "js", "data_management.js")
    assert "source-option-grid input[type=\"checkbox\"]:checked" in dm_js or (
        "source-option-grid input[type='checkbox']:checked" in dm_js
    )
    assert "offsetParent" not in dm_js
    assert ":visible" not in dm_js
    assert "updateRecommendedSources" in dm_js
    assert "checkbox.checked = recommended.has(sourceId)" in dm_js


def test_simple_mode_renumbers_fetch_not_advanced():
    """Simple: Fetch is step 2 (sources hidden). Advanced keeps Fetch as step 3."""
    html = _read("templates", "data_management.html")
    assert "dm-step-simple" in html
    assert "dm-step-advanced" in html
    assert "2. Fetch Articles" in html
    assert "3. Fetch Articles" in html
    assert "dm-sub-simple" in html
    assert "dm-sub-advanced" in html
    assert "Steps 1–3." in html  # Advanced page lead (prepare is optional after auto-embed)
    assert "Steps 1–2." in html  # Simple page lead
    css = _read("static", "css", "style.css")
    # Simple labels default-hidden; advanced labels hide only under data-mode=simple.
    assert ".dm-step-simple" in css
    assert 'html[data-mode="simple"] .dm-step-advanced' in css
    assert 'html[data-mode="simple"] .dm-step-simple' in css
    assert 'html[data-mode="simple"] .dm-sub-advanced' in css
    assert 'html[data-mode="simple"] .dm-sub-simple' in css


def test_prepare_section_is_optional_and_gated_both_modes():
    """Both modes: optional prepare card, hidden until papers are ready (or forceShow)."""
    html = _read("templates", "data_management.html")
    assert 'id="prepare-section"' in html
    # Pre-JS default: hidden so the card never flashes on empty libraries.
    assert re.search(r'id="prepare-section"[^>]*\bhidden\b', html) or re.search(
        r'\bhidden\b[^>]*id="prepare-section"', html
    ), "prepare-section must start with the hidden attribute"
    assert "Optional: re-prepare for search" in html
    assert "prepare-heading-simple" in html
    assert "prepare-heading-advanced" in html
    # Advanced keeps step number but marks optional; Simple is un-numbered.
    assert "4. Optional: re-prepare for search" in html
    assert "<strong>Optional.</strong>" in html or "Optional." in html
    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"] .prepare-heading-advanced' in css
    assert ".prepare-heading-simple" in css
    dm = _read("static", "js", "data_management.js")
    assert "updatePrepareSectionVisibility" in dm
    assert "forceShow" in dm
    assert "_pipelineBusy" in dm
    assert "_lastReadyArticles" in dm
    assert "readyArticles" in dm
    # Same gate for both modes — no early unhide for Advanced only.
    fn = dm[dm.find("function updatePrepareSectionVisibility") : dm.find("async function loadPageData")]
    assert "if (!simple)" not in fn
    assert "_pipelineBusy" in fn
    assert "_lastReadyArticles" in fn


def test_fetch_form_submits_on_enter():
    """Enter in the query field must start fetch (native form submit → doFetch)."""
    html = _read("templates", "data_management.html")
    assert 'id="fetch-form"' in html
    assert 'type="submit"' in html and 'id="fetch-btn"' in html
    dm = _read("static", "js", "data_management.js")
    assert "fetch-form" in dm
    assert "preventDefault" in dm
    # Submit handler must call doFetch (not only a click listener on the button).
    assert re.search(r"fetch-form[\s\S]{0,200}doFetch|submit[\s\S]{0,80}doFetch", dm)


def test_fetch_auto_chains_to_prepare_both_modes():
    """After a successful fetch, prepare starts without a second click (all modes)."""
    dm = _read("static", "js", "data_management.js")
    assert "fromAutoChain" in dm
    assert "Getting your papers ready" in dm
    assert "_pipelineBusy" in dm
    assert "sawActive" in dm
    chain_block = dm[dm.find("fetchedOk") : dm.find("async function doCreateEmbeddings")]
    assert "fromAutoChain" in chain_block
    # Auto-chain must not be gated on Simple only.
    assert "isSimpleMode" not in chain_block
    assert "total_fetched" in dm
    assert "/api/create-embeddings" in dm
    assert "waitForJob" in dm
    # Progress for auto-chain uses the fetch bar so Simple always sees it.
    assert "fetch-progress-fill" in dm
    assert "fetch-progress-wrap" in dm


def test_silent_dedup_after_auto_prepare_simple_only():
    """Phase 6: Simple runs resolve-duplicates after prepare; failures never throw.

    Advanced must not auto-resolve here — Clean up remains the Advanced path.
    """
    dm = _read("static", "js", "data_management.js")
    assert "silentResolveDuplicatesAfterPrepare" in dm
    assert "/api/resolve-duplicates" in dm
    assert "threshold: 0.98" in dm or "threshold:0.98" in dm
    # Failure path continues (warn + null), never rethrows into the fetch chain.
    fn = dm[
        dm.find("async function silentResolveDuplicatesAfterPrepare") : dm.find(
            "async function doCreateEmbeddings"
        )
    ]
    assert "console.warn" in fn
    assert "return null" in fn
    # Called only on Simple auto-chain success, not for Advanced.
    assert "fromAutoChain && simple" in dm
    # Advanced Clean up still owns interactive resolve (unchanged page).
    stats_js = _read("static", "js", "statistics.js")
    assert "/api/resolve-duplicates" in stats_js
    assert "doResolveAll" in stats_js


def test_no_auto_cluster_on_fetch():
    """Clustering must never start from the fetch completion path."""
    dm = _read("static", "js", "data_management.js")
    # create-clusters must not appear in fetch success handling.
    fetch_fn = dm[dm.find("async function doFetch") : dm.find("async function doCreateEmbeddings")]
    assert "/api/create-clusters" not in fetch_fn
    assert "create-clusters" not in fetch_fn


# ---------------------------------------------------------------------------
# Clean up + Quick screen (both modes share page; Simple is default path)
# ---------------------------------------------------------------------------


def test_clean_up_page_and_quick_screen_ui_present():
    html = _read("templates", "statistics.html")
    assert "Clean up" in html
    assert "quick-screen" in html
    assert "Screen out least related" in html  # primary action
    assert "Preview first" in html  # optional, not primary
    assert "cleanup-work" in html
    assert "empty-state-actions" in html
    assert "1. Remove duplicates" in html
    assert "2. Quick screen" in html
    assert "3. Screening report" in html
    js = _read("static", "js", "statistics.js")
    assert "/api/screening/quick-preview" in js
    assert "low_relevance" in js
    assert "doQuickScreenApplyNow" in js
    assert "doQuickScreenPreview" in js
    assert "doQuickScreenApply" in js
    assert "doQuickScreenUndo" in js
    assert "updateCleanupWorkVisibility" in js
    # Primary path still uses separate preview + exclude API calls (apply is explicit).
    assert "quick-preview" in js
    assert "action: 'exclude'" in js or 'action: "exclude"' in js
    assert "low_relevance" in js


def test_quick_preview_route_registered():
    """Deploy guard: live app must expose quick-preview (avoids silent 404)."""
    paths = route_paths(app)
    assert "/api/screening/quick-preview" in paths
    assert "/api/screening" in paths


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
    # off_topic remains user-selectable (Search Not relevant / student pick).
    assert "off_topic" in USER_SELECTABLE_REASONS
    assert "off_topic" not in SYSTEM_REASONS


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
        emb = {(str(i), "pubmed"): np.eye(8, dtype=np.float32)[i] for i in range(8)}
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


# ---------------------------------------------------------------------------
# Search: dual subtitles + work gate + Not relevant (both modes)
# ---------------------------------------------------------------------------


def test_search_simple_subtitle_and_work_gate():
    """Simple mode drops Step 4 of 4; search UI stays hidden until papers are ready."""
    html = _read("templates", "search.html")
    assert "search-sub-simple" in html
    assert "search-sub-advanced" in html
    assert "search-title-simple" in html
    assert "search-title-advanced" in html
    assert "search-help-simple" in html
    assert "search-help-advanced" in html
    assert "Step 4 of 4" in html  # Advanced only
    assert "search-work" in html
    # Simple help must not mention Seed; Advanced help may.
    simple_help = html[html.find("search-help-simple") : html.find("input-method-toggle")]
    assert "Seed" not in simple_help
    assert "Seed" in html  # Advanced block still documents seed mode
    # Screening report link uses Clean up naming.
    assert "Clean up" in html or "/statistics" in html
    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"] .search-sub-advanced' in css
    assert ".search-sub-simple" in css  # default-hidden; shown under data-mode=simple
    assert 'html[data-mode="simple"] .search-sub-simple' in css
    assert 'html[data-mode="simple"] .search-title-advanced' in css
    assert "search-help-simple" in css
    js = _read("static", "js", "search.js")
    assert "updateSearchWorkVisibility" in js
    assert "articles_with_embeddings" in js
    assert "key_points_origin" in js


def test_search_not_relevant_button_uses_off_topic():
    """Per-card Not relevant screens out with off_topic and offers undo."""
    js = _read("static", "js", "search.js")
    assert "not-relevant-btn" in js
    assert "Not relevant" in js
    assert "off_topic" in js
    assert "replaceCardWithUndo" in js
    assert "undo-not-relevant" in js
    assert "/api/screening" in js


def test_search_advanced_keeps_seed_and_ranking_in_dom():
    """Advanced controls remain in the template (Simple only CSS-hides them)."""
    html = _read("templates", "search.html")
    assert 'value="seed"' in html
    assert "Seed paper" in html
    assert "lexical-boost" in html
    assert "Export whole library" in html or "lib-export-scope" in html
    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"]' in css and "seed" in css


# ---------------------------------------------------------------------------
# Cross-mode dual-label pattern (no cross-bleed)
# ---------------------------------------------------------------------------


def test_dual_mode_labels_never_cross_bleed_in_css():
    """Simple labels default-hidden; advanced counterparts hide under data-mode=simple.

    Default-hide (not html:not) is intentional: if data-mode is missing or CSS is
    partially applied, only Advanced text shows — never both stacked.
    """
    css = _read("static", "css", "style.css")
    pairs = [
        ("dm-step-advanced", "dm-step-simple"),
        ("dm-sub-advanced", "dm-sub-simple"),
        ("prepare-heading-advanced", "prepare-heading-simple"),
        ("prepare-lead-advanced", "prepare-lead-simple"),
        ("search-sub-advanced", "search-sub-simple"),
        ("search-title-advanced", "search-title-simple"),
        ("search-help-advanced", "search-help-simple"),
    ]
    for advanced, simple in pairs:
        assert (
            f'html[data-mode="simple"] .{advanced}' in css
            or f".{advanced}" in css
        ), f"missing simple-mode hide for {advanced}"
        # Simple variant must be hidden by default (not only under :not simple).
        assert f".{simple}" in css, f"missing default-hide for {simple}"
        assert (
            f'html[data-mode="simple"] .{simple}' in css
        ), f"missing simple-mode show for {simple}"


def test_ai_saved_key_points_survive_append_not_replace(tmp_path):
    """AI key points survive append-fetch + re-prepare; only replace clears them.

    Contract: keep until replace-collection (clear_all). Add-to-collection and
    re-search/re-prepare must not wipe student-approved AI rewrites.
    """
    from app.services.enrich import attach_key_points
    from app.services.pipeline import LiteratureSearchPipeline
    from app.storage.database import ArticleDatabase

    path = str(tmp_path / "kp.db")
    db = ArticleDatabase(db_path=path)
    try:
        db.insert_articles(
            [
                {
                    "article_id": "a1",
                    "source": "pubmed",
                    "title": "Paper A",
                    "abstract": "Abstract with enough text for key points extraction path.",
                    "year": "2020",
                    "authors": [],
                    "journal": "",
                }
            ],
            dedupe=False,
        )
        db.insert_key_points(
            {("a1", "pubmed"): ["AI bullet one.", "AI bullet two."]},
            origin="ai",
        )
        assert db.get_key_points_origin_map()[("a1", "pubmed")] == "ai"

        # Simulate append-fetch: add another paper, upsert existing metadata.
        db.insert_articles(
            [
                {
                    "article_id": "a1",
                    "source": "pubmed",
                    "title": "Paper A updated title",
                    "abstract": "Abstract with enough text for key points extraction path.",
                    "year": "2020",
                    "authors": [],
                    "journal": "",
                },
                {
                    "article_id": "a2",
                    "source": "pubmed",
                    "title": "Paper B",
                    "abstract": "Another abstract for a newly appended paper in the library.",
                    "year": "2021",
                    "authors": [],
                    "journal": "",
                },
            ],
            dedupe=False,
        )
        # Append prepare: only_missing=True and force full extractive both leave AI alone.
        p = LiteratureSearchPipeline(db_path=path)
        try:
            assert p._generate_key_points(only_missing=True) >= 0
            assert p._generate_key_points(only_missing=False) >= 0
            assert db.get_key_points_map()[("a1", "pubmed")] == [
                "AI bullet one.",
                "AI bullet two.",
            ]
            assert db.get_key_points_origin_map()[("a1", "pubmed")] == "ai"

            # Re-search style enrich still surfaces AI origin + bullets.
            arts = [{"article_id": "a1", "source": "pubmed"}]
            attach_key_points(arts, p)
            assert arts[0]["key_points"] == ["AI bullet one.", "AI bullet two."]
            assert arts[0]["key_points_origin"] == "ai"
        finally:
            p.close()

        # Replace-fetch wipes the library including AI key points.
        db.clear_all()
        assert db.get_key_points_map() == {}
        assert db.get_ai_key_points_keys() == set()
    finally:
        db.close()


# --- Fetch → prepare handoff (added after live review) ----------------------

def _dm_js() -> str:
    import pathlib
    return (pathlib.Path(__file__).resolve().parent.parent
            / "static" / "js" / "data_management.js").read_text()


def test_prepare_card_stays_hidden_while_auto_chain_runs():
    """Re-prepare must not appear while fetch or the first prepare is running.

    During an auto-chain the embed progress is mirrored onto the fetch bar, so
    the prepare card has nothing to show — revealing it mid-embed just pops a
    "Re-prepare" control into view for work already in progress. Gate is
    _pipelineBusy (covers fetch + auto-chain) and readyArticles > 0, for both modes.
    """
    src = _dm_js()
    assert "_pipelineBusy" in src
    assert "_lastReadyArticles" in src
    assert "if (_pipelineBusy)" in src or "if (_pipelineBusy) {" in src
    assert "readyArticles" in src
    # Auto-chain start must not force the card open mid-run.
    assert "fromAutoChain: true" in src
    # forceShow is only for failed auto-prepare recovery, not the happy path start.
    assert "autoChainFailed" in src
    # Must not use the old total-articles-only gate (showed mid-fetch with 0 ready).
    assert "sec.hidden = _autoChainActive ||" not in src
    # Advanced must not always force the card open.
    fn = src[src.find("function updatePrepareSectionVisibility") : src.find("async function loadPageData")]
    assert "isSimpleMode" not in fn or "if (!simple)" not in fn


def test_next_step_shortcut_exists_and_starts_hidden():
    """Simple users should not have to scroll back to the nav after a fetch."""
    import pathlib
    import re
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "templates" / "data_management.html").read_text()
    tag = re.search(r'<div[^>]*id="fetch-next-step"[^>]*>', html)
    assert tag, "fetch-next-step shortcut missing"
    assert "u-hidden" in tag.group(0), "shortcut must start hidden"
    assert 'href="/statistics"' in html, "shortcut must link to Clean up"


def test_next_step_shortcut_is_simple_mode_only_and_resets():
    src = _dm_js()
    assert "function setNextStepVisible" in src
    # Gated on Simple mode
    block = src.split("function setNextStepVisible", 1)[1].split("}\n", 1)[0]
    assert "isSimpleMode" in block, "shortcut must be Simple-mode only"
    # Hidden again when a new fetch starts, so it never points forward mid-job
    assert src.count("setNextStepVisible(false)") >= 2, (
        "shortcut must reset on a new fetch and when the chain starts"
    )
    assert "setNextStepVisible(true)" in src, "shortcut must appear on success"
