"""Different-work loader: skip when an open copy exists; unstar hides it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_open_other_copy_skips_different_work():
    _run_node(_OPEN_COPY_HARNESS)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_sixth_open_url_skips_different_work():
    _run_node(_SIXTH_OPEN_HARNESS)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_pending_different_work_does_not_restore_after_unstar():
    _run_node(_UNSTAR_HARNESS)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_different_work_loads_on_open_and_empty_removes_disclosure():
    _run_node(_OPEN_ON_DEMAND_HARNESS)


def _run_node(script: str) -> None:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "different-work-js-complete" in result.stdout


_SANDBOX = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
 constructor(tag = 'div') {
  this.tagName = String(tag).toUpperCase();
  this.dataset = {};
  this.textContent = '';
  this.children = {};
  this.childNodes = [];
  this.parentNode = null;
  this.hidden = false;
  this.value = '';
  this.open = false;
  this.style = { display: '', setProperty() {} };
  this._listeners = {};
  const classes = new Set();
  this._classes = classes;
  this.classList = {
   add: (v) => String(v || '').split(/\s+/).filter(Boolean).forEach((c) => classes.add(c)),
   remove: (v) => classes.delete(v),
   contains: (v) => classes.has(v),
   toggle: (v, on) => {
    const next = on == null ? !classes.has(v) : !!on;
    if (next) classes.add(v); else classes.delete(v);
    return next;
   },
  };
 }
 get className() { return [...this._classes].join(' '); }
 set className(value) {
  this._classes.clear();
  String(value || '').split(/\s+/).filter(Boolean).forEach((c) => this._classes.add(c));
 }
 addEventListener(type, fn) {
  (this._listeners[type] ||= []).push(fn);
 }
 dispatchEvent(event) {
  const type = event && event.type ? event.type : event;
  for (const fn of this._listeners[type] || []) fn(event);
 }
 matches(sel) {
  if (!sel) return false;
  if (sel.startsWith('.')) return this.classList.contains(sel.slice(1));
  return this.children[sel] != null;
 }
 querySelector(sel) {
  if (this.children[sel]) return this.children[sel];
  for (const child of this.childNodes) {
   if (child.matches && child.matches(sel)) return child;
   const found = child.querySelector && child.querySelector(sel);
   if (found) return found;
  }
  return null;
 }
 querySelectorAll() { return []; }
 appendChild(node) {
  node.parentNode = this;
  this.childNodes.push(node);
  return node;
 }
 prepend(node) {
  node.parentNode = this;
  this.childNodes.unshift(node);
  return node;
 }
 insertAdjacentElement(pos, node) {
  if (!this.parentNode) return node;
  const sibs = this.parentNode.childNodes;
  const i = sibs.indexOf(this);
  node.parentNode = this.parentNode;
  if (pos === 'afterend') sibs.splice(i + 1, 0, node);
  else if (pos === 'beforeend') this.appendChild(node);
  return node;
 }
 remove() {
  if (!this.parentNode) return;
  const sibs = this.parentNode.childNodes;
  const i = sibs.indexOf(this);
  if (i >= 0) sibs.splice(i, 1);
  this.parentNode = null;
 }
 replaceWith(node) {
  if (!this.parentNode) return;
  const sibs = this.parentNode.childNodes;
  const i = sibs.indexOf(this);
  if (i >= 0) {
   node.parentNode = this.parentNode;
   sibs[i] = node;
  }
  this.parentNode = null;
 }
 setAttribute() {}
 getAttribute() { return null; }
}

function makeCard(articleId, source, { starred = true, noneListed = true } = {}) {
 const card = new Element('article');
 card.dataset.articleId = articleId;
 card.dataset.source = source;
 const star = new Element('button');
 if (starred) star.classList.add('is-starred');
 const chip = new Element(noneListed ? 'span' : 'a');
 chip.textContent = noneListed ? 'No open copy listed (CrossRef)' : 'Open copy listed';
 card.children['.star-btn'] = star;
 card.children['.result-access-chip'] = chip;
 return card;
}

const cards = [];
const pending = [];
const lastMount = new Map();
const librarySelect = new Element('select');
librarySelect.value = 'lib-a';
librarySelect.dataset.activeId = 'lib-a';
librarySelect.dataset.pageLibraryId = 'lib-a';
const byId = { 'nav-library-select': librarySelect, 'results-list': new Element('div') };

const sandbox = {
 console, assert, Element, cards, pending, lastMount, librarySelect,
 document: {
  addEventListener() {},
  getElementById: (id) => byId[id] || (byId[id] = new Element()),
  querySelector: () => null,
  querySelectorAll: (sel) => sel.includes('result-row') ? cards.slice() : [],
  createElement: (tag) => new Element(tag),
  documentElement: { getAttribute: () => null },
  body: new Element('body'),
 },
 window: {},
 escapeHtml: (s) => String(s),
 escapeAttr: (s) => String(s),
 getSourceName: (s) => s,
 pageLibraryId: () => librarySelect.dataset.pageLibraryId || '',
 withPageLibrary: (body) => {
  body.library_id = librarySelect.dataset.pageLibraryId || '';
  return body;
 },
 apiCall: async (path, options) => {
  return await new Promise((resolve, reject) => {
   pending.push({ path, body: options && options.body, resolve, reject });
  });
 },
 setTimeout() {},
 URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
 Event: class { constructor(type) { this.type = type; } },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/search.js', 'utf8'), sandbox);
vm.runInContext(`
mountOtherCopies = (card, copies) => {};
`, sandbox);

function resetPage() {
 cards.length = 0;
 pending.length = 0;
 vm.runInContext('otherCopiesCache = new Map(); differentWorkCache = new Map(); differentWorkInflight = new Set(); otherCopiesGen += 1;', sandbox);
}

async function openDifferentWork(card) {
 const node = card.querySelector('.result-different-work');
 assert.ok(node, 'expected a different-work disclosure');
 node.open = true;
 node.dispatchEvent({ type: 'toggle' });
 for (let i = 0; i < 20 && !pending.some((row) => row.path === '/api/articles/different-work'); i++) {
  await Promise.resolve();
 }
}
"""

_OPEN_COPY_HARNESS = _SANDBOX + r"""
(async () => {
 resetPage();
 const article = {
  article_id: 'A', source: 'pubmed', starred: true,
  access: { state: 'none_listed' },
 };
 const card = makeCard('A', 'pubmed');
 cards.push(card);
 const load = vm.runInContext('loadOtherCopiesForResults', sandbox);
 const loading = load([article]);
 assert.equal(pending.length, 1);
 assert.equal(pending[0].path, '/api/articles/other-copies');
 pending[0].resolve({
  articles: [{
   article_id: 'A', source: 'pubmed',
   copies: [{ where: 'Zenodo', url: 'https://zenodo.org/a.pdf', open_listed: true }],
  }],
 });
 await loading;
 assert.equal(pending.length, 1);
 assert.equal(card.querySelector('.result-different-work'), null);
 console.log('different-work-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""

_SIXTH_OPEN_HARNESS = _SANDBOX + r"""
(async () => {
 resetPage();
 const article = {
  article_id: 'A', source: 'pubmed', starred: true,
  access: { state: 'none_listed' },
 };
 const card = makeCard('A', 'pubmed');
 cards.push(card);
 const load = vm.runInContext('loadOtherCopiesForResults', sandbox);
 const loading = load([article]);
 assert.equal(pending.length, 1);
 assert.equal(pending[0].path, '/api/articles/other-copies');
 pending[0].resolve({
  articles: [{
   article_id: 'A', source: 'pubmed',
   has_open_copy: true,
   copies: [0, 1, 2, 3, 4].map((i) => ({
    where: 'Host ' + i,
    url: 'https://example.org/copy/' + i,
    open_listed: false,
   })),
  }],
 });
 await loading;
 assert.equal(pending.length, 1);
 assert.equal(card.querySelector('.result-different-work'), null);
 console.log('different-work-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""

_UNSTAR_HARNESS = _SANDBOX + r"""
(async () => {
 resetPage();
 const article = {
  article_id: 'A', source: 'pubmed', starred: true,
  access: { state: 'none_listed' },
 };
 const card = makeCard('A', 'pubmed');
 cards.push(card);
 const load = vm.runInContext('loadOtherCopiesForResults', sandbox);
 const dropCache = vm.runInContext(
  '(article) => { otherCopiesCache.delete(otherCopiesKey(article)); differentWorkCache.delete(otherCopiesKey(article)); }',
  sandbox,
 );
 const mount = vm.runInContext('mountDifferentWork', sandbox);
 const loading = load([article]);
 assert.equal(pending[0].path, '/api/articles/other-copies');
 pending[0].resolve({ articles: [{ article_id: 'A', source: 'pubmed', copies: [] }] });
 await loading;
 assert.equal(pending.length, 1);
 await openDifferentWork(card);
 assert.equal(pending.length, 2);
 assert.equal(pending[1].path, '/api/articles/different-work');
 card.children['.star-btn'].classList.remove('is-starred');
 dropCache({ article_id: 'A', source: 'pubmed' });
 mount(card, []);
 pending[1].resolve({
  articles: [{
   article_id: 'A', source: 'pubmed',
   suggestions: [{ title: 'Other', url: 'https://example.org/x.pdf', difference: '2019 vs 2008' }],
  }],
 });
 await Promise.resolve();
 await Promise.resolve();
 assert.equal(card.querySelector('.result-different-work'), null);
 console.log('different-work-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""

_OPEN_ON_DEMAND_HARNESS = _SANDBOX + r"""
(async () => {
 resetPage();
 const article = {
  article_id: 'A', source: 'pubmed', starred: true,
  access: { state: 'none_listed' },
 };
 const card = makeCard('A', 'pubmed');
 cards.push(card);
 const load = vm.runInContext('loadOtherCopiesForResults', sandbox);
 const loading = load([article]);
 assert.equal(pending.length, 1);
 assert.equal(pending[0].path, '/api/articles/other-copies');
 pending[0].resolve({ articles: [{ article_id: 'A', source: 'pubmed', copies: [] }] });
 await loading;
 assert.equal(pending.length, 1);
 assert.ok(card.querySelector('.result-different-work'));
 await openDifferentWork(card);
 assert.equal(pending.length, 2);
 assert.equal(pending[1].path, '/api/articles/different-work');
 pending[1].resolve({
  articles: [{ article_id: 'A', source: 'pubmed', suggestions: [] }],
 });
 for (let i = 0; i < 20 && card.querySelector('.result-different-work'); i++) {
  await Promise.resolve();
 }
 assert.equal(card.querySelector('.result-different-work'), null);
 console.log('different-work-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""
