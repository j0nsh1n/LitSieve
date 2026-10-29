"""One-flow Search UI and workflow guardrails.

These tests keep the single Search workflow's collection, screening, ranking,
result interaction, and export behavior covered without asserting the retired
Simple/Advanced preference or its former page split.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import route_paths

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


def _simple_js() -> str:
    """Search tools shared by the collection and screening workflow."""
    return _read("static", "js", "simple_tools.js") + "\n" + _read(
        "static", "js", "collect.js"
    )


def _dm_markup() -> str:
    """Search page plus its collection partial."""
    return _read("templates", "search.html") + "\n" + _read(
        "templates", "partials", "collect_ui.html"
    )


# ---------------------------------------------------------------------------
# Pre-paint theme initialization and the one-flow notice
# ---------------------------------------------------------------------------


def test_theme_init_sets_theme_before_paint_without_mode_state():
    """theme-init stays blocking for theme, with no retired layout preference."""
    base = _read("templates", "base.html")
    tag = re.search(r"<script[^>]*theme-init\.js[^>]*>", base)
    assert tag, "base.html no longer loads theme-init.js"
    assert "defer" not in tag.group(0), tag.group(0)
    assert "async" not in tag.group(0), tag.group(0)
    assert "type=\"module\"" not in tag.group(0).lower(), tag.group(0)
    head = base.split("</head>")[0]
    assert "theme-init.js" in head, "theme-init.js must be in <head>"

    init = _read("static", "js", "theme-init.js")
    assert "localStorage.getItem('theme')" in init
    assert "uiMode" not in init
    assert "data-mode" not in init
    assert "type=\"module\"" not in init
    assert "no defer" in init.lower() or "Must stay a plain blocking" in init


def test_one_flow_has_no_layout_toggle_or_mode_writes():
    """The app has one Search flow; legacy mode is only read by the notice."""
    base = _read("templates", "base.html")
    assert 'id="mode-toggle"' not in base
    assert "reading-toggle" not in base
    common = _read("static", "js", "common.js")
    assert "setUiMode" not in common
    assert "isSimpleMode" not in common
    assert "localStorage.setItem('uiMode'" not in common
    assert "localStorage.setItem('uiMode'" not in _read("static", "js", "theme-init.js")
    # Existing Simple users are recognized only to avoid a confusing notice.
    notice = common[common.find("function showOneFlowNotice") :]
    assert "localStorage.getItem('uiMode')" in notice
    assert "localStorage.setItem(marker, '1')" in notice
    assert "localStorage.setItem('uiMode'" not in notice


# ---------------------------------------------------------------------------
# Navigation is a single Search flow.
# ---------------------------------------------------------------------------


def test_nav_exposes_one_search_workflow():
    """The app nav points to Search; collection tools are part of that page."""
    base = _read("templates", "base.html")
    nav = base[base.find('<div class="nav-links"') : base.find("</div>", base.find('<div class="nav-links"'))]
    assert 'href="/search"' in nav
    assert ">Search</a>" in nav
    assert "/data-management" not in nav
    assert "/clusters" not in nav
    assert "/statistics" not in nav
    search = _read("templates", "search.html")
    assert 'id="search-collect"' in search
    assert 'include "partials/collect_ui.html"' in search


def test_mobile_nav_uses_collapsed_drawer():
    """On narrow screens, the Search nav stays reachable in the menu drawer."""
    css = _read("static", "css", "style.css")
    start = css.find("/* Tablet and below: one row")
    assert start != -1
    nav = css[start : css.find("@media (max-width: 640px)", start)]
    assert ".nav-menu-toggle" in nav
    assert ".nav-drawer" in nav
    assert "display: none" in nav
    assert ".navbar.nav-open .nav-drawer" in nav


# ---------------------------------------------------------------------------
# Collection controls and source selection
# ---------------------------------------------------------------------------


def test_search_keeps_fetch_options_and_search_methods_available():
    """Collection options and ranking methods remain wired in the Search flow."""
    dm = _dm_markup()
    assert 'id="source-option-grid"' in dm
    assert 'id="fetch-email"' in dm
    assert 'id="search-collect"' in dm

    search = _read("templates", "search.html")
    assert 'value="seed"' in search
    assert "lexical-boost" in search
    panel = _read("templates", "partials", "simple_search_panel.html")
    assert 'id="simple-export-results-btn"' in panel


def test_fetch_submits_selected_sources_without_visibility_filter():
    """Selected sources are gathered from controls; layout visibility is irrelevant."""
    dm_js = _read("static", "js", "collect.js")
    assert "source-option-grid input[type=\"checkbox\"]:checked" in dm_js or (
        "source-option-grid input[type='checkbox']:checked" in dm_js
    )
    assert "offsetParent" not in dm_js
    assert ":visible" not in dm_js
    assert "updateRecommendedSources" in dm_js
    assert "checkbox.checked = recommended.has(sourceId)" in dm_js


def test_collect_has_guided_question_copy_and_collapsed_optional_options():
    """The one collection flow keeps the student-facing prompts and optional controls."""
    html = _dm_markup()
    assert "dm-step-simple" in html
    assert "Which areas does your topic belong to?" in html
    assert "What topic do you want papers about?" in html
    assert "topic-pack-grid" not in html
    assert 'details class="advanced-details" hidden' in html
    assert "Contact email" in html


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
    # Native POST is not a real API and would fail instead of invoking doFetch.
    assert 'method="post"' not in form_tag, form.group(0)
    dm = _read("static", "js", "collect.js")
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


def test_fetch_auto_chains_to_prepare_without_a_second_click():
    """After a successful fetch, preparation starts without another user action."""
    dm = _read("static", "js", "collect.js")
    assert "fromAutoChain" in dm
    assert "Getting your papers ready" in dm
    assert "_pipelineBusy" in dm
    assert "sawActive" in dm
    chain_block = dm[dm.find("fetchedOk") : dm.find("async function doCreateEmbeddings")]
    assert "fromAutoChain" in chain_block
    assert "total_fetched" in dm
    assert "/api/create-embeddings" in dm
    assert "waitForJob" in dm
    # Progress for auto-chain uses the fetch bar so Simple always sees it.
    assert "fetch-progress-fill" in dm
    assert "fetch-progress-wrap" in dm


def test_silent_dedup_after_auto_prepare_is_best_effort():
    """The one-flow fetch chain tries duplicate cleanup without failing prepare."""
    dm = _read("static", "js", "collect.js")
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
    assert "silentResolveDuplicatesAfterPrepare()" in dm


def test_no_auto_cluster_on_fetch():
    """Clustering must never start from the fetch completion path."""
    dm = _read("static", "js", "collect.js")
    # create-clusters must not appear in fetch success handling.
    fetch_fn = dm[dm.find("async function doFetch") : dm.find("async function doCreateEmbeddings")]
    assert "/api/create-clusters" not in fetch_fn
    assert "create-clusters" not in fetch_fn


# ---------------------------------------------------------------------------
# Screening in the Search flow
# ---------------------------------------------------------------------------


def test_search_screening_popup_and_apply_undo_ui_present():
    """Screening preview/apply/undo is reachable in the one Search flow."""
    html = _read("templates", "partials", "simple_screening_card.html")
    assert "Quick screen" in html or "Narrow it down" in html
    assert 'id="simple-screen-modal"' in html
    assert "Show me what would go" in html
    js = _simple_js()
    assert "/api/screening/quick-preview" in js
    assert "low_relevance" in js
    assert "doSimpleScreenApply" in js
    assert "doSimpleScreenPreview" in js
    assert "doSimpleScreenUndo" in js
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
        assert result["staying"]
        assert len(result["staying"]) == result["total_ranked"] - result["proposed_count"]
        stay_ids = {c["article_id"] for c in result["staying"]}
        assert ids.isdisjoint(stay_ids)
        row = result["candidates"][0]
        assert "abstract" in row
        assert "authors" in row
        assert "similarity_score" in row
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
# Search: one-flow heading + work gate + per-result screening
# ---------------------------------------------------------------------------


def test_search_heading_and_work_gate():
    """Search uses one clear heading and waits until papers are ready."""
    html = _read("templates", "search.html")
    assert "Search your collection" in html
    assert "search-title-advanced" not in html
    assert "search-sub-advanced" not in html
    assert "search-work" in html
    assert "search-kicker-simple" in html
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


def test_search_options_include_seed_and_ranking_controls():
    """Search keeps the optional seed and ranking methods available."""
    html = _read("templates", "search.html")
    assert 'value="seed"' in html
    assert "Seed paper" in html
    assert "lexical-boost" in html
    panel = _read("templates", "partials", "simple_search_panel.html")
    assert "Export papers" in panel
    assert "promptSimpleExportScope" in _read("static", "js", "search.js")
    assert "Starting from this paper" in html


def test_more_like_this_paper_reranks_without_fetch():
    """Result cards can rank the current library from a selected paper."""
    html = _read("templates", "search.html")
    js = _read("static", "js", "search.js")
    assert "More like this" in js
    more = js[js.index("async function doMoreLikeThisPaper") : js.index("function clientSort")]
    assert "more-like-this-btn" in js
    assert "/api/search/seed" in more
    assert "include_seed: true" in more
    assert "/api/fetch" not in more
    assert "/api/multi-fetch" not in more
    assert "load-sample-corpus" not in more


# ---------------------------------------------------------------------------
# User-facing copy and optional controls
# ---------------------------------------------------------------------------


def test_search_copy_and_controls_have_no_duplicate_mode_variants():
    html = _read("templates", "search.html")
    assert "search-help-advanced" not in html
    assert "search-title-advanced" not in html
    assert html.count("Search your collection") == 1
    assert 'id="search-workbench"' in html
    assert 'id="query-text"' in html
    assert 'id="input-method-toggle"' in html


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


def test_search_display_filter_chips_are_easy_options():
    """Display chips filter the on-screen list without running another search."""
    html = _read("templates", "search.html")
    assert 'id="display-filters"' in html
    assert 'data-filter="all"' in html
    assert 'id="simple-starred-chip"' in html
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
    assert 'html[data-mode="simple"]' not in css


def test_fetch_requires_start_over_or_add_when_library_has_papers():
    """Fetching into a populated library requires an explicit mode selection."""
    html = _dm_markup()
    assert 'id="simple-fetch-locked"' in html
    assert 'id="simple-fetch-unlock-btn"' in html
    assert 'id="fetch-lead"' in html
    assert 'id="fetch-form"' in html
    # The form is available after the replace/add choice unlocks it.
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
    # The collection guard has no layout-mode branch.

    css = _read("static", "css", "style.css")
    assert "body[data-guest=\"1\"] #simple-fetch-locked" in css
    assert ".simple-fetch-locked" in css


# --- Search screening workflow ---

SIMPLE_SCREEN_FRACTIONS = {"low": 0.10, "medium": 0.25, "high": 0.50}


def test_simple_screen_levels_map_to_documented_fractions():
    """Low/Medium/High must match 0.10 / 0.25 / 0.50 and stay in API bounds."""
    dm = _simple_js()
    assert "SIMPLE_SCREEN_LEVELS" in dm
    for level, frac in SIMPLE_SCREEN_FRACTIONS.items():
        assert f"{level}: {frac}" in dm or f"{level}:{frac}" in dm, level
        assert 0.05 <= frac <= 0.50
    # The three screening levels are part of the Search workflow.
    page = _read("templates", "search.html")
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
    assert "openSimpleScreenTriage()" in fn
    assert "innerHTML" not in fn
    html = _read("templates", "partials", "simple_screening_card.html")
    assert 'id="screen-triage-go-rows"' in html
    assert 'id="screen-triage-stay-rows"' in html
    assert 'id="screen-triage-detail-body"' in html
    css = _read("static", "css", "style.css")
    assert ".screen-triage-workbench" in css
    assert "grid-template-columns: minmax(16rem, 38%) minmax(0, 1fr)" in css
    assert "_screenTriageMatches()" in dm
    assert "moveScreenTriagePaper" in dm


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
    assert "await refreshSimpleScreeningCard()" in apply_fn
    undo_fn = dm[dm.find("async function doSimpleScreenUndo") : dm.find("async function silentResolveDuplicatesAfterPrepare")]
    if "async function doSimpleScreenUndo" not in dm:
        undo_fn = dm[dm.find("async function doSimpleScreenUndo") :]
    assert 'action: "include"' in undo_fn or "action: 'include'" in undo_fn
    assert "loadSimpleScreenUndoItems" in undo_fn
    assert "clearSimpleScreenUndoItems" in undo_fn


def test_narrow_it_down_type_copy_and_optional_checkbox():
    html = _read("templates", "partials", "simple_screening_card.html")
    assert "data-simple-screen-kept-no-abstract" in html
    assert html.count('<input type="checkbox" data-simple-screen-also-types>') == 2
    assert "data-simple-screen-also-types checked" not in html
    js = _simple_js()
    assert "books and chapters kept: no abstract to judge" in js
    assert "Also set aside ${optN} book reviews and trial registrations" in js
    assert "_mergeSimpleScreenTypeAside" in js
    assert "_simpleScreenApplyItems" in js
    assert "_syncOptionalTypeAsidePlacement" in js
    apply_fn = js[js.find("async function doSimpleScreenApply") : js.find("function doSimpleScreenSkip")]
    assert "_simpleScreenApplyItems(data)" in apply_fn
    merge = js[js.find("function _mergeSimpleScreenTypeAside") : js.find("function _simpleScreenApplyItems")]
    assert "_simpleScreenAlsoTypesOn()" in merge
    assert "_simpleTriageKeptKeys.has(key)" in merge
    page = _read("templates", "search.html")
    assert 'src="/static/js/simple_tools.js?v=20261029c"' in page


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
    assert "def get_excluded_items(" in _read("app", "storage", "database.py")
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
    radio = wire[wire.find('name="simple-screen-level"'):wire.find("wireSimpleScreenAlsoTypes")]
    assert "addEventListener('change'" in radio
    assert "loadSimpleScreenCounts" not in radio
    assert "applySimpleScreenCountLabels" in radio


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
    assert "A subject, not your full research question" in html
    assert 'class="dm-step-simple">Topic</label>' in html
    assert "Save the question for" in html and "Search." in html
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
    assert "Sieving your papers" in html
    assert 'id="search-buffering-sources"' not in html
    assert "Scooping up your first batch" in html
    tools = _read("static", "js", "simple_tools.js")
    assert "function showSimpleBuffering" in tools
    assert "function hideSimpleBuffering" in tools
    assert "function holdSimpleWait" in tools
    assert "function finishSimpleWaitThenSearch" in tools
    assert "Scooping up your first batch" in tools
    assert "Almost got it" in tools
    dm = _read("static", "js", "collect.js")
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


def test_search_side_panel_and_export_actions_are_available():
    page = _read("templates", "search.html")
    assert 'include "partials/simple_search_panel.html"' in page
    html = _read("templates", "partials", "simple_search_panel.html")
    assert 'id="search-simple-panel"' in html
    assert 'id="simple-export-results-btn"' in html
    assert 'id="simple-screening-report-btn"' in html
    assert 'screening-report?format=txt' in html
    assert 'id="funnel-split-bar"' in html
    assert 'id="rail-stat-removed"' in html
    assert "funnel-track--collected" in html
    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"]' not in css
    assert "var(--funnel-kept-pct)" in css
    assert ".funnel-track--split" in css
    js = _read("static", "js", "search.js")
    assert "updateSimpleSearchPanel" in js
    assert "syncSimpleRailAnchor" in js
    assert "simple-export-results-btn" in js
    fill = js[js.find("function fillSimpleRailStats") : js.find("async function loadSearchEmptyState")]
    assert "setProperty('--funnel-kept-pct'" in fill
    assert "setProperty('--funnel-removed-pct'" in fill
    assert "rail-stat-removed" in fill


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


def test_search_workflow_markup_uses_shared_partials():
    """Search composes collection and screening from their shared partials."""
    search = _read("templates", "search.html")
    collect = _read("templates", "partials", "collect_ui.html")
    assert 'include "partials/collect_ui.html"' in search
    assert 'include "partials/simple_screening_card.html"' in search
    assert 'include "partials/guest_fetch_note.html"' in collect
    assert 'include "partials/simple_search_panel.html"' in search
    assert 'id="simple-screening-card"' in _read("templates", "partials", "simple_screening_card.html")
    assert 'id="search-simple-panel"' in _read("templates", "partials", "simple_search_panel.html")
    assert "Narrow it down" in _read("templates", "partials", "simple_screening_card.html")


# ---------------------------------------------------------------------------
# Results open in place (Phase 14): compact rows, one open at a time
# ---------------------------------------------------------------------------


def test_search_results_open_in_place_one_at_a_time():
    """Each result uses an accessible toggle, closing other rows as it opens."""
    js = _read("static", "js", "search.js")
    build = js[js.index("function buildResultCard") : js.index("function renderResults")]
    assert build.count('class="result-toggle"') == 1
    assert 'class="result-toggle"' in build
    assert 'aria-expanded="false"' in build
    assert 'aria-controls="result-body-${idx}"' in build
    assert 'id="result-body-${idx}"' in build
    opener = js[js.index("function setResultRowOpen") : js.index("function buildResultCard")]
    assert "setAttribute('aria-expanded', open ? 'true' : 'false')" in opener
    assert "#results-list .result-row.is-open" in opener
    render = js[js.index("function renderResults") : js.index("function renderResults") + 1200]
    assert "openResultRow(container.querySelector('.result-row'), false)" in render
    css = _read("static", "css", "style.css")
    assert '.result-row:not(.is-open) .result-row-body' in css
    assert '.result-row.is-open .result-row-body' in css
    assert 'html[data-mode="simple"]' not in css


def test_simple_collect_is_one_guided_column():
    """Topic first; the areas sit under it and decide the databases.

    With the optional Laya model the areas are picked from the topic and shown
    as one line with Change; the grid stays open when nothing is picked. The
    topic box is never hidden, so Start over keeps its unlock button reachable.
    """
    js = _read("static", "js", "collect.js")
    grid = js[js.index("function renderTopicGrid") : js.index("function renderTopicPacks")]
    assert "topic.icon_svg" in grid
    assert 'stroke="currentColor"' in grid
    assert "renderAreaState();" in grid
    state = js[js.index("function renderAreaState") : js.index("function setAreas")]
    assert "const collapsed = !areasExpanded && names.length > 0;" in state
    assert "picker.hidden = collapsed;" in state
    toggle = js[js.index("function toggleTopic") : js.index("function recommendModel")]
    assert "areasSource = 'manual';" in toggle  # a hand choice wins over Laya
    pick = js[js.index("async function pickAreasFromTopic") : js.index("function sendAreaFeedback")]
    assert "areasSource === 'manual'" in pick and "setAreas(ids, 'laya');" in pick
    assert "areasExpanded = false;" in pick
    restore = js[js.index("function restoreFetchPrefs") : js.index("function restoreFetchPrefs") + 2400]
    assert "areasSource = 'saved'; areasExpanded = false;" in restore
    assert "await pickAreasFromTopic(query);" in js  # Find before the debounce still gets areas
    assert "openAreaPicker();" in js
    for gone in ("syncCollectStep", "revealCollectStep", "collect-topics-next"):
        assert gone not in js
    html = _read("templates", "partials", "collect_ui.html")
    assert html.index('id="fetch-query"') < html.index('id="collect-areas-summary"') < html.index('id="topic-grid"') < html.index('id="fetch-btn"')
    assert 'id="collect-areas-change"' in html
    assert "Next: name your topic" not in html
    css = _read("static", "css", "style.css")
    assert ":not(.has-topic)" not in css
    assert ".topic-grid {\n    display: flex;" in css
    assert ".topic-icon svg {" in css
    from app.content.source_catalog import list_topics_for_api
    topics = list_topics_for_api()
    assert topics
    for topic in topics:
        assert topic["icon_svg"].startswith("<"), topic["id"]
        assert "<script" not in topic["icon_svg"]
