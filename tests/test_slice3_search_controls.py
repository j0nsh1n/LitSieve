"""Exercise Search chips through their real handlers with a small DOM boundary."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

def test_selected_modal_choice_keeps_keyboard_focus_ring():
    css = (REPO / "static/css/style.css").read_text()
    checked = css.index(".lra-modal-choice .lra-choice-chip:has(input:checked) {")
    focus = css.index(".lra-modal-choice .lra-choice-chip:has(input:focus-visible)")
    assert focus > css.index("}", checked)
    assert "box-shadow: var(--focus-ring)" in css[focus:css.index("}", focus)]


HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
class Element {
 constructor() {
  this.value = ''; this.checked = false; this.disabled = false;
  this.textContent = ''; this.dataset = {}; this.attributes = {};
  this.listeners = {}; this.children = {}; this.style = {setProperty() {}};
  const classes = new Set();
  this.classList = {
   add: (v) => classes.add(v), remove: (v) => classes.delete(v),
   contains: (v) => classes.has(v),
   toggle: (v, on) => { if (on ?? !classes.has(v)) classes.add(v); else classes.delete(v); },
  };
 }
 addEventListener(type, fn) { this.listeners[type] = fn; }
 dispatchEvent(event) { this.listeners[event.type]?.(event); }
 setAttribute(k, v) { this.attributes[k] = v; }
 getAttribute(k) { return this.attributes[k]; }
 removeAttribute(k) { delete this.attributes[k]; }
 querySelector(k) { return this.children[k] ??= new Element(); }
 querySelectorAll() { return []; }
 appendChild() {}
 closest() { return null; }
 focus() {}
 click() {}
 remove() {}
}
const elements = {};
const el = (id) => elements[id] ??= new Element();
const method = new Element(); method.value = 'text';
const boxes = ['pubmed', 'arxiv'].map((value) => Object.assign(new Element(), {value, checked: true}));
const stored = new Map();
const requests = []; const exports = []; const notices = [];
let stats = {sources: {sample: 28, pubmed: 3, arxiv: 3}, starred: 0};
let hits = [
 {article_id: 'a', source: 'sample', similarity_score: 0.9, year: '2019', title: 'Zeta', journal: 'Alpha'},
 {article_id: 'b', source: 'pubmed', similarity_score: 0.5, year: '2024', title: 'Alpha', journal: 'Zeta'},
 {article_id: 'c', source: 'arxiv', similarity_score: 0.7, year: '', title: 'Middle', journal: 'Middle'},
];
let failRequest = false;
let heldRequest = null;
let releaseRequest = null;
const sandbox = {
 console, assert, Element, el, method, boxes, requests, exports, notices,
 document: {
  addEventListener() {}, getElementById: el,
  querySelector: (s) => s.includes('input_method') ? method : null,
  querySelectorAll: (s) => s.includes('search-source') ? boxes : [],
  documentElement: {getAttribute: () => null},
  createElement: () => new Element(), body: new Element(),
 },
 window: {}, Event: class {constructor(type) {this.type = type;}},
 sessionStorage: {getItem: (k) => stored.get(k), setItem: (k,v) => stored.set(k,v), removeItem: (k) => stored.delete(k)},
 setLoading() {}, updateRangeFill() {}, showNotification: (...args) => notices.push(args),
 escapeHtml: (s) => String(s), escapeAttr: (s) => String(s), getSourceName: (s) => s,
 getArticleUrl: () => 'https://example.test/paper', withPageLibrary: (body) => body,
 apiCall: async (path, options) => {
  if (path === '/api/statistics') return stats;
  if (path === '/api/libraries') return {active_id: 'lib-a'};
  requests.push({path, body: JSON.parse(JSON.stringify(options.body))});
  if (failRequest) throw new Error('request failed');
  if (heldRequest) await heldRequest;
  return {results: hits, seed_count: 1, seed: {article_id: 'seed-a', source: 'pubmed', title: 'Seed'}};
 },
 fetch: async (path, options) => {
  exports.push({path, body: JSON.parse(options.body)});
  return {ok: true, blob: async () => ({}), headers: {get: () => ''}};
 },
 URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}},
 setTimeout() {},
 setStats: (v) => { stats = v; },
 setHits: (v) => { hits = v; }, setFailure: (v) => { failRequest = v; },
 holdRequest: () => { heldRequest = new Promise((resolve) => { releaseRequest = resolve; }); },
 releaseRequest: () => { heldRequest = null; releaseRequest(); },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/search.js', 'utf8'), sandbox);
vm.runInContext(`
el('top-k').value = '10'; el('sort-by').value = 'similarity';
el('lexical-boost').checked = true; el('nav-library-select').value = 'lib-a';
let rendered = []; let renderedExtra = [];
renderResults = (rows, extra = []) => { rendered = rows; renderedExtra = extra; };
syncDisplayFilterSourceChips = () => {};
updateSimpleSearchPanel = () => {};
showResultSkeletons = () => {};
clearResultSkeletonsOnError = () => {};
wireSearchFilterAdapters();
`, sandbox);
"""


def run_search_js(body: str) -> None:
    script = HARNESS + "\nvm.runInContext(" + repr(
        "(async () => {\n" + body + "\nconsole.log('search-handler-complete');\n})().catch((err) => { throw err; });"
    ) + ", sandbox);"
    result = subprocess.run(
        ["node", "-e", script], cwd=REPO, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "search-handler-complete" in result.stdout, "Search handler did not finish"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_sources_filter_current_hits_without_another_search():
    run_search_js(r"""
await applyAvailableSources();
el('query-text').value = 'question'; await doSearch({skipOptions: true});
const before = requests.length;
openSiteForm = async (form) => {
 assert.deepEqual(form.fields[0].options.map((o) => o.hint), ['1 paper', '1 paper', '1 paper']);
 return {sources: ['sample']};
};
await promptSimpleSources();
assert.equal(requests.length, before);
assert.deepEqual([...visibleResults().map((a) => a.source)], ['sample']);
assert.equal(readSearchSession().filters.display.sources.sample, true);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_sources_cancel_validate_and_preserve_sample_selection_on_refresh():
    run_search_js(r"""
await applyAvailableSources();
const before = JSON.stringify(searchState.filters);
openSiteForm = async (form) => {
 assert.ok(form.validate({sources: []}));
 return null;
};
await promptSimpleSources();
assert.equal(JSON.stringify(searchState.filters), before);
assert.equal(requests.length, 0);
searchState.filters.source_filter = ['sample'];
syncSearchFilterControls();
await applyAvailableSources();
assert.deepEqual([...collectSearchFilters().source_filter], ['sample']);
searchState.filters.source_filter = [];
assert.equal(requireSelectedSources(collectSearchFilters(), false), false);
setStats({sources: {sample: 28}, starred: 0});
librarySourceCounts = {}; await applyAvailableSources();
assert.deepEqual([...collectSearchFilters().source_filter], ['sample']);
searchState.filters.source_filter = [];
assert.equal(requireSelectedSources(collectSearchFilters(), false), false);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_type_filter_persists_and_is_sent_on_replay():
    run_search_js(r"""
setStats({sources: {pubmed: 2}, starred: 0,
 work_type_counts: {'journal-article': 2, 'not-stored': 1}});
await applyAvailableSources();
el('query-text').value = 'saved question';
await doSearch({skipOptions: true});
assert.equal('work_type_filter' in requests.at(-1).body, false);
openSiteForm = async (form) => {
 assert.equal(form.title, 'Type');
 assert.deepEqual(form.fields[0].options.map((v) => v.value),
  ['journal-article', 'not-stored']);
 return {types: ['journal-article']};
};
await promptSimpleTypes();
assert.deepEqual([...requests.at(-1).body.work_type_filter], ['journal-article']);
assert.deepEqual([...readSearchSession().filters.work_type_filter], ['journal-article']);
assert.equal(el('simple-type-chip').textContent, 'Type: 1 of 2');
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_free_to_read_persists_and_is_sent_on_replay():
    run_search_js(r"""
await applyAvailableSources();
el('query-text').value = 'saved question';
await doSearch({skipOptions: true});
assert.equal('free_to_read' in requests.at(-1).body, false);
await toggleFreeToRead();
assert.equal(requests.at(-1).body.free_to_read, true);
assert.equal(readSearchSession().filters.free_to_read, true);
assert.equal(el('simple-free-to-read-chip').getAttribute('aria-pressed'), 'true');
await toggleFreeToRead();
assert.equal('free_to_read' in requests.at(-1).body, false);
assert.equal(readSearchSession().filters.free_to_read, false);
assert.equal(el('simple-free-to-read-chip').getAttribute('aria-pressed'), 'false');
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_chips_cannot_start_competing_reruns_until_request_finishes():
    run_search_js(r"""
await applyAvailableSources();
el('query-text').value = 'saved question';
holdRequest();
const first = doSearch({skipOptions: true});
await Promise.resolve(); await Promise.resolve();
assert.equal(searchState.requestPending, true);
let prompts = 0;
openSiteForm = async () => { prompts++; return null; };
await promptSimpleSources(); await promptSimpleSort(); await promptSimpleStarred();
assert.equal(prompts, 0);
releaseRequest(); await first;
assert.equal(searchState.requestPending, false);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_sort_uses_copy_restores_hybrid_rank_and_exports_visible_order():
    run_search_js(r"""
await applyAvailableSources();
el('sort-by').value = 'year'; syncSearchFiltersFromForm();
el('query-text').value = 'saved question'; await doSearch({skipOptions: true});
assert.equal(requests.at(-1).body.sort_by, 'similarity');
assert.equal(lastSearchParams.sort_by, 'year');
const raw = lastResults.map((v) => v.article_id).join(',');
openSiteForm = async () => null;
await promptSimpleSort();
assert.equal(searchState.filters.sort_by, 'year');
for (const [sort, expected] of [
 ['year', ['b', 'a', 'c']], ['journal', ['a', 'c', 'b']],
 ['title', ['b', 'c', 'a']], ['similarity', ['a', 'b', 'c']],
]) {
 openSiteForm = async () => ({sort}); await promptSimpleSort();
 assert.deepEqual([...rendered.map((v) => v.article_id)], expected);
 assert.equal(lastResults.map((v) => v.article_id).join(','), raw);
 await doExportResults('ris');
 assert.deepEqual([...exports.at(-1).body.items.map((v) => v.article_id)], expected);
 assert.equal(readSearchSession().filters.sort_by, sort);
}
displayFilterState.sources = {pubmed: true};
searchState.filters.source_filter = ['sample'];
showSearchResults();
assert.deepEqual([...rendered.map((v) => v.article_id)], ['b']);
await doExportResults('ris');
assert.deepEqual([...exports.at(-1).body.items.map((v) => v.article_id)], ['b']);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_ranking_pico_visibility_request_gate_and_cancel():
    run_search_js(r"""
await applyAvailableSources();
el('pico-population').value = '   ';
el('pico-boost').checked = true; syncSearchFiltersFromForm();
const before = JSON.stringify(searchState.filters);
openSiteForm = async (form) => {
 assert.ok(form.fields.some((f) => f.id === 'lexical_boost' && f.section === 'Ranking'));
 assert.ok(!form.fields.some((f) => f.id === 'pico_boost'));
 return null;
};
assert.equal(await promptSimpleSearchScope(), false);
assert.equal(JSON.stringify(searchState.filters), before);
el('query-text').value = 'question'; await doSearch({skipOptions: true});
assert.equal(requests.at(-1).body.pico_boost, false);
el('pico-outcome').value = ' outcome ';
openSiteForm = async (form) => {
 assert.ok(!form.fields.some((f) => f.id === 'lexical_boost' || f.id === 'pico_boost'));
 return null;
};
await promptSimpleSearchScope('starred');
openSiteForm = async (form) => {
 assert.ok(form.fields.some((f) => f.id === 'lexical_boost'));
 assert.ok(!form.fields.some((f) => f.id === 'pico_boost'));
 return null;
};
await promptSimpleSearchScope('seed');
openSiteForm = async (form) => {
 assert.ok(form.fields.some((f) => f.id === 'pico_boost'));
 assert.ok(form.validate({count: 0, year_min: '', year_max: ''}));
 assert.ok(form.validate({count: 10, year_min: '2025', year_max: '2020'}));
 return {count: '20', year_min: '2010', year_max: '2025', lexical_boost: 'off', pico_boost: 'on'};
};
await doSearch();
assert.equal(requests.at(-1).body.lexical_boost, false);
assert.equal(requests.at(-1).body.pico_boost, true);
assert.equal(requests.at(-1).body.top_k, 20);
assert.equal(requests.at(-1).body.year_min, 2010);
assert.equal(requests.at(-1).body.year_max, 2025);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_starred_action_tracks_first_last_star_and_keeps_seeds():
    run_search_js(r"""
await applyAvailableSources();
let actions;
openSiteChoice = async (form) => { actions = form.choices; return null; };
await promptSimpleStarred();
assert.ok(!actions.some((v) => v.value === 'find'));
const article = {article_id: 'a', source: 'pubmed', title: 'Paper'};
lastResults = [article];
const card = buildResultCard(article, 0);
const click = {preventDefault() {}, stopPropagation() {}};
await card.querySelector('.star-btn').listeners.click(click);
assert.equal(requests.at(-1).body.starred, true);
assert.equal(article.starred, true);
await promptSimpleStarred(); assert.ok(actions.some((v) => v.value === 'find'));
await card.querySelector('.star-btn').listeners.click(click);
assert.equal(requests.at(-1).body.starred, false);
await promptSimpleStarred(); assert.ok(!actions.some((v) => v.value === 'find'));
setFailure(true); await card.querySelector('.star-btn').listeners.click(click); setFailure(false);
await promptSimpleStarred(); assert.ok(!actions.some((v) => v.value === 'find'));
refreshStarredCount(1); displayFilterState.starred = true;
openSiteChoice = async () => 'find';
setHits([{...article, starred: true, similarity_score: 1}]);
await promptSimpleStarred();
assert.equal(requests.at(-1).path, '/api/search/starred');
assert.equal(displayFilterState.starred, true);
assert.equal(rendered.length, 0);
assert.equal(starredResults[0].starred, true);
displayFilterState.starred = false; showSearchResults();
assert.equal(rendered[0].article_id, 'a');
assert.equal(rendered[0].starred, false);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_v1_nested_session_restore_and_library_isolation():
    run_search_js(r"""
await applyAvailableSources();
const old = {v: 1, library_id: 'lib-a', mode: 'text', query_text: 'old question',
 top_k: 7, sort_by: 'year', lexical_boost: false, pico_boost: false,
 source_filter: ['pubmed'], year_min: 2010, year_max: 2020};
applySearchSessionToForm(old);
assert.equal(collectSearchFilters().top_k, 7);
assert.equal(collectSearchFilters().sort_by, 'year');
assert.deepEqual([...collectSearchFilters().source_filter], ['pubmed']);
const nested = {...old, library_id: 'lib-b', filters: {
 top_k: 12, sort_by: 'title', lexical_boost: true, pico_boost: false,
 source_filter: ['sample'], year_min: null, year_max: null,
 display: {starred: true, noted: true, recent: false, sources: {sample: true}},
}};
sessionStorage.setItem(SEARCH_SESSION_KEY, JSON.stringify(nested));
await restoreSearchSession();
assert.equal(requests.length, 0);
assert.equal(el('query-text').value, 'old question');
nested.library_id = 'lib-a';
sessionStorage.setItem(SEARCH_SESSION_KEY, JSON.stringify(nested));
await restoreSearchSession();
assert.equal(requests.at(-1).body.top_k, 12);
assert.equal(requests.at(-1).body.sort_by, 'similarity');
assert.equal(searchState.filters.sort_by, 'title');
assert.equal(requests.at(-1).body.lexical_boost, true);
assert.deepEqual([...requests.at(-1).body.source_filter], ['sample']);
assert.equal(el('year-min').value, '');
assert.equal(displayFilterState.starred, false);
assert.equal(displayFilterState.noted, false);
assert.equal(displayFilterState.sources.sample, true);
await saveSearchSession();
assert.equal(readSearchSession().v, 1);
assert.equal(readSearchSession().filters.display.noted, false);
clearSearchWorkspace(); assert.equal(readSearchSession(), null);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_paper_identifiers_and_study_type_stay_in_the_abstract():
    run_search_js(r"""
const article = {article_id: 'PMID-123', source: 'pubmed', title: 'Trial',
 abstract: 'The trial abstract', study_type: 'randomized_controlled_trial'};
renderStudyTypeBadge = () => '<span class="study-type-badge">Trial</span>';
const simple = buildResultCard(article, 0).innerHTML;
const start = simple.indexOf('<details class="result-abstract">');
const end = simple.indexOf('</details>', start);
assert.ok(start > 0 && end > start);
assert.ok(simple.indexOf('PMID-123') > start && simple.indexOf('PMID-123') < end);
assert.ok(simple.indexOf('study-type-badge') > start && simple.indexOf('study-type-badge') < end);
assert.equal((simple.match(/study-type-badge/g) || []).length, 1);
assert.ok(!simple.slice(0, start).includes('PMID-123'));
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_presets_and_starred_sections_restore_and_export():
    run_search_js(r"""
await applyAvailableSources(); refreshStarredCount(1);
el('query-text').value = 'question'; await doSearch({skipOptions: true});
const original = lastResults.map((a) => a.article_id).join(',');
assert.ok(displayRecentYear());
setHits([{article_id: 'a', source: 'sample', starred: true},
 {article_id: 'new', source: 'pubmed', year: '2024', note: 'note'}]);
await doStarredSearch({skipOptions: true});
assert.equal(lastResults.map((a) => a.article_id).join(','), original);
assert.deepEqual([...rendered.map((a) => a.article_id)], ['a', 'b', 'c']);
assert.deepEqual([...renderedExtra.map((a) => a.article_id)], ['new']);
assert.deepEqual([...visibleExportResults().map((a) => a.article_id)], ['a', 'b', 'c', 'new']);
await doExportResults('ris');
assert.deepEqual([...exports.at(-1).body.items.map((a) => a.article_id)], ['a', 'b', 'c', 'new']);
const saved = readSearchSession();
assert.equal(saved.starred_results.length, 2);
setHits([{article_id: 'a', source: 'sample', year: '2019'},
 {article_id: 'b', source: 'pubmed', year: '2024'}, {article_id: 'c', source: 'arxiv'}]);
starredResults = []; await restoreSearchSession();
assert.equal(starredResults.length, 2);
displayFilterState.noted = true; displayFilterState.recent = true;
lastResults = [{article_id: 'a', source: 'sample', year: '2020'}]; showSearchResults();
assert.equal(displayFilterState.noted, false);
assert.equal(displayFilterState.recent, false);
await doSearch({skipOptions: true}); assert.equal(starredResults.length, 0);
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_starred_results_restore_without_a_query():
    run_search_js(r"""
await applyAvailableSources(); refreshStarredCount(1);
el('query-text').value = 'unsent question';
setHits([{article_id: 'seed', source: 'sample', starred: true}]);
await doStarredSearch({skipOptions: true});
assert.equal(lastResults.length, 0);
assert.equal(visibleExportResults()[0].article_id, 'seed');
starredResults = []; const before = requests.length; await restoreSearchSession();
assert.equal(requests.length, before);
assert.equal(visibleExportResults()[0].article_id, 'seed');
""")
