"""Audit 19.5, 19.7-19.14: the Search page flow and its wait screens."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _slice(source, start, end):
    i = source.index(start)
    return source[i:source.index(end, i + len(start))]


def _node(script, *args):
    out = subprocess.run(
        ["node", "-e", script, *args], cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_level_counts_are_asked_for_once_per_question():
    """The modal opening and the card refresh used to send six requests (19.5)."""
    result = _node(r"""
const fs = require('fs'), vm = require('vm');
const t = fs.readFileSync('static/js/simple_tools.js', 'utf8');
const cut = (a, b) => t.slice(t.indexOf(a), t.indexOf(b, t.indexOf(a)));
let calls = 0;
const sandbox = {
  SIMPLE_SCREEN_LEVELS: {low: 0.1, medium: 0.25, high: 0.5},
  document: {getElementById: (id) => (id === 'simple-screen-query' ? {value: 'Does sleep help?'} : null)},
  setStatus() {}, applySimpleScreenCountLabels() {}, console, withPageLibrary: (body) => body,
  apiCall: async () => { calls += 1; await new Promise((r) => setTimeout(r, 10)); return {proposed_count: 1, total_ranked: 9}; },
  setTimeout,
};
vm.runInNewContext(
  'var _simpleScreenCounts = { low: null, medium: null, high: null };\nlet _simpleScreenCountsLoading = null;\n'
  + cut('function simpleScreenQuery()', 'function prefillSimpleScreenQuery()')
  + cut('async function loadSimpleScreenCounts()', 'function applySimpleScreenCountLabels()')
  + ';this.load = loadSimpleScreenCounts;', sandbox);
(async () => {
  await Promise.all([sandbox.load(), sandbox.load()]);
  const afterBoth = calls;
  await sandbox.load();
  console.log(JSON.stringify({afterBoth, afterThird: calls}));
})();
""")
    assert result == {"afterBoth": 3, "afterThird": 3}


def test_back_clears_the_set_aside_status_line():
    close = _slice(_read("static", "js", "simple_tools.js"), "function closeSimpleScreenTriage()", "function _screenTriageOrder()")
    assert "setStatus('simple-screen-status', '', 'info');" in close


@needs_node
def test_fetch_lock_and_replace_warning_run_without_prepare_section():
    """No template renders #prepare-section; the lock must still update (19.7)."""
    result = _node(r"""
const fs = require('fs'), vm = require('vm');
const c = fs.readFileSync('static/js/collect.js', 'utf8');
const fn = c.slice(c.indexOf('function updatePrepareSectionVisibility('), c.indexOf('async function loadPageData()'));
const calls = [];
const sandbox = {
  document: {getElementById: () => null},
  _lastTotalArticles: 0, _lastReadyArticles: 0, _pipelineBusy: false,
  updateSimpleFetchLock: () => calls.push('lock'),
  updateReplaceConsequence: () => calls.push('consequence'),
};
vm.runInNewContext('var _lastTotalArticles = 0, _lastReadyArticles = 0;' + fn + ';updatePrepareSectionVisibility(63, {readyArticles: 0}); this.total = _lastTotalArticles;', sandbox);
console.log(JSON.stringify({calls, total: sandbox.total}));
""")
    assert result == {"calls": ["lock", "consequence"], "total": 63}


@needs_node
def test_closing_the_wait_screen_brings_back_the_more_dock():
    """Group by theme hid #simple-screening-card until a reload (19.8)."""
    result = _node(r"""
const fs = require('fs'), vm = require('vm');
const t = fs.readFileSync('static/js/simple_tools.js', 'utf8');
const cut = (a, b) => t.slice(t.indexOf(a), t.indexOf(b, t.indexOf(a)));
const els = {};
const mk = (id, hidden) => (els[id] = {id, hidden, dataset: {}, textContent: '', setAttribute() {}, classList: {add() {}, remove() {}}});
mk('search-preparing', true); mk('simple-screening-card', false); mk('simple-screen-modal', true);
mk('search-buffering-cancel', true); els['search-buffering-cancel'].disabled = true;
const sandbox = {
  window: {}, document: {getElementById: (id) => els[id] || null, body: {classList: {add() {}, remove() {}}}},
  _startWaitMessages() {}, _stopWaitMessages() {}, _setWaitPct() {}, _waitMsgIndex: 0,
};
vm.runInNewContext('var _waitMsgIndex = 0;' + cut('function showSimpleBuffering(', 'function holdSimpleWait()'), sandbox);
vm.runInNewContext("showSimpleBuffering('prepare');", sandbox);
const during = els['simple-screening-card'].hidden;
const cancelUsable = els['search-buffering-cancel'].disabled === false;
vm.runInNewContext('hideSimpleBuffering();', sandbox);
console.log(JSON.stringify({during, after: els['simple-screening-card'].hidden, cancelUsable}));
""")
    assert result == {"during": True, "after": False, "cancelUsable": True}


def test_the_ninety_percent_hold_always_has_an_exit():
    tools = _read("static", "js", "simple_tools.js")
    wrapper = _slice(tools, "async function refreshSimpleScreeningCard()", "async function _refreshSimpleScreeningCardNow()")
    assert "await settleSimpleWaitHold();" in wrapper
    settle = _slice(wrapper, "async function settleSimpleWaitHold()", "\n}\n")
    assert "if (_isPipelineBusy()) return;" in settle
    assert "if (isSimpleScreenGatePending()) return;" in settle
    assert "await finishSimpleWaitThenSearch();" in settle


def test_the_fetch_topic_is_never_the_research_question():
    tools = _read("static", "js", "simple_tools.js")
    for name, end in (
        ("function simpleScreenQuery()", "function prefillSimpleScreenQuery()"),
        ("function getResearchQuestionCandidate()", "function applyVerifiedResearchQuestion("),
        ("function applyVerifiedResearchQuestion(", "async function resolveSimplePrepareModeBeforeRequest("),
    ):
        assert "fetch-query" not in _slice(tools, name, end), name


def test_one_failed_progress_poll_does_not_end_the_wait():
    wait = _slice(_read("static", "js", "collect.js"), "function waitForJob(", "function buildFetchSourceReportModel(")
    assert "pollFailures = 0;" in wait
    assert "if (pollFailures < 2 && e.status !== 401) return;" in wait


@needs_node
def test_request_errors_read_as_sentences():
    result = _node(r"""
const fs = require('fs'), vm = require('vm');
const c = fs.readFileSync('static/js/common.js', 'utf8');
const fn = c.slice(c.indexOf('function apiErrorSentence('), c.indexOf('// === Notification system ==='));
const sandbox = {};
vm.runInNewContext(fn + `;this.out = [
  apiErrorSentence(422, {detail: [{type: 'string_too_long', loc: ['body', 'note'], msg: 'String should have at most 8000 characters', ctx: {max_length: 8000}}]}),
  apiErrorSentence(422, {detail: [{type: 'missing', loc: ['body', 'query'], msg: 'Field required'}]}),
  apiErrorSentence(429, {error: 'Rate limit exceeded: 8 per 1 minute'}),
  apiErrorSentence(400, {detail: 'Pick at least one database to search.'}),
  apiErrorSentence(500, {}),
];`, sandbox);
console.log(JSON.stringify(sandbox.out));
""")
    assert result == [
        "That note is too long. Keep it to 8000 characters or fewer.",
        "Fill in the query and try again.",
        "Too many requests in a short time. Wait a minute and try again.",
        "Pick at least one database to search.",
        "The server could not finish that. Try again in a moment.",
    ]
    assert "[object Object]" not in _read("static", "js", "common.js")


def test_show_original_abstract_opens_the_details():
    reader = _read("static", "js", "reader.js")
    scroll = _slice(reader, "const scrollToAbstract = (ev) => {", "const paint = (data) => {")
    assert "details.open = true" in scroll


def test_the_wait_finish_does_not_depend_on_animation_frames():
    """A background tab pauses requestAnimationFrame; a timer finishes anyway."""
    tools = _read("static", "js", "simple_tools.js")
    fin = _slice(tools, "function finishSimpleWaitThenSearch()", "function setNextStepVisible(")
    assert "setTimeout(finish, dur + 500);" in fin
    assert "if (finished) return;" in fin
