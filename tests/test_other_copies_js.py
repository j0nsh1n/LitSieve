"""Deferred other-copies loader: unstar and overlapping page/star requests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_pending_other_copies_do_not_restore_after_unstar():
    _run_node(_UNSTAR_HARNESS)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
@pytest.mark.parametrize("first", ["page", "star"])
def test_starring_another_card_keeps_page_copies(first: str):
    _run_node(_ORDER_HARNESS.replace("FIRST_RESOLVE", first))


def _run_node(script: str) -> None:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "other-copies-js-complete" in result.stdout


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
  this.hidden = false;
  this.value = '';
  this.style = { display: '', setProperty() {} };
  const classes = new Set();
  this.classList = {
   add: (v) => classes.add(v),
   remove: (v) => classes.delete(v),
   contains: (v) => classes.has(v),
   toggle: (v, on) => {
    const next = on == null ? !classes.has(v) : !!on;
    if (next) classes.add(v); else classes.delete(v);
    return next;
   },
  };
 }
 addEventListener() {}
 querySelector(sel) { return this.children[sel] || null; }
 querySelectorAll() { return []; }
 remove() {}
 replaceWith() {}
 insertAdjacentElement() {}
 prepend() {}
 appendChild() {}
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
  if (path !== '/api/articles/other-copies') return {};
  return await new Promise((resolve, reject) => {
   pending.push({ body: options && options.body, resolve, reject });
  });
 },
 setTimeout() {},
 URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
 Event: class { constructor(type) { this.type = type; } },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/js/search.js', 'utf8'), sandbox);
vm.runInContext(`
mountOtherCopies = (card, copies) => {
 const key = (card.dataset.articleId || '') + '\\t' + (card.dataset.source || '');
 lastMount.set(key, Array.isArray(copies) ? copies.map((row) => row && row.url) : []);
};
`, sandbox);

function mountedUrls(articleId, source) {
 return sandbox.lastMount.get(articleId + '\t' + source) || [];
}

function resetPage() {
 cards.length = 0;
 pending.length = 0;
 sandbox.lastMount.clear();
}
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
 const dropCache = vm.runInContext('(article) => otherCopiesCache.delete(otherCopiesKey(article))', sandbox);
 const mount = vm.runInContext('mountOtherCopies', sandbox);
 const loading = load([article]);
 assert.equal(pending.length, 1);
 card.children['.star-btn'].classList.remove('is-starred');
 dropCache({ article_id: 'A', source: 'pubmed' });
 mount(card, []);
 pending[0].resolve({
  articles: [{
   article_id: 'A', source: 'pubmed',
   copies: [{ where: 'Zenodo', url: 'https://zenodo.org/a.pdf', open_listed: true }],
  }],
 });
 await loading;
 assert.deepEqual(mountedUrls('A', 'pubmed'), []);
 console.log('other-copies-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""

_ORDER_HARNESS = _SANDBOX + r"""
(async () => {
 const first = 'FIRST_RESOLVE';
 resetPage();
 const articleA = {
  article_id: 'A', source: 'pubmed', starred: true,
  access: { state: 'none_listed' },
 };
 const articleB = {
  article_id: 'B', source: 'crossref', starred: true,
  access: { state: 'none_listed' },
 };
 const cardA = makeCard('A', 'pubmed', { starred: true });
 const cardB = makeCard('B', 'crossref', { starred: false });
 cards.push(cardA, cardB);
 const load = vm.runInContext('loadOtherCopiesForResults', sandbox);
 const pageReq = load([articleA]);
 assert.equal(pending.length, 1);
 cardB.children['.star-btn'].classList.add('is-starred');
 const starReq = load([articleB]);
 assert.equal(pending.length, 2);
 const payloadA = {
  articles: [{
   article_id: 'A', source: 'pubmed',
   copies: [{ where: 'PMC', url: 'https://pmc.example/A', open_listed: true }],
  }],
 };
 const payloadB = {
  articles: [{
   article_id: 'B', source: 'crossref',
   copies: [{ where: 'Zenodo', url: 'https://zenodo.org/B', open_listed: true }],
  }],
 };
 if (first === 'star') {
  pending[1].resolve(payloadB);
  await starReq;
  pending[0].resolve(payloadA);
  await pageReq;
 } else {
  pending[0].resolve(payloadA);
  await pageReq;
  pending[1].resolve(payloadB);
  await starReq;
 }
 assert.deepEqual(mountedUrls('A', 'pubmed'), ['https://pmc.example/A']);
 assert.deepEqual(mountedUrls('B', 'crossref'), ['https://zenodo.org/B']);
 console.log('other-copies-js-complete');
})().catch((err) => { console.error(err); process.exit(1); });
"""
