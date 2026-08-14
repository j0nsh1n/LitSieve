// Simple-mode tools shared by Data Management and Search.
// Screening popup, re-prepare / start-over dialogs, Search tools strip,
// and the one-page collect/search state. Search also loads data_management.js
// for fetch/topics (collect UI lives on /search).

var _lastTotalArticles = (typeof _lastTotalArticles === 'number') ? _lastTotalArticles : 0;
var _simpleOnlyMissing = true;
var _lastFetchSourceReportText = '';

function _isPipelineBusy() {
 return typeof _pipelineBusy === 'boolean' && _pipelineBusy;
}

/** Simple Search: collect (empty / unprepared / ?collect=1) vs rank/export. */
function wantsSimpleCollectView(stats) {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) return false;
 if (_collectQueryOn()) return true;
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

function syncSimpleOnePageState(stats) {
 const collect = document.getElementById('search-collect');
 if (!collect) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const ready = Number(stats && stats.articles_with_embeddings) || 0;
 const total = Number(stats && stats.total_articles) || _lastTotalArticles || 0;
 const showCollect = simple && wantsSimpleCollectView(stats);
 const forceCollect = simple && _collectQueryOn();
 collect.hidden = !showCollect;
 collect.classList.toggle('has-papers', simple && total > 0 && !forceCollect);
 collect.classList.toggle('is-startover', !!forceCollect);
 if (document.body) {
  document.body.classList.toggle('simple-collecting', showCollect);
 }
 if (typeof updateNavStepNumbers === 'function') updateNavStepNumbers();
 const empty = document.getElementById('search-empty-state');
 if (empty) {
  // Advanced empty-state only. Simple uses collect.
  if (simple) empty.hidden = true;
 }
 const work = document.getElementById('search-workbench');
 if (work) {
  work.hidden = !ready || showCollect;
 }
 if (showCollect) {
  const card = document.getElementById('simple-screening-card');
  if (card) card.hidden = true;
 }
 if (typeof updateSearchWorkVisibility === 'function' && !showCollect) {
  updateSearchWorkVisibility(stats || { articles_with_embeddings: ready });
 }
 if (typeof updateSimpleToolsStrip === 'function') {
  updateSimpleToolsStrip(stats);
 }
}

function setNextStepVisible(visible) {
 if (typeof window._lraSetNextStepVisible === 'function') {
  window._lraSetNextStepVisible(visible);
  return;
 }
 const el = document.getElementById('fetch-next-step');
 if (!el) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const show = !!(visible && simple);
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
let _simpleScreenCandidates = [];
let _simpleScreenLastItems = null;
/** Session-only: skip hides the decision UI until reload (pending is corpus-derived). */
let _simpleScreenSkippedSession = false;
// Last Narrow-it-down exclusion set (per library) so Undo survives a soft reload.
// Corpus API is the source of truth after restart; this is a fast path.
const SIMPLE_SCREEN_UNDO_KEY = 'lra_simple_screen_undo_v1';

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
 if (!lib) return;
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

let _simpleScreenWired = false;

function simpleScreenSelectedLevel() {
 const el = document.querySelector('input[name="simple-screen-level"]:checked');
 return (el && el.value) || 'medium';
}

function simpleScreenFraction(level) {
 return SIMPLE_SCREEN_LEVELS[level] != null ? SIMPLE_SCREEN_LEVELS[level] : 0.25;
}

function simpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 if (el && el.value.trim()) return el.value.trim();
 const fetchQ = document.getElementById('fetch-query');
 return (fetchQ && fetchQ.value.trim()) || '';
}

function prefillSimpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 if (!el) return;
 // Always surface a candidate so the confirm box is never empty when we know one,
 // but do not overwrite if the student already edited the field.
 if (el.value.trim()) return;
 try {
  const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null');
  if (prefs && prefs.query) {
   el.value = prefs.query;
   return;
  }
 } catch (e) { /* ignore */ }
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ && fetchQ.value.trim()) el.value = fetchQ.value.trim();
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

function closeSimpleScreenModal() {
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
 }
 _simpleScreenModalOpener = document.activeElement instanceof HTMLElement
  ? document.activeElement
  : document.getElementById('simple-screen-open-btn');
 if (!document.body.classList.contains('lra-modal-open')) {
  const scrollY = window.scrollY || window.pageYOffset || 0;
  document.body.dataset.lraScrollY = String(scrollY);
  document.body.style.top = `-${scrollY}px`;
  document.body.classList.add('lra-modal-open');
  modal.setAttribute('data-owns-scroll-lock', '1');
 }
 modal.hidden = false;
 prefillSimpleScreenQuery();
 loadSimpleScreenCounts();

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
 const card = document.getElementById('simple-screening-card');
 if (!card) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 if (!simple || _isPipelineBusy()) {
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
  const lowRel = Number(
   report && report.excluded && report.excluded.low_relevance
  ) || 0;
  const total = Number(stats.total_articles) || 0;

  if (ready <= 0) {
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
   if (outcome) {
    outcome.hidden = false;
    outcome.classList.remove('u-hidden');
   }
   if (outcomeMsg) {
    outcomeMsg.textContent =
     `Set aside ${lowRel} paper${lowRel === 1 ? '' : 's'} as less related to your question.`;
   }
   // Always offer a small Undo when low_relevance exclusions exist (corpus-backed).
   if (undoBtn) {
    undoBtn.hidden = false;
    undoBtn.textContent = 'Undo';
   }
   if (openBtn) openBtn.hidden = true;
   if (dockHint) dockHint.hidden = true;
   // Warm the undo cache in the background; the button stays visible either way.
   fetchLowRelevanceUndoItems();
   setSimpleScreenGotoVisible(true);
   return;
  }

  if (isSimpleScreenSkipped()) {
   if (decision) decision.hidden = true;
   if (actions) actions.hidden = true;
   setSimpleScreenConfirmVisible(false);
   if (outcome) {
    outcome.hidden = false;
    outcome.classList.remove('u-hidden');
   }
   if (outcomeMsg) {
    outcomeMsg.textContent = 'Screening skipped — you can still search everything you fetched.';
   }
   if (undoBtn) undoBtn.hidden = true;
   if (openBtn) openBtn.hidden = false;
   if (dockHint) dockHint.hidden = true;
   setSimpleScreenGotoVisible(true);
   return;
  }

  // Pending: confirm question + levels + actions; fetch counts once.
  if (decision) decision.hidden = false;
  if (actions) actions.hidden = false;
  setSimpleScreenConfirmVisible(true);
  if (outcome) {
   outcome.hidden = true;
   outcome.classList.add('u-hidden');
  }
  if (undoBtn) undoBtn.hidden = true;
  if (openBtn) openBtn.hidden = false;
  if (dockHint) dockHint.hidden = false;
  setSimpleScreenGotoVisible(false);
  const totalEl = document.getElementById('simple-screen-total');
  if (totalEl) {
   totalEl.hidden = false;
   totalEl.textContent = `${ready} paper${ready === 1 ? '' : 's'} ready to rank`
    + (total > ready ? ` (${total} in collection).` : '.');
  }
  await loadSimpleScreenCounts();
 } catch (e) {
  console.warn('refreshSimpleScreeningCard failed:', e);
  card.hidden = true;
 }
}

async function loadSimpleScreenCounts() {
 const query = simpleScreenQuery();
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
     body: { query, fraction },
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
  queryEl.addEventListener('change', () => {
   _simpleScreenCounts = { low: null, medium: null, high: null };
   loadSimpleScreenCounts();
  });
  queryEl.addEventListener('input', () => {
   clearTimeout(t);
   t = setTimeout(() => {
    _simpleScreenCounts = { low: null, medium: null, high: null };
    loadSimpleScreenCounts();
   }, 600);
  });
 }
 // Radios only switch labels already loaded — no re-fetch.
}

function _simpleScreenEnsureQuery(query) {
 if (_simpleScreenCounts._query !== query) {
  _simpleScreenCounts = { low: null, medium: null, high: null, _query: query };
 }
}

async function doSimpleScreenPreview() {
 const level = simpleScreenSelectedLevel();
 const fraction = simpleScreenFraction(level);
 const query = simpleScreenQuery();
 const btn = document.getElementById('simple-screen-preview-btn');
 const panel = document.getElementById('simple-screen-preview');
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
    body: { query, fraction },
   });
   _simpleScreenCounts[level] = data;
   applySimpleScreenCountLabels();
  }
  const candidates = data.candidates || [];
  _simpleScreenCandidates = candidates;
  if (!panel) return;
  panel.innerHTML = '';
  if (!candidates.length) {
   panel.innerHTML = '<p class="info-text">Nothing to set aside at this level.</p>';
  } else {
   const list = document.createElement('div');
   list.className = 'simple-screen-list';
   candidates.forEach((c) => {
    const row = document.createElement('div');
    row.className = 'quick-screen-row';
    const title = document.createElement('span');
    title.className = 'qs-title';
    title.textContent = c.title || '(no title)';
    const meta = document.createElement('span');
    meta.className = 'qs-meta help-text';
    meta.textContent =
     `${c.year || ''} · ${typeof getSourceName === 'function' ? getSourceName(c.source) : c.source}`;
    row.appendChild(title);
    row.appendChild(meta);
    list.appendChild(row);
   });
   panel.appendChild(list);
  }
  panel.hidden = false;
  panel.classList.remove('u-hidden');
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
 if (!query) {
  showNotification('Enter a research question first.', 'error');
  return;
 }
 setLoading(btn, true);
 setStatus('simple-screen-status', 'Setting aside the least related papers…', 'info');
 try {
  _simpleScreenEnsureQuery(query);
  let data = _simpleScreenCounts[level];
  if (!data) {
   data = await apiCall('/api/screening/quick-preview', {
    method: 'POST',
    body: { query, fraction },
   });
   _simpleScreenCounts[level] = data;
  }
  const candidates = data.candidates || [];
  if (!candidates.length) {
   setStatus('simple-screen-status', 'Nothing to set aside at this level.', 'info');
   return;
  }
  const items = candidates.map((c) => ({
   article_id: c.article_id,
   source: c.source,
  }));
  const applied = await apiCall('/api/screening', {
   method: 'POST',
   body: { items, action: 'exclude', reason: 'low_relevance' },
  });
  saveSimpleScreenUndoItems(items);
  _simpleScreenCandidates = [];
  const n = applied.count || items.length;
  const decision = document.getElementById('simple-screen-levels');
  const actions = document.getElementById('simple-screen-actions');
  if (decision) decision.hidden = true;
  if (actions) actions.hidden = true;
  setSimpleScreenConfirmVisible(false);
  const outcome = document.getElementById('simple-screen-outcome');
  const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
  const undoBtn = document.getElementById('simple-screen-undo-btn');
  if (outcome) {
   outcome.hidden = false;
   outcome.classList.remove('u-hidden');
  }
  if (outcomeMsg) {
   outcomeMsg.textContent = `Set aside ${n} paper${n === 1 ? '' : 's'}.`;
  }
  // Always offer a small Undo after Narrow it down completes (this tab session).
  if (undoBtn) {
   undoBtn.hidden = false;
   undoBtn.textContent = 'Undo';
  }
  const preview = document.getElementById('simple-screen-preview');
  if (preview) {
   preview.hidden = true;
   preview.classList.add('u-hidden');
  }
  setStatus('simple-screen-status', `Set aside ${n} paper(s). You can undo once.`, 'success');
  showNotification(`Set aside ${n} paper(s).`, 'success');
  setSimpleScreenGotoVisible(true);
  updateNavStats();
  closeSimpleScreenModal();
  const openBtn = document.getElementById('simple-screen-open-btn');
  if (openBtn) openBtn.hidden = true;
 } catch (e) {
  setStatus('simple-screen-status', `Could not set papers aside: ${e.message}`, 'error');
  showNotification(`Could not set papers aside: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

function doSimpleScreenSkip() {
 setSimpleScreenSkipped(true);
 clearSimpleScreenUndoItems();
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
 const outcome = document.getElementById('simple-screen-outcome');
 const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 if (outcome) {
  outcome.hidden = false;
  outcome.classList.remove('u-hidden');
 }
 if (outcomeMsg) {
  outcomeMsg.textContent = 'Screening skipped — you can still search everything you fetched.';
 }
 if (undoBtn) undoBtn.hidden = true;
 setStatus('simple-screen-status', '', 'info');
 setSimpleScreenGotoVisible(true);
 closeSimpleScreenModal();
 const openBtn = document.getElementById('simple-screen-open-btn');
 if (openBtn) openBtn.hidden = false;
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

function getResearchQuestionCandidate() {
 const screen = document.getElementById('simple-screen-query');
 if (screen && screen.value.trim()) return screen.value.trim();
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ && fetchQ.value.trim()) return fetchQ.value.trim();
 try {
  const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null');
  if (prefs && prefs.query && String(prefs.query).trim()) {
   return String(prefs.query).trim();
  }
 } catch (e) { /* ignore */ }
 return '';
}

/** Write a verified question into fetch + screening fields and persist prefs. */
function applyVerifiedResearchQuestion(query) {
 const q = String(query || '').trim();
 if (!q) return;
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ) fetchQ.value = q;
 const screen = document.getElementById('simple-screen-query');
 if (screen) screen.value = q;
 // Counts were for the old question — force a re-rank after re-prepare.
 _simpleScreenCounts = { low: null, medium: null, high: null };
 try {
  saveFetchPrefs();
 } catch (e) { /* ignore */ }
}

/**
 * Simple re-prepare dialog: research question lives *in the same popup* as
 * only-new / redo-all (not a separate step). Sets #only-missing + verified
 * query. Returns false if cancelled.
 */
async function resolveSimplePrepareModeBeforeRequest() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) {
  return true;
 }
 let ready = 0;
 let total = Number(_lastTotalArticles) || 0;
 try {
  const stats = await apiCall('/api/statistics');
  ready = Number(stats.articles_with_embeddings) || 0;
  total = Number(stats.total_articles) || total;
  _lastTotalArticles = total;
 } catch (err) {
  console.warn('Could not load prepare counts for dialog:', err);
 }
 const box = document.getElementById('only-missing');
 const current = getResearchQuestionCandidate();

 // Always open a re-prepare dialog with the research question field visible.
 // When nothing is prepared yet, only Continue / Cancel (no scope choice).
 if (typeof openSiteChoice !== 'function') {
  if (ready <= 0 && box) box.checked = true;
  return true;
 }

 const allLabel = total > 0 ? `Redo all ${total}` : 'Redo all papers';
 const choices = ready <= 0
  ? [
   { label: 'Continue', value: 'missing', primary: true },
   { label: 'Cancel', value: null, cancel: true },
  ]
  : [
   { label: 'Only new papers', value: 'missing', primary: true },
   { label: allLabel, value: 'all' },
   { label: 'Cancel', value: null, cancel: true },
  ];

 const result = await openSiteChoice({
  title: 'Re-prepare papers for search',
  message: ready <= 0
   ? 'Check that this research question is still what you want. Edit if needed — Narrow it down will use it next.'
   : 'Check that this research question is still what you want, then choose how much to re-prepare. Only new papers need this most of the time.',
  withInput: true,
  inputLabel: 'Your research question',
  defaultValue: current,
  placeholder: 'e.g., climate change effects on ecosystems',
  requireNonEmpty: true,
  emptyMessage: 'Please confirm your research question before re-preparing.',
  selectAll: !current,
  choices,
 });
 if (result == null) return false;

 // withInput → { value, input }; bare string if modal helper is older.
 let scope = result;
 let question = current;
 if (result && typeof result === 'object' && 'value' in result) {
  scope = result.value;
  question = result.input;
 }
 if (scope == null) return false;

 applyVerifiedResearchQuestion(String(question || '').trim());
 if (box) box.checked = scope !== 'all';
 _simpleOnlyMissing = scope !== 'all';
 return true;
}

async function resolveSimpleFetchModeBeforeRequest() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) {
  return true;
 }
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
 // Empty collection: choice is meaningless — start fresh, no dialog.
 if (total <= 0) {
  setMode('replace');
  return true;
 }
 if (typeof openSiteChoice !== 'function') {
  // Fallback: keep radios (hidden in Simple CSS) if modal helper missing.
  return true;
 }
 const nLabel = total === 1 ? '1 paper' : `${total} papers`;
 const choice = await openSiteChoice({
  title: 'You already have papers',
  message:
   `You already have ${nLabel}. Start fresh keeps notes, stars, and saved AI key points ` +
   `only on papers that come back. Papers that do not return are deleted, ` +
   `along with their notes. Or add these results to what you have?`,
  choices: [
   { label: 'Start fresh', value: 'replace', primary: true },
   { label: 'Add to them', value: 'append' },
   { label: 'Cancel', value: null, cancel: true },
  ],
 });
 if (choice == null) return false;
 const picked = choice === 'append' ? 'append' : 'replace';
 setMode(picked);
 _persistFetchMode(picked);
 return true;
}


function _onSearchPage() {
 return !!(document.getElementById('search-workbench') || document.getElementById('results-section'));
}

function updateSimpleToolsStrip(stats) {
 const strip = document.getElementById('simple-tools-strip') || document.getElementById('simple-screen-dock');
 if (!strip) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
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
 const show = !!(simple && total > 0 && !_collectQueryOn());
 strip.hidden = !show;
}

function openSimpleSourceReport(stats) {
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
 if (typeof resolveSimplePrepareModeBeforeRequest === 'function') {
  const ok = await resolveSimplePrepareModeBeforeRequest();
  if (!ok) return;
 }
 const status = document.getElementById('simple-tools-status');
 const btn = document.getElementById('simple-tools-reprepare-btn');
 if (status) status.textContent = 'Preparing papers…';
 if (btn) btn.disabled = true;
 try {
  const onlyMissing = _simpleOnlyMissing !== false;
  const started = await apiCall('/api/create-embeddings', {
   method: 'POST',
   body: { model: 'general', only_missing: onlyMissing },
  });
  if (started && started.status === 'started' && typeof waitForJob === 'function') {
   await waitForJob('embed', null, null, null, null);
  } else if (started && started.status === 'started') {
   await _waitForEmbedJob();
  }
  if (status) status.textContent = 'Papers are ready.';
  showNotification('Papers are ready for search.', 'success');
  if (typeof refreshSimpleScreeningCard === 'function') {
   await refreshSimpleScreeningCard();
  }
  if (typeof loadPageData === 'function') {
   await loadPageData();
  } else {
   const stats = await apiCall('/api/statistics');
   updateSimpleToolsStrip(stats);
  }
 } catch (e) {
  if (status) status.textContent = '';
  showNotification(`Could not re-prepare: ${e.message}`, 'error');
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
    const data = await apiCall('/api/progress');
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
    + 'Starred papers and papers with notes stay. You can search again after this.',
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
  const result = await apiCall('/api/start-over', { method: 'POST', body: {} });
  const kept = Number(result && result.remaining) || 0;
  const deleted = Number(result && result.deleted) || 0;
  _lastTotalArticles = kept;
  if (typeof updateNavStats === 'function') updateNavStats();
  await resetSearchAndNarrowingForStartOver();
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
  if (_onSearchPage()) {
   setCollectQueryOnUrl();
   if (typeof _simpleFetchUnlocked !== 'undefined') {
    _simpleFetchUnlocked = true;
    _simpleFetchModePicked = true;
   }
   if (typeof updateSimpleFetchLock === 'function') updateSimpleFetchLock();
   try {
    const stats = await apiCall('/api/statistics');
    _lastTotalArticles = Number(stats.total_articles) || kept;
    syncSimpleOnePageState(stats);
    if (typeof updateSimpleToolsStrip === 'function') updateSimpleToolsStrip(stats);
    if (typeof updatePrepareSectionVisibility === 'function') {
     updatePrepareSectionVisibility(_lastTotalArticles, {
      readyArticles: Number(stats.articles_with_embeddings) || 0,
     });
    }
   } catch (e) {
    syncSimpleOnePageState({
     total_articles: kept,
     articles_with_embeddings: 0,
    });
   }
   const q = document.getElementById('fetch-query');
   if (q) {
    q.focus();
    if (typeof q.select === 'function') q.select();
   }
   return;
  }
  window.location.href = '/search?collect=1';
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
}

document.addEventListener('DOMContentLoaded', () => {
 wireSimpleToolsStrip();
 if (typeof isSimpleMode === 'function' && isSimpleMode() && _onSearchPage()) {
  apiCall('/api/statistics').then((stats) => {
   syncSimpleOnePageState(stats);
   updateSimpleToolsStrip(stats);
   if (typeof refreshSimpleScreeningCard === 'function') {
    refreshSimpleScreeningCard();
   }
  }).catch(() => { /* ignore */ });
 }
 const modeBtn = document.getElementById('mode-toggle');
 if (modeBtn) {
  modeBtn.addEventListener('click', () => {
   requestAnimationFrame(() => {
    apiCall('/api/statistics').then((stats) => {
     if (typeof syncSimpleOnePageState === 'function') syncSimpleOnePageState(stats);
     updateSimpleToolsStrip(stats);
     if (typeof refreshSimpleScreeningCard === 'function') refreshSimpleScreeningCard();
    }).catch(() => {});
   });
  });
 }
});
