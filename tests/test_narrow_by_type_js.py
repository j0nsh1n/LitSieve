"""Narrow it down optional type rows: count, Keep, and apply keys agree."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_optional_type_selection_count_and_apply_keys_agree():
    result = subprocess.run(
        ["node", "-e", _HARNESS],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "narrow-by-type-js-complete" in result.stdout


_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

class Element {
 constructor(tag = 'div') {
  this.tagName = String(tag).toUpperCase();
  this.id = '';
  this.name = '';
  this.type = '';
  this.value = '';
  this.checked = false;
  this.disabled = false;
  this.hidden = false;
  this._text = '';
  this.childNodes = [];
  this.parentNode = null;
  this.dataset = {};
  this.attributes = {};
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
 get textContent() {
  const kids = this.childNodes.map((n) => n.textContent || '').join('');
  return this._text + kids;
 }
 set textContent(value) {
  this._text = String(value);
  this.childNodes = [];
 }
 setAttribute(name, value) {
  this.attributes[name] = String(value);
  if (name.startsWith('data-')) {
   const key = name.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
   this.dataset[key] = String(value);
  }
 }
 getAttribute(name) {
  if (Object.prototype.hasOwnProperty.call(this.attributes, name)) return this.attributes[name];
  if (name.startsWith('data-')) {
   const key = name.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
   if (Object.prototype.hasOwnProperty.call(this.dataset, key)) return this.dataset[key];
  }
  return null;
 }
 hasAttribute(name) { return this.getAttribute(name) != null; }
 addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
 dispatchEvent(event) {
  const type = event && event.type ? event.type : event;
  for (const fn of this._listeners[type] || []) fn(event && event.type ? event : { type });
 }
 matches(sel) {
  if (!sel) return false;
  let rest = sel;
  let wantChecked = false;
  if (rest.endsWith(':checked')) {
   wantChecked = true;
   rest = rest.slice(0, -8);
  }
  let ok = false;
  if (rest.startsWith('.')) ok = this.classList.contains(rest.slice(1));
  else if (rest.startsWith('#')) ok = this.id === rest.slice(1);
  else if (rest.startsWith('[') && rest.endsWith(']')) {
   ok = this._attrSel(rest.slice(1, -1));
  } else {
   const tagEnd = rest.search(/[.#\[]/);
   const tag = (tagEnd < 0 ? rest : rest.slice(0, tagEnd)).toUpperCase();
   ok = !tag || this.tagName === tag;
   const attr = rest.match(/\[([^\]]+)\]/);
   if (ok && attr) ok = this._attrSel(attr[1]);
  }
  if (ok && wantChecked) ok = !!this.checked;
  return ok;
 }
 _attrSel(body) {
  const eq = body.indexOf('=');
  if (eq < 0) {
   if (body.startsWith('data-')) {
    const key = body.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    return Object.prototype.hasOwnProperty.call(this.dataset, key) || this.hasAttribute(body);
   }
   return this.hasAttribute(body);
  }
  const attr = body.slice(0, eq);
  const want = body.slice(eq + 1).replace(/^["']|["']$/g, '');
  if (attr === 'name') return this.name === want;
  return this.getAttribute(attr) === want;
 }
 querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
 querySelectorAll(sel) {
  const out = [];
  const visit = (node) => {
   if (node.matches && node.matches(sel)) out.push(node);
   for (const child of node.childNodes || []) visit(child);
  };
  visit(this);
  return out;
 }
 appendChild(node) {
  node.parentNode = this;
  this.childNodes.push(node);
  return node;
 }
 focus() {}
 scrollIntoView() {}
}

const body = new Element('body');
const els = {};
function byId(tag, id) {
 const el = new Element(tag);
 el.id = id;
 els[id] = el;
 body.appendChild(el);
 return el;
}

const queryEl = byId('input', 'simple-screen-query');
queryEl.value = 'How do school start times affect sleep?';
const level = byId('input', 'simple-screen-level-medium');
level.name = 'simple-screen-level';
level.type = 'radio';
level.value = 'medium';
level.checked = true;
level.setAttribute('name', 'simple-screen-level');
byId('ul', 'screen-triage-go-rows');
byId('ul', 'screen-triage-stay-rows');
byId('h3', 'screen-triage-go-heading');
byId('h3', 'screen-triage-stay-heading');
const applyBtn = byId('button', 'screen-triage-apply-btn');
byId('p', 'screen-triage-lead');
byId('div', 'screen-triage-detail-body');
byId('button', 'screen-triage-keep-btn');
byId('button', 'screen-triage-aside-btn');
const preview = byId('div', 'simple-screen-preview');
preview.hidden = false;

function makeAlsoTypes() {
 const label = new Element('label');
 label.setAttribute('data-simple-screen-also-types-label', '');
 const box = new Element('input');
 box.type = 'checkbox';
 box.checked = false;
 box.setAttribute('data-simple-screen-also-types', '');
 const text = new Element('span');
 text.setAttribute('data-simple-screen-also-types-text', '');
 label.appendChild(box);
 label.appendChild(text);
 body.appendChild(label);
 return box;
}
const boxModal = makeAlsoTypes();
makeAlsoTypes();

const documentRef = {
 body,
 getElementById: (id) => els[id] || null,
 querySelector(sel) { return this.querySelectorAll(sel)[0] || null; },
 querySelectorAll(sel) { return body.querySelectorAll(sel); },
 createElement: (tag) => new Element(tag),
 addEventListener() {},
 removeEventListener() {},
};

const paper = (article_id, title, extra) => Object.assign({
 article_id, source: 'pubmed', title, abstract: 'abs', journal: 'J', year: '2020', authors: [],
}, extra || {});

const candidate = paper('ja', 'Sleep in teens');
const otherStay = paper('nulltype', 'Untyped sleep paper');
const review = paper('review', 'A book review', { work_type: 'book-review' });
const trial = paper('trial', 'NCT sleep trial', { work_type: 'registry-record' });
const data = {
 candidates: [candidate],
 staying: [otherStay, review, trial],
 optional_type_aside: [review, trial],
 proposed_count: 1,
 total_ranked: 4,
};

const sandbox = {
 console,
 assert,
 document: documentRef,
 window: {},
 localStorage: { getItem: () => null, setItem() {} },
 location: { href: 'http://localhost/search' },
 history: { replaceState() {} },
 setTimeout: (fn) => fn(),
 URL,
 getSourceName: (s) => s,
 showNotification() {},
 setStatus() {},
 setLoading() {},
 apiCall: async () => ({}),
 withPageLibrary: (b) => b,
};
sandbox.window = sandbox;
sandbox.global = sandbox;
sandbox.candidate = candidate;
sandbox.otherStay = otherStay;
sandbox.review = review;
sandbox.trial = trial;
sandbox.data = data;
sandbox.boxModal = boxModal;

const tools = fs.readFileSync('static/js/simple_tools.js', 'utf8');
vm.runInNewContext(tools + `
function rowKeys(id) {
 return Array.from(document.getElementById(id).childNodes)
  .map((li) => {
   const btn = (li.childNodes || []).find((n) => n.classList && n.classList.contains('screen-triage-row'));
   return btn && btn.dataset.key;
  })
  .filter(Boolean)
  .map((k) => k.split('::')[0]);
}
function snapshot() {
 const apply = document.getElementById('screen-triage-apply-btn');
 const items = _simpleScreenApplyItems(data).map((it) => it.article_id);
 const go = rowKeys('screen-triage-go-rows');
 const n = items.length;
 assert.equal(apply.textContent, 'Set aside ' + n + ' paper' + (n === 1 ? '' : 's'));
 assert.equal(!!apply.disabled, n <= 0);
 assert.deepEqual(go, items);
 assert.equal(document.getElementById('screen-triage-go-heading').textContent, 'Would go (' + n + ')');
 return {
  label: apply.textContent,
  disabled: !!apply.disabled,
  goHeading: document.getElementById('screen-triage-go-heading').textContent,
  stayHeading: document.getElementById('screen-triage-stay-heading').textContent,
  go,
  stay: rowKeys('screen-triage-stay-rows'),
  items,
 };
}
function seedPreview() {
 _simpleScreenCounts = { low: null, medium: data, high: null, _query: simpleScreenQuery() };
 _simpleTriageGo = [candidate];
 _simpleTriageStay = [otherStay, review, trial];
 _simpleTriageKeptKeys = new Set();
 _simpleTriageAsideKeys = new Set();
 _simpleTriageUsed = true;
 _simpleTriageLevel = 'medium';
 _simpleTriageQuery = simpleScreenQuery();
 _simpleTriageKey = _screenPaperKey(candidate);
 boxModal.checked = false;
 document.querySelectorAll('[data-simple-screen-also-types]').forEach((el) => { el.checked = false; });
 renderScreenTriage();
}
function setAlsoTypes(on) {
 boxModal.checked = !!on;
 boxModal.dispatchEvent({ type: 'change' });
}

wireSimpleScreenAlsoTypes();
seedPreview();

let s = snapshot();
assert.equal(s.label, 'Set aside 1 paper');
assert.equal(s.disabled, false);
assert.deepEqual(s.go, ['ja']);
assert.deepEqual(s.items, ['ja']);
assert.ok(s.stay.includes('review') && s.stay.includes('trial'));

_simpleTriageKey = _screenPaperKey(candidate);
moveScreenTriagePaper('stay');
s = snapshot();
assert.equal(s.label, 'Set aside 0 papers');
assert.equal(s.disabled, true);
assert.deepEqual(s.items, []);

setAlsoTypes(true);
s = snapshot();
assert.equal(s.label, 'Set aside 2 papers');
assert.equal(s.disabled, false);
assert.deepEqual(s.go.sort(), ['review', 'trial']);
assert.deepEqual(s.items.sort(), ['review', 'trial']);
assert.ok(s.stay.includes('ja'));
assert.ok(!s.go.includes('ja'));
assert.equal(s.goHeading, 'Would go (2)');

seedPreview();
setAlsoTypes(true);
s = snapshot();
assert.equal(s.label, 'Set aside 3 papers');
assert.equal(s.disabled, false);
assert.deepEqual(s.go, ['ja', 'review', 'trial']);
assert.deepEqual(s.items, ['ja', 'review', 'trial']);
assert.equal(s.goHeading, 'Would go (3)');
assert.ok(s.stay.includes('nulltype'));
assert.ok(!s.stay.includes('review'));
assert.ok(!s.stay.includes('trial'));

_simpleTriageKey = _screenPaperKey(review);
moveScreenTriagePaper('stay');
s = snapshot();
assert.equal(s.label, 'Set aside 2 papers');
assert.deepEqual(s.items.sort(), ['ja', 'trial']);
assert.ok(s.stay.includes('review'));
assert.ok(!s.items.includes('review'));

setAlsoTypes(false);
s = snapshot();
assert.equal(s.label, 'Set aside 1 paper');
assert.deepEqual(s.items, ['ja']);
assert.ok(s.stay.includes('review') && s.stay.includes('trial'));
assert.ok(!s.go.includes('review') && !s.go.includes('trial'));

seedPreview();
setAlsoTypes(true);
_simpleTriageKey = _screenPaperKey(trial);
moveScreenTriagePaper('stay');
s = snapshot();
assert.ok(!s.items.includes('trial'));
setAlsoTypes(false);
s = snapshot();
assert.deepEqual(s.items, ['ja']);
assert.ok(!s.items.includes('trial'));

console.log('narrow-by-type-js-complete');
`, sandbox);
"""
