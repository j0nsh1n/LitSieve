"""Phase 13, slice 2: Simple students pick an exclusion reason.

Clusters has a reason select. Simple asks with chips, in the Set aside
popup and on the Not relevant line. Narrow it down, duplicate copies, and
theme groups are not choices: their own Undo paths key on those reasons.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_screening import screening_app  # noqa: F401
from test_set_aside_list import (
    _exclude,
    _read,
    _register_client,
    _seed_user_library,
)

REPO = Path(__file__).resolve().parents[1]


def _between(text: str, start: str, end: str) -> str:
    a = text.find(start)
    assert a >= 0, f"missing {start!r}"
    b = text.find(end, a + len(start))
    assert b >= 0, f"missing {end!r} after {start!r}"
    return text[a:b]


def _chip_block() -> str:
    card = _read("templates", "partials", "simple_screening_card.html")
    return _between(card, 'id="simple-set-aside-reasons"', 'id="simple-set-aside-groups"')


def test_reason_chips_match_the_reason_table_and_skip_system_reasons():
    from app.content.screening_reasons import (
        REASON_CHIPS,
        SYSTEM_REASONS,
        USER_SELECTABLE_REASONS,
    )

    found = re.findall(
        r'data-reason="([^"]+)"[^>]*>([^<]+)',
        _chip_block(),
    )
    assert found == list(REASON_CHIPS)
    codes = [code for code, _label in found]
    assert "manual" not in codes
    assert set(codes).isdisjoint(SYSTEM_REASONS)
    assert set(codes) <= set(USER_SELECTABLE_REASONS)
    # The popup starts closed. Why? opens it.
    assert "hidden" in _chip_block().split(">", 1)[0]


def test_why_button_skips_system_groups_and_reexcludes_with_the_chip():
    js = _read("static", "js", "simple_tools.js")
    gate = _between(js, "function setAsideCanChooseReason", "\nfunction showSetAsideReasons")
    assert "'low_relevance'" in gate
    assert "'duplicate'" in gate
    assert "'cluster'" in gate

    render = _between(js, "function renderSimpleSetAsideGroups", "\nfunction onSetAsideListClick")
    assert "setAsideCanChooseReason(it.reason)" in render
    assert "data-set-aside-why" in render

    apply = _between(js, "async function applySetAsideReason", "\nasync function undoSetAsideReason")
    assert "setAsideCanChooseReason(reason)" in apply
    assert "action: 'exclude'" in apply
    assert "reason: reason" in apply
    assert "low_relevance" not in apply

    wiring = _between(js, "function wireSimpleToolsStrip", "\n}\n")
    assert "'simple-set-aside-reasons')" in wiring
    assert "'simple-set-aside-reason-undo')" in wiring


def test_not_relevant_why_is_simple_only_and_the_line_stays_up():
    js = _read("static", "js", "search.js")
    handler = _between(js, "notRelBtn.addEventListener", "function fillWhyReasonChips")
    assert "why: simpleMode" in handler
    assert "showSearchResults()" not in handler
    assert "syncResultCountAfterScreen()" in handler

    undo = _between(js, "function replaceCardWithUndo", "function showResultSkeletons")
    assert "why-not-relevant" in undo
    assert "opts && opts.why" in undo
    assert "showSearchResults()" not in undo
    assert "action: 'include'" in undo

    fill = _between(js, "function fillWhyReasonChips", "function syncResultCountAfterScreen")
    assert "low_relevance" in fill and "duplicate" in fill and "cluster" in fill
    assert "simple-set-aside-reasons" in fill


def test_changing_reason_moves_the_screening_report_count(screening_app):
    c = _register_client(screening_app, "reasons1")
    _seed_user_library(screening_app, c, n=3, with_clusters=False)
    _exclude(c, "1", "off_topic")
    _exclude(c, "2", "low_relevance")

    _exclude(c, "1", "wrong_population")

    report = c.get("/api/screening-report?format=json").json()
    excluded = report["excluded"]
    assert int(excluded.get("off_topic") or 0) == 0
    assert int(excluded["wrong_population"]) == 1
    assert int(excluded["low_relevance"]) == 1

    listed = c.get("/api/screening/excluded").json()
    by_id = {item["article_id"]: item["reason"] for item in listed["items"]}
    assert by_id["1"] == "wrong_population"
    assert by_id["2"] == "low_relevance"

    # Undo for Narrow it down still sees only its own group.
    narrow = c.get("/api/screening/excluded?reason=low_relevance").json()
    assert [item["article_id"] for item in narrow["items"]] == ["2"]
