"""Search page side of audit 19.1-19.3 and 19.16: sort, rail, duplicates, undated group."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _slice(source, start, end):
    i = source.index(start)
    return source[i:source.index(end, i)]


def _client_sort(results, sort_by):
    search = _read("static", "js", "search.js")
    code = _slice(search, "function clientSort(", "function renderPicoBlock(")
    script = r"""
const vm = require('vm');
const [code, results, sortBy] = JSON.parse(process.argv[1]);
const sandbox = {};
vm.runInNewContext(code + ';this.out = clientSort(' + JSON.stringify(results) + ', ' + JSON.stringify(sortBy) + ');', sandbox);
console.log(JSON.stringify(sandbox.out.map((a) => a.id)));
"""
    out = subprocess.run(
        ["node", "-e", script, json.dumps([code, results, sort_by])],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


PAPERS = [
    {"id": "a", "similarity_score": 0.30, "year": "2020", "title": "B", "journal": "Z"},
    {"id": "undated", "similarity_score": 0.90, "year": "", "title": "A", "journal": "A", "no_year": True},
    {"id": "b", "similarity_score": 0.70, "year": "2018", "title": "C", "journal": "M"},
]


def test_similarity_keeps_the_server_order():
    # The server sorts by the same blended score the cards show.
    rows = [p for p in PAPERS if not p.get("no_year")]
    assert _client_sort(rows, "similarity") == ["a", "b"]


def test_undated_papers_stay_last_under_every_sort():
    for sort_by in ("similarity", "year", "journal", "title"):
        assert _client_sort(PAPERS, sort_by)[-1] == "undated", sort_by


def test_no_year_group_has_a_full_width_heading():
    search = _read("static", "js", "search.js")
    render = _slice(search, "function buildResultListItem(", "\n}\n")
    assert "No year listed" in render
    assert "results-group-heading" in render
    css = _read("static", "css", "style.css")
    assert ".results-group-heading, .results-group-note) {\n    grid-column: 1 / -1;" in css


def test_year_range_hint_explains_publication_year_and_undated_papers():
    template = _read("templates", "search.html")
    assert (
        "Uses the year each paper was published. "
        "Papers with no year stay in the list, after the dated ones."
    ) in template
    assert "Papers with unknown year are hidden when a range is set." not in template


def _chip_label(work_type):
    search = _read("static", "js", "search.js")
    start = search.index("const WORK_TYPE_CHIP_LABELS")
    end = search.index("function availableWorkTypeIds")
    code = search[start:end]
    script = r"""
const vm = require('vm');
const [code, workType] = JSON.parse(process.argv[1]);
const sandbox = {};
vm.runInNewContext(code + ';this.out = workTypeChipLabel(' + JSON.stringify(workType) + ');', sandbox);
console.log(JSON.stringify(sandbox.out));
"""
    out = subprocess.run(
        ["node", "-e", script, json.dumps([code, work_type])],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def test_js_type_chip_words_match_python():
    from app.services.work_types import WORK_TYPE_CHIP_LABELS, work_type_chip_label

    for stored, label in WORK_TYPE_CHIP_LABELS.items():
        assert _chip_label(stored) == label
        assert work_type_chip_label(stored) == label
    assert _chip_label(None) == ""
    assert _chip_label("unknown") == ""
    assert _chip_label("other") == ""
    card = _slice(_read("static", "js", "search.js"), "function buildResultCard(", "const noteRowHtml")
    assert "workTypeChipLabel(article.work_type)" in card
    assert "result-type-chip" in card
    assert "accessChipHtml(article)" in card
    assert "result-head-chips" in card
    tags_open = card.index('<span class="result-tags">')
    tags_close = card.index("</span>", tags_open)
    tags_html = card[tags_open:tags_close]
    assert "${accessChip}" not in tags_html
    assert "${accessChip}" in card
    assert card.index("result-head-chips") < tags_open


def test_access_chip_wording_and_forbidden_claims():
    search = _read("static", "js", "search.js")
    helper = _slice(search, "function accessChipHtml(", "function freeToReadForRequest")
    assert "Open copy listed" in helper
    assert "No open copy listed" in helper
    assert "result-access-chip" in helper
    assert "access.sources" in helper
    assert "sources.join(', ')" in helper
    lowered = helper.lower()
    assert "verified" not in lowered
    assert "free pdf" not in lowered
    assert "guaranteed" not in lowered
    template = _read("templates", "search.html")
    assert 'id="simple-free-to-read-chip"' in template
    assert "Free to read" in template
    assert 'src="/static/js/search.js?v=20261030c"' in template


def test_other_copies_disclosure_wording():
    search = _read("static", "js", "search.js")
    helper = _slice(search, "function otherCopiesHtml(", "function mountOtherCopies")
    assert "Other listed copies (" in helper
    assert 'target="_blank"' in helper
    assert 'rel="noopener"' in helper
    assert "Open copy listed" in helper
    lowered = helper.lower()
    assert "verified" not in lowered
    assert "full text available" not in lowered
    assert "free" not in lowered
    assert "function loadOtherCopiesForResults(" in search
    assert "/api/articles/other-copies" in search
    assert "none_listed" in search
    css = _read("static", "css", "style.css")
    assert ".result-other-copies" in css
    assert 'href="/static/css/style.css?v=20261030b"' in _read("templates", "base.html")


def test_access_chip_stays_visible_when_layouts_hide_tags():
    css = _read("static", "css", "style.css")
    assert "html[data-layout=\"index\"] .result-row .result-tags { display: none; }" in css
    assert "html[data-layout=\"index\"] .result-row .result-access-chip" in css
    catalog_chip = css[css.index("html[data-layout=\"index\"] .result-row .result-access-chip"):]
    catalog_chip = catalog_chip[:catalog_chip.index("}")]
    assert "display: none" not in catalog_chip
    assert "display: flex" in catalog_chip
    assert ".result-row .result-row-head > .tag:not(.result-access-chip)" in css
    phone = css[css.index("@media (max-width: 640px)"):]
    table_hide = (
        'html[data-layout="table"] .result-row:not(.is-open) .result-head-chips'
        ' { display: none; }'
    )
    assert table_hide not in phone
    assert (
        'html[data-layout="table"] .result-row:not(.is-open) .result-tags'
        ' { display: none; }'
    ) in phone
    table_chip = phone[phone.index(
        'html[data-layout="table"] .result-row:not(.is-open) .result-access-chip'
    ):]
    table_chip = table_chip[:table_chip.index("}")]
    assert "display: none" not in table_chip
    assert "display: flex" in table_chip


def test_different_work_disclosure_wording():
    search = _read("static", "js", "search.js")
    helper = _slice(search, "function differentWorkHtml(", "function mountDifferentWork")
    assert "Different work you can read (" in helper
    assert "Different paper" in helper
    assert "Open copy listed" in helper
    assert 'target="_blank"' in helper
    assert 'rel="noopener"' in helper
    lowered = helper.lower()
    assert "verified" not in lowered
    assert "full text" not in lowered
    assert "free" not in lowered
    assert "same findings" not in lowered
    assert "equivalent" not in lowered
    assert "function loadDifferentWorkForResults(" in search
    assert "/api/articles/different-work" in search
    assert "cardHasOpenOtherCopy" in search


def test_score_tooltip_says_the_list_is_sorted_by_it():
    card = _slice(_read("static", "js", "search.js"), "function buildResultCard(", "const url = getArticleUrl")
    assert "sorted" in card
    assert "Similarity score (0–1): how closely" not in card
    assert "exact words" in card


def test_rail_refreshes_after_every_screening_change():
    search = _read("static", "js", "search.js")
    sync = _slice(search, "function syncResultCountAfterScreen(", "function replaceCardWithUndo(")
    assert "refreshRailStats();" in sync  # Not relevant and its Undo
    rail = _slice(search, "async function refreshRailStats(", "async function loadSearchEmptyState(")
    assert "/api/screening-report?format=json" in rail
    assert "fillSimpleRailStats(stats, report)" in rail
    themes = _read("static", "js", "simple_themes.js")
    assert themes.count("refreshRailStats()") == 2  # theme Set aside and its Undo
    start_over = _slice(_read("static", "js", "simple_tools.js"), "async function simpleToolsStartOver(", "showNotification(")
    assert "refreshRailStats()" in start_over


def test_narrow_it_down_shows_the_duplicates_with_undo():
    card = _read("templates", "partials", "simple_screening_card.html")
    assert 'id="simple-screen-dups"' in card
    assert 'id="simple-screen-dups-undo"' in card
    tools = _read("static", "js", "simple_tools.js")
    render = _slice(tools, "function renderSimpleScreenDuplicates(", "async function doSimpleScreenDuplicatesUndo(")
    assert "already set aside" in render
    undo = _slice(tools, "async function doSimpleScreenDuplicatesUndo(", "function getResearchQuestionCandidate(")
    assert "/api/screening/excluded?reason=duplicate" in undo
    assert "action: 'include'" in undo
    assert "refreshSimpleScreeningCard()" in undo
    assert "addEventListener('click', doSimpleScreenDuplicatesUndo)" in tools


def test_papers_ready_leaves_out_set_aside_papers():
    tools = _read("static", "js", "simple_tools.js")
    pending = _slice(tools, "// Set-aside papers (duplicates included) are not ranked", "setSimpleScreenGatePending(true);")
    assert "const rankable = Math.max(0, ready - excludedTotal);" in pending
    assert "${rankable} paper" in pending
    assert "renderSimpleScreenDuplicates(" in pending


def test_the_after_prepare_status_says_set_aside_not_removed():
    collect = _read("static", "js", "collect.js")
    dedup = _slice(collect, "async function silentResolveDuplicatesAfterPrepare", "async function doCreateEmbeddings")
    assert "Removed" not in dedup
    assert "Narrow it down can bring" in dedup
