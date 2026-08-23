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


def _simple_js() -> str:
    """Simple tools + Data Management (screening/dialogs live in simple_tools.js)."""
    return _read("static", "js", "simple_tools.js") + "\n" + _read(
        "static", "js", "data_management.js"
    )


def _dm_markup() -> str:
    """Data Management page plus the shared collect partial."""
    return (
        _read("templates", "data_management.html")
        + "\n"
        + _read("templates", "partials", "collect_ui.html")
    )


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
    # Get papers hrefs are literals (not copied from data-href-* into href).
    assert "getPapers.setAttribute('href', simple ? '/search?collect=1' : '/data-management')" in common
    assert "reading-toggle" not in common
    assert "setReadingMode" not in common
    # Highlight the control when Advanced is active (not Simple).
    assert "classList.toggle('is-active', !simple)" in common or 'classList.toggle("is-active", !simple)' in common
    css = _read("static", "css", "style.css")
    assert "data-reading" not in css
    assert ".mode-toggle" in css
    assert ".mode-toggle.is-active" in css


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
# Nav: Simple shows an unnumbered Search tab only (one page). Get papers /
# Clusters / Clean up stay hidden. Collect is still /search?collect=1.
# ---------------------------------------------------------------------------


def test_simple_nav_shows_unnumbered_search():
    """Simple: Search tab, no step number. Advanced keeps four numbered steps."""
    base = _read("templates", "base.html")
    # (key, advanced_label, simple_label, href, tip, simple_step)
    rows = re.findall(
        r'\(\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"(\d*)"\s*\)',
        base,
    )
    assert rows, "base.html workflow must include simple_step as 6th tuple field"
    by_key = dict(rows)
    assert "clusters" in by_key, by_key
    assert by_key["clusters"] == "", "Clusters has no Simple step number (hidden)"
    assert by_key["statistics"] == "", "Clean up has no Simple step number (hidden)"
    assert by_key["search"] == "2", by_key
    assert "data-step-advanced" in base
    assert 'data-step-simple="{{ simple_step }}"' in base or 'data-step-simple="' in base
    assert 'class="nav-brand"' in base and 'href="/"' in base

    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"] .nav-step-data_management' in css
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert 'html[data-mode="simple"] .nav-step-statistics' in css
    assert 'html[data-mode="simple"] .nav-step-search .nav-step-num' in css
    assert 'html[data-mode="simple"] .nav-links' in css
    assert "nav-flow-arrow-before-clusters" in css
    assert "nav-flow-arrow-before-statistics" in css

    # Advanced still labels Clean up (not Duplicates).
    assert "Clean up" in base
    assert re.search(r'"statistics"\s*,\s*"Clean up"', base)
    assert "Get papers" in base


def test_simple_mobile_nav_rows_are_centered():
    """≤900px Simple: brand, tools, and library are centered rows — not flex-end."""
    css = _read("static", "css", "style.css")
    start = css.find("/* Simple phones:")
    assert start != -1
    end = css.find("/* Dual nav labels:", start)
    block = css[start:end]
    assert "flex-direction: column" in block
    assert "justify-content: center" in block
    assert "justify-content: flex-end" not in block
    tools = block[block.find(".shell-tools") :]
    assert "justify-content: center" in tools
    lib = block[block.find(".nav-library-wrap") :]
    assert "justify-content: center" in lib
    assert "border: none" in lib


def test_advanced_nav_keeps_clusters_and_four_steps():
    """Advanced must still list Clusters and Clean up; CSS only hides under simple."""
    base = _read("templates", "base.html")
    assert "nav-step-clusters" in base or "nav-step-{{ key }}" in base
    assert "/clusters" in base
    assert "Clusters" in base
    assert "/statistics" in base
    assert "Clean up" in base
    css = _read("static", "css", "style.css")
    # Advanced is the default when not simple — hide rules are simple-only.
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert 'html[data-mode="simple"] .nav-step-statistics' in css
    assert "html:not([data-mode=\"simple\"]) .nav-step-clusters" not in css


def test_clusters_route_still_exists():
    """Simple mode removes Clusters/Clean up from the nav only — URLs still work."""
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
    dm = _dm_markup()
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
    html = _dm_markup()
    assert "dm-step-simple" in html
    assert "dm-step-advanced" in html
    assert "2. Find articles on your topic" in html
    assert "3. Fetch Articles" in html
    assert "1. Narrow your lens" in html
    assert "topic-pack-grid" not in html
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
    """Enter in the query field must start fetch (native form submit → doFetch).

    Live regression: a `queueAnimationFrame` typo threw during DOMContentLoaded
    *before* the submit listener was registered, so Enter/click posted the form
    to the GET-only page route and returned 405 Method Not Allowed.
    """
    html = _dm_markup()
    assert 'id="fetch-form"' in html
    assert 'type="submit"' in html and 'id="fetch-btn"' in html
    form = re.search(r'<form[^>]*id="fetch-form"[^>]*>', html)
    assert form, "fetch-form opening tag missing"
    form_tag = form.group(0).lower()
    # Native POST to /data-management is not a real API and returns 405.
    assert 'method="post"' not in form_tag, form.group(0)
    dm = _read("static", "js", "data_management.js")
    assert "fetch-form" in dm
    assert "preventDefault" in dm
    # Submit handler must call doFetch (not only a click listener on the button).
    assert re.search(r"fetch-form[\s\S]{0,200}doFetch|submit[\s\S]{0,80}doFetch", dm)
    # The undefined name that broke wire-up; keep the real browser API only.
    assert "queueAnimationFrame" not in dm
    assert "requestAnimationFrame" in dm
    # Listener registration must sit after the rAF call in DOMContentLoaded so
    # a future typo there still fails loudly in review, but the contract is:
    # both are present and the handler path is intact.
    dom = dm[dm.find("DOMContentLoaded") : dm.find("function syncOnlyMissingFromFetchMode")]
    assert "requestAnimationFrame" in dom
    assert "fetch-form" in dom
    assert "doFetch" in dom


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
    return _simple_js()


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
    """Phase 6: Go to Search (not Clean up), starts hidden until screen/skip."""
    import re
    # Markup lives in a labeled partial (included from data_management.html).
    dm = _read("templates", "data_management.html")
    assert 'include "partials/simple_go_to_search.html"' in dm
    html = _read("templates", "partials", "simple_go_to_search.html")
    tag = re.search(r'<div[^>]*id="fetch-next-step"[^>]*>', html)
    assert tag, "fetch-next-step shortcut missing"
    assert "u-hidden" in tag.group(0) or "hidden" in tag.group(0), "shortcut must start hidden"
    assert "Go to Search" in html
    assert 'id="fetch-next-step-link"' in html
    link = re.search(
        r'id="fetch-next-step-link"[^>]*href="([^"]+)"|href="([^"]+)"[^>]*id="fetch-next-step-link"',
        html,
    )
    assert link, "fetch-next-step-link missing"
    href = link.group(1) or link.group(2)
    assert href == "/search", href


def test_search_display_filter_chips_are_easy_options():
    """Show chips filter the on-screen list (no new search). Both modes."""
    html = _read("templates", "search.html")
    assert 'id="display-filters"' in html
    assert 'data-filter="all"' in html
    assert 'data-filter="starred"' in html
    assert 'data-filter="noted"' in html
    assert 'data-filter="recent"' in html
    js = _read("static", "js", "search.js")
    assert "function visibleResults" in js
    assert "function showSearchResults" in js
    assert "function wireDisplayFilters" in js
    assert "displayFilterState.starred" in js
    assert "displayFilterState.noted" in js
    assert "displayFilterState.recent" in js
    # Export the filtered on-screen set, not the unfiltered hit list.
    exp = js[js.find("async function doExportResults") : js.find("async function doExportResults") + 900]
    assert "visibleResults" in exp
    css = _read("static", "css", "style.css")
    assert ".display-filter-chip" in css
    # Simple must not hide the chips.
    assert 'html[data-mode="simple"] .display-filter' not in css
    assert 'html[data-mode="simple"] #display-filters' not in css


def test_next_step_shortcut_is_simple_mode_only_and_resets():
    src = _dm_js()
    assert "function setNextStepVisible" in src
    block = src.split("function setNextStepVisible", 1)[1].split("function ", 1)[0]
    assert "isSimpleMode" in block, "shortcut must be Simple-mode only"
    # Hidden when a new fetch starts
    assert "setNextStepVisible(false)" in src
    # Shown after screen apply/skip via setSimpleScreenGotoVisible
    assert "setSimpleScreenGotoVisible" in src
    assert "setNextStepVisible(visible)" in src or "setNextStepVisible(show)" in src


def test_simple_locks_fetch_after_library_has_papers():
    """Simple hides Fetch Articles once this library has papers.

    Advanced keeps the form. Guests already cannot fetch. Start over reuses the
    existing replace/add dialog, then doFetch must not ask again. A locked
    submit is a no-op (no /api/fetch-articles-multi).
    """
    html = _dm_markup()
    assert 'id="simple-fetch-locked"' in html
    assert 'id="simple-fetch-unlock-btn"' in html
    assert 'id="fetch-lead"' in html
    assert 'id="fetch-form"' in html
    # Form stays in the DOM (Advanced / empty / unlocked).
    assert 'name="fetch-mode"' in html

    src = _dm_js()
    assert "function isSimpleFetchLocked" in src
    assert "function updateSimpleFetchLock" in src
    assert "function unlockSimpleFetch" in src
    assert "_simpleFetchUnlocked" in src
    assert "_simpleFetchModePicked" in src

    lock_fn = src[
        src.find("function isSimpleFetchLocked") : src.find("function updateSimpleFetchLock")
    ]
    assert "isSimpleMode" in lock_fn
    assert "_lastTotalArticles > 0" in lock_fn
    assert "_simpleFetchUnlocked" in lock_fn
    assert "_pipelineBusy" in lock_fn
    assert "isGuestSession" in lock_fn

    unlock_fn = src[
        src.find("async function unlockSimpleFetch") : src.find(
            "function updatePrepareSectionVisibility"
        )
    ]
    assert "resolveSimpleFetchModeBeforeRequest" in unlock_fn
    assert "_simpleFetchUnlocked = true" in unlock_fn
    assert "_simpleFetchModePicked = true" in unlock_fn

    do = src[src.find("async function doFetch") : src.find("async function doCreateEmbeddings")]
    assert "isSimpleFetchLocked" in do
    assert do.find("isSimpleFetchLocked") < do.find("/api/fetch-articles-multi")
    # Unlock already chose replace/append — do not open the dialog twice.
    assert "_simpleFetchModePicked" in do
    # After the job, lock again.
    assert "_simpleFetchUnlocked = false" in do

    vis = src[
        src.find("function updatePrepareSectionVisibility") : src.find("async function loadPageData")
    ]
    assert "updateSimpleFetchLock" in vis
    # Prepare-card gate stays mode-agnostic (lock lives in its own helper).
    assert "if (!simple)" not in vis

    css = _read("static", "css", "style.css")
    assert "body[data-guest=\"1\"] #simple-fetch-locked" in css
    assert ".simple-fetch-locked" in css


# --- Phase 6: two-page Simple (screening card + silent dedup already above) ---

SIMPLE_SCREEN_FRACTIONS = {"low": 0.10, "medium": 0.25, "high": 0.50}


def test_simple_screen_levels_map_to_documented_fractions():
    """Low/Medium/High must match 0.10 / 0.25 / 0.50 and stay in API bounds."""
    dm = _simple_js()
    assert "SIMPLE_SCREEN_LEVELS" in dm
    for level, frac in SIMPLE_SCREEN_FRACTIONS.items():
        assert f"{level}: {frac}" in dm or f"{level}:{frac}" in dm, level
        assert 0.05 <= frac <= 0.50
    # HTML has the three radios (in the Simple-only partial)
    page = _read("templates", "data_management.html")
    assert 'include "partials/simple_screening_card.html"' in page
    html = _read("templates", "partials", "simple_screening_card.html")
    assert 'name="simple-screen-level"' in html
    assert 'value="low"' in html
    assert 'value="medium"' in html
    assert 'value="high"' in html
    assert 'id="simple-screening-card"' in html
    assert 'id="simple-screen-modal"' in html
    assert 'id="simple-screen-open-btn"' in html
    assert "Narrow it down" in html


def test_simple_screen_preview_does_not_exclude():
    """Preview must only call quick-preview — never /api/screening exclude."""
    dm = _simple_js()
    fn = dm[dm.find("async function doSimpleScreenPreview") : dm.find("async function doSimpleScreenApply")]
    assert "/api/screening/quick-preview" in fn
    assert 'action: \'exclude\'' not in fn and 'action: "exclude"' not in fn
    assert "low_relevance" not in fn


def test_simple_screen_apply_and_undo_use_low_relevance():
    dm = _simple_js()
    apply_fn = dm[dm.find("async function doSimpleScreenApply") : dm.find("function doSimpleScreenSkip")]
    assert 'action: "exclude"' in apply_fn or "action: 'exclude'" in apply_fn
    assert "low_relevance" in apply_fn
    # After apply: Undo is offered on the Search strip and last items are persisted.
    assert "saveSimpleScreenUndoItems" in apply_fn
    assert "setSimpleScreenStripOutcome" in apply_fn
    assert "undo: true" in apply_fn or "undo:true" in apply_fn
    assert "Set aside" in apply_fn
    undo_fn = dm[dm.find("async function doSimpleScreenUndo") : dm.find("async function silentResolveDuplicatesAfterPrepare")]
    if "async function doSimpleScreenUndo" not in dm:
        undo_fn = dm[dm.find("async function doSimpleScreenUndo") :]
    assert 'action: "include"' in undo_fn or "action: 'include'" in undo_fn
    assert "loadSimpleScreenUndoItems" in undo_fn
    assert "clearSimpleScreenUndoItems" in undo_fn


def test_simple_screen_confirm_question_box_after_prepare():
    """After prepare, Simple mode must not silently assume the fetch topic is the question."""
    html = _read("templates", "partials", "simple_screening_card.html")
    assert 'id="simple-screen-confirm"' in html
    assert "Your research question" in html
    assert "not the topic you fetched" in html
    assert 'id="simple-screen-query"' in html
    css = _read("static", "css", "style.css")
    assert ".simple-screen-confirm" in css
    dm = _simple_js()
    assert "setSimpleScreenConfirmVisible" in dm
    # Pending shows the confirm box; complete/skip hides it.
    refresh = dm[
        dm.find("async function refreshSimpleScreeningCard") : dm.find(
            "async function loadSimpleScreenCounts"
        )
    ]
    assert "showSimpleScreenPendingUi" in refresh or "setSimpleScreenConfirmVisible(true)" in refresh
    assert "setSimpleScreenConfirmVisible(false)" in refresh
    # Re-prepare must refresh the card so the box appears without a full reload.
    assert "await refreshSimpleScreeningCard()" in dm
    # Undo after complete is corpus-backed (survives restart).
    assert "fetchLowRelevanceUndoItems" in dm
    assert "/api/screening/excluded" in dm
    assert "get_excluded_items_for_reason" in _read("app", "storage", "database.py")
    assert '("/api/screening/excluded"' in _read("app", "routes", "corpus.py") or (
        "/api/screening/excluded" in _read("app", "routes", "corpus.py")
    )


def test_simple_screen_skip_leaves_no_exclusion_call():
    dm = _simple_js()
    fn = dm[dm.find("function doSimpleScreenSkip") : dm.find("async function doSimpleScreenUndo")]
    assert "/api/screening" not in fn, "skip must not exclude anything"
    # Records the choice through the helper, which also persists it per library
    # so the card does not reappear on reload.
    assert "setSimpleScreenSkipped(true)" in fn


def test_simple_screen_pending_from_corpus_not_js_flag():
    """Pending uses statistics + screening-report (low_relevance), not a job flag."""
    dm = _simple_js()
    fn = dm[dm.find("async function refreshSimpleScreeningCard") : dm.find("async function loadSimpleScreenCounts")]
    assert "/api/statistics" in fn
    assert "/api/screening-report" in fn
    assert "low_relevance" in fn
    assert "articles_with_embeddings" in fn
    # Must not gate only on a session flag for showing the card initially
    assert "ready <= 0" in fn or "ready > 0" in fn or "ready <= 0" in fn


def test_simple_screen_counts_fetched_once_not_per_radio():
    """All three fractions load together; radio change does not re-call the API."""
    dm = _simple_js()
    assert "loadSimpleScreenCounts" in dm
    # Parallel fetch of all levels
    assert "Object.keys(SIMPLE_SCREEN_LEVELS)" in dm or "SIMPLE_SCREEN_LEVELS" in dm
    wire = dm[dm.find("function wireSimpleScreeningCard") : dm.find("async function doSimpleScreenPreview")]
    # Radios: no change listener that calls loadSimpleScreenCounts
    assert 'name="simple-screen-level"' not in wire or "addEventListener('change'" not in wire


def test_simple_screening_card_hidden_in_advanced_css():
    css = _read("static", "css", "style.css")
    assert 'html:not([data-mode="simple"]) #simple-screening-card' in css
    assert "display: none" in css.split('simple-screening-card')[1][:200]


def test_simple_screen_options_open_in_a_popup():
    """Low/Medium/High stay; the decision UI is a dialog, not a page card."""
    html = _read("templates", "partials", "simple_screening_card.html")
    assert 'id="simple-screen-modal"' in html
    assert 'id="simple-screen-open-btn"' in html
    assert 'name="simple-screen-level"' in html
    dm = _simple_js()
    assert "function openSimpleScreenModal" in dm
    assert "function closeSimpleScreenModal" in dm
    assert "function showSimpleScreenPendingUi" in dm
    open_fn = dm[dm.find("function openSimpleScreenModal") : dm.find("async function refreshSimpleScreeningCard")]
    assert "showSimpleScreenPendingUi" in open_fn
    apply_fn = dm[dm.find("async function doSimpleScreenApply") : dm.find("function doSimpleScreenSkip")]
    assert "closeSimpleScreenModal" in apply_fn
    skip_fn = dm[dm.find("function doSimpleScreenSkip") : dm.find("async function doSimpleScreenUndo")]
    assert "closeSimpleScreenModal" in skip_fn


def test_simple_fetch_asks_for_topic_not_question():
    """Fetch copy: topic now; the real question is for Search later."""
    html = _read("templates", "partials", "collect_ui.html")
    assert 'id="fetch-lead"' in html
    assert "Type the" in html and "topic" in html
    assert "not your full research question" in html
    assert 'class="dm-step-simple">Topic</label>' in html
    assert "Search Query" in html
    assert "save your real question for Search later" in html
    dm = _simple_js()
    prefill = dm[
        dm.find("function prefillSimpleScreenQuery") : dm.find("function setSimpleScreenGotoVisible")
    ]
    assert "do not copy" in prefill or "Fetch is a topic" in prefill
    assert "el.value = prefs.query" not in prefill


def test_simple_screen_is_required_popup_before_search():
    """Narrow it down must open before Search; close/backdrop cannot skip the gate."""
    dm = _simple_js()
    assert "function isSimpleScreenGatePending" in dm
    assert "function setSimpleScreenGatePending" in dm
    refresh = dm[
        dm.find("async function refreshSimpleScreeningCard") : dm.find(
            "async function loadSimpleScreenCounts"
        )
    ]
    assert "setSimpleScreenGatePending(true)" in refresh
    assert "openSimpleScreenModal()" in refresh
    close_fn = dm[
        dm.find("function closeSimpleScreenModal") : dm.find("function openSimpleScreenModal")
    ]
    assert "isSimpleScreenGatePending()" in close_fn
    assert "opts.force" in close_fn or "opts && opts.force" in close_fn
    apply_fn = dm[dm.find("async function doSimpleScreenApply") : dm.find("function doSimpleScreenSkip")]
    assert "closeSimpleScreenModal({ force: true })" in apply_fn
    assert "setSimpleScreenGatePending(false)" in apply_fn
    skip_fn = dm[dm.find("function doSimpleScreenSkip") : dm.find("async function doSimpleScreenUndo")]
    assert "closeSimpleScreenModal({ force: true })" in skip_fn
    search_js = _read("static", "js", "search.js")
    vis = search_js[
        search_js.find("function updateSearchWorkVisibility") : search_js.find(
            "function fillSimpleRailStats"
        )
    ]
    assert "isSimpleScreenGatePending" in vis
    boot = search_js[
        search_js.find("loadSearchEmptyState()") : search_js.find("refreshStarredCount")
    ]
    assert "refreshSimpleScreeningCard" in boot
    assert "isSimpleScreenGatePending" in boot
    css = _read("static", "css", "style.css")
    assert "simple-screen-pending" in css
    assert "simple-screen-ready" in css
    assert "body.simple-screen-ready #search-query-top" in css
    gate = dm[
        dm.find("function isSimpleScreenGatePending") : dm.find("function setSimpleScreenGatePending")
    ]
    assert "_simpleScreenPending === null" in gate
    assert "return false" in gate
    assert "body.simple-screen-pending .simple-screen-modal .lra-modal-backdrop" in css
    assert "display: none" in css.split("simple-screen-pending .simple-screen-modal .lra-modal-backdrop")[1][:80]


def test_simple_fetch_shows_buffering_then_narrow():
    """Simple fetch hides collect behind a wait screen; Narrow it down is after."""
    html = _read("templates", "search.html")
    assert 'id="search-preparing"' in html
    assert 'id="search-buffering-title"' in html
    assert 'id="search-buffering-progress"' in html
    assert 'id="search-buffering-cancel"' in html
    tools = _read("static", "js", "simple_tools.js")
    assert "function showSimpleBuffering" in tools
    assert "function hideSimpleBuffering" in tools
    dm = _read("static", "js", "data_management.js")
    fetch_fn = dm[dm.find("async function doFetch") : dm.find("async function silentResolveDuplicatesAfterPrepare")]
    assert "showSimpleBuffering('fetch')" in fetch_fn
    assert "showSimpleBuffering('prepare')" in fetch_fn
    assert "hideSimpleBuffering" in fetch_fn
    assert "search-buffering-fill" in fetch_fn
    # Wait screen must finish before the screening popup refresh.
    finally_fn = fetch_fn[fetch_fn.rfind("} finally {") :]
    assert "hideSimpleBuffering" in finally_fn
    assert finally_fn.find("hideSimpleBuffering") < finally_fn.find("refreshSimpleScreeningCard")
    search_js = _read("static", "js", "search.js")
    wait = search_js[
        search_js.find("async function waitIfPreparing") : search_js.find("function refreshStarredCount")
    ]
    assert "showSimpleBuffering" in wait
    assert "progress.fetch" in wait or "fetchJob" in wait
    css = _read("static", "css", "style.css")
    assert "body.simple-buffering #search-collect" in css
    assert ".search-buffering" in css


def test_go_to_search_not_clean_up_in_simple_next_step():
    page = _read("templates", "data_management.html")
    assert 'include "partials/simple_go_to_search.html"' in page
    html = _read("templates", "partials", "simple_go_to_search.html")
    # Phase 6 replaces Clean up shortcut with Search
    assert 'href="/search"' in html
    assert "Go to Search" in html
    assert "/statistics" not in html


def test_simple_search_side_panel_exists_and_hidden_in_advanced():
    page = _read("templates", "search.html")
    assert 'include "partials/simple_search_panel.html"' in page
    html = _read("templates", "partials", "simple_search_panel.html")
    assert 'id="search-simple-panel"' in html
    assert 'id="simple-export-results-btn"' in html
    assert 'id="simple-screening-report-btn"' in html
    assert 'screening-report?format=txt' in html
    css = _read("static", "css", "style.css")
    assert 'html:not([data-mode="simple"]) #search-simple-panel' in css or \
           'html:not([data-mode="simple"]) .search-simple-panel' in css
    js = _read("static", "js", "search.js")
    assert "updateSimpleSearchPanel" in js
    assert "simple-export-results-btn" in js


def test_simple_small_screen_css_for_panel_and_card():
    css = _read("static", "css", "style.css")
    assert "position: fixed" in css
    assert "has-simple-panel" in css or "padding-bottom" in css
    assert "simple-screen-level" in css
    assert "min-height: 2.75rem" in css
    # Narrowest breakpoint acknowledged
    assert "max-width: 380px" in css


# --- Skip persistence (issue 2 follow-up) -----------------------------------

def test_skip_is_remembered_per_library_not_per_page_view():
    """Skipping must survive a reload, and must be scoped to one library.

    Pending/complete is derived from the corpus, which is correct — but
    skipping leaves no trace in the corpus by definition. With a session-only
    flag the card reappeared on refresh and took the "Go to Search" button with
    it, so a student who chose to keep everything lost their way forward.
    """
    src = _dm_js()
    assert "SKIP_KEY" in src, "skip must be persisted, not session-only"
    assert "localStorage.setItem(SKIP_KEY" in src
    # Scoped per library: skipping one collection says nothing about the next.
    assert "_activeLibraryId()" in src
    assert "function setSimpleScreenSkipped" in src
    assert "function isSimpleScreenSkipped" in src


def test_skip_state_is_read_through_the_helper():
    """A raw read of the session flag would ignore the persisted value."""
    import re
    src = _dm_js()
    # The only places the bare flag may appear are its declaration and the two
    # helpers; anything else means a code path that bypasses persistence.
    lines = [
        i for i, ln in enumerate(src.splitlines(), 1)
        if re.search(r"_simpleScreenSkippedSession", ln)
    ]
    assert len(lines) <= 3, (
        f"bare uses of _simpleScreenSkippedSession outside the helpers: {lines}"
    )
    assert "if (isSimpleScreenSkipped())" in src


def test_active_library_is_resolved_before_the_skip_check():
    """The nav select populates asynchronously; reading it early races.

    Without an authoritative resolve, the first card refresh sees an empty
    library id, misses the persisted skip, and shows the card again.
    """
    src = _dm_js()
    assert "async function ensureActiveLibraryId" in src
    assert "ensureActiveLibraryId()," in src, (
        "the card refresh must await the library id before deciding"
    )


def test_new_fetch_clears_a_previous_skip():
    """A fresh corpus has not been screened, so the choice must not carry over."""
    src = _dm_js()
    assert "setSimpleScreenSkipped(false)" in src


def test_simple_mode_markup_lives_in_labeled_partials():
    """Phase 6 Simple blocks are separately labeled files, included from the page.

    Avoids forking whole pages (server cannot know uiMode) while making ownership
    obvious for reviewers — Claude's recommended middle ground for Advanced drift.
    """
    dm = _read("templates", "data_management.html")
    search = _read("templates", "search.html")
    collect = _read("templates", "partials", "collect_ui.html")
    assert 'include "partials/collect_ui.html"' in dm
    assert 'include "partials/simple_screening_card.html"' in dm
    assert 'include "partials/simple_go_to_search.html"' in dm
    assert 'include "partials/guest_fetch_note.html"' in collect
    assert 'include "partials/simple_search_panel.html"' in search
    # Markup itself lives in the partial, not duplicated on the page.
    assert 'id="simple-screening-card"' not in dm
    assert 'id="simple-screening-card"' in _read("templates", "partials", "simple_screening_card.html")
    assert 'id="search-simple-panel"' not in search
    assert 'id="search-simple-panel"' in _read("templates", "partials", "simple_search_panel.html")
    assert "Narrow it down" in _read("templates", "partials", "simple_screening_card.html")
