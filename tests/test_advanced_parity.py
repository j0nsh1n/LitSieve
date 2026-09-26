"""Phase 13, slice 0: one row per Advanced-only feature and its Simple home.

Every row names the Simple control (an element id or a JS function) that
replaces an Advanced feature, and checks that it exists. Rows for slices not
built yet are ``xfail(strict=True)``: they fail today, and the moment a slice
adds the control the row starts passing and pytest fails until the ``xfail``
is removed. Removing Advanced (slice 10) may not merge while any row is
still expected to fail.

A later slice may rename a control, but must then change the row to the new
name in the same PR. A row must never be deleted: if the feature is dropped,
Jonathan records the drop in roadmap.md and the row asserts the drop note.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def _card() -> str:
    return _read("templates", "partials", "simple_screening_card.html")


def _search_templates() -> str:
    return (
        _read("templates", "search.html")
        + _read("templates", "partials", "collect_ui.html")
        + _read("templates", "partials", "simple_search_panel.html")
        + _card()
    )


def _search_js() -> str:
    return (
        _read("static", "js", "search.js")
        + _read("static", "js", "simple_tools.js")
        + _read("static", "js", "data_management.js")
    )


later = pytest.mark.xfail(strict=True, reason="Phase 13 slice not built yet")


# Slice 1 -------------------------------------------------------------------

def test_restore_any_set_aside_paper_from_simple():
    """Clusters page restore → Set aside popup, every reason, restore one or a group."""
    card = _card()
    assert 'id="simple-set-aside-modal"' in card
    js = _read("static", "js", "simple_tools.js")
    assert "data-set-aside-restore-group" in js
    assert "apiCall('/api/screening/excluded')" in js


# Slice 2 -------------------------------------------------------------------

@later
def test_choose_an_exclusion_reason():
    """Clusters reason select → reason chips in the Set aside popup."""
    assert 'id="simple-set-aside-reasons"' in _card()


# Slice 3 -------------------------------------------------------------------

@later
def test_sort_chip():
    assert 'id="simple-sort-chip"' in _search_templates()


@later
def test_sources_chip():
    assert 'id="simple-sources-chip"' in _search_templates()


@later
def test_more_like_my_starred_from_starred_chip():
    assert 'id="simple-starred-chip"' in _search_templates()


@later
def test_ranking_options_in_search_options_popup():
    """Exact-word and PICO boosts join the count and year fields."""
    fn = _search_js()
    start = fn.find("async function promptSimpleSearchScope")
    assert start >= 0
    body = fn[start:fn.find("\n}\n", start)]
    assert "lexical_boost" in body and "pico_boost" in body


# Slice 4 -------------------------------------------------------------------

@later
def test_search_by_switch_question_pico_paper():
    assert 'id="simple-search-by"' in _search_templates()


# Slice 5 -------------------------------------------------------------------

@later
def test_export_whole_library_from_save_your_work():
    assert 'id="simple-export-scope"' in _search_templates()


# Slice 6 -------------------------------------------------------------------

@later
def test_choose_databases_in_fetch_dialog():
    assert 'id="simple-fetch-databases"' in _search_templates()


@later
def test_contact_email_shown_only_for_pubmed_and_europepmc():
    js = _search_js()
    assert "simple-fetch-databases" in js and "fetch-email" in js
    assert "europepmc" in js.lower() and "pubmed" in js.lower()
    assert 'id="simple-fetch-databases"' in _search_templates()


# Slice 7 -------------------------------------------------------------------

@later
def test_what_we_fetched_popup_has_sources_years_and_coverage():
    assert 'id="simple-what-we-fetched"' in _search_templates()
    assert "/api/coverage" in _read("static", "js", "simple_tools.js")


@later
def test_check_for_duplicates_from_set_aside_popup():
    assert "data-set-aside-check-duplicates" in _card()
    js = _read("static", "js", "simple_tools.js")
    assert "Strict" in js and "Loose" in js


# Slice 8 -------------------------------------------------------------------

@later
def test_reprepare_popup_has_model_disclosure():
    assert 'id="simple-reprepare-model"' in _search_templates() or (
        "simple-reprepare-model" in _search_js()
    )


# Slice 9 -------------------------------------------------------------------

@later
def test_group_by_theme_popup():
    assert 'id="simple-group-by-theme"' in _search_templates()
    assert "/api/create-clusters" in _read("static", "js", "simple_tools.js")


# Already in Simple; stays where it is ----------------------------------------

def test_count_and_year_range_stay_in_search_options():
    js = _read("static", "js", "search.js")
    start = js.find("async function promptSimpleSearchScope")
    body = js[start:js.find("\n}\n", start)]
    assert "id: 'count'" in body
    assert "id: 'year_min'" in body and "id: 'year_max'" in body
