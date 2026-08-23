// Operator workbench. Named actions only; common.js provides apiCall.

document.addEventListener('DOMContentLoaded', () => {
 loadStatus();
 loadTree();
 loadDiff();
 renderTabs();
 bind('ops-reauth', reauth);
 bind('ops-lock', lockNow);
 bind('ops-sb-lock', () => { isUnlocked() ? lockNow() : reauth(); });
 bind('ops-theme', () => document.getElementById('theme-toggle')?.click());
 bind('ops-panel-toggle', togglePanel);
 const ttlSel = document.getElementById('ops-ttl');
 if (ttlSel) {
  const saved = localStorage.getItem('opsUnlockMinutes');
  if (saved && [...ttlSel.options].some((o) => o.value === saved)) ttlSel.value = saved;
  ttlSel.addEventListener('change', () => {
   localStorage.setItem('opsUnlockMinutes', ttlSel.value);
  });
 }
 bind('ops-save', saveFile);
 bind('ops-validate', () => { showPane('check'); expandPanel(); validate(); });
 bind('ops-commit', commit);
 bind('ops-deploy', deploy);
 bind('ops-revert', revertLast);
 bind('ops-grok-ask', askGrok);
 bind('ops-grok-copy', copyTui);
 const editor = document.getElementById('ops-editor');
 if (editor) {
  editor.addEventListener('keydown', onEditorKey);
  editor.addEventListener('input', onEditorInput);
  editor.addEventListener('scroll', syncGutterScroll);
  editor.addEventListener('click', paintCursor);
  editor.addEventListener('keyup', paintCursor);
 }
 const commitBox = document.getElementById('ops-message');
 if (commitBox) {
  commitBox.addEventListener('keydown', (ev) => {
   if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
    ev.preventDefault();
    commit();
   }
  });
 }
 const grokPrompt = document.getElementById('ops-grok-prompt');
 if (grokPrompt) {
  grokPrompt.addEventListener('keydown', (ev) => {
   if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
    ev.preventDefault();
    askGrok();
   }
  });
 }
 const filter = document.getElementById('ops-filter');
 if (filter) filter.addEventListener('input', () => renderTree(_files));
 document.querySelectorAll('.ops-activity-btn').forEach((btn) => {
  btn.addEventListener('click', () => showSide(btn.getAttribute('data-side')));
 });
 document.querySelectorAll('.ops-panel [data-pane]').forEach((btn) => {
  btn.addEventListener('click', () => { expandPanel(); showPane(btn.getAttribute('data-pane')); });
 });
 document.addEventListener('keydown', onWorkbenchKey);
});

let _path = '';
let _tabs = [];
let _status = {};
let _files = [];
let _tui = '';
let _lockTimer = 0;
let _busy = '';

function bind(id, fn) {
 const el = document.getElementById(id);
 if (el) el.addEventListener('click', fn);
}

function onWorkbenchKey(ev) {
 if (!(ev.ctrlKey || ev.metaKey)) return;
 const tag = (ev.target && ev.target.tagName) || '';
 if (ev.key === 'b' || ev.key === 'B') {
  ev.preventDefault();
  document.querySelector('.ops-ide')?.classList.toggle('is-side-open');
 }
 if (ev.key === 'j' || ev.key === 'J') {
  ev.preventDefault();
  togglePanel();
 }
 if (ev.key === 's' || ev.key === 'S') {
  if (tag === 'TEXTAREA' || tag === 'INPUT') return;
  ev.preventDefault();
  saveFile();
 }
}

function onEditorKey(ev) {
 if ((ev.ctrlKey || ev.metaKey) && (ev.key === 's' || ev.key === 'S')) {
  ev.preventDefault();
  saveFile();
  return;
 }
 if (ev.key === 'Tab') {
  ev.preventDefault();
  const el = ev.target;
  const start = el.selectionStart;
  const end = el.selectionEnd;
  el.value = el.value.slice(0, start) + '\t' + el.value.slice(end);
  el.selectionStart = el.selectionEnd = start + 1;
  onEditorInput();
 }
}

function onEditorInput() {
 flushEditorToTab();
 paintGutter();
 paintHighlight();
 paintCursor();
 renderTabs();
}

function paintGutter() {
 const editor = document.getElementById('ops-editor');
 const gutter = document.getElementById('ops-gutter');
 if (!editor || !gutter) return;
 const n = (editor.value.match(/\n/g) || []).length + 1;
 const from = gutter.dataset.lines | 0;
 if (from === n) {
  syncGutterScroll();
  return;
 }
 gutter.dataset.lines = String(n);
 gutter.textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n');
 syncGutterScroll();
}

function syncGutterScroll() {
 const editor = document.getElementById('ops-editor');
 const gutter = document.getElementById('ops-gutter');
 const hl = document.getElementById('ops-hl');
 if (editor && gutter) gutter.scrollTop = editor.scrollTop;
 if (editor && hl) {
  hl.scrollTop = editor.scrollTop;
  hl.scrollLeft = editor.scrollLeft;
 }
}

function paintCursor() {
 const editor = document.getElementById('ops-editor');
 const out = document.getElementById('ops-sb-cursor');
 if (!editor || !out || editor.disabled) {
  if (out) out.textContent = 'Ln 1, Col 1';
  return;
 }
 const pos = editor.selectionStart || 0;
 const toCursor = editor.value.slice(0, pos);
 const lines = toCursor.split('\n');
 out.textContent = `Ln ${lines.length}, Col ${lines[lines.length - 1].length + 1}`;
}

function isPyPath(path) {
 return /\.(py|pyw|pyi)$/i.test(path || '');
}

function setHighlightMode(path) {
 const wrap = document.getElementById('ops-editor-wrap');
 if (wrap) wrap.classList.toggle('is-py', isPyPath(path));
}

function paintHighlight() {
 const editor = document.getElementById('ops-editor');
 const hl = document.getElementById('ops-hl');
 if (!editor || !hl) return;
 if (!isPyPath(_path) || editor.disabled) {
  hl.textContent = '';
  return;
 }
 hl.innerHTML = highlightPython(editor.value) + '\n';
 syncGutterScroll();
}

const PY_FLOW = {
 if: 1, else: 1, elif: 1, for: 1, while: 1, break: 1, continue: 1,
 return: 1, yield: 1, try: 1, except: 1, finally: 1, raise: 1, with: 1,
 assert: 1, pass: 1, match: 1, case: 1,
};
const PY_KW = {
 def: 1, class: 1, import: 1, from: 1, as: 1, lambda: 1, and: 1, or: 1,
 not: 1, in: 1, is: 1, async: 1, await: 1, global: 1, nonlocal: 1, del: 1,
 True: 1, False: 1, None: 1,
};
const PY_BI = {
 abs: 1, all: 1, any: 1, ascii: 1, bin: 1, bool: 1, bytearray: 1, bytes: 1,
 callable: 1, chr: 1, classmethod: 1, compile: 1, complex: 1, dict: 1, dir: 1,
 divmod: 1, enumerate: 1, eval: 1, exec: 1, filter: 1, float: 1, format: 1,
 frozenset: 1, getattr: 1, globals: 1, hasattr: 1, hash: 1, help: 1, hex: 1,
 id: 1, input: 1, int: 1, isinstance: 1, issubclass: 1, iter: 1, len: 1,
 list: 1, locals: 1, map: 1, max: 1, memoryview: 1, min: 1, next: 1, object: 1,
 oct: 1, open: 1, ord: 1, pow: 1, print: 1, property: 1, range: 1, repr: 1,
 reversed: 1, round: 1, set: 1, setattr: 1, slice: 1, sorted: 1,
 staticmethod: 1, str: 1, sum: 1, super: 1, tuple: 1, type: 1, vars: 1, zip: 1,
 Exception: 1, ValueError: 1, TypeError: 1, KeyError: 1, IndexError: 1,
 AttributeError: 1, RuntimeError: 1, StopIteration: 1, NotImplementedError: 1,
 OSError: 1, FileNotFoundError: 1, ImportError: 1, NameError: 1,
};

function pySpan(kind, text) {
 return '<span class="tok-' + kind + '">' + escapeHtml(text) + '</span>';
}

function highlightPython(src) {
 if (!src) return '';
 if (src.length > 400000) return escapeHtml(src);
 let out = '';
 let i = 0;
 const n = src.length;
 let expect = '';

 while (i < n) {
  const ch = src.charAt(i);
  if (ch === '#') {
   let j = i;
   while (j < n && src.charAt(j) !== '\n') j += 1;
   out += pySpan('com', src.slice(i, j));
   i = j;
   continue;
  }
  if (ch === '@' && pyDecoratorHere(src, i)) {
   let j = i + 1;
   while (j < n && /[A-Za-z0-9_.]/.test(src.charAt(j))) j += 1;
   out += pySpan('dec', src.slice(i, j));
   i = j;
   expect = '';
   continue;
  }
  const strStart = pyStringStart(src, i);
  if (strStart) {
   const taken = pyTakeString(src, i, strStart);
   out += taken.html;
   i = taken.next;
   expect = '';
   continue;
  }
  if (/[0-9]/.test(ch) || (ch === '.' && i + 1 < n && /[0-9]/.test(src.charAt(i + 1)))) {
   let j = i;
   if (src.charAt(j) === '0' && j + 1 < n && 'xXoObB'.indexOf(src.charAt(j + 1)) !== -1) {
    j += 2;
    while (j < n && /[0-9A-Fa-f_]/.test(src.charAt(j))) j += 1;
   } else {
    while (j < n && /[0-9_]/.test(src.charAt(j))) j += 1;
    if (j < n && src.charAt(j) === '.') {
     j += 1;
     while (j < n && /[0-9_]/.test(src.charAt(j))) j += 1;
    }
    if (j < n && (src.charAt(j) === 'e' || src.charAt(j) === 'E')) {
     j += 1;
     if (j < n && (src.charAt(j) === '+' || src.charAt(j) === '-')) j += 1;
     while (j < n && /[0-9_]/.test(src.charAt(j))) j += 1;
    }
    if (j < n && (src.charAt(j) === 'j' || src.charAt(j) === 'J')) j += 1;
   }
   out += pySpan('num', src.slice(i, j));
   i = j;
   expect = '';
   continue;
  }
  if (/[A-Za-z_]/.test(ch)) {
   let j = i + 1;
   while (j < n && /[A-Za-z0-9_]/.test(src.charAt(j))) j += 1;
   const id = src.slice(i, j);
   let kind = '';
   if (expect === 'fn') kind = 'fn';
   else if (expect === 'cls') kind = 'cls';
   else if (PY_FLOW[id]) kind = 'flow';
   else if (PY_KW[id]) kind = 'kw';
   else if (id === 'self' || id === 'cls') kind = 'kw';
   else if (PY_BI[id]) kind = 'bi';
   out += kind ? pySpan(kind, id) : escapeHtml(id);
   if (id === 'def') expect = 'fn';
   else if (id === 'class') expect = 'cls';
   else if (id === 'async') expect = expect;
   else expect = '';
   i = j;
   continue;
  }
  out += escapeHtml(ch);
  if (!/\s/.test(ch) && ch !== ':') expect = '';
  i += 1;
 }
 return out;
}

function pyDecoratorHere(src, i) {
 let k = i - 1;
 while (k >= 0 && (src.charAt(k) === ' ' || src.charAt(k) === '\t')) k -= 1;
 return k < 0 || src.charAt(k) === '\n';
}

function pyStringStart(src, i) {
 const rest = src.slice(i, i + 5);
 const m = rest.match(/^([rRuUfFbB]{0,2})('''|"""|'|")/);
 if (!m) return null;
 const pref = (m[1] || '').toLowerCase();
 if (pref.length === 2 && !{ rf: 1, fr: 1, rb: 1, br: 1 }[pref]) return null;
 if (pref.length === 1 && 'rfub'.indexOf(pref) === -1) return null;
 return { prefix: m[1] || '', quote: m[2], f: pref.indexOf('f') !== -1 };
}

function pyTakeString(src, i, start) {
 const q = start.quote;
 const open = start.prefix + q;
 let j = i + open.length;
 const n = src.length;
 let html = pySpan('str', open);
 while (j < n) {
  if (start.f && src.charAt(j) === '{') {
   if (src.charAt(j + 1) === '{') {
    html += pySpan('str', '{{');
    j += 2;
    continue;
   }
   const inner = pyTakeFExpr(src, j);
   html += inner.html;
   j = inner.next;
   continue;
  }
  if (start.f && src.charAt(j) === '}' && src.charAt(j + 1) === '}') {
   html += pySpan('str', '}}');
   j += 2;
   continue;
  }
  if (src.slice(j, j + q.length) === q) {
   html += pySpan('str', q);
   j += q.length;
   return { html: html, next: j };
  }
  if (src.charAt(j) === '\\' && q.length === 1) {
   html += pySpan('str', src.slice(j, j + 2));
   j += 2;
   continue;
  }
  let k = j + 1;
  while (k < n) {
   const c = src.charAt(k);
   if (c === '\\' && q.length === 1) break;
   if (c === q.charAt(0) && src.slice(k, k + q.length) === q) break;
   if (start.f && c === '{') break;
   k += 1;
  }
  html += pySpan('str', src.slice(j, k));
  j = k;
 }
 return { html: html, next: j };
}

function pyTakeFExpr(src, i) {
 const n = src.length;
 let depth = 0;
 let j = i;
 while (j < n) {
  const c = src.charAt(j);
  if (c === '{') {
   depth += 1;
   j += 1;
   continue;
  }
  if (c === '}') {
   depth -= 1;
   j += 1;
   if (depth === 0) break;
   continue;
  }
  const st = pyStringStart(src, j);
  if (st) {
   const taken = pyTakeString(src, j, st);
   j = taken.next;
   continue;
  }
  if (c === '#') {
   while (j < n && src.charAt(j) !== '\n') j += 1;
   continue;
  }
  j += 1;
 }
 const body = src.slice(i + 1, j - (src.charAt(j - 1) === '}' ? 1 : 0));
 return {
  html: pySpan('kw', '{') + highlightPython(body) + pySpan('kw', '}'),
  next: j,
 };
}

function showSide(name) {
 document.querySelectorAll('.ops-activity-btn').forEach((btn) => {
  btn.classList.toggle('is-on', btn.getAttribute('data-side') === name);
 });
 document.querySelectorAll('.ops-side').forEach((pane) => {
  const on = pane.id === 'ops-side-' + name;
  pane.hidden = !on;
  pane.classList.toggle('is-on', on);
 });
 document.querySelector('.ops-ide')?.classList.add('is-side-open');
}

function showPane(name) {
 document.querySelectorAll('.ops-panel [data-pane]').forEach((btn) => {
  btn.classList.toggle('is-on', btn.getAttribute('data-pane') === name);
 });
 document.querySelectorAll('.ops-panel .ops-pane').forEach((pane) => {
  const on = pane.id === 'ops-pane-' + name;
  pane.hidden = !on;
  pane.classList.toggle('is-on', on);
 });
}

function togglePanel() {
 document.getElementById('ops-panel')?.classList.toggle('is-collapsed');
}

function expandPanel() {
 document.getElementById('ops-panel')?.classList.remove('is-collapsed');
}

function shortSha(sha) {
 return (sha || '—').slice(0, 8);
}

function appendOutput(line) {
 const pre = document.getElementById('ops-output');
 if (!pre) return;
 const prev = pre.textContent === 'Ship output appears here.' ? '' : (pre.textContent || '');
 const stamp = new Date().toISOString().slice(11, 19);
 pre.textContent = (prev ? prev + '\n' : '') + stamp + '  ' + line;
 pre.scrollTop = pre.scrollHeight;
}

async function loadStatus() {
 const line = document.getElementById('ops-status-line');
 const pill = document.getElementById('ops-grok-pill');
 try {
  _status = await apiCall('/api/ops/status');
  paintLockUi();
  tickLockClock();
  paintStatusLine();
  const grok = _status.grok || {};
  _tui = grok.tui_command || '';
  if (pill) {
   pill.textContent = grok.connected
    ? (grok.version || 'Grok CLI')
    : 'Grok off';
   pill.classList.toggle('is-on', !!grok.connected);
   pill.title = grok.binary || '';
  }
  const hint = document.getElementById('ops-grok-hint');
  if (hint) {
   hint.textContent = grok.connected
    ? `Connected to this desktop CLI (${grok.version || 'grok'}). Asks run on staging. Open the same chat in a terminal with Copy TUI.`
    : (grok.detail || 'Grok Build CLI is not installed on this host.');
  }
  renderHistory(_status.history || []);
 } catch (e) {
  if (line) line.textContent = e.message || 'Could not load status.';
 }
}

function paintStatusLine() {
 const line = document.getElementById('ops-status-line');
 if (!line) return;
 line.textContent = `staging ${shortSha(_status.staging_sha)}`
  + (_status.dirty ? '  ●' : '  clean')
  + `  live ${shortSha(_status.live_sha)}`;
}

async function loadTree() {
 const box = document.getElementById('ops-tree');
 try {
  const data = await apiCall('/api/ops/files');
  _files = data.files || [];
  renderTree(_files);
 } catch (e) {
  if (box) box.textContent = e.message || 'Tree failed';
 }
}

function renderTree(files) {
 const box = document.getElementById('ops-tree');
 if (!box) return;
 const q = (document.getElementById('ops-filter')?.value || '').trim().toLowerCase();
 const shown = q ? files.filter((p) => p.toLowerCase().includes(q)) : files;
 if (!shown.length) {
  box.textContent = 'No matching files.';
  return;
 }
 box.innerHTML = renderNode(nest(shown), '');
 box.querySelectorAll('[data-path]').forEach((btn) => {
  btn.addEventListener('click', () => openFile(btn.getAttribute('data-path')));
 });
}

function nest(files) {
 const root = {};
 files.forEach((p) => {
  const parts = p.split('/');
  let node = root;
  parts.forEach((part, i) => {
   if (i === parts.length - 1) {
    node[part] = p;
   } else {
    if (typeof node[part] !== 'object' || node[part] === null) node[part] = {};
    node = node[part];
   }
  });
 });
 return root;
}

function renderNode(node, prefix) {
 return Object.keys(node).sort().map((key) => {
  const val = node[key];
  if (typeof val === 'string') {
   const on = val === _path ? ' is-on' : '';
   const ext = key.includes('.') ? key.split('.').pop() : '';
   return `<button type="button" class="${on}" data-path="${escapeAttr(val)}" data-ext="${escapeAttr(ext)}">${escapeHtml(key)}</button>`;
  }
  return `<details open><summary>${escapeHtml(key)}</summary>${renderNode(val, prefix + key + '/')}</details>`;
 }).join('');
}

function currentTab() {
 return _tabs.find((t) => t.path === _path) || null;
}

function flushEditorToTab() {
 const tab = currentTab();
 const editor = document.getElementById('ops-editor');
 if (!tab || !editor || editor.disabled) return;
 tab.content = editor.value;
 tab.dirty = tab.content !== tab.original;
}

function renderTabs() {
 const bar = document.getElementById('ops-tabs');
 if (!bar) return;
 if (!_tabs.length) {
  bar.innerHTML = '<span class="ops-tab-empty">No file open</span>';
  return;
 }
 bar.innerHTML = _tabs.map((tab) => {
  const on = tab.path === _path ? ' is-on' : '';
  const dirty = tab.dirty ? ' is-dirty' : '';
  const name = tab.path.split('/').pop();
  return `<button type="button" class="ops-filetab${on}${dirty}" data-tab="${escapeAttr(tab.path)}" title="${escapeAttr(tab.path)}" role="tab" aria-selected="${tab.path === _path ? 'true' : 'false'}">`
   + `<span class="ops-filetab-name">${escapeHtml(name)}</span>`
   + `<span class="ops-filetab-x" data-close="${escapeAttr(tab.path)}" title="Close">×</span>`
   + `</button>`;
 }).join('');
 bar.querySelectorAll('[data-tab]').forEach((btn) => {
  btn.addEventListener('click', (e) => {
   if (e.target.closest('[data-close]')) return;
   switchTab(btn.getAttribute('data-tab'));
  });
 });
 bar.querySelectorAll('[data-close]').forEach((btn) => {
  btn.addEventListener('click', (e) => {
   e.preventDefault();
   e.stopPropagation();
   closeTab(btn.getAttribute('data-close'));
  });
 });
}

function applyTab(tab) {
 const editor = document.getElementById('ops-editor');
 const title = document.getElementById('ops-file-title');
 const label = document.getElementById('ops-file-path');
 const save = document.getElementById('ops-save');
 const welcome = document.getElementById('ops-welcome');
 const wrap = document.getElementById('ops-editor-wrap');
 if (title) title.textContent = tab.path.split('/').pop();
 if (label) label.textContent = tab.path;
 if (editor) {
  editor.disabled = false;
  editor.value = tab.content;
  setHighlightMode(tab.path);
  paintGutter();
  paintHighlight();
  paintCursor();
  editor.focus();
 }
 if (save) save.disabled = false;
 if (welcome) welcome.hidden = true;
 if (wrap) wrap.hidden = false;
}

function showWelcome() {
 const editor = document.getElementById('ops-editor');
 const save = document.getElementById('ops-save');
 const welcome = document.getElementById('ops-welcome');
 const wrap = document.getElementById('ops-editor-wrap');
 const label = document.getElementById('ops-file-path');
 const title = document.getElementById('ops-file-title');
 _path = '';
 if (editor) {
  editor.value = '';
  editor.disabled = true;
 }
 if (save) save.disabled = true;
 if (welcome) welcome.hidden = false;
 if (wrap) {
  wrap.hidden = true;
  wrap.classList.remove('is-py');
 }
 const hl = document.getElementById('ops-hl');
 if (hl) hl.textContent = '';
 if (label) label.textContent = 'Open a file to start editing';
 if (title) title.textContent = 'untitled';
 paintCursor();
}

function switchTab(path) {
 if (path === _path) return;
 flushEditorToTab();
 const tab = _tabs.find((t) => t.path === path);
 if (!tab) {
  openFile(path);
  return;
 }
 _path = path;
 applyTab(tab);
 renderTabs();
 renderTree(_files);
}

function closeTab(path) {
 flushEditorToTab();
 const tab = _tabs.find((t) => t.path === path);
 if (tab && tab.dirty) {
  if (!window.confirm('Close ' + path.split('/').pop() + ' without saving?')) return;
 }
 _tabs = _tabs.filter((t) => t.path !== path);
 if (_path === path) {
  const next = _tabs[_tabs.length - 1];
  if (next) {
   _path = next.path;
   applyTab(next);
  } else {
   showWelcome();
  }
 }
 renderTabs();
 renderTree(_files);
}

async function openFile(path) {
 flushEditorToTab();
 const existing = _tabs.find((t) => t.path === path);
 if (existing) {
  _path = path;
  applyTab(existing);
  renderTabs();
  renderTree(_files);
  document.querySelector('.ops-ide')?.classList.remove('is-side-open');
  return;
 }
 _path = path;
 renderTree(_files);
 try {
  const data = await apiCall('/api/ops/file?path=' + encodeURIComponent(path));
  const content = data.content || '';
  const tab = { path, content, original: content, dirty: false };
  _tabs.push(tab);
  applyTab(tab);
  renderTabs();
  document.querySelector('.ops-ide')?.classList.remove('is-side-open');
 } catch (e) {
  const label = document.getElementById('ops-file-path');
  if (label) label.textContent = e.message || 'Could not read file';
 }
}

function chosenMinutes() {
 const sel = document.getElementById('ops-ttl');
 const n = parseInt(sel && sel.value, 10);
 return Number.isFinite(n) && n > 0 ? n : 10;
}

function grokHeld() {
 return _busy === 'grok' || _status.unlock_hold === 'ask_grok';
}

function isUnlocked() {
 return !!_status.reauth || grokHeld();
}

function lockLabel() {
 if (grokHeld()) {
  const until = Number(_status.reauth_until || 0);
  const left = until - Math.floor(Date.now() / 1000);
  if (left > 0 && left < 60) return `Grok · ${left}s`;
  if (left >= 60) {
   const m = Math.floor(left / 60);
   if (m < 60) return `Grok · ${m}m`;
   return `Grok · ${Math.floor(m / 60)}h`;
  }
  return 'Grok running';
 }
 if (!_status.reauth) return 'locked';
 const until = Number(_status.reauth_until || 0);
 const left = until - Math.floor(Date.now() / 1000);
 if (left <= 0) return 'locked';
 if (left < 60) return `unlocked ${left}s`;
 const m = Math.floor(left / 60);
 if (m < 60) return `unlocked ${m}m`;
 return `unlocked ${Math.floor(m / 60)}h ${m % 60}m`;
}

function paintLockUi() {
 const unlockBtn = document.getElementById('ops-reauth');
 const lockBtn = document.getElementById('ops-lock');
 const sb = document.getElementById('ops-sb-lock');
 const bar = document.querySelector('.ops-statusbar');
 const open = isUnlocked();
 if (unlockBtn) unlockBtn.hidden = open;
 if (lockBtn) {
  lockBtn.hidden = !open;
  lockBtn.title = grokHeld()
   ? 'Lock now (Grok keeps running; you will need the password again after)'
   : 'Lock now';
 }
 if (sb) sb.textContent = lockLabel();
 if (bar) {
  bar.classList.toggle('is-locked', !open);
  bar.classList.toggle('is-held', grokHeld());
 }
}

function tickLockClock() {
 if (_lockTimer) clearInterval(_lockTimer);
 _lockTimer = 0;
 if (!isUnlocked()) return;
 const until = Number(_status.reauth_until || 0);
 if (until <= 0) return;
 _lockTimer = setInterval(() => {
  const left = Number(_status.reauth_until || 0) - Math.floor(Date.now() / 1000);
  if (left <= 0 && !grokHeld()) {
   clearInterval(_lockTimer);
   _lockTimer = 0;
   _status.reauth = false;
   paintLockUi();
   loadStatus();
   return;
  }
  const sb = document.getElementById('ops-sb-lock');
  if (sb) sb.textContent = lockLabel();
 }, 1000);
}

async function reauth() {
 const minutes = chosenMinutes();
 const vals = await openSiteForm({
  title: 'Unlock Ship',
  message: `Password is required before save, Grok, or deploy. Stays unlocked for ${minutes} minute${minutes === 1 ? '' : 's'} (change “Unlock for” first if you want longer).`,
  confirmLabel: 'Unlock',
  fields: [{ id: 'password', label: 'Password', type: 'password', value: '' }],
  validate: (v) => (String(v.password || '') ? null : 'Password required.'),
 });
 if (!vals) return;
 try {
  await apiCall('/api/ops/reauth', {
   method: 'POST',
   body: { password: vals.password, minutes },
  });
  showNotification(`Unlocked for ${minutes} minute${minutes === 1 ? '' : 's'}.`, 'success');
  await loadStatus();
 } catch (e) {
  showNotification(e.message || 'Unlock failed', 'error');
 }
}

async function lockNow() {
 try {
  await apiCall('/api/ops/lock', { method: 'POST', body: {} });
  showNotification('Ship locked.', 'success');
  await loadStatus();
 } catch (e) {
  showNotification(e.message || 'Lock failed', 'error');
 }
}

async function saveFile() {
 if (!_path) return;
 flushEditorToTab();
 const tab = currentTab();
 const status = document.getElementById('ops-save-status');
 try {
  await apiCall('/api/ops/file', {
   method: 'POST',
   body: { path: _path, content: tab ? tab.content : '' },
  });
  if (tab) {
   tab.original = tab.content;
   tab.dirty = false;
   renderTabs();
  }
  if (status) status.textContent = 'saved';
  appendOutput('saved ' + _path);
  await loadDiff();
  await loadStatus();
 } catch (e) {
  if (status) status.textContent = e.message || 'Save failed';
  appendOutput('save failed: ' + (e.message || 'Save failed'));
  if (/re-enter your password|unlock/i.test(e.message || '')) reauth();
 }
}

async function loadDiff() {
 const pre = document.getElementById('ops-diff');
 try {
  const data = await apiCall('/api/ops/diff');
  if (pre) pre.textContent = data.diff || data.status || '(clean)';
 } catch (e) {
  if (pre) pre.textContent = e.message || 'Diff failed';
 }
}

async function validate() {
 const pre = document.getElementById('ops-validate-out');
 if (pre) pre.textContent = 'running…';
 appendOutput('check started');
 try {
  const data = await apiCall('/api/ops/validate', { method: 'POST', body: {} });
  const lines = (data.steps || []).map((s) => `${s.name}: ${s.ok ? 'pass' : 'FAIL'}\n${s.output || ''}`);
  if (pre) pre.textContent = lines.join('\n---\n') || 'pass';
  showNotification('Checks passed.', 'success');
  appendOutput('check passed');
  await loadStatus();
 } catch (e) {
  if (pre) pre.textContent = e.message || 'Check failed';
  showNotification(e.message || 'Check failed', 'error');
  appendOutput('check failed: ' + (e.message || 'Check failed'));
 }
}

async function commit() {
 const message = (document.getElementById('ops-message')?.value || '').trim();
 const status = document.getElementById('ops-ship-status');
 if (!message) {
  showNotification('Commit message required.', 'error');
  showSide('scm');
  return;
 }
 try {
  const data = await apiCall('/api/ops/commit', { method: 'POST', body: { message } });
  if (status) status.textContent = `commit ${shortSha(data.sha)}`;
  appendOutput('commit ' + shortSha(data.sha));
  await loadDiff();
  await loadStatus();
 } catch (e) {
  if (status) status.textContent = e.message || 'Commit failed';
  appendOutput('commit failed: ' + (e.message || 'Commit failed'));
  if (/re-enter your password/i.test(e.message || '')) reauth();
 }
}

async function deploy() {
 const vals = await openSiteForm({
  title: 'Deploy live',
  message: 'Restarts the running site. Type DEPLOY to confirm.',
  confirmLabel: 'Deploy',
  fields: [{ id: 'confirm', label: 'Type DEPLOY', type: 'text', value: '' }],
  validate: (v) => (String(v.confirm || '') === 'DEPLOY' ? null : 'Type DEPLOY exactly.'),
 });
 if (!vals) return;
 const status = document.getElementById('ops-ship-status');
 try {
  const st = await apiCall('/api/ops/status');
  const data = await apiCall('/api/ops/deploy', {
   method: 'POST',
   body: { confirm: 'DEPLOY', sha: st.staging_sha },
  });
  if (status) status.textContent = `deploy ${shortSha(data.sha)}`;
  showNotification('Deployed.', 'success');
  appendOutput('deploy ' + shortSha(data.sha));
  await loadStatus();
  await loadDiff();
 } catch (e) {
  if (status) status.textContent = e.message || 'Deploy failed';
  showNotification(e.message || 'Deploy failed', 'error');
  appendOutput('deploy failed: ' + (e.message || 'Deploy failed'));
  if (/re-enter your password/i.test(e.message || '')) reauth();
 }
}

async function revertLast() {
 const status = document.getElementById('ops-ship-status');
 try {
  const data = await apiCall('/api/ops/revert-last', { method: 'POST', body: {} });
  if (status) status.textContent = `revert ${shortSha(data.sha)}`;
  appendOutput('revert ' + shortSha(data.sha));
  await loadStatus();
 } catch (e) {
  if (status) status.textContent = e.message || 'Revert failed';
  appendOutput('revert failed: ' + (e.message || 'Revert failed'));
  if (/re-enter your password/i.test(e.message || '')) reauth();
 }
}

async function askGrok() {
 if (grokHeld()) {
  showNotification('Grok is already running.', 'info');
  return;
 }
 const prompt = (document.getElementById('ops-grok-prompt')?.value || '').trim();
 const out = document.getElementById('ops-grok-out');
 if (prompt.length < 3) {
  showNotification('Type a short prompt for Grok.', 'error');
  showSide('grok');
  return;
 }
 const askBtn = document.getElementById('ops-grok-ask');
 showSide('grok');
 if (out) out.textContent = 'Grok is working on staging…';
 _busy = 'grok';
 if (askBtn) askBtn.disabled = true;
 paintLockUi();
 tickLockClock();
 try {
  const data = await apiCall('/api/ops/grok', {
   method: 'POST',
   body: { prompt, path: _path || '' },
  });
  if (out) out.textContent = data.text || 'done';
  appendOutput('grok done');
  await loadDiff();
  await loadTree();
 } catch (e) {
  if (out) out.textContent = e.message || 'Grok failed';
  appendOutput('grok failed: ' + (e.message || 'Grok failed'));
  if (/re-enter your password/i.test(e.message || '')) reauth();
 } finally {
  _busy = '';
  if (askBtn) askBtn.disabled = false;
  paintLockUi();
  await loadStatus();
 }
}

async function copyTui() {
 const cmd = _tui || 'grok';
 try {
  await navigator.clipboard.writeText(cmd);
  showNotification('Copied TUI command.', 'success');
 } catch (e) {
  showNotification(cmd, 'info');
 }
}

function renderHistory(rows) {
 const list = document.getElementById('ops-history');
 if (!list) return;
 if (!rows.length) {
  list.innerHTML = '<li>No deploys yet.</li>';
  return;
 }
 list.innerHTML = rows.map((row) => (
  `<li><span>${escapeHtml(shortSha(row.sha))} ${escapeHtml(row.result)}</span>`
  + `<span class="ops-path">${escapeHtml([row.created_at, row.actor_username].filter(Boolean).join(' · '))}</span>`
  + (row.previous_sha
   ? `<button type="button" class="ops-btn" data-roll="${escapeAttr(row.previous_sha)}">rollback</button>`
   : '')
  + '</li>'
 )).join('');
 list.querySelectorAll('[data-roll]').forEach((btn) => {
  btn.addEventListener('click', () => rollbackTo(btn.getAttribute('data-roll')));
 });
}

async function rollbackTo(sha) {
 const status = document.getElementById('ops-ship-status');
 try {
  const data = await apiCall('/api/ops/rollback', { method: 'POST', body: { sha } });
  if (status) status.textContent = `rollback ${shortSha(data.sha)}`;
  appendOutput('rollback ' + shortSha(data.sha));
  await loadStatus();
 } catch (e) {
  if (status) status.textContent = e.message || 'Rollback failed';
  if (/re-enter your password/i.test(e.message || '')) reauth();
 }
}
