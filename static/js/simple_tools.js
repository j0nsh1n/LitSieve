// Collection and screening popups on Search.
// Screening popup, re-prepare / start-over dialogs, Search tools strip,
// and the one-page collect/search state. Search also loads collect.js
// for fetch/topics (collect UI lives on /search).

var _lastTotalArticles = (typeof _lastTotalArticles === 'number') ? _lastTotalArticles : 0;
var _simpleOnlyMissing = true;
var _lastFetchSourceReportText = '';

function _isPipelineBusy() {
 return typeof _pipelineBusy === 'boolean' && _pipelineBusy;
}

/** Simple Search: collect (empty / unprepared / ?collect=1) vs rank/export. */
function wantsSimpleCollectView(stats) {
 if (_collectQueryOn()) return true;
 if (window._preparingCorpus) return false;
 const ready = Number(stats && stats.articles_with_embeddings) || 0;
 return ready <= 0;
}

function clearCollectQueryFromUrl() {
 if (!_collectQueryOn()) return;
 try {
  const url = new URL(location.href);
  url.searchParams.delete('collect');
  const q = url.searchParams.toString();
  history.replaceState({}, '', url.pathname + (q ? '?' + q : '') + url.hash);
 } catch (e) { /* ignore */ }
}

function setCollectQueryOnUrl() {
 try {
  const url = new URL(location.href);
  url.searchParams.set('collect', '1');
  history.replaceState({}, '', url.pathname + '?' + url.searchParams.toString());
 } catch (e) {
  window.location.href = '/search?collect=1';
 }
}

var _sourcesLoadedForReady = null;
function syncSimpleOnePageState(stats) {
 const collect = document.getElementById('search-collect');
 if (!collect) return;
 const ready = Number(stats && stats.articles_with_embeddings) || 0;
 _lastReadyEmbeddings = ready;
 const total = Number(stats && stats.total_articles) || _lastTotalArticles || 0;
 const showCollect = wantsSimpleCollectView(stats);
 const forceCollect = _collectQueryOn();
 collect.hidden = !showCollect;
 collect.classList.toggle('has-papers', total > 0 && !forceCollect);
 collect.classList.toggle('is-startover', !!forceCollect);
 if (document.body) {
  document.body.classList.toggle('simple-collecting', showCollect);
 }
 const empty = document.getElementById('search-empty-state');
 if (empty) {
  empty.hidden = true;
 }
 const work = document.getElementById('search-workbench');
 if (work) {
  const gated = typeof isSimpleScreenGatePending === 'function' && isSimpleScreenGatePending();
  work.hidden = !ready || showCollect || gated;
 }
 if (showCollect) {
  const card = document.getElementById('simple-screening-card');
  if (card) card.hidden = true;
  if (typeof setSimpleScreenGatePending === 'function') setSimpleScreenGatePending(false);
 }
 if (typeof updateSearchWorkVisibility === 'function' && !showCollect) {
  updateSearchWorkVisibility(stats || { articles_with_embeddings: ready });
 }
 if (typeof updateSimpleToolsStrip === 'function') {
  updateSimpleToolsStrip(stats);
 }
 // The source chips and Save your work read the library's sources, loaded
 // once at page load; a first fetch on this page must load them again or
 // the Sources dialog is empty and blocks the search (audit 19.15).
 if (typeof _sourcesLoadedForReady !== 'undefined' && typeof applyAvailableSources === 'function'
  && ready > 0 && !showCollect && _sourcesLoadedForReady !== ready) {
  _sourcesLoadedForReady = ready;
  applyAvailableSources();
 }
}

function isSimpleBuffering() {
 return !!(window._preparingCorpus || (document.body && document.body.classList.contains('simple-buffering')));
}

// LitSieve, so the wait reads as panning: scoop, swirl, wash, fine grains.
// Order tracks the real phases (fetch, read, dedup, embed) and the LAST line is
// what holdSimpleWait() parks on at 90%, so it must sit comfortably for a while.
var WAIT_STATUS_LINES = [
 'Scooping up your first batch',
 'Swirling through titles and abstracts',
 'Washing out the repeats',
 'Down to the fine grains',
 'Almost got it',
];
var _waitMsgTimer = null;
var _waitMsgIndex = 0;

function _setWaitPct(pct) {
 const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
 const fill = document.getElementById('search-buffering-fill');
 if (fill) fill.style.setProperty('--wait-pct', clamped + '%');
 const bar = document.getElementById('search-wait-bar');
 if (bar) bar.setAttribute('aria-valuenow', String(Math.round(clamped)));
}

function _stopWaitMessages() {
 if (_waitMsgTimer) {
  clearInterval(_waitMsgTimer);
  _waitMsgTimer = null;
 }
}

function _startWaitMessages() {
 if (_waitMsgTimer) return;
 const status = document.getElementById('search-preparing-status');
 if (status && !status.textContent) {
  status.textContent = WAIT_STATUS_LINES[0];
 }
 if (!_waitMsgIndex) {
  _waitMsgIndex = 0;
  if (status) status.textContent = WAIT_STATUS_LINES[0];
 }
 _waitMsgTimer = setInterval(() => {
  if (window._simpleWaitHolding) return;
  _waitMsgIndex = (_waitMsgIndex + 1) % WAIT_STATUS_LINES.length;
  const el = document.getElementById('search-preparing-status');
  if (el) {
   el.classList.remove('line-swap');
   void el.offsetWidth;
   el.textContent = WAIT_STATUS_LINES[_waitMsgIndex];
   el.classList.add('line-swap');
  }
 }, 2500);
}

function showSimpleBuffering(phase) {
 const el = document.getElementById('search-preparing');
 if (!el) return;
 window._preparingCorpus = true;
 window._simpleBufferingPhase = phase || 'fetch';
 el.hidden = false;
 el.setAttribute('aria-busy', 'true');
 if (document.body) {
  document.body.classList.add('simple-buffering');
  document.body.classList.remove('simple-collecting');
 }
 const title = document.getElementById('search-buffering-title');
 const lead = document.getElementById('search-buffering-lead');
 const cancel = document.getElementById('search-buffering-cancel');
 if (title) title.textContent = 'Sieving your papers';
 if (lead) lead.textContent = 'Stay on this page';
 if (cancel) {
  cancel.hidden = (phase === 'prepare') || !!window._simpleWaitHolding;
  // A cancel disables it; every new wait starts with it usable (19.9).
  cancel.disabled = false;
 }
 _startWaitMessages();
 const collect = document.getElementById('search-collect');
 if (collect) collect.hidden = true;
 const card = document.getElementById('simple-screening-card');
 if (card) {
  const modal = document.getElementById('simple-screen-modal');
  if ((!modal || modal.hidden) && !card.hidden) {
   card.hidden = true;
   // Remember that the wait screen hid the More dock, so closing it brings
   // the dock back (Group by theme never refreshed it; audit 19.8).
   card.dataset.waitHid = '1';
  }
 }
}

function hideSimpleBuffering() {
 window._preparingCorpus = false;
 window._simpleBufferingPhase = '';
 window._simpleWaitHolding = false;
 _stopWaitMessages();
 _waitMsgIndex = 0;
 const el = document.getElementById('search-preparing');
 if (el) {
  el.hidden = true;
  el.classList.remove('is-holding');
  el.setAttribute('aria-busy', 'false');
 }
 if (document.body) document.body.classList.remove('simple-buffering');
 const cancel = document.getElementById('search-buffering-cancel');
 if (cancel) cancel.hidden = true;
 const card = document.getElementById('simple-screening-card');
 if (card && card.dataset.waitHid === '1') {
  delete card.dataset.waitHid;
  card.hidden = false;
 }
 _setWaitPct(0);
}

function holdSimpleWait() {
 window._simpleWaitHolding = true;
 window._preparingCorpus = true;
 const el = document.getElementById('search-preparing');
 if (el) {
  el.hidden = false;
  el.classList.add('is-holding');
  el.setAttribute('aria-busy', 'true');
 }
 if (document.body) document.body.classList.add('simple-buffering');
 _setWaitPct(90);
 const cancel = document.getElementById('search-buffering-cancel');
 if (cancel) cancel.hidden = true;
 const status = document.getElementById('search-preparing-status');
 if (status) status.textContent = WAIT_STATUS_LINES[WAIT_STATUS_LINES.length - 1];
}

function finishSimpleWaitThenSearch() {
 if (!window._simpleWaitHolding && !(document.body && document.body.classList.contains('simple-buffering'))) {
  return Promise.resolve();
 }
 window._simpleWaitHolding = false;
 const el = document.getElementById('search-preparing');
 if (el) el.classList.remove('is-holding');
 _stopWaitMessages();
 const status = document.getElementById('search-preparing-status');
 if (status) status.textContent = 'Opening Search';
 const reduce = typeof matchMedia === 'function'
  && matchMedia('(prefers-reduced-motion: reduce)').matches;
 const dur = reduce ? 0 : 2000;
 const t0 = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
 return new Promise((resolve) => {
  let finished = false;
  const finish = () => {
   if (finished) return;
   finished = true;
   _setWaitPct(100);
   hideSimpleBuffering();
   const go = (stats) => {
    if (typeof syncSimpleOnePageState === 'function') syncSimpleOnePageState(stats);
    resolve();
   };
   if (typeof apiCall === 'function') {
    apiCall('/api/statistics').then(go).catch(() => go({ articles_with_embeddings: 1 }));
   } else {
    go({ articles_with_embeddings: 1 });
   }
  };
  const tick = (now) => {
   if (finished) return;
   const t = dur ? Math.min(1, ((now || Date.now()) - t0) / dur) : 1;
   _setWaitPct(90 + 10 * t);
   if (t < 1) {
    requestAnimationFrame(tick);
    return;
   }
   finish();
  };
  // Animation frames pause in a background tab; never leave the student on
  // the wait screen because of that.
  setTimeout(finish, dur + 500);
  if (dur && typeof requestAnimationFrame === 'function') requestAnimationFrame(tick);
  else tick(t0 + dur);
 });
}

function setNextStepVisible(visible) {
 if (typeof window._lraSetNextStepVisible === 'function') {
  window._lraSetNextStepVisible(visible);
  return;
 }
 const el = document.getElementById('fetch-next-step');
 if (!el) return;
 const show = !!(visible );
 el.hidden = !show;
 el.classList.toggle('u-hidden', !show);
}

function _persistFetchMode(mode) {
 try {
  const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || '{}') || {};
  prefs.mode = mode === 'append' ? 'append' : 'replace';
  localStorage.setItem(FETCH_PREFS_KEY, JSON.stringify(prefs));
 } catch (e) { /* ignore */ }
}

// --- Phase 6 Simple screening card ------------------------------------------
// Levels → quick-preview fraction. Counts fetched once, not on every radio click.
const SIMPLE_SCREEN_LEVELS = {
 low: 0.10,
 medium: 0.25,
 high: 0.50,
};
/** @type {Record<string, {proposed_count:number, total_ranked:number, candidates:array}|null>} */
var _simpleScreenCounts = { low: null, medium: null, high: null };
// The open modal and the card refresh both ask for counts; share one request.
let _simpleScreenCountsLoading = null;
let _simpleScreenCandidates = [];
let _simpleTriageUsed = false;
let _simpleTriageLevel = '';
let _simpleTriageQuery = '';
let _simpleTriageGo = [];
let _simpleTriageStay = [];
let _simpleTriageKey = '';
let _simpleTriageKeyHandler = null;
let _simpleScreenLastItems = null;
/** Session-only: skip hides the decision UI until reload (pending is corpus-derived). */
let _simpleScreenSkippedSession = false;
// Last Narrow-it-down exclusion set (per library) so Undo survives a soft reload.
// Corpus API is the source of truth after restart; this is a fast path.
const SIMPLE_SCREEN_UNDO_KEY = 'lra_simple_screen_undo_v1';

// Last known prepared-paper count (for revealing Search after Narrow it down).
var _lastReadyEmbeddings = (typeof _lastReadyEmbeddings === 'number') ? _lastReadyEmbeddings : 0;
// null = not computed yet. On Simple Search, treat unknown as pending so the
// workbench cannot flash before Narrow it down opens.
var _simpleScreenPending = (typeof _simpleScreenPending === 'undefined') ? null : _simpleScreenPending;

function isSimpleScreenGatePending() {
 if (!_onSearchPage()) return false;
 if (typeof _collectQueryOn === 'function' && _collectQueryOn()) return false;
 // Unknown (null) must not hide the Search field — refresh will set true
 // and open Narrow it down when it is actually required.
 if (_simpleScreenPending === null) return false;
 return !!_simpleScreenPending;
}

function setSimpleScreenGatePending(pending) {
 _simpleScreenPending = pending === null ? null : !!pending;
 applySimpleScreenGateUi();
}

function applySimpleScreenGateUi() {
 const gated = isSimpleScreenGatePending();
 const collecting = typeof wantsSimpleCollectView === 'function'
  && wantsSimpleCollectView({ articles_with_embeddings: _lastReadyEmbeddings });
 const readySearch = !gated && !collecting && _lastReadyEmbeddings > 0;
 if (document.body) {
  document.body.classList.toggle('simple-screen-pending', gated);
  document.body.classList.toggle('simple-screen-ready', readySearch);
 }
 const dock = document.getElementById('simple-screen-dock');
 if (dock) dock.hidden = gated;
 const closeBtn = document.getElementById('simple-screen-modal-close');
 if (closeBtn) closeBtn.hidden = gated;
 if (typeof updateSearchWorkVisibility === 'function') {
  updateSearchWorkVisibility({ articles_with_embeddings: _lastReadyEmbeddings });
 }
 const work = document.getElementById('search-workbench');
 if (work) work.hidden = !readySearch;
 const qtop = document.getElementById('search-query-top');
 if (qtop) qtop.hidden = !readySearch;
 if (typeof syncSimpleRailAnchor === 'function') syncSimpleRailAnchor();
}

function copyScreenQuestionToSearch() {
 const el = document.getElementById('simple-screen-query');
 const q = el && el.value.trim();
 const box = document.getElementById('query-text');
 if (q && box && !String(box.value || '').trim()) box.value = q;
}

/** Restore question + levels + actions (needed after skip hid them). */
function showSimpleScreenPendingUi() {
 const decision = document.getElementById('simple-screen-levels');
 const actions = document.getElementById('simple-screen-actions');
 const preview = document.getElementById('simple-screen-preview');
 const outcome = document.getElementById('simple-screen-outcome');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 if (decision) decision.hidden = false;
 if (actions) actions.hidden = false;
 setSimpleScreenConfirmVisible(true);
 if (preview) {
  preview.hidden = true;
  preview.classList.add('u-hidden');
 }
 if (outcome) {
  outcome.hidden = true;
  outcome.classList.add('u-hidden');
 }
 if (undoBtn) undoBtn.hidden = true;
}

// Skip is remembered per library, not just per page view.
//
// "Pending vs complete" is derived from the corpus (prepared papers, and
// whether any low_relevance exclusions exist), which is correct and survives a
// reload. Skipping leaves no trace in the corpus by definition, so without
// this the card reappears on refresh and — worse — the "Go to Search" button
// they were just offered disappears with it.
//
// Per library, because skipping one collection says nothing about the next.
const SKIP_KEY = 'lra_screen_skipped_v1';

// Resolved once per page and cached. The nav select is populated
// asynchronously by common.js, so reading it during the first card refresh
// races and comes back empty — which would silently lose a persisted skip.
let _activeLibIdCache = '';

function _activeLibraryId() {
 const sel = document.getElementById('nav-library-select');
 return (sel && sel.value) || _activeLibIdCache || '';
}

/** Authoritative active library id; falls back to the API before the nav loads. */
async function ensureActiveLibraryId() {
 const fromSelect = (document.getElementById('nav-library-select') || {}).value;
 if (fromSelect) {
  _activeLibIdCache = fromSelect;
  return fromSelect;
 }
 if (_activeLibIdCache) return _activeLibIdCache;
 try {
  const data = await apiCall('/api/libraries');
  _activeLibIdCache = (data && data.active_id) || '';
 } catch (e) {
  _activeLibIdCache = '';
 }
 return _activeLibIdCache;
}

function _skipStore() {
 try {
  return JSON.parse(localStorage.getItem(SKIP_KEY) || '{}') || {};
 } catch (e) {
  return {};
 }
}

function isSimpleScreenSkipped() {
 if (_simpleScreenSkippedSession) return true;
 const lib = _activeLibraryId();
 if (!lib) return false;
 return _skipStore()[lib] === true;
}

function setSimpleScreenSkipped(skipped) {
 _simpleScreenSkippedSession = skipped;
 const lib = _activeLibraryId();
 if (!lib) {
  // The nav select may not have loaded yet; without the library id a Skip
  // lived only until the next reload and Narrow it down came back.
  if (typeof ensureActiveLibraryId === 'function') {
   ensureActiveLibraryId().then((id) => {
    if (id) setSimpleScreenSkipped(skipped);
   }).catch(() => {});
  }
  return;
 }
 try {
  const store = _skipStore();
  if (skipped) {
   store[lib] = true;
  } else {
   delete store[lib];
  }
  localStorage.setItem(SKIP_KEY, JSON.stringify(store));
 } catch (e) {
  // Private mode / storage disabled: fall back to session-only behaviour.
 }
}

function _simpleScreenUndoStore() {
 try {
  return JSON.parse(localStorage.getItem(SIMPLE_SCREEN_UNDO_KEY) || '{}') || {};
 } catch (e) {
  return {};
 }
}

/** Persist last set-aside items (localStorage) as a fast path; corpus API is authoritative. */
function saveSimpleScreenUndoItems(items) {
 _simpleScreenLastItems = items && items.length ? items : null;
 const lib = _activeLibraryId();
 if (!lib) return;
 try {
  const store = _simpleScreenUndoStore();
  if (_simpleScreenLastItems) {
   store[lib] = _simpleScreenLastItems;
  } else {
   delete store[lib];
  }
  localStorage.setItem(SIMPLE_SCREEN_UNDO_KEY, JSON.stringify(store));
 } catch (e) {
  // Private mode: in-memory only.
 }
}

function loadSimpleScreenUndoItems() {
 if (_simpleScreenLastItems && _simpleScreenLastItems.length) {
  return _simpleScreenLastItems;
 }
 const lib = _activeLibraryId();
 if (!lib) return null;
 try {
  const stored = _simpleScreenUndoStore()[lib];
  if (Array.isArray(stored) && stored.length) {
   _simpleScreenLastItems = stored;
   return stored;
  }
 } catch (e) { /* ignore */ }
 return null;
}

function clearSimpleScreenUndoItems() {
 saveSimpleScreenUndoItems(null);
}

/** Load low_relevance exclusions from the server so Undo works after a full restart. */
async function fetchLowRelevanceUndoItems() {
 const cached = loadSimpleScreenUndoItems();
 if (cached && cached.length) return cached;
 try {
  const data = await apiCall('/api/screening/excluded?reason=low_relevance');
  const items = (data && data.items) || [];
  if (items.length) {
   saveSimpleScreenUndoItems(items);
   return items;
  }
 } catch (e) {
  console.warn('fetchLowRelevanceUndoItems failed:', e);
 }
 return null;
}

/** Show/hide the confirm-your-question box with the decision UI (pending only). */
function setSimpleScreenConfirmVisible(visible) {
 const el = document.getElementById('simple-screen-confirm');
 if (el) el.hidden = !visible;
}

/* ---------- Set aside list: every reason, restore one paper or a group ---------- */
let _setAsideModalOpener = null;
let _setAsideModalKey = null;
let _setAsideItems = [];
let _setAsideLastRestore = null;
let _setAsideReasonTarget = null;
let _setAsideReasonUndo = null;

function isSimpleSetAsideOpen() {
 const modal = document.getElementById('simple-set-aside-modal');
 return !!(modal && !modal.hidden);
}

function closeSimpleSetAsideModal() {
 const modal = document.getElementById('simple-set-aside-modal');
 if (!modal || modal.hidden) return;
 modal.hidden = true;
 if (modal.getAttribute('data-owns-scroll-lock') === '1') {
  modal.removeAttribute('data-owns-scroll-lock');
  document.body.classList.remove('lra-modal-open');
  document.body.style.top = '';
  const y = parseInt(document.body.dataset.lraScrollY || '0', 10) || 0;
  delete document.body.dataset.lraScrollY;
  window.scrollTo(0, y);
 }
 if (_setAsideModalKey) {
  document.removeEventListener('keydown', _setAsideModalKey, true);
  _setAsideModalKey = null;
 }
 const opener = _setAsideModalOpener;
 _setAsideModalOpener = null;
 if (opener && typeof opener.focus === 'function') {
  try { opener.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
 }
}

async function openSimpleSetAsideModal() {
 const modal = document.getElementById('simple-set-aside-modal');
 if (!modal || isSimpleSetAsideOpen()) return;
 _setAsideModalOpener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
 if (!document.body.classList.contains('lra-modal-open')) {
  const scrollY = window.scrollY || window.pageYOffset || 0;
  document.body.dataset.lraScrollY = String(scrollY);
  document.body.style.top = `-${scrollY}px`;
  document.body.classList.add('lra-modal-open');
  modal.setAttribute('data-owns-scroll-lock', '1');
 }
 modal.hidden = false;
 _setAsideLastRestore = null;
 _setAsideReasonTarget = null;
 const again = document.getElementById('simple-set-aside-again');
 if (again) again.hidden = true;
 const reasons = document.getElementById('simple-set-aside-reasons');
 if (reasons) reasons.hidden = true;
 const status = document.getElementById('simple-set-aside-status');
 if (status) {
  status.textContent = '';
  status.className = 'status-indicator';
 }
 const card = modal.querySelector('[data-site-modal-card]') || modal;
 const focusable = () => Array.from(card.querySelectorAll(
  'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])'
 )).filter((el) => !el.closest('[hidden]'));
 _setAsideModalKey = (ev) => {
  if (ev.key === 'Escape') {
   ev.preventDefault();
   ev.stopPropagation();
   closeSimpleSetAsideModal();
   return;
  }
  if (ev.key !== 'Tab') return;
  const list = focusable();
  if (!list.length) return;
  const first = list[0];
  const last = list[list.length - 1];
  const active = document.activeElement;
  if (ev.shiftKey && (active === first || !card.contains(active))) {
   ev.preventDefault();
   last.focus();
  } else if (!ev.shiftKey && (active === last || !card.contains(active))) {
   ev.preventDefault();
   first.focus();
  }
 };
 document.addEventListener('keydown', _setAsideModalKey, true);
 const closeBtn = document.getElementById('simple-set-aside-close');
 if (closeBtn) closeBtn.focus();
 await loadSimpleSetAsideList();
}

/** Every set-aside paper, grouped by reason. Not just low_relevance: this is
 *  the one place a Simple student can bring back duplicates and Not relevant. */
async function loadSimpleSetAsideList() {
 const host = document.getElementById('simple-set-aside-groups');
 if (!host) return;
 host.innerHTML = '<p class="help-text">Loading…</p>';
 try {
  const data = await apiCall('/api/screening/excluded');
  _setAsideItems = (data && data.items) || [];
  renderSimpleSetAsideGroups(_setAsideItems, (data && data.groups) || []);
  syncSetAsideReasonChrome();
 } catch (e) {
  host.innerHTML = '';
  setStatus('simple-set-aside-status', `Could not load the list: ${e.message}`, 'error');
 }
}

function renderSimpleSetAsideGroups(items, groups) {
 const host = document.getElementById('simple-set-aside-groups');
 if (!host) return;
 if (!items.length) {
  host.innerHTML = '<p class="help-text">Nothing is set aside. Every paper you collected is in your searches.</p>';
  return;
 }
 const byReason = {};
 items.forEach((it) => {
  (byReason[it.reason] = byReason[it.reason] || []).push(it);
 });
 host.innerHTML = groups.map((g) => {
  const rows = (byReason[g.reason] || []).map((it) => {
   const meta = [it.year, it.source].filter(Boolean).join(' · ');
   const whyBtn = setAsideCanChooseReason(it.reason)
    ? `<button type="button" class="btn btn-secondary btn-sm" data-set-aside-why="${escapeAttr(it.article_id)}|${escapeAttr(it.source)}">Why?</button>`
    : '';
   return `<li><div class="set-aside-row">
    <div class="screen-triage-row-body">
     <span class="screen-triage-row-title">${escapeHtml(it.title || it.article_id)}</span>
     <span class="screen-triage-row-meta">${escapeHtml(meta)}</span>
    </div>
    <div class="set-aside-row-actions">
     ${whyBtn}
     <button type="button" class="btn btn-secondary btn-sm"
      data-set-aside-restore="${escapeAttr(it.article_id)}|${escapeAttr(it.source)}"
      data-set-aside-reason="${escapeAttr(it.reason)}">Restore</button>
    </div>
   </div></li>`;
  }).join('');
  const n = (byReason[g.reason] || []).length;
  // One paper has its own Restore; a group button would repeat it.
  const groupBtn = n > 1
   ? `<button type="button" class="btn btn-secondary btn-sm"
     data-set-aside-restore-group="${escapeAttr(g.reason)}">Restore all ${n}</button>`
   : '';
  return `<section class="set-aside-group" data-reason="${escapeAttr(g.reason)}">
   <div class="set-aside-group-head">
    <h3 class="screen-triage-group-title">${escapeHtml(g.label)} (${n})</h3>
    ${groupBtn}
   </div>
   <ul class="screen-triage-rows set-aside-rows">${rows}</ul>
  </section>`;
 }).join('');
}

function onSetAsideListClick(ev) {
 const why = ev.target.closest('[data-set-aside-why]');
 if (why) {
  const parts = (why.getAttribute('data-set-aside-why') || '').split('|');
  const articleId = parts[0];
  const source = parts.slice(1).join('|');
  const item = _setAsideItems.find((it) => it.article_id === articleId && it.source === source);
  if (item && setAsideCanChooseReason(item.reason)) showSetAsideReasons(item);
  return;
 }
 const one = ev.target.closest('[data-set-aside-restore]');
 const group = ev.target.closest('[data-set-aside-restore-group]');
 if (one) {
  const [articleId, source] = one.getAttribute('data-set-aside-restore').split('|');
  const items = _setAsideItems.filter((it) => it.article_id === articleId && it.source === source);
  restoreSetAside(items, one.getAttribute('data-set-aside-reason'), one);
 } else if (group) {
  const reason = group.getAttribute('data-set-aside-restore-group');
  restoreSetAside(_setAsideItems.filter((it) => it.reason === reason), reason, group);
 }
}

async function restoreSetAside(items, reason, btn) {
 if (!items.length) return;
 setLoading(btn, true);
 try {
  const keys = items.map((it) => ({ article_id: it.article_id, source: it.source }));
  await apiCall('/api/screening', { method: 'POST', body: { items: keys, action: 'include' } });
  _setAsideLastRestore = { items: keys, reason };
  // Narrow it down's own Undo caches this group; it no longer matches.
  if (reason === 'low_relevance') clearSimpleScreenUndoItems();
  const n = keys.length;
  setStatus(
   'simple-set-aside-status',
   `Restored ${n} paper${n === 1 ? '' : 's'}. ${n === 1 ? 'It is' : 'They are'} back in your searches.`,
   'success'
  );
  const again = document.getElementById('simple-set-aside-again');
  if (again) again.hidden = false;
  await loadSimpleSetAsideList();
  await refreshSimpleScreeningCard();
 } catch (e) {
  setStatus('simple-set-aside-status', `Could not restore: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

/** One-click undo of the last restore: set the same papers aside with the same reason. */
async function doSetAsideAgain() {
 const last = _setAsideLastRestore;
 const btn = document.getElementById('simple-set-aside-again');
 if (!last || !last.items.length) return;
 setLoading(btn, true);
 try {
  await apiCall('/api/screening', {
   method: 'POST',
   body: { items: last.items, action: 'exclude', reason: last.reason },
  });
  _setAsideLastRestore = null;
  if (btn) btn.hidden = true;
  setStatus('simple-set-aside-status', `Set ${last.items.length} paper${last.items.length === 1 ? '' : 's'} aside again.`, 'success');
  await loadSimpleSetAsideList();
  await refreshSimpleScreeningCard();
 } catch (e) {
  setStatus('simple-set-aside-status', `Could not set them aside: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

/** Narrow it down, duplicates, and theme groups keep the reason the app wrote.
 *  Changing one would take that paper out of its own Undo. */
function setAsideCanChooseReason(reason) {
 return reason !== 'low_relevance' && reason !== 'duplicate' && reason !== 'cluster';
}

function showSetAsideReasons(item) {
 const panel = document.getElementById('simple-set-aside-reasons');
 if (!panel || !item) return;
 _setAsideReasonTarget = {
  article_id: item.article_id,
  source: item.source,
  reason: item.reason,
  title: item.title || item.article_id,
 };
 const lead = document.getElementById('simple-set-aside-reasons-lead');
 if (lead) {
  lead.textContent = `Why set aside "${_setAsideReasonTarget.title}"? It stays out of your searches.`;
 }
 panel.querySelectorAll('[data-reason]').forEach((btn) => {
  const on = btn.getAttribute('data-reason') === item.reason;
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
 });
 panel.hidden = false;
 const undo = document.getElementById('simple-set-aside-reason-undo');
 if (undo) undo.hidden = !_setAsideReasonUndo;
 panel.scrollIntoView({ block: 'nearest' });
}

function onSetAsideReasonClick(ev) {
 const chip = ev.target.closest('[data-reason]');
 if (!chip || chip.disabled) return;
 ev.preventDefault();
 applySetAsideReason(chip.getAttribute('data-reason'));
}

async function applySetAsideReason(reason) {
 const target = _setAsideReasonTarget;
 if (!target || !reason || reason === target.reason) return;
 if (!setAsideCanChooseReason(reason)) return;
 const panel = document.getElementById('simple-set-aside-reasons');
 const buttons = panel ? Array.from(panel.querySelectorAll('[data-reason]')) : [];
 buttons.forEach((btn) => { btn.disabled = true; });
 try {
  await apiCall('/api/screening', {
   method: 'POST',
   body: withPageLibrary({
    items: [{ article_id: target.article_id, source: target.source }],
    action: 'exclude',
    reason: reason,
   }),
  });
  _setAsideReasonUndo = {
   article_id: target.article_id,
   source: target.source,
   reason: target.reason,
  };
  const chip = buttons.find((btn) => btn.getAttribute('data-reason') === reason);
  const label = chip ? chip.textContent.trim() : reason;
  setStatus('simple-set-aside-status', `Reason saved: ${label}.`, 'success');
  await loadSimpleSetAsideList();
  const updated = _setAsideItems.find((it) => it.article_id === target.article_id && it.source === target.source);
  if (updated) showSetAsideReasons(updated);
 } catch (e) {
  setStatus('simple-set-aside-status', `Could not save the reason: ${e.message}`, 'error');
 } finally {
  buttons.forEach((btn) => { btn.disabled = false; });
 }
}

async function undoSetAsideReason() {
 const last = _setAsideReasonUndo;
 const btn = document.getElementById('simple-set-aside-reason-undo');
 if (!last) return;
 const still = _setAsideItems.find((it) => it.article_id === last.article_id && it.source === last.source);
 if (!still) {
  _setAsideReasonUndo = null;
  if (btn) btn.hidden = true;
  setStatus('simple-set-aside-status', 'That paper is back in your searches.', 'info');
  return;
 }
 setLoading(btn, true);
 try {
  await apiCall('/api/screening', {
   method: 'POST',
   body: withPageLibrary({
    items: [{ article_id: last.article_id, source: last.source }],
    action: 'exclude',
    reason: last.reason,
   }),
  });
  _setAsideReasonUndo = null;
  if (btn) btn.hidden = true;
  setStatus('simple-set-aside-status', 'Put the old reason back.', 'success');
  await loadSimpleSetAsideList();
  const updated = _setAsideItems.find((it) => it.article_id === last.article_id && it.source === last.source);
  const panel = document.getElementById('simple-set-aside-reasons');
  if (updated && panel && !panel.hidden) showSetAsideReasons(updated);
 } catch (e) {
  setStatus('simple-set-aside-status', `Could not put the old reason back: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

function syncSetAsideReasonChrome() {
 if (_setAsideReasonTarget) {
  const still = _setAsideItems.find((it) =>
   it.article_id === _setAsideReasonTarget.article_id && it.source === _setAsideReasonTarget.source);
  if (!still) {
   const panel = document.getElementById('simple-set-aside-reasons');
   if (panel) panel.hidden = true;
   _setAsideReasonTarget = null;
  }
 }
 if (_setAsideReasonUndo) {
  const stillUndo = _setAsideItems.find((it) =>
   it.article_id === _setAsideReasonUndo.article_id && it.source === _setAsideReasonUndo.source);
  if (!stillUndo) _setAsideReasonUndo = null;
 }
 const undo = document.getElementById('simple-set-aside-reason-undo');
 if (undo) undo.hidden = !_setAsideReasonUndo;
}

let _simpleScreenWired = false;

function simpleScreenSelectedLevel() {
 const el = document.querySelector('input[name="simple-screen-level"]:checked');
 return (el && el.value) || 'medium';
}

function simpleScreenFraction(level) {
 return SIMPLE_SCREEN_LEVELS[level] != null ? SIMPLE_SCREEN_LEVELS[level] : 0.25;
}

/** The typed research question only. The fetch topic is a subject, not a
 * question, so it never stands in for one (audit 19.11). */
function simpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 return (el && el.value.trim()) || '';
}

function prefillSimpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 if (!el) return;
 // Fetch is a topic, not the research question — do not copy it in.
 // Keep whatever they already typed (or what re-prepare verified).
 if (el.value.trim()) return;
}

function setSimpleScreenStripOutcome(msg, opts) {
 const outcome = document.getElementById('simple-screen-outcome');
 const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 const hint = document.getElementById('simple-screen-dock-hint');
 if (hint) hint.hidden = true;
 if (!msg) {
  if (outcome) {
   outcome.hidden = true;
   outcome.classList.add('u-hidden');
  }
  if (undoBtn) undoBtn.hidden = true;
  return;
 }
 if (outcome) {
  outcome.hidden = false;
  outcome.classList.remove('u-hidden');
 }
 if (outcomeMsg) outcomeMsg.textContent = msg;
 if (undoBtn) {
  undoBtn.hidden = !(opts && opts.undo);
  undoBtn.textContent = 'Undo';
 }
}

function setSimpleScreenGotoVisible(visible) {
 const el = document.getElementById('simple-screen-goto');
 const onSearch = _onSearchPage();
 if (el) el.hidden = !visible || onSearch;
 if (!onSearch) setNextStepVisible(visible);
}

let _simpleScreenModalOpener = null;
let _simpleScreenModalKey = null;

function isSimpleScreenModalOpen() {
 const modal = document.getElementById('simple-screen-modal');
 return !!(modal && !modal.hidden);
}

function closeSimpleScreenModal(opts) {
 const force = !!(opts && opts.force);
 // Pending gate: only Apply or Skip may close the popup.
 if (isSimpleScreenGatePending() && !force) return;
 closeSimpleScreenTriage();
 const modal = document.getElementById('simple-screen-modal');
 if (!modal || modal.hidden) return;
 modal.hidden = true;
 const ownsLock = modal.getAttribute('data-owns-scroll-lock') === '1';
 modal.removeAttribute('data-owns-scroll-lock');
 if (ownsLock) {
  document.body.classList.remove('lra-modal-open');
  document.body.style.top = '';
  const y = parseInt(document.body.dataset.lraScrollY || '0', 10) || 0;
  delete document.body.dataset.lraScrollY;
  window.scrollTo(0, y);
 }
 if (_simpleScreenModalKey) {
  document.removeEventListener('keydown', _simpleScreenModalKey, true);
  _simpleScreenModalKey = null;
 }
 const opener = _simpleScreenModalOpener;
 _simpleScreenModalOpener = null;
 if (opener && typeof opener.focus === 'function') {
  try { opener.focus({ preventScroll: true }); } catch (e) {
   try { opener.focus(); } catch (e2) { /* ignore */ }
  }
 }
}

function openSimpleScreenModal() {
 const modal = document.getElementById('simple-screen-modal');
 const card = document.querySelector('.simple-screen-modal-card');
 if (!modal) return;
 if (isSimpleScreenSkipped()) {
  setSimpleScreenSkipped(false);
  setSimpleScreenGatePending(true);
 }
 if (isSimpleScreenGatePending()) {
  showSimpleScreenPendingUi();
 }
 if (isSimpleScreenModalOpen()) {
  applySimpleScreenGateUi();
  return;
 }
 _simpleScreenModalOpener = document.activeElement instanceof HTMLElement
  ? document.activeElement
  : document.getElementById('simple-screen-open-btn');
 // Required gate is a page step (no Search behind it) — do not dim/lock the page.
 if (!isSimpleScreenGatePending() && !document.body.classList.contains('lra-modal-open')) {
  const scrollY = window.scrollY || window.pageYOffset || 0;
  document.body.dataset.lraScrollY = String(scrollY);
  document.body.style.top = `-${scrollY}px`;
  document.body.classList.add('lra-modal-open');
  modal.setAttribute('data-owns-scroll-lock', '1');
 }
 modal.hidden = false;
 prefillSimpleScreenQuery();
 loadSimpleScreenCounts();
 const applyOnOpen = document.getElementById('simple-screen-apply-btn');
 const qOnOpen = document.getElementById('simple-screen-query');
 if (applyOnOpen && qOnOpen) applyOnOpen.disabled = !qOnOpen.value.trim();

 const focusableSelector = [
  'button:not([disabled])',
  '[href]',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
 ].join(',');
 const host = card || modal;
 const getFocusable = () => Array.from(host.querySelectorAll(focusableSelector)).filter((el) => {
  const r = el.getBoundingClientRect();
  return r.width > 0 || r.height > 0;
 });
 _simpleScreenModalKey = (ev) => {
  if (isSimpleScreenTriageOpen()) return;
  // The account panel sits beside this step, not under it: leave its keys alone.
  const settings = document.getElementById('settings-panel');
  if (settings && !settings.hidden && (settings.contains(document.activeElement) || ev.key === 'Escape')) return;
  if (ev.key === 'Escape') {
   ev.preventDefault();
   ev.stopPropagation();
   closeSimpleScreenModal();
   return;
  }
  if (ev.key !== 'Tab') return;
  const list = getFocusable();
  if (!list.length) return;
  const first = list[0];
  const last = list[list.length - 1];
  const active = document.activeElement;
  if (ev.shiftKey) {
   if (active === first || !host.contains(active)) {
    ev.preventDefault();
    last.focus();
   }
  } else if (active === last || !host.contains(active)) {
   ev.preventDefault();
   first.focus();
  }
 };
 document.addEventListener('keydown', _simpleScreenModalKey, true);
 setTimeout(() => {
  const q = document.getElementById('simple-screen-query');
  if (q) q.focus();
 }, 30);
}

/**
 * Pending/complete from corpus, not a job flag:
 *  - pending: prepared papers exist and no low_relevance exclusions yet
 *  - complete: low_relevance > 0 (applied at least once)
 */
async function refreshSimpleScreeningCard() {
 try {
  await _refreshSimpleScreeningCardNow();
 } finally {
  await settleSimpleWaitHold();
 }
}

/** The 90% hold waits only for Narrow it down's Apply or Skip. When the card
 * ends anywhere else (already screened, skipped, nothing ready, an error),
 * finish the wait instead of parking on "Almost got it" (audit 19.10). */
async function settleSimpleWaitHold() {
 if (!window._simpleWaitHolding) return;
 // Mid fetch + prepare the card stays hidden on purpose; the refresh that
 // runs once the job ends decides.
 if (_isPipelineBusy()) return;
 if (isSimpleScreenGatePending()) return;
 await finishSimpleWaitThenSearch();
}

async function _refreshSimpleScreeningCardNow() {
 const card = document.getElementById('simple-screening-card');
 if (!card) return;
 if (_isPipelineBusy()) {
  card.hidden = true;
  return;
 }
 if (_collectQueryOn()) {
  card.hidden = true;
  return;
 }
 try {
  const [stats, report] = await Promise.all([
   apiCall('/api/statistics'),
   apiCall('/api/screening-report?format=json'),
   // Resolves (and caches) the active library so a persisted skip is not
   // missed just because the nav select has not populated yet.
   ensureActiveLibraryId(),
  ]);
  if (typeof fillSimpleRailStats === 'function') {
   fillSimpleRailStats(stats, report);
  }
  const ready = Number(stats.articles_with_embeddings) || 0;
  _lastReadyEmbeddings = ready;
  const lowRel = Number(
   report && report.excluded && report.excluded.low_relevance
  ) || 0;
  const total = Number(stats.total_articles) || 0;

  if (ready <= 0) {
   setSimpleScreenGatePending(false);
   if (total > 0 && _onSearchPage()) {
    card.hidden = false;
    wireSimpleToolsStrip();
    updateSimpleToolsStrip(stats);
    const openBtn = document.getElementById('simple-screen-open-btn');
    if (openBtn) openBtn.hidden = true;
    const dockHint = document.getElementById('simple-screen-dock-hint');
    if (dockHint) dockHint.hidden = true;
    setSimpleScreenGotoVisible(false);
    return;
   }
   card.hidden = true;
   setSimpleScreenGotoVisible(false);
   return;
  }

  card.hidden = false;
  prefillSimpleScreenQuery();
  wireSimpleScreeningCard();

  const decision = document.getElementById('simple-screen-levels');
  const actions = document.getElementById('simple-screen-actions');
  const outcome = document.getElementById('simple-screen-outcome');
  const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
  const undoBtn = document.getElementById('simple-screen-undo-btn');
  const preview = document.getElementById('simple-screen-preview');

  const openBtn = document.getElementById('simple-screen-open-btn');
  const dockHint = document.getElementById('simple-screen-dock-hint');

  if (lowRel > 0) {
   // Complete: already screened this library.
   if (decision) decision.hidden = true;
   if (actions) actions.hidden = true;
   setSimpleScreenConfirmVisible(false);
   if (preview) {
    preview.hidden = true;
    preview.classList.add('u-hidden');
   }
   setSimpleScreenStripOutcome(
    `Set aside ${lowRel} paper${lowRel === 1 ? '' : 's'}`,
    { undo: true }
   );
   if (openBtn) openBtn.hidden = true;
   if (dockHint) dockHint.hidden = true;
   // Warm the undo cache in the background; the button stays visible either way.
   fetchLowRelevanceUndoItems();
   setSimpleScreenGotoVisible(true);
   setSimpleScreenGatePending(false);
   return;
  }

  if (isSimpleScreenSkipped()) {
   if (decision) decision.hidden = true;
   if (actions) actions.hidden = true;
   setSimpleScreenConfirmVisible(false);
   setSimpleScreenStripOutcome('');
   if (openBtn) openBtn.hidden = false;
   if (dockHint) dockHint.hidden = true;
   setSimpleScreenGotoVisible(true);
   setSimpleScreenGatePending(false);
   return;
  }

  // Pending: confirm question + levels + actions; fetch counts once.
  showSimpleScreenPendingUi();
  if (undoBtn) undoBtn.hidden = true;
  if (openBtn) openBtn.hidden = false;
  if (dockHint) dockHint.hidden = false;
  setSimpleScreenGotoVisible(false);
  // Set-aside papers (duplicates included) are not ranked, so leave them out
  // here too; the level counts below are "about X of" this number.
  const excludedTotal = Number(report && report.excluded && report.excluded.total) || 0;
  const rankable = Math.max(0, ready - excludedTotal);
  const totalEl = document.getElementById('simple-screen-total');
  if (totalEl) {
   totalEl.hidden = false;
   totalEl.textContent = `${rankable} paper${rankable === 1 ? '' : 's'} ready to rank`
    + (total > rankable ? ` (${total} in collection).` : '.');
  }
  renderSimpleScreenDuplicates(
   Number(report && report.excluded && report.excluded.duplicate) || 0
  );
  setSimpleScreenGatePending(true);
  if (_onSearchPage()) openSimpleScreenModal();
  await loadSimpleScreenCounts();
 } catch (e) {
  console.warn('refreshSimpleScreeningCard failed:', e);
  card.hidden = true;
  setSimpleScreenGatePending(false);
 }
}

async function loadSimpleScreenCounts() {
 const query = simpleScreenQuery();
 if (_simpleScreenCountsLoading && _simpleScreenCountsLoading.query === query) {
  return _simpleScreenCountsLoading.promise;
 }
 const promise = _loadSimpleScreenCounts(query);
 _simpleScreenCountsLoading = { query, promise };
 try {
  return await promise;
 } finally {
  if (_simpleScreenCountsLoading && _simpleScreenCountsLoading.promise === promise) {
   _simpleScreenCountsLoading = null;
  }
 }
}

async function _loadSimpleScreenCounts(query) {
 const status = document.getElementById('simple-screen-status');
 if (!query) {
  ['low', 'medium', 'high'].forEach((level) => {
   const el = document.getElementById(`simple-screen-count-${level}`);
   if (el) el.textContent = '…';
  });
  if (status) {
   setStatus('simple-screen-status', 'Enter a research question to see how many papers each level would set aside.', 'info');
  }
  return;
 }
 if (status) setStatus('simple-screen-status', 'Counting papers for each level…', 'info');
 // Fetch all three fractions once (parallel). Reuse until query changes.
 const qKey = query;
 if (_simpleScreenCounts._query === qKey
  && _simpleScreenCounts.low && _simpleScreenCounts.medium && _simpleScreenCounts.high) {
  applySimpleScreenCountLabels();
  if (status) setStatus('simple-screen-status', '', 'info');
  return;
 }
 try {
  const entries = await Promise.all(
   Object.keys(SIMPLE_SCREEN_LEVELS).map(async (level) => {
    const fraction = SIMPLE_SCREEN_LEVELS[level];
    const data = await apiCall('/api/screening/quick-preview', {
     method: 'POST',
     body: withPageLibrary({ query, fraction }),
    });
    return [level, data];
   })
  );
  _simpleScreenCounts = { low: null, medium: null, high: null, _query: qKey };
  entries.forEach(([level, data]) => {
   _simpleScreenCounts[level] = data;
  });
  applySimpleScreenCountLabels();
  if (status) setStatus('simple-screen-status', '', 'info');
 } catch (e) {
  if (status) setStatus('simple-screen-status', `Could not rank papers: ${e.message}`, 'error');
  console.warn('loadSimpleScreenCounts failed:', e);
 }
}

function applySimpleScreenCountLabels() {
 const total =
  (_simpleScreenCounts.medium && _simpleScreenCounts.medium.total_ranked)
  || (_simpleScreenCounts.low && _simpleScreenCounts.low.total_ranked)
  || 0;
 ['low', 'medium', 'high'].forEach((level) => {
  const el = document.getElementById(`simple-screen-count-${level}`);
  if (!el) return;
  const data = _simpleScreenCounts[level];
  if (!data) {
   el.textContent = '…';
   return;
  }
  const n = Number(data.proposed_count) || 0;
  const t = Number(data.total_ranked) || total || 0;
  el.textContent = t ? `${n} of ${t}` : String(n);
 });
 const selected = _simpleScreenCounts[simpleScreenSelectedLevel()];
 renderSimpleScreenTypeNotes(selected);
}

function renderSimpleScreenTypeNotes(data) {
 const keptN = data && Array.isArray(data.kept_no_abstract)
  ? data.kept_no_abstract.length : 0;
 const optN = data && Array.isArray(data.optional_type_aside)
  ? data.optional_type_aside.length : 0;
 document.querySelectorAll('[data-simple-screen-kept-no-abstract]').forEach((el) => {
  el.hidden = keptN <= 0;
  if (keptN > 0) {
   el.textContent = `${keptN} books and chapters kept: no abstract to judge`;
  }
 });
 document.querySelectorAll('[data-simple-screen-also-types-label]').forEach((label) => {
  label.hidden = optN <= 0;
  if (optN <= 0) {
   const box = label.querySelector('[data-simple-screen-also-types]');
   if (box) box.checked = false;
  }
 });
 document.querySelectorAll('[data-simple-screen-also-types-text]').forEach((el) => {
  el.textContent = `Also set aside ${optN} book reviews and trial registrations`;
 });
}

function wireSimpleScreenAlsoTypes() {
 const boxes = document.querySelectorAll('[data-simple-screen-also-types]');
 boxes.forEach((box) => {
  box.addEventListener('change', () => {
   boxes.forEach((other) => {
    if (other !== box) other.checked = box.checked;
   });
  });
 });
}

function _simpleScreenAlsoTypesOn() {
 return Array.from(document.querySelectorAll('[data-simple-screen-also-types]'))
  .some((el) => el.checked);
}

function _mergeSimpleScreenTypeAside(items, data) {
 if (!_simpleScreenAlsoTypesOn()) return items;
 const extra = (data && data.optional_type_aside) || [];
 const seen = new Set(items.map((it) => `${it.article_id}::${it.source}`));
 const out = items.slice();
 extra.forEach((c) => {
  const key = `${c.article_id}::${c.source}`;
  if (seen.has(key)) return;
  seen.add(key);
  out.push({ article_id: c.article_id, source: c.source });
 });
 return out;
}

function wireSimpleScreeningCard() {
 if (_simpleScreenWired) return;
 _simpleScreenWired = true;
 const previewBtn = document.getElementById('simple-screen-preview-btn');
 const applyBtn = document.getElementById('simple-screen-apply-btn');
 const skipBtn = document.getElementById('simple-screen-skip-btn');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 const queryEl = document.getElementById('simple-screen-query');
 if (previewBtn) previewBtn.addEventListener('click', doSimpleScreenPreview);
 if (applyBtn) applyBtn.addEventListener('click', doSimpleScreenApply);
 if (skipBtn) skipBtn.addEventListener('click', doSimpleScreenSkip);
 if (undoBtn) undoBtn.addEventListener('click', doSimpleScreenUndo);
 const dupsUndoBtn = document.getElementById('simple-screen-dups-undo');
 if (dupsUndoBtn) dupsUndoBtn.addEventListener('click', doSimpleScreenDuplicatesUndo);
 document.querySelectorAll('input[name="simple-screen-level"]').forEach((el) => {
  el.addEventListener('change', () => applySimpleScreenCountLabels());
 });
 wireSimpleScreenAlsoTypes();
 const openBtn = document.getElementById('simple-screen-open-btn');
 if (openBtn) openBtn.addEventListener('click', openSimpleScreenModal);
 document.querySelectorAll('[data-simple-screen-close]').forEach((el) => {
  el.addEventListener('click', (ev) => {
   ev.preventDefault();
   closeSimpleScreenModal();
  });
 });
 if (queryEl) {
  let t = null;
  const syncApply = () => {
   const apply = document.getElementById('simple-screen-apply-btn');
   if (apply) apply.disabled = !queryEl.value.trim();
  };
  syncApply();
  queryEl.addEventListener('change', () => {
   _simpleScreenCounts = { low: null, medium: null, high: null };
   _simpleTriageUsed = false;
   loadSimpleScreenCounts();
   syncApply();
  });
  queryEl.addEventListener('input', () => {
   syncApply();
   clearTimeout(t);
   t = setTimeout(() => {
    _simpleScreenCounts = { low: null, medium: null, high: null };
    _simpleTriageUsed = false;
    loadSimpleScreenCounts();
   }, 600);
  });
 }
 const triageApply = document.getElementById('screen-triage-apply-btn');
 const keepBtn = document.getElementById('screen-triage-keep-btn');
 const asideBtn = document.getElementById('screen-triage-aside-btn');
 const detailClose = document.getElementById('screen-triage-detail-close');
 if (triageApply) triageApply.addEventListener('click', doSimpleScreenApply);
 if (keepBtn) keepBtn.addEventListener('click', () => moveScreenTriagePaper('stay'));
 if (asideBtn) asideBtn.addEventListener('click', () => moveScreenTriagePaper('go'));
 if (detailClose) {
  detailClose.addEventListener('click', () => {
   const detail = document.getElementById('screen-triage-detail');
   if (detail) detail.classList.remove('is-open');
  });
 }
 document.querySelectorAll('[data-screen-triage-close]').forEach((el) => {
  el.addEventListener('click', (ev) => {
   ev.preventDefault();
   closeSimpleScreenTriage();
  });
 });
 // Radios reuse loaded counts. They do not re-fetch.
}

function _simpleScreenEnsureQuery(query) {
 if (_simpleScreenCounts._query !== query) {
  _simpleScreenCounts = { low: null, medium: null, high: null, _query: query };
  _simpleTriageUsed = false;
 }
}

function _screenPaperKey(p) {
 return `${p.article_id}::${p.source}`;
}

function _screenAuthorsLine(p) {
 const a = p && p.authors;
 if (Array.isArray(a)) return a.filter(Boolean).join('; ');
 return String(a || '');
}

function _screenScoreLabel(p) {
 const n = Number(p && p.similarity_score);
 if (!Number.isFinite(n)) return '';
 return n.toFixed(2);
}

function _screenTriageMatches() {
 return _simpleTriageUsed
  && _simpleTriageLevel === simpleScreenSelectedLevel()
  && _simpleTriageQuery === simpleScreenQuery();
}

function isSimpleScreenTriageOpen() {
 const el = document.getElementById('simple-screen-preview');
 return !!(el && !el.hidden);
}

function closeSimpleScreenTriage() {
 const el = document.getElementById('simple-screen-preview');
 if (!el || el.hidden) {
  if (_simpleTriageKeyHandler) {
   document.removeEventListener('keydown', _simpleTriageKeyHandler, true);
   _simpleTriageKeyHandler = null;
  }
  return;
 }
 el.hidden = true;
 el.classList.add('u-hidden');
 document.body.classList.remove('simple-screen-triage-open');
 // "Showing N paper(s) that would be set aside" described the closed list (19.5).
 setStatus('simple-screen-status', '', 'info');
 const detail = document.getElementById('screen-triage-detail');
 if (detail) detail.classList.remove('is-open');
 if (_simpleTriageKeyHandler) {
  document.removeEventListener('keydown', _simpleTriageKeyHandler, true);
  _simpleTriageKeyHandler = null;
 }
 const btn = document.getElementById('simple-screen-preview-btn');
 if (btn && typeof btn.focus === 'function') {
  try { btn.focus({ preventScroll: true }); } catch (e) {
   try { btn.focus(); } catch (e2) { /* ignore */ }
  }
 }
}

function _screenTriageOrder() {
 return _simpleTriageGo.concat(_simpleTriageStay);
}

function _screenTriagePaper(key) {
 return _screenTriageOrder().find((p) => _screenPaperKey(p) === key) || null;
}

function _screenTriageRowEl(key) {
 return Array.from(document.querySelectorAll('.screen-triage-row'))
  .find((el) => el.dataset.key === key) || null;
}

function _screenTriageGoing(key) {
 return _simpleTriageGo.some((p) => _screenPaperKey(p) === key);
}

function renderScreenTriage() {
 const goRows = document.getElementById('screen-triage-go-rows');
 const stayRows = document.getElementById('screen-triage-stay-rows');
 const goHead = document.getElementById('screen-triage-go-heading');
 const stayHead = document.getElementById('screen-triage-stay-heading');
 const applyBtn = document.getElementById('screen-triage-apply-btn');
 const lead = document.getElementById('screen-triage-lead');
 if (goHead) goHead.textContent = `Would go (${_simpleTriageGo.length})`;
 if (stayHead) stayHead.textContent = `Would stay (${_simpleTriageStay.length})`;
 if (applyBtn) {
  const n = _simpleTriageGo.length;
  applyBtn.textContent = `Set aside ${n} paper${n === 1 ? '' : 's'}`;
  applyBtn.disabled = n <= 0;
 }
 if (lead) {
  lead.textContent = _simpleTriageGo.length
   ? `Papers least related to your question. Read them, keep any you still want. Nothing is excluded until you set them aside.`
   : `Nothing would be set aside at this level. You can still mark papers below.`;
 }
 if (goRows) {
  goRows.textContent = '';
  _simpleTriageGo.forEach((p) => goRows.appendChild(_screenTriageRow(p)));
 }
 if (stayRows) {
  stayRows.textContent = '';
  _simpleTriageStay.forEach((p) => stayRows.appendChild(_screenTriageRow(p)));
 }
 renderScreenTriageDetail();
}

function _screenTriageRow(paper) {
 const li = document.createElement('li');
 const btn = document.createElement('button');
 btn.type = 'button';
 btn.className = 'screen-triage-row';
 const key = _screenPaperKey(paper);
 btn.dataset.key = key;
 if (_simpleTriageKey === key) btn.setAttribute('aria-current', 'true');
 const score = document.createElement('span');
 score.className = 'screen-triage-row-score';
 score.textContent = _screenScoreLabel(paper) || '—';
 const body = document.createElement('span');
 body.className = 'screen-triage-row-body';
 const title = document.createElement('span');
 title.className = 'screen-triage-row-title';
 title.textContent = paper.title || '(no title)';
 const meta = document.createElement('span');
 meta.className = 'screen-triage-row-meta';
 const srcName = typeof getSourceName === 'function' ? getSourceName(paper.source) : paper.source;
 meta.textContent = [paper.journal, paper.year, srcName].filter(Boolean).join(' · ');
 body.appendChild(title);
 body.appendChild(meta);
 btn.appendChild(score);
 btn.appendChild(body);
 btn.addEventListener('click', () => selectScreenTriagePaper(key, false));
 li.appendChild(btn);
 return li;
}

function renderScreenTriageDetail() {
 const host = document.getElementById('screen-triage-detail-body');
 const keepBtn = document.getElementById('screen-triage-keep-btn');
 const asideBtn = document.getElementById('screen-triage-aside-btn');
 const paper = _screenTriagePaper(_simpleTriageKey);
 if (!host) return;
 host.textContent = '';
 if (!paper) {
  const empty = document.createElement('p');
  empty.className = 'help-text';
  empty.textContent = 'Select a paper to read it.';
  host.appendChild(empty);
  if (keepBtn) keepBtn.disabled = true;
  if (asideBtn) asideBtn.disabled = true;
  return;
 }
 const going = _screenTriageGoing(_simpleTriageKey);
 if (keepBtn) keepBtn.disabled = !going;
 if (asideBtn) asideBtn.disabled = going;

 const kicker = document.createElement('p');
 kicker.className = 'screen-triage-kicker';
 const score = _screenScoreLabel(paper);
 kicker.textContent = [score && `Match ${score}`, paper.journal, paper.year]
  .filter(Boolean).join(' · ');
 const title = document.createElement('h3');
 title.className = 'screen-triage-detail-title';
 title.textContent = paper.title || '(no title)';
 const authors = document.createElement('p');
 authors.className = 'screen-triage-authors';
 authors.textContent = _screenAuthorsLine(paper);
 const absLabel = document.createElement('h4');
 absLabel.className = 'screen-triage-kicker';
 absLabel.textContent = 'Abstract';
 const abs = document.createElement('p');
 abs.className = 'screen-triage-abstract';
 abs.textContent = paper.abstract || 'No abstract on file.';
 host.appendChild(kicker);
 host.appendChild(title);
 host.appendChild(authors);
 host.appendChild(absLabel);
 host.appendChild(abs);

 const active = _screenTriageRowEl(_simpleTriageKey);
 if (active && typeof active.scrollIntoView === 'function') {
  active.scrollIntoView({ block: 'nearest' });
 }
}

function selectScreenTriagePaper(key, moveFocus) {
 const order = _screenTriageOrder();
 if (!order.length) {
  _simpleTriageKey = '';
  renderScreenTriage();
  return;
 }
 let next = key;
 if (!order.some((p) => _screenPaperKey(p) === next)) {
  next = _screenPaperKey(order[0]);
 }
 _simpleTriageKey = next;
 const detail = document.getElementById('screen-triage-detail');
 if (detail) detail.classList.add('is-open');
 renderScreenTriage();
 if (moveFocus) {
 const row = _screenTriageRowEl(_simpleTriageKey);
 if (row) row.focus();
 }
}

function moveScreenTriagePaper(dest) {
 const key = _simpleTriageKey;
 const paper = _screenTriagePaper(key);
 if (!paper) return;
 _simpleTriageGo = _simpleTriageGo.filter((p) => _screenPaperKey(p) !== key);
 _simpleTriageStay = _simpleTriageStay.filter((p) => _screenPaperKey(p) !== key);
 if (dest === 'go') _simpleTriageGo.unshift(paper);
 else _simpleTriageStay.push(paper);
 _simpleScreenCandidates = _simpleTriageGo.slice();
 selectScreenTriagePaper(key, false);
}

function stepScreenTriage(delta) {
 const order = _screenTriageOrder();
 if (!order.length) return;
 const keys = order.map(_screenPaperKey);
 let i = keys.indexOf(_simpleTriageKey);
 if (i < 0) i = 0;
 else i = (i + delta + keys.length) % keys.length;
 selectScreenTriagePaper(keys[i], true);
}

function openSimpleScreenTriage() {
 const el = document.getElementById('simple-screen-preview');
 const panel = el && el.querySelector('.screen-triage-panel');
 if (!el) return;
 el.hidden = false;
 el.classList.remove('u-hidden');
 document.body.classList.add('simple-screen-triage-open');
 const first = _simpleTriageGo[0] || _simpleTriageStay[0];
 _simpleTriageKey = first ? _screenPaperKey(first) : '';
 const detail = document.getElementById('screen-triage-detail');
 if (detail && _simpleTriageKey) detail.classList.add('is-open');
 renderScreenTriage();
 if (_simpleTriageKeyHandler) {
  document.removeEventListener('keydown', _simpleTriageKeyHandler, true);
 }
 _simpleTriageKeyHandler = (ev) => {
  if (!isSimpleScreenTriageOpen()) return;
  const tag = (ev.target && ev.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (ev.key === 'Escape') {
   ev.preventDefault();
   ev.stopPropagation();
   closeSimpleScreenTriage();
   return;
  }
  const k = ev.key.toLowerCase();
  if (k === 'j') {
   ev.preventDefault();
   stepScreenTriage(1);
  } else if (k === 'k') {
   ev.preventDefault();
   stepScreenTriage(-1);
  }
  if (ev.key !== 'Tab' || !panel) return;
  const focusableSelector = [
   'button:not([disabled])',
   '[href]',
   'input:not([disabled]):not([type="hidden"])',
   'select:not([disabled])',
   'textarea:not([disabled])',
   '[tabindex]:not([tabindex="-1"])',
  ].join(',');
  const list = Array.from(panel.querySelectorAll(focusableSelector)).filter((node) => {
   const r = node.getBoundingClientRect();
   return r.width > 0 || r.height > 0;
  });
  if (!list.length) return;
  const firstEl = list[0];
  const lastEl = list[list.length - 1];
  const active = document.activeElement;
  if (ev.shiftKey) {
   if (active === firstEl || !panel.contains(active)) {
    ev.preventDefault();
    lastEl.focus();
   }
  } else if (active === lastEl || !panel.contains(active)) {
   ev.preventDefault();
   firstEl.focus();
  }
 };
 document.addEventListener('keydown', _simpleTriageKeyHandler, true);
 const firstRow = document.querySelector('.screen-triage-row');
 if (firstRow) firstRow.focus();
}

async function doSimpleScreenPreview() {
 const level = simpleScreenSelectedLevel();
 const fraction = simpleScreenFraction(level);
 const query = simpleScreenQuery();
 const btn = document.getElementById('simple-screen-preview-btn');
 if (!query) {
  showNotification('Enter a research question first.', 'error');
  return;
 }
 setLoading(btn, true);
 setStatus('simple-screen-status', 'Finding the least related papers…', 'info');
 try {
  _simpleScreenEnsureQuery(query);
  let data = _simpleScreenCounts[level];
  if (!data) {
   data = await apiCall('/api/screening/quick-preview', {
    method: 'POST',
    body: withPageLibrary({ query, fraction }),
   });
   _simpleScreenCounts[level] = data;
   applySimpleScreenCountLabels();
  }
  const candidates = data.candidates || [];
  const staying = data.staying || [];
  _simpleScreenCandidates = candidates.slice();
  _simpleTriageGo = candidates.slice();
  _simpleTriageStay = staying.slice();
  _simpleTriageUsed = true;
  _simpleTriageLevel = level;
  _simpleTriageQuery = query;
  renderSimpleScreenTypeNotes(data);
  if (!candidates.length && !staying.length) {
   setStatus('simple-screen-status', 'Nothing to set aside at this level.', 'info');
   return;
  }
  openSimpleScreenTriage();
  setStatus(
   'simple-screen-status',
   `Showing ${candidates.length} paper(s) that would be set aside. Nothing is excluded yet.`,
   'info'
  );
 } catch (e) {
  setStatus('simple-screen-status', `Preview failed: ${e.message}`, 'error');
  showNotification(`Preview failed: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

async function doSimpleScreenApply() {
 const level = simpleScreenSelectedLevel();
 const fraction = simpleScreenFraction(level);
 const query = simpleScreenQuery();
 const btn = document.getElementById('simple-screen-apply-btn');
 const triageBtn = document.getElementById('screen-triage-apply-btn');
 const loadBtn = isSimpleScreenTriageOpen() && triageBtn ? triageBtn : btn;
 if (!query) {
  showNotification('Enter a research question first.', 'error');
  return;
 }
 setLoading(loadBtn, true);
 setStatus('simple-screen-status', 'Setting aside the least related papers…', 'info');
 try {
  _simpleScreenEnsureQuery(query);
  let data = _simpleScreenCounts[level];
  if (!data) {
   data = await apiCall('/api/screening/quick-preview', {
    method: 'POST',
    body: withPageLibrary({ query, fraction }),
   });
   _simpleScreenCounts[level] = data;
  }
  const candidates = data.candidates || [];
  let items;
  if (_screenTriageMatches()) {
   items = _simpleTriageGo.map((c) => ({
    article_id: c.article_id,
    source: c.source,
   }));
  } else {
   items = candidates.map((c) => ({
    article_id: c.article_id,
    source: c.source,
   }));
  }
  items = _mergeSimpleScreenTypeAside(items, data);
  if (!items.length) {
   setStatus('simple-screen-status', 'Nothing to set aside at this level.', 'info');
   return;
  }
  const applied = await apiCall('/api/screening', {
   method: 'POST',
   body: { items, action: 'exclude', reason: 'low_relevance' },
  });
  saveSimpleScreenUndoItems(items);
  _simpleScreenCandidates = [];
  _simpleTriageUsed = false;
  closeSimpleScreenTriage();
  const n = applied.count || items.length;
  const decision = document.getElementById('simple-screen-levels');
  const actions = document.getElementById('simple-screen-actions');
  if (decision) decision.hidden = true;
  if (actions) actions.hidden = true;
  setSimpleScreenConfirmVisible(false);
  setSimpleScreenStripOutcome(
   `Set aside ${n} paper${n === 1 ? '' : 's'}`,
   { undo: true }
  );
  const preview = document.getElementById('simple-screen-preview');
  if (preview) {
   preview.hidden = true;
   preview.classList.add('u-hidden');
  }
  setStatus('simple-screen-status', `Set aside ${n} paper(s). You can undo once.`, 'success');
  showNotification(`Set aside ${n} paper(s).`, 'success');
  setSimpleScreenGotoVisible(true);
  await refreshSimpleScreeningCard();
  updateNavStats();
  copyScreenQuestionToSearch();
  setSimpleScreenGatePending(false);
  closeSimpleScreenModal({ force: true });
  const openBtn = document.getElementById('simple-screen-open-btn');
  if (openBtn) openBtn.hidden = true;
  if (typeof finishSimpleWaitThenSearch === 'function') {
   finishSimpleWaitThenSearch();
  }
 } catch (e) {
  setStatus('simple-screen-status', `Could not set papers aside: ${e.message}`, 'error');
  showNotification(`Could not set papers aside: ${e.message}`, 'error');
 } finally {
  setLoading(loadBtn, false);
 }
}

function doSimpleScreenSkip() {
 setSimpleScreenSkipped(true);
 clearSimpleScreenUndoItems();
 closeSimpleScreenTriage();
 const decision = document.getElementById('simple-screen-levels');
 const actions = document.getElementById('simple-screen-actions');
 const preview = document.getElementById('simple-screen-preview');
 if (decision) decision.hidden = true;
 if (actions) actions.hidden = true;
 setSimpleScreenConfirmVisible(false);
 if (preview) {
  preview.hidden = true;
  preview.classList.add('u-hidden');
 }
 setSimpleScreenStripOutcome('');
 setStatus('simple-screen-status', '', 'info');
 setSimpleScreenGotoVisible(true);
 copyScreenQuestionToSearch();
 setSimpleScreenGatePending(false);
 closeSimpleScreenModal({ force: true });
 const openBtn = document.getElementById('simple-screen-open-btn');
 if (openBtn) openBtn.hidden = false;
 if (typeof finishSimpleWaitThenSearch === 'function') {
  finishSimpleWaitThenSearch();
 }
 const hint = document.getElementById('simple-screen-dock-hint');
 if (hint) hint.hidden = true;
}

async function doSimpleScreenUndo() {
 const btn = document.getElementById('simple-screen-undo-btn');
 setLoading(btn, true);
 try {
  // Cache first; otherwise one corpus request (errors surface to catch).
  let items = loadSimpleScreenUndoItems();
  if (!items || !items.length) {
   const data = await apiCall('/api/screening/excluded?reason=low_relevance');
   items = (data && data.items) || [];
   if (items.length) saveSimpleScreenUndoItems(items);
  }
  if (!items.length) {
   showNotification('Nothing to undo.', 'info');
   return;
  }
  await apiCall('/api/screening', {
   method: 'POST',
   body: { items, action: 'include' },
  });
  const n = items.length;
  clearSimpleScreenUndoItems();
  setSimpleScreenSkipped(false);
  _simpleScreenCounts = { low: null, medium: null, high: null };
  setStatus('simple-screen-status', `Restored ${n} paper(s).`, 'success');
  showNotification(`Restored ${n} paper(s).`, 'success');
  await refreshSimpleScreeningCard();
  updateNavStats();
 } catch (e) {
  setStatus('simple-screen-status', `Undo failed: ${e.message}`, 'error');
  showNotification(`Undo failed: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

/** "N duplicate copies already set aside" inside Narrow it down (audit 19.3). */
function renderSimpleScreenDuplicates(count) {
 const line = document.getElementById('simple-screen-dups');
 const msg = document.getElementById('simple-screen-dups-msg');
 if (!line || !msg) return;
 line.hidden = count <= 0;
 if (count > 0) {
  msg.textContent = count === 1
   ? '1 duplicate copy already set aside (the best copy stays).'
   : `${count} duplicate copies already set aside (the best copy of each stays).`;
 }
}

async function doSimpleScreenDuplicatesUndo() {
 const btn = document.getElementById('simple-screen-dups-undo');
 setLoading(btn, true);
 try {
  const lib = typeof pageLibraryId === 'function' ? pageLibraryId() : '';
  const data = await apiCall('/api/screening/excluded?reason=duplicate'
   + (lib ? '&library_id=' + encodeURIComponent(lib) : ''));
  const items = ((data && data.items) || []).map((it) => ({
   article_id: it.article_id, source: it.source,
  }));
  if (!items.length) {
   renderSimpleScreenDuplicates(0);
   return;
  }
  await apiCall('/api/screening', {
   method: 'POST',
   body: withPageLibrary({ items, action: 'include' }),
  });
  _simpleScreenCounts = { low: null, medium: null, high: null };
  await refreshSimpleScreeningCard();
  updateNavStats();
  // After the refresh, which redraws the counts and clears the status line.
  const n = items.length;
  setStatus(
   'simple-screen-status',
   `Brought back ${n} duplicate cop${n === 1 ? 'y' : 'ies'}.`,
   'success'
  );
 } catch (e) {
  setStatus('simple-screen-status', `Undo failed: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

/** Re-prepare's pre-fill: the question already typed, never the fetch topic
 * (the saved fetch preferences hold the topic too). */
function getResearchQuestionCandidate() {
 const screen = document.getElementById('simple-screen-query');
 return (screen && screen.value.trim()) || '';
}

/** Write a verified question into the screening field; the topic stays. */
function applyVerifiedResearchQuestion(query) {
 const q = String(query || '').trim();
 if (!q) return;
 const screen = document.getElementById('simple-screen-query');
 if (screen) screen.value = q;
 // Counts were for the old question — force a re-rank after re-prepare.
 _simpleScreenCounts = { low: null, medium: null, high: null };
}

/**
 * Simple re-prepare dialog: research question lives *in the same popup* as
 * only-new / redo-all (not a separate step). Sets #only-missing + verified
 * query. Returns false if cancelled.
 */
async function resolveSimplePrepareModeBeforeRequest() {
 const models = _simplePrepareModelCatalog();
 if (!models.length) {
  showNotification('The embedding model list is unavailable. Reload Search and try again.', 'error');
  return false;
 }
 const current = getResearchQuestionCandidate();
 let selectedModel = _simplePreferredPrepareModel(models);
 if (typeof openSiteForm !== 'function') return false;
 const result = await openSiteForm({
  title: 'Re-prepare papers for search',
  message: 'Keep your research question, choose which papers to prepare, and optionally change the embedding model.',
  confirmLabel: 'Re-prepare',
  cancelLabel: 'Cancel',
  fields: [
   {id: 'research_question', label: 'Your research question', type: 'text', value: current, placeholder: 'e.g., climate change effects on ecosystems'},
   {id: 'prepare_scope', label: 'Papers to prepare', type: 'choice', value: 'only_missing', options: [
    {value: 'only_missing', label: 'Only missing papers', hint: 'Recommended'},
    {value: 'all', label: 'Redo all papers'},
   ]},
  ],
  onReady: (root) => {
   const fields = root.querySelector('.lra-modal-fields');
   if (!fields) return;
   const disclosure = document.createElement('details');
   disclosure.className = 'advanced-details lra-modal-choice';
   disclosure.id = 'simple-reprepare-model-options';
   const summary = document.createElement('summary');
   summary.textContent = 'Embedding model';
   const body = document.createElement('div');
   body.className = 'advanced-body';
   const label = document.createElement('label');
   label.htmlFor = 'simple-prepare-model';
   label.textContent = 'Analysis model';
   const select = document.createElement('select');
   select.id = 'simple-prepare-model';
   select.className = 'lra-modal-input';
   models.forEach((model) => {
    const option = document.createElement('option');
    option.value = model.value;
    option.textContent = model.label;
    if (model.value === selectedModel) option.selected = true;
    select.append(option);
   });
   body.append(label, select);
   disclosure.append(summary, body);
   fields.append(disclosure);
  },
  validate: (values) => {
   if (!String(values.research_question || '').trim()) return 'Please confirm your research question before re-preparing.';
   const chosen = _simpleSelectedPrepareModel();
   if (!models.some((model) => model.value === chosen)) return 'Choose an available embedding model.';
   // openSiteForm removes its dialog before resolving the promise, so capture
   // the selection while validation still has access to the live field.
   selectedModel = chosen;
   return '';
  },
 });
 if (result == null) return false;
 const question = String(result.research_question || '').trim();
 const model = selectedModel;
 const onlyMissing = result.prepare_scope !== 'all';
 applyVerifiedResearchQuestion(question);
 const box = document.getElementById('only-missing');
 if (box) box.checked = onlyMissing;
 _simpleOnlyMissing = onlyMissing;
 if (typeof setConfirmedSimplePreparePreferences === 'function') {
  setConfirmedSimplePreparePreferences(model, onlyMissing);
 }
 return {model, onlyMissing, question};
}

function _simplePrepareModelCatalog() {
 let injected = [];
 const catalog = document.getElementById('embedding-model-catalog');
 try {
  const raw = catalog && (catalog.getAttribute('data-models') || (catalog.dataset && catalog.dataset.models));
  const parsed = JSON.parse(raw || '[]');
  if (Array.isArray(parsed)) injected = parsed;
 } catch (e) { /* the rendered select remains a catalog-backed fallback */ }
 const select = document.getElementById('embedding-model');
 const fromSelect = select && select.options ? Array.from(select.options).map((option) => ({
  value: String(option.value || ''), label: String(option.textContent || option.label || option.value || ''),
 })) : [];
 const list = injected.length ? injected : fromSelect;
 const seen = new Set();
 return list.filter((model) => {
  if (!model || !String(model.value || '').trim() || seen.has(String(model.value))) return false;
  seen.add(String(model.value));
  return true;
 }).map((model) => ({value: String(model.value), label: String(model.label || model.value)}));
}

function _simplePreferredPrepareModel(models) {
 const current = document.getElementById('embedding-model');
 let preferred = current && current.value;
 if (!preferred) {
  try {
   const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null');
   if (prefs && prefs.modelManual && prefs.model) preferred = prefs.model;
  } catch (e) { /* use topic recommendation below */ }
 }
 if (!preferred && typeof recommendModel === 'function') preferred = recommendModel();
 return models.some((model) => model.value === preferred) ? preferred : models[0].value;
}

function _simpleSelectedPrepareModel() {
 const select = document.getElementById('simple-prepare-model');
 return select ? String(select.value || '') : '';
}

// Per-database cap presets for the Simple pre-fetch dialog. 100 is the
// long-standing default; a student can still write any number from 10 to 2000.
var FETCH_COUNT_PRESETS = [25, 50, 100, 200];

async function resolveSimpleFetchModeBeforeRequest(opts) {
 let total = Number(_lastTotalArticles) || 0;
 try {
  const stats = await apiCall('/api/statistics');
  if (stats && stats.total_articles != null) {
   total = Number(stats.total_articles) || 0;
   _lastTotalArticles = total;
  }
 } catch (err) {
  console.warn('Could not load paper count for fetch dialog:', err);
 }
 const setMode = (value) => {
  const radio = document.querySelector(`input[name="fetch-mode"][value="${value}"]`);
  if (radio) radio.checked = true;
  syncOnlyMissingFromFetchMode();
 };
 // Empty collection: the fresh-or-add choice is meaningless, so only the
 // count is asked. Start over already asked it, so it is not asked twice.
 if (total <= 0) setMode('replace');
 const askMode = total > 0 && !(opts && opts.modeAlreadyPicked);
 if (typeof openSiteForm !== 'function') {
  // Fallback: keep the hidden fields' values if the modal helper is missing.
  return true;
 }
 const maxEl = document.getElementById('fetch-max');
 const current = parseInt(maxEl && maxEl.value, 10) || 100;
 const preset = FETCH_COUNT_PRESETS.includes(current) ? String(current) : '';
 const sourceCheckboxes = Array.from(
  document.querySelectorAll('#source-option-grid input[type="checkbox"]')
 );
 const sourceOptions = sourceCheckboxes.map((checkbox) => {
  const card = checkbox.closest('.source-option');
  const name = card && card.querySelector('.source-name-label');
  const description = card && card.querySelector('.source-desc');
  return {
   value: checkbox.value,
   label: (name && name.textContent.trim()) || checkbox.value,
   hint: description && description.textContent.trim(),
  };
 });
 const selectedSources = sourceCheckboxes.filter((checkbox) => checkbox.checked)
  .map((checkbox) => checkbox.value);
 const fetchEmail = document.getElementById('fetch-email');
 const fields = [
  {
   id: 'count',
   type: 'choice',
   label: 'How many papers from each database?',
   value: preset,
   options: [
    { value: '25', label: '25', hint: 'quick look' },
    { value: '50', label: '50', hint: 'a solid start' },
    { value: '100', label: '100', hint: 'usual' },
    { value: '200', label: '200', hint: 'thorough' },
   ],
  },
  {
   id: 'custom',
   type: 'number',
   label: 'Or write your own (10 to 2000)',
   value: preset ? '' : String(current),
   placeholder: 'e.g. 150',
   min: 10,
   max: 2000,
   step: 10,
  },
 ];
 if (askMode) {
  const nLabel = total === 1 ? '1 paper' : `${total} papers`;
  const currentMode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
  fields.push({
   id: 'mode',
   type: 'choice',
   label: `You already have ${nLabel}. What should happen to them?`,
   value: currentMode,
   options: [
    { value: 'replace', label: 'Start fresh', hint: 'papers that do not come back are removed, with their notes' },
    { value: 'append', label: 'Add to them', hint: 'keep everything you have' },
   ],
  });
 }
 fields.push(
  {
   id: 'sources',
   type: 'multi-choice',
   label: 'Databases to search',
   value: selectedSources,
   options: sourceOptions,
  },
  {
   id: 'contact_email',
   type: 'email',
   label: 'Contact email for PubMed and Europe PMC (optional)',
   value: fetchEmail ? fetchEmail.value : '',
   placeholder: 'you@example.edu',
  }
 );
 const choice = await openSiteForm({
  title: 'Before we fetch',
  message: 'Each database returns up to this many papers. More takes longer to fetch and prepare, and leaves more to screen.',
  confirmLabel: 'Find articles',
  fields,
  onReady: (root) => {
   const fieldsRoot = root.querySelector('.lra-modal-fields');
   const sourcesField = root.querySelector('[data-field="sources"]');
   const emailField = root.querySelector('[data-field="contact_email"]');
   if (!fieldsRoot || !sourcesField || !emailField) return;
   const disclosure = document.createElement('details');
   disclosure.id = 'simple-fetch-databases';
   disclosure.className = 'advanced-details lra-modal-choice';
   const summary = document.createElement('summary');
   summary.textContent = 'Databases';
   disclosure.append(summary, sourcesField, emailField);
   fieldsRoot.append(disclosure);

   const syncEmailVisibility = () => {
    const selected = Array.from(
     sourcesField.querySelectorAll('input[type="checkbox"]:checked')
    ).map((input) => input.value);
    emailField.hidden = !selected.includes('pubmed') && !selected.includes('europepmc');
   };
   sourcesField.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    input.addEventListener('change', syncEmailVisibility);
   });
   syncEmailVisibility();
  },
  validate: (vals) => {
   const custom = String(vals.custom || '').trim();
   if (custom) {
    const n = parseInt(custom, 10);
    if (!Number.isFinite(n) || n < 10 || n > 2000) return 'Write a number from 10 to 2000.';
   } else if (!vals.count) {
    return 'Pick how many papers from each database, or write your own number.';
   }
   if (askMode && !vals.mode) return 'Choose what happens to the papers you already have.';
   if (!Array.isArray(vals.sources) || vals.sources.length === 0) {
    return 'Choose at least one database to search.';
   }
   return '';
  },
 });
 if (choice == null) return false;
 const custom = String(choice.custom || '').trim();
 const count = custom ? parseInt(custom, 10) : parseInt(choice.count, 10);
 if (maxEl && Number.isFinite(count)) maxEl.value = String(count);
 const pickedSources = new Set(
  Array.isArray(choice.sources) ? choice.sources.map((source) => String(source)) : []
 );
 sourceCheckboxes.forEach((checkbox) => {
  checkbox.checked = pickedSources.has(checkbox.value);
 });
 sourceCheckboxes.forEach((checkbox) => {
  checkbox.dispatchEvent(new Event('change', { bubbles: true }));
 });
 if (fetchEmail && typeof choice.contact_email === 'string') {
  fetchEmail.value = choice.contact_email;
  fetchEmail.dispatchEvent(new Event('input', { bubbles: true }));
  fetchEmail.dispatchEvent(new Event('change', { bubbles: true }));
 }
 if (askMode) {
  const picked = choice.mode === 'append' ? 'append' : 'replace';
  setMode(picked);
  _persistFetchMode(picked);
 }
 if (typeof saveFetchPrefs === 'function') saveFetchPrefs();
 return true;
}


function _onSearchPage() {
 return !!(document.getElementById('search-workbench') || document.getElementById('results-section'));
}

function updateSimpleToolsStrip(stats) {
 const strip = document.getElementById('simple-tools-strip') || document.getElementById('simple-screen-dock');
 if (!strip) return;
 const total = Number(stats && stats.total_articles) || 0;
 _lastTotalArticles = total;
 const sources = (stats && stats.sources) || {};
 const sourceCount = Object.keys(sources).filter((id) => (Number(sources[id]) || 0) > 0).length;
 const countEl = document.getElementById('simple-tools-count');
 if (countEl) {
  const papers = total === 1 ? '1 paper' : `${total} papers`;
  const src = sourceCount
   ? ` · ${sourceCount} source${sourceCount === 1 ? '' : 's'}`
   : '';
  countEl.textContent = papers + src;
  countEl.hidden = total <= 0;
  if (countEl.tagName === 'BUTTON' || countEl.getAttribute('type') === 'button') {
   countEl.disabled = total <= 0;
  }
 }
 const show = !!(total > 0 && !_collectQueryOn());
 strip.hidden = !show;
}

function openSimpleSourceReport(stats) {
 if (typeof openCollectionReport === 'function') return openCollectionReport();
 const sources = (stats && stats.sources) || {};
 const lines = Object.keys(sources)
  .filter((id) => (Number(sources[id]) || 0) > 0)
  .sort((a, b) => (Number(sources[b]) || 0) - (Number(sources[a]) || 0))
  .map((id) => {
   const name = typeof getSourceName === 'function' ? getSourceName(id) : id;
   return `${name}: ${sources[id]}`;
  });
 const message = _lastFetchSourceReportText
  || (lines.length ? lines.join('\n') : 'No source counts yet.');
 if (typeof openSiteAlert === 'function') {
  openSiteAlert({ title: 'What we fetched', message });
 } else {
  showNotification(message.replace(/\n/g, ' · '), 'info');
 }
}

async function simpleToolsReprepare() {
 const status = document.getElementById('simple-tools-status');
 const btn = document.getElementById('simple-tools-reprepare-btn');
 if (status) status.textContent = 'Preparing papers…';
 if (btn) btn.disabled = true;
 try {
  if (typeof doCreateEmbeddings !== 'function') throw new Error('Prepare action is unavailable. Reload Search and try again.');
  const result = await doCreateEmbeddings({ fromSimpleReprepare: true });
  // Success or cancel, "Preparing papers…" is over either way (audit 19.15).
  if (status) status.textContent = result ? 'Papers are ready for search.' : '';
 } catch (e) {
  if (status) status.textContent = '';
  // doCreateEmbeddings already reports its own errors.
  if (typeof doCreateEmbeddings !== 'function') showNotification(`Could not re-prepare: ${e.message}`, 'error');
 } finally {
  if (btn) btn.disabled = false;
 }
}

function _waitForEmbedJob(timeoutMs) {
 timeoutMs = timeoutMs || 600000;
 const started = Date.now();
 return new Promise((resolve, reject) => {
  const tick = async () => {
   try {
    if (Date.now() - started > timeoutMs) {
     reject(new Error('Timed out waiting for prepare'));
     return;
    }
    const data = await apiCall(progressUrl());
    const p = data && data.embed;
    if (p && p.active) {
     setTimeout(tick, 400);
     return;
    }
    if (p && p.error) {
     reject(new Error(p.error));
     return;
    }
    resolve((p && p.result) || {});
   } catch (e) {
    reject(e);
   }
  };
  setTimeout(tick, 300);
 });
}

/** After Start over, the next prepare must not revive search or Narrow it down. */
var _resetAfterStartOver = false;

/** Start over: drop last search + Narrow it down. Notes/stars/AI key points stay. */
async function resetSearchAndNarrowingForStartOver() {
 _resetAfterStartOver = true;
 if (typeof clearSearchWorkspace === 'function') {
  clearSearchWorkspace();
 }
 setSimpleScreenSkipped(false);
 clearSimpleScreenUndoItems();
 _simpleScreenCounts = { low: null, medium: null, high: null };
 const screen = document.getElementById('simple-screen-query');
 if (screen) screen.value = '';
 try {
  const excl = await apiCall('/api/screening/excluded?reason=low_relevance');
  const items = (excl && excl.items) || [];
  if (items.length) {
   await apiCall('/api/screening', {
    method: 'POST',
    body: { items, action: 'include', reason: 'low_relevance' },
   });
  }
 } catch (e) {
  console.warn('Could not reset Narrow it down after start over:', e);
 }
}

async function simpleToolsStartOver() {
 const total = Number(_lastTotalArticles) || 0;
 if (total > 0) {
  if (typeof openSiteConfirm !== 'function') return;
  const ok = await openSiteConfirm({
   title: 'Start over?',
   message:
    'Remove papers that are not starred and have no note. '
    + 'Starred papers and papers with notes stay, still ready to search '
    + 'if they were already prepared.',
   confirmLabel: 'Start over',
   cancelLabel: 'Cancel',
   danger: true,
  });
  if (!ok) return;
 }
 const status = document.getElementById('simple-tools-status');
 const btn = document.getElementById('simple-tools-startover-btn');
 if (status) status.textContent = 'Keeping starred and noted papers…';
 if (btn) btn.disabled = true;
 try {
  const result = await apiCall('/api/start-over', { method: 'POST', body: withPageLibrary({}) });
  const kept = Number(result && result.remaining) || 0;
  const deleted = Number(result && result.deleted) || 0;
  _lastTotalArticles = kept;
  if (typeof updateNavStats === 'function') updateNavStats();
  if (typeof refreshRailStats === 'function') refreshRailStats();
  if (status) {
   status.textContent = deleted
    ? `Kept ${kept} annotated paper${kept === 1 ? '' : 's'}; removed ${deleted}.`
    : (kept
     ? `Kept ${kept} annotated paper${kept === 1 ? '' : 's'}.`
     : 'Collection cleared.');
  }
  showNotification(
   deleted
    ? `Start over: kept ${kept} starred/noted paper${kept === 1 ? '' : 's'}, removed ${deleted}.`
    : (kept
     ? `Start over: kept ${kept} annotated paper${kept === 1 ? '' : 's'}.`
     : 'Collection cleared for a new search.'),
   'success'
  );
  let stats = { total_articles: kept, articles_with_embeddings: 0 };
  try {
   stats = await apiCall('/api/statistics');
   _lastTotalArticles = Number(stats.total_articles) || kept;
  } catch (e) { /* use counts from the start-over response */ }
  const ready = Number(stats.articles_with_embeddings) || 0;
  // Kept papers that are already prepared stay on Search. Do not force
  // ?collect=1 or undo Narrow it down — those steps already happened.
  if (kept > 0 && ready > 0) {
   if (typeof clearSearchWorkspace === 'function') clearSearchWorkspace();
  } else {
   await resetSearchAndNarrowingForStartOver();
  }
  if (_onSearchPage()) {
   if (kept <= 0 || ready <= 0) {
    setCollectQueryOnUrl();
    if (typeof _simpleFetchUnlocked !== 'undefined') {
     _simpleFetchUnlocked = true;
     _simpleFetchModePicked = true;
    }
   }
   if (typeof updateSimpleFetchLock === 'function') updateSimpleFetchLock();
   syncSimpleOnePageState(stats);
   if (typeof updateSimpleToolsStrip === 'function') updateSimpleToolsStrip(stats);
   if (typeof updatePrepareSectionVisibility === 'function') {
    updatePrepareSectionVisibility(_lastTotalArticles, {
     readyArticles: ready,
    });
   }
   if (kept > 0 && ready > 0) {
    const q = document.getElementById('query-text');
    if (q && typeof q.focus === 'function') q.focus();
   } else {
    const q = document.getElementById('fetch-query');
    if (q) {
     q.focus();
     if (typeof q.select === 'function') q.select();
    }
   }
   return;
  }
  window.location.href = (kept > 0 && ready > 0) ? '/search' : '/search?collect=1';
 } catch (e) {
  if (status) status.textContent = '';
  showNotification(`Could not start over: ${e.message}`, 'error');
 } finally {
  if (btn) btn.disabled = false;
 }
}

function wireSimpleToolsStrip() {
 const reprepare = document.getElementById('simple-tools-reprepare-btn');
 const startover = document.getElementById('simple-tools-startover-btn');
 const countEl = document.getElementById('simple-tools-count');
 if (reprepare && reprepare.dataset.wired !== '1') {
  reprepare.dataset.wired = '1';
  reprepare.addEventListener('click', simpleToolsReprepare);
 }
 if (startover && startover.dataset.wired !== '1') {
  startover.dataset.wired = '1';
  startover.addEventListener('click', simpleToolsStartOver);
 }
 if (countEl && countEl.dataset.wired !== '1') {
  countEl.dataset.wired = '1';
  countEl.addEventListener('click', () => {
   apiCall('/api/statistics').then(openSimpleSourceReport).catch(() => {
    openSimpleSourceReport(null);
   });
  });
 }
 // Set aside list. Wired here, not in the screening card, so it works before
 // the papers are prepared (the card's own wiring waits for embeddings).
 const once = (el, handler) => {
  if (!el || el.dataset.wired === '1') return;
  el.dataset.wired = '1';
  el.addEventListener('click', handler);
 };
 once(document.getElementById('simple-set-aside-btn'), openSimpleSetAsideModal);
 once(document.getElementById('funnel-set-aside-btn'), openSimpleSetAsideModal);
 document.querySelectorAll('[data-set-aside-close]').forEach((el) => {
  once(el, (ev) => {
   ev.preventDefault();
   closeSimpleSetAsideModal();
  });
 });
 once(document.getElementById('simple-set-aside-groups'), onSetAsideListClick);
 once(document.getElementById('simple-set-aside-reasons'), onSetAsideReasonClick);
 once(document.getElementById('simple-set-aside-reason-undo'), undoSetAsideReason);
 once(document.getElementById('simple-set-aside-again'), doSetAsideAgain);
}

document.addEventListener('DOMContentLoaded', () => {
 wireSimpleToolsStrip();
 if (_onSearchPage()) {
  apiCall('/api/statistics').then((stats) => {
   syncSimpleOnePageState(stats);
   updateSimpleToolsStrip(stats);
   if (typeof refreshSimpleScreeningCard === 'function') {
    refreshSimpleScreeningCard();
   }
  }).catch(() => { /* ignore */ });
 }

});
