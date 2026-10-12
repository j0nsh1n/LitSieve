"""Search-by controls use real Search handlers with mocked browser boundaries."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_simple_search_by_switch_visibility_payload_and_seed_restore():
    node = subprocess.run(
        ["node", "-e", _NODE_SEARCH_BY],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert node.returncode == 0, node.stderr + node.stdout


def test_search_by_switch_is_under_search_bar_and_available_in_simple_mode():
    html = (REPO / "templates/search.html").read_text(encoding="utf-8")
    css = (REPO / "static/css/style.css").read_text(encoding="utf-8")
    card = html.index('id="searchcard"')
    switch = html.index('id="input-method-toggle"')
    assert card < switch
    assert 'aria-label="Search by"' in html
    assert 'value="text" checked> Question' in html
    assert 'value="pico"> PICO' in html
    assert 'value="seed"> Start from a paper' in html
    for input_id in (
        "pico-population",
        "pico-intervention",
        "pico-comparison",
        "pico-outcome",
        "seed-query",
    ):
        assert f'<label for="{input_id}">' in html
        assert f'id="{input_id}"' in html
    assert 'html[data-mode="simple"] .search-query-top .input-method-toggle' not in css
    assert 'html[data-mode="simple"] #seed-input-panel' not in css


_NODE_SEARCH_BY = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
 constructor(value = '') {
  this.value = value; this.checked = false; this.disabled = false;
  this.textContent = ''; this.dataset = {};
  this.style = {setProperty() {}, removeProperty() {}};
  this.attributes = {}; this.hidden = false;
  const classes = new Set();
  this.classList = {
   add: (v) => classes.add(v), remove: (v) => classes.delete(v),
   contains: (v) => classes.has(v),
   toggle: (v, on) => { if (on ?? !classes.has(v)) classes.add(v); else classes.delete(v); },
  };
 }
 addEventListener() {}
 querySelectorAll() { return []; }
 dispatchEvent(event) {
  if (event.type !== 'change') return;
  radios.forEach((radio) => { radio.checked = radio === this; });
  setMethodPanel(this.value);
 }
 setAttribute(k, v) { this.attributes[k] = v; }
 getAttribute(k) { return this.attributes[k]; }
}

const ids = {};
const el = (id) => ids[id] ??= new Element();
const radios = ['text', 'pico', 'seed'].map((value) => new Element(value));
let setMethodPanel = () => {};
radios[0].checked = true;
el('top-k').value = '10'; el('sort-by').value = 'similarity';
el('lexical-boost').checked = true;
el('nav-library-select').value = 'lib-a';
el('nav-library-select').dataset.activeId = 'lib-a';
const stored = new Map();
const requests = [];
const sandbox = {
 console, assert, Event: class { constructor(type) { this.type = type; } },
 document: {
  addEventListener() {},
  getElementById: el,
  querySelector(selector) {
   const value = selector.match(/value="([^"]+)"/)?.[1];
   if (selector.includes('input_method') && selector.includes(':checked')) {
    return radios.find((radio) => radio.checked) || radios[0];
   }
   if (selector.includes('input_method') && value) return radios.find((r) => r.value === value) || null;
   return null;
  },
  querySelectorAll(selector) {
   if (selector.includes('input_method')) return radios;
   if (selector.includes('search-source')) return [];
   return [];
  },
 },
 window: {},
 sessionStorage: {
  getItem: (key) => stored.get(key) ?? null,
  setItem: (key, value) => stored.set(key, value),
  removeItem: (key) => stored.delete(key),
 },
 isSimpleMode: () => true,
 wantsSimpleCollectView: () => false,
 stats: {articles_with_embeddings: 1},
 getSourceName: (source) => source,
 showNotification: (...args) => { throw new Error(args.join(':')); },
 setLoading() {}, showResultSkeletons() {}, showSearchResults() {},
 updateRangeFill() {}, syncSearchFiltersFromForm() {}, syncSearchFilterControls() {},
 updateSearchWorkVisibility() {},
 apiCall: async (path, options) => {
  requests.push({path, body: JSON.parse(JSON.stringify(options.body))});
  if (path === '/api/search/seed') {
   return {seed: {article_id: options.body.seed, source: 'pubmed', title: 'Seed'}, results: []};
  }
  return {results: []};
 },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/search.js', 'utf8'), sandbox);
setMethodPanel = (mode) => sandbox.applySearchInputMethod(mode);

(async () => {
 sandbox.applySearchInputMethod('text');
 assert.equal(el('text-input-panel').style.display, 'flex');
 assert.equal(el('pico-input-panel').classList.contains('u-hidden'), true);
 assert.equal(el('seed-input-panel').classList.contains('u-hidden'), true);
 sandbox.setInputMethod('pico');
 assert.equal(el('pico-input-panel').style.display, 'block');
 assert.equal(el('pico-input-panel').classList.contains('u-hidden'), false);
 el('pico-population').value = 'adolescents';
 await sandbox.doSearch({skipOptions: true});
 assert.equal(requests.at(-1).path, '/api/search');
 assert.match(requests.at(-1).body.query_text, /Population: adolescents/);

 sandbox.setInputMethod('seed');
 el('seed-query').value = 'manual PMID';
 await sandbox.doSearch({skipOptions: true});
 assert.equal(requests.at(-1).path, '/api/search/seed');
 assert.equal(requests.at(-1).body.seed, 'manual PMID');
 assert.equal(requests.at(-1).body.include_seed, undefined);
 assert.equal(vm.runInContext('lastSuccessfulSession.include_seed', sandbox), false);

 sandbox.setInputMethod('text');
 el('seed-query').value = '';
 await sandbox.restoreSearchSession();
 assert.equal(radios.find((radio) => radio.value === 'seed').checked, true);
 assert.equal(el('seed-input-panel').classList.contains('u-hidden'), false);
 assert.equal(el('seed-query').value, 'manual PMID');
 assert.equal(requests.at(-1).body.seed, 'manual PMID');

 await sandbox.doMoreLikeThisPaper({article_id: 'stored PMID', title: 'Stored seed'}, {skipOptions: true});
 assert.equal(requests.at(-1).body.include_seed, true);
 assert.equal(vm.runInContext('lastSuccessfulSession.include_seed', sandbox), true);
 sandbox.setInputMethod('text');
 await sandbox.restoreSearchSession();
 assert.equal(radios.find((radio) => radio.value === 'seed').checked, true);
 assert.equal(requests.at(-1).body.seed, 'stored PMID');
 assert.equal(requests.at(-1).body.include_seed, true);
 console.log('search-by-handlers-complete');
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
