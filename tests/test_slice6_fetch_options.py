"""Run Simple fetch option handling through the real dialog resolver and fetch handler."""

from __future__ import annotations

import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_simple_fetch_options_apply_on_confirm_and_stay_unchanged_on_cancel():
    node = subprocess.run(
        ["node", "-e", _HARNESS],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert node.returncode == 0, node.stderr + node.stdout


_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const simple = fs.readFileSync('static/js/simple_tools.js', 'utf8');
const data = fs.readFileSync('static/js/collect.js', 'utf8');

function extractFn(src, name) {
 const marker = 'async function ' + name;
 const start = src.indexOf(marker);
 if (start < 0) throw new Error('missing ' + name);
 let i = src.indexOf('{', start); let depth = 0;
 for (; i < src.length; i++) {
  if (src[i] === '{') depth++;
  else if (src[i] === '}' && --depth === 0) return src.slice(start, i + 1);
 }
 throw new Error('unbalanced ' + name);
}

class Element {
 constructor(value = '', tag = 'div') {
  this.value = value; this.checked = false; this.hidden = false;
  this.disabled = false; this.textContent = ''; this.listeners = {};
  this.style = {}; this.children = []; this.className = ''; this.tag = tag;
  this.changeEvents = 0;
 }
 addEventListener(type, fn) { this.listeners[type] = fn; }
 dispatchEvent(event) {
  if (event.type === 'change') this.changeEvents++;
  this.listeners[event.type]?.(event);
 }
 append(...nodes) { this.children.push(...nodes); }
 querySelectorAll(selector) {
  if (selector === 'input[type="checkbox"]:checked') return (this.modalInputs || []).filter((el) => el.checked);
  if (selector === 'input[type="checkbox"]') return this.modalInputs || [];
  return [];
 }
}

async function run(cancel) {
 const boxes = ['pubmed', 'europepmc', 'arxiv'].map((id) => {
  const box = new Element(id); box.checked = id === 'pubmed';
  const card = {
   querySelector(selector) {
    if (selector === '.source-name-label') return {textContent: id};
    if (selector === '.source-desc') return {textContent: id === 'arxiv' ? 'Physics preprints' : 'Biomedical'};
    return null;
   },
  };
  box.closest = () => card;
  return box;
 });
 const modalInputs = [];
 const fieldsRoot = new Element();
 const sourcesField = new Element();
 sourcesField.modalInputs = modalInputs;
 const emailField = new Element(); emailField.hidden = false;
 const root = {
  querySelector(selector) {
   if (selector === '.lra-modal-fields') return fieldsRoot;
   if (selector === '[data-field="sources"]') return sourcesField;
   if (selector === '[data-field="contact_email"]') return emailField;
   return null;
  },
 };
 const controls = {
  'fetch-query': new Element('sleep and school'),
  'fetch-email': new Element('remembered@school.edu'),
  'fetch-max': new Element('100'),
  'fetch-btn': new Element(),
  'fetch-cancel-btn': new Element(),
 };
 const mode = new Element('replace'); mode.checked = true;
 const requests = []; const notifications = []; const saved = [];
 const sandbox = {
  console, Event, window: {}, selectedTopics: new Set(['health']),
  _lastTotalArticles: 0, _simpleFetchModePicked: false,
  FETCH_COUNT_PRESETS: [25, 50, 100, 200],
  document: {
   getElementById: (id) => controls[id] || null,
   querySelector(selector) {
    if (selector.includes('fetch-mode')) return mode;
    return null;
   },
   querySelectorAll(selector) {
    if (selector.includes('#source-option-grid')) {
     return selector.includes(':checked') ? boxes.filter((box) => box.checked) : boxes;
    }
    if (selector.includes('fetch-mode')) return [mode];
    return [];
   },
   createElement: (tag) => new Element('', tag),
  },
  isSimpleMode: () => true,
  isSimpleFetchLocked: () => false,
  apiCall: async (path, options = {}) => {
   requests.push({path, options});
   if (path === '/api/statistics') return {total_articles: 0};
   if (path === '/api/fetch-articles-multi') return {total_fetched: 0, by_source: {}};
   throw new Error('unexpected request ' + path);
  },
  openSiteForm: async (form) => {
   const sourceFieldDef = form.fields.find((field) => field.id === 'sources');
   const emailFieldDef = form.fields.find((field) => field.id === 'contact_email');
   assert.equal(sourceFieldDef.type, 'multi-choice');
   assert.equal(JSON.stringify(sourceFieldDef.value), '["pubmed"]');
   assert.equal(JSON.stringify(sourceFieldDef.options.map((option) => option.value)), '["pubmed","europepmc","arxiv"]');
   assert.equal(emailFieldDef.value, 'remembered@school.edu');
   assert.ok(form.validate({count: '100', custom: '', sources: []}));

   for (const option of sourceFieldDef.options) {
    const input = new Element(option.value);
    input.checked = sourceFieldDef.value.includes(option.value);
    modalInputs.push(input);
   }
   form.onReady(root);
   const disclosure = fieldsRoot.children.at(-1);
   assert.equal(disclosure.tag, 'details');
   assert.equal(disclosure.id, 'simple-fetch-databases');
   assert.equal(disclosure.className, 'advanced-details lra-modal-choice');
   assert.equal(disclosure.open, undefined);
   assert.equal(disclosure.children[0].textContent, 'Databases');
   assert.equal(emailField.hidden, false);
   modalInputs.find((input) => input.value === 'pubmed').checked = false;
   modalInputs.find((input) => input.value === 'pubmed').dispatchEvent({type: 'change'});
   assert.equal(emailField.hidden, true);
   const europe = modalInputs.find((input) => input.value === 'europepmc');
   europe.checked = true;
   europe.dispatchEvent({type: 'change'});
   assert.equal(emailField.hidden, false);

   if (cancel) return null;
   return {count: '100', custom: '', sources: ['arxiv'], contact_email: ''};
  },
  setNextStepVisible() {}, syncOnlyMissingFromFetchMode() {},
  showNotification: (...args) => notifications.push(args),
  setSimpleScreenSkipped() {}, clearSimpleScreenUndoItems() {},
  updatePrepareSectionVisibility() {}, refreshSimpleScreeningCard() {},
  setLoading() {}, setStatus() {}, applyFetchResult() {},
  hideSimpleBuffering() {}, saveFetchPrefs: () => saved.push({
   sources: boxes.filter((box) => box.checked).map((box) => box.value),
   email: controls['fetch-email'].value,
  }),
  withPageLibrary: (body) => body,
  // Area picker (Laya switch): topics are already selected here, so these stay idle.
  pickAreasFromTopic: async () => false, openAreaPicker() {}, sendAreaFeedback() {},
 };
 vm.runInNewContext(
  extractFn(simple, 'resolveSimpleFetchModeBeforeRequest') + '\n' +
  extractFn(data, 'doFetch'), sandbox,
 );
 await vm.runInNewContext('doFetch()', sandbox);

 if (cancel) {
  assert.deepEqual(requests.map((request) => request.path), ['/api/statistics']);
  assert.deepEqual(boxes.filter((box) => box.checked).map((box) => box.value), ['pubmed']);
  assert.equal(controls['fetch-email'].value, 'remembered@school.edu');
  assert.equal(saved.length, 0);
 } else {
  const fetchRequest = requests.find((request) => request.path === '/api/fetch-articles-multi');
  assert.ok(fetchRequest);
  assert.equal(JSON.stringify(fetchRequest.options.body.sources), '["arxiv"]');
  assert.equal(fetchRequest.options.body.email, null);
  assert.deepEqual(boxes.filter((box) => box.checked).map((box) => box.value), ['arxiv']);
  assert.equal(controls['fetch-email'].value, '');
  assert.ok(boxes.every((box) => box.changeEvents === 1));
  assert.ok(saved.length > 0);
 }
}

(async () => { await run(false); await run(true); })().catch((err) => {
 console.error(err); process.exitCode = 1;
});
"""
