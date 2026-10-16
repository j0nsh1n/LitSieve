// === Search page logic ===

let lastSearchParams = null;
let lastQueryTokens = [];
/** Last on-screen result list (export “these results” uses this exact order). */
let lastResults = [];
const searchState = {
 requestPending: false,
 filters: {
  top_k: 10, sort_by: 'similarity', pico_boost: false, lexical_boost: true,
  source_filter: [], year_min: null, year_max: null,
  display: { starred: false, noted: false, recent: false, sources: {} },
 },
};
const displayFilterState = searchState.filters.display;
let librarySourceCounts = {};
let libraryStarredCount = 0;
let lastSuccessfulSession = null;

function applySearchInputMethod(mode) {
 const active = ['text', 'pico', 'seed'].includes(mode) ? mode : 'text';
 const textPanel = document.getElementById('text-input-panel');
 const picoPanel = document.getElementById('pico-input-panel');
 const seedPanel = document.getElementById('seed-input-panel');
 const card = document.getElementById('searchcard');
 [
  [textPanel, active === 'text', 'flex'],
  [picoPanel, active === 'pico', 'block'],
  [seedPanel, active === 'seed', 'block'],
 ].forEach(([panel, visible, display]) => {
  if (!panel) return;
  panel.classList.toggle('u-hidden', !visible);
  panel.style.display = visible ? display : 'none';
 });
 if (card) card.classList.toggle('is-alt-method', active !== 'text');
}

function displayRecentYear() {
 return new Date().getFullYear() - 5;
}

/** sessionStorage key: refresh keeps query + filters; re-runs search on load. */
const SEARCH_SESSION_KEY = 'lra_search_session_v1';
/** Skip auto-restore while applying form (avoids loops). */
let _restoringSearch = false;

document.addEventListener('DOMContentLoaded', () => {
 wireSearchFilterAdapters();
 // Empty state + hide search UI until papers are prepared; only then restore.
 loadSearchEmptyState()
  .then((stats) => waitIfPreparing(stats))
  .then((stats) => {
   const ready = !!(stats && (stats.articles_with_embeddings || 0) > 0);
   const collecting = typeof wantsSimpleCollectView === 'function'
    && wantsSimpleCollectView(stats);
   return applyAvailableSources().then(() => {
    // Start over / empty collect must not revive the previous query.
    if (collecting) {
     clearSearchWorkspace();
     if (typeof _collectQueryOn === 'function' && _collectQueryOn()
      && typeof resetSearchAndNarrowingForStartOver === 'function') {
      return resetSearchAndNarrowingForStartOver();
     }
     return;
    }
    if (ready) {
     const afterScreen = () => {
      if (typeof isSimpleScreenGatePending === 'function' && isSimpleScreenGatePending()) {
       return;
      }
      return restoreSearchSession();
     };
     if (typeof refreshSimpleScreeningCard === 'function') {
      return refreshSimpleScreeningCard().then(afterScreen);
     }
     return afterScreen();
    }
   }).then(() => {
    refreshStarredCount(stats == null ? null : stats.starred);
   });
  })
  .catch(() => {
   refreshStarredCount(null);
  });

 document.querySelectorAll('input[name="input_method"]').forEach(radio => {
 radio.addEventListener('change', () => {
 if (radio.checked) applySearchInputMethod(radio.value);
 });
 });
 const initialMethod = document.querySelector('input[name="input_method"]:checked');
 applySearchInputMethod(initialMethod ? initialMethod.value : 'text');

 const topkSlider = document.getElementById('top-k');
 const topkDisplay = document.getElementById('topk-display');
 topkSlider.addEventListener('input', () => {
 topkDisplay.textContent = topkSlider.value;
 });

 wireDisplayFilters();
 document.getElementById('search-btn').addEventListener('click', doSearch);
 const starredBtn = document.getElementById('starred-search-btn');
 if (starredBtn) starredBtn.addEventListener('click', doStarredSearch);

 // Page Help toggle is wired in common.js (initPageHelp).

 const exportBtn = document.getElementById('simple-export-results-btn');
 if (exportBtn) exportBtn.addEventListener('click', () => promptSimpleExportScope());

 document.getElementById('query-text').addEventListener('keydown', (e) => {
 if (e.key === 'Enter' && !e.shiftKey) {
 e.preventDefault();
 doSearch();
 }
 });
});

// ---------------------------------------------------------------------------
// Persist last search across refresh (sessionStorage; re-run API on load)
// ---------------------------------------------------------------------------

function activeLibraryId() {
 const sel = document.getElementById('nav-library-select');
 if (sel && (sel.dataset.activeId || sel.value)) {
  return sel.dataset.activeId || sel.value;
 }
 return '';
}

async function resolveLibraryId() {
 let id = activeLibraryId();
 if (id) return id;
 try {
  const data = await apiCall('/api/libraries');
  return (data && data.active_id) || '';
 } catch (e) {
  return '';
 }
}

function captureSearchSession(kind, opts = {}) {
 // kind: 'text' | 'pico' | 'seed' | 'starred'
 const mode = (kind === 'starred' || kind === 'seed')
  ? kind
  : (document.querySelector('input[name="input_method"]:checked') || {}).value || 'text';
 const filters = collectSearchFilters();
 return {
  v: 1,
  library_id: activeLibraryId(),
  mode,
  include_seed: mode === 'seed' && opts.include_seed === true,
  query_text: (document.getElementById('query-text') || {}).value || '',
  pico_population: (document.getElementById('pico-population') || {}).value || '',
  pico_intervention: (document.getElementById('pico-intervention') || {}).value || '',
  pico_comparison: (document.getElementById('pico-comparison') || {}).value || '',
  pico_outcome: (document.getElementById('pico-outcome') || {}).value || '',
  seed_query: (document.getElementById('seed-query') || {}).value || '',
  top_k: filters.top_k,
  sort_by: filters.sort_by,
  pico_boost: filters.pico_boost,
  lexical_boost: filters.lexical_boost,
  source_filter: filters.source_filter,
  year_min: filters.year_min,
  year_max: filters.year_max,
  filters: JSON.parse(JSON.stringify(searchState.filters)),
  saved_at: Date.now(),
 };
}

async function saveSearchSession(kind) {
 if (_restoringSearch) return;
 try {
  const state = lastSuccessfulSession
   ? Object.assign({}, lastSuccessfulSession, collectSearchFilters(), {
    filters: JSON.parse(JSON.stringify(searchState.filters)), saved_at: Date.now(),
   }) : captureSearchSession(kind);
  if (!state.library_id) {
   state.library_id = await resolveLibraryId();
  }
  sessionStorage.setItem(SEARCH_SESSION_KEY, JSON.stringify(state));
 } catch (e) { /* quota / private mode */ }
}

function readSearchSession() {
 try {
  const raw = sessionStorage.getItem(SEARCH_SESSION_KEY);
  if (!raw) return null;
  const state = JSON.parse(raw);
  if (!state || state.v !== 1) return null;
  return state;
 } catch (e) {
  return null;
 }
}

function setInputMethod(mode) {
 const radio = document.querySelector(`input[name="input_method"][value="${mode}"]`);
 if (!radio) return;
 radio.checked = true;
 radio.dispatchEvent(new Event('change', { bubbles: true }));
}

function applySearchSessionToForm(state) {
 if (!state) return;
 state = Object.assign({}, state, state.filters || {});
 _restoringSearch = true;
 try {
  if (state.mode === 'text' || state.mode === 'pico' || state.mode === 'seed') {
   setInputMethod(state.mode);
  }
  const qt = document.getElementById('query-text');
  if (qt && state.query_text != null) qt.value = state.query_text;
  const setVal = (id, v) => {
   const el = document.getElementById(id);
   if (el && v != null) el.value = v;
  };
  setVal('pico-population', state.pico_population);
  setVal('pico-intervention', state.pico_intervention);
  setVal('pico-comparison', state.pico_comparison);
  setVal('pico-outcome', state.pico_outcome);
  setVal('seed-query', state.seed_query);

  const topk = document.getElementById('top-k');
  const topkDisplay = document.getElementById('topk-display');
  if (topk && state.top_k != null) {
   topk.value = String(state.top_k);
   if (topkDisplay) topkDisplay.textContent = String(state.top_k);
   if (typeof updateRangeFill === 'function') updateRangeFill(topk);
  }
  const sortBy = document.getElementById('sort-by');
  if (sortBy && state.sort_by) sortBy.value = state.sort_by;
  const picoBoost = document.getElementById('pico-boost');
  if (picoBoost && typeof state.pico_boost === 'boolean') picoBoost.checked = state.pico_boost;
  const lexBoost = document.getElementById('lexical-boost');
  if (lexBoost && typeof state.lexical_boost === 'boolean') lexBoost.checked = state.lexical_boost;
  setVal('year-min', state.year_min != null ? String(state.year_min) : '');
  setVal('year-max', state.year_max != null ? String(state.year_max) : '');

  // Source checkboxes: only re-check ones that are available (not disabled).
  if (Array.isArray(state.source_filter) && state.source_filter.length) {
   const want = new Set(state.source_filter);
   document.querySelectorAll('input[name="search-source"]').forEach((cb) => {
    if (cb.disabled) return;
    cb.checked = want.has(cb.value);
   });
  }
  syncSearchFiltersFromForm();
  const savedFilters = state.filters;
  const savedSources = savedFilters ? savedFilters.source_filter : state.source_filter;
  if (Array.isArray(savedSources)) {
   const available = Object.keys(librarySourceCounts);
   searchState.filters.source_filter = available.length
    ? savedSources.filter((id) => available.includes(id)) : savedSources.slice();
   const legacyAllSources = !savedSources.length && !enabledSearchSourceBoxes().length;
   if (legacyAllSources) {
    searchState.filters.source_filter = available;
   }
  }
  if (savedFilters && savedFilters.display) {
   Object.assign(displayFilterState, savedFilters.display, {
    sources: Object.assign({}, savedFilters.display.sources || {}),
   });
  }
  syncSearchFilterControls();
 } finally {
  _restoringSearch = false;
 }
}

function clearSearchWorkspace() {
 try {
  sessionStorage.removeItem(SEARCH_SESSION_KEY);
 } catch (e) { /* quota / private mode */ }
 lastSearchParams = null;
 lastQueryTokens = [];
 lastResults = [];
 lastSuccessfulSession = null;
 const qt = document.getElementById('query-text');
 if (qt) qt.value = '';
 ['pico-population', 'pico-intervention', 'pico-comparison', 'pico-outcome', 'seed-query']
  .forEach((id) => {
   const el = document.getElementById(id);
   if (el) el.value = '';
  });
 const list = document.getElementById('results-list');
 if (list) list.innerHTML = '';
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.add('u-hidden');
  resultsSec.style.display = 'none';
 }
 const exportSec = document.getElementById('export-results-section');
 if (exportSec) {
  exportSec.hidden = true;
  exportSec.style.display = 'none';
 }
 const countEl = document.getElementById('result-count');
 if (countEl) countEl.textContent = '0';
 const banner = document.getElementById('seed-banner');
 if (banner) banner.style.display = 'none';
 displayFilterState.starred = false;
 displayFilterState.noted = false;
 displayFilterState.recent = false;
 displayFilterState.sources = {};
 syncDisplayFilterChipState();
 if (typeof updateSimpleSearchPanel === 'function') updateSimpleSearchPanel(false);
}

async function restoreSearchSession() {
 if (typeof _collectQueryOn === 'function' && _collectQueryOn()) return;
 const state = readSearchSession();
 if (!state) return;

 const libId = await resolveLibraryId();
 // Don't restore a search from another library after a switch.
 if (state.library_id && libId && state.library_id !== libId) return;

 applySearchSessionToForm(state);

 if (state.mode === 'starred') {
  await doStarredSearch({ fromRestore: true });
  return;
 }
 const legacySimpleSeedReplay = state.mode === 'seed'
  && state.include_seed == null
  ;
 if (state.mode === 'seed' && (state.include_seed === true || legacySimpleSeedReplay)) {
  const seedId = (state.seed_query || '').trim();
  if (!seedId) return;
  await doMoreLikeThisPaper({ article_id: seedId }, { fromRestore: true });
  return;
 }
 // Only auto-run when there is something to search with.
 const q = buildQueryText();
 if (!q) return;
 await doSearch({ fromRestore: true });
}

function parseOptionalYear(id) {
 const el = document.getElementById(id);
 if (!el || el.value === '' || el.value == null) return null;
 const n = parseInt(el.value, 10);
 return Number.isFinite(n) ? n : null;
}

function enabledSearchSourceBoxes() {
 return Array.from(document.querySelectorAll('input[name="search-source"]'))
  .filter((cb) => !cb.disabled);
}

function syncSearchFiltersFromForm() {
 const topK = parseInt(document.getElementById('top-k').value, 10);
 const sortBy = document.getElementById('sort-by').value;
 const picoBoost = document.getElementById('pico-boost').checked;
 const lexicalEl = document.getElementById('lexical-boost');
 const lexicalBoost = lexicalEl ? lexicalEl.checked : true;
 const enabled = enabledSearchSourceBoxes();
 // No enabled boxes (demo sample, or empty library): [] means every source.
 // When boxes exist, only the checked ones are sent.
 const selectedSources = enabled
  .filter((cb) => cb.checked)
  .map((cb) => cb.value);
 const extraSources = searchState.filters.source_filter.filter((id) =>
  !Array.from(document.querySelectorAll('input[name="search-source"]')).some((cb) => cb.value === id)
  && Number(librarySourceCounts[id]) > 0);
 Object.assign(searchState.filters, {
 top_k: topK,
 sort_by: sortBy,
 pico_boost: picoBoost,
 lexical_boost: lexicalBoost,
 source_filter: selectedSources.concat(extraSources),
 year_min: parseOptionalYear('year-min'),
 year_max: parseOptionalYear('year-max'),
 });
}

function collectSearchFilters() {
 const { display, ...request } = searchState.filters;
 if (!hasPicoText()) {
  request.pico_boost = false;
 }
 return Object.assign({}, request, { source_filter: request.source_filter.slice() });
}

function hasPicoText() {
 return ['pico-population', 'pico-intervention', 'pico-comparison', 'pico-outcome']
  .some((id) => String(document.getElementById(id)?.value || '').trim());
}

function syncSearchFilterControls() {
 const filters = searchState.filters;
 document.getElementById('sort-by').value = filters.sort_by;
 document.querySelectorAll('input[name="search-source"]').forEach((cb) => {
  cb.checked = !cb.disabled && filters.source_filter.includes(cb.value);
 });
 syncSimpleResultChips();
}

function wireSearchFilterAdapters() {
 const ids = ['top-k', 'sort-by', 'pico-boost', 'lexical-boost', 'year-min', 'year-max'];
 ids.forEach((id) => {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener('change', () => {
   syncSearchFiltersFromForm();
   if (id === 'sort-by' && lastResults.length) showSearchResults();
   saveSearchSession();
  });
 });
 document.querySelectorAll('input[name="search-source"]').forEach((cb) => {
  cb.addEventListener('change', syncSearchFiltersFromForm);
 });
 syncSearchFiltersFromForm();
 document.getElementById('simple-sort-chip')?.addEventListener('click', promptSimpleSort);
 document.getElementById('simple-sources-chip')?.addEventListener('click', promptSimpleSources);
 document.getElementById('simple-starred-chip')?.addEventListener('click', promptSimpleStarred);
}

function requireSelectedSources(filters, fromRestore) {
 if (Object.keys(librarySourceCounts).length === 0 && enabledSearchSourceBoxes().length === 0) return true;
 if (filters.source_filter.length === 0) {
  if (!fromRestore) showNotification('Please select at least one source.', 'error');
  return false;
 }
 return true;
}

function updateSearchWorkVisibility(stats) {
 // Hide query/controls/export until papers are prepared (same gate as empty-state).
 // Simple also waits until Narrow it down is applied or skipped.
 const emb = (stats && stats.articles_with_embeddings) || 0;
 const gated = typeof isSimpleScreenGatePending === 'function' && isSimpleScreenGatePending();
 const ready = emb > 0 && !gated;
 document.querySelectorAll('.search-work').forEach((el) => {
  // results + seed-banner stay hidden until a search runs (u-hidden / style).
  if (el.id === 'results-section' || el.id === 'seed-banner') {
   if (!ready) {
    el.classList.add('u-hidden');
    el.style.display = 'none';
   }
   return;
  }
  if (el.id === 'export-results-section') {
   // Only show export after there are on-screen results; never before ready.
   if (!ready) {
    el.hidden = true;
    el.style.display = 'none';
   }
   return;
  }
  el.hidden = !ready;
 });
}

function fillSimpleRailStats(stats, report) {
 const host = document.getElementById('simple-rail-stats');
 if (!host) return;
 const total = Number((report && report.total_articles) || (stats && stats.total_articles) || 0);
 const dups = Number(report && report.excluded && report.excluded.duplicate) || 0;
 const excludedTotal = Number(report && report.excluded && report.excluded.total) || 0;
 // Screened out is non-duplicate exclusions (PRISMA / txt report split).
 const out = Math.max(0, excludedTotal - dups);
 const kept = report && report.included != null
  ? Number(report.included)
  : Math.max(0, total - excludedTotal);
 const removed = Math.max(0, dups + out);
 const set = (id, n) => {
  const el = document.getElementById(id);
  if (el) el.textContent = String(n);
 };
 set('rail-stat-fetched', total);
 set('rail-stat-dups', dups);
 set('rail-stat-out', out);
 set('rail-stat-kept', kept);
 set('rail-stat-removed', removed);
 const seeSetAside = document.getElementById('funnel-set-aside-btn');
 if (seeSetAside) seeSetAside.hidden = removed <= 0;
 const keptPct = total > 0 ? (100 * kept / total) : 0;
 const removedPct = total > 0 ? (100 * removed / total) : 0;
 host.style.setProperty('--funnel-kept-pct', keptPct + '%');
 host.style.setProperty('--funnel-removed-pct', removedPct + '%');
 const collectedBar = document.getElementById('funnel-collected-bar');
 if (collectedBar) {
  collectedBar.setAttribute('aria-label', `Collected ${total} papers`);
 }
 const splitBar = document.getElementById('funnel-split-bar');
 if (splitBar) {
  splitBar.setAttribute(
   'aria-label',
   `Of ${total} collected: ${kept} kept, ${removed} removed`
   + ` (${dups} duplicates, ${out} screened out)`
  );
 }
 host.hidden = total <= 0;
}

/** Re-read the counts behind the Kept / Removed / Screened out rail (audit 19.2). */
async function refreshRailStats() {
 if (!document.getElementById('simple-rail-stats')) return;
 try {
  const [stats, report] = await Promise.all([
   apiCall('/api/statistics'),
   apiCall('/api/screening-report?format=json'),
  ]);
  fillSimpleRailStats(stats, report);
 } catch (e) {
  // The rail keeps its last numbers; the next change or reload corrects them.
 }
}

async function loadSearchEmptyState() {
 try {
 const stats = await apiCall('/api/statistics');
 if (typeof syncSimpleOnePageState === 'function') {
  syncSimpleOnePageState(stats);
 }
 if (document.getElementById('simple-rail-stats')
  ) {
  try {
   const report = await apiCall('/api/screening-report?format=json');
   fillSimpleRailStats(stats, report);
  } catch (e) {
   fillSimpleRailStats(stats, null);
  }
 }

 if (!wantsSimpleCollectView(stats)) {
  updateSearchWorkVisibility(stats);
 }
 return stats;
 } catch (e) {
 if (typeof syncSimpleOnePageState === 'function') {
  syncSimpleOnePageState({ articles_with_embeddings: 0, total_articles: 0 });
 }
 updateSearchWorkVisibility({ articles_with_embeddings: 0 });
 return null;
 }
}

async function waitIfPreparing(stats) {
 const banner = document.getElementById('search-preparing');
 const status = document.getElementById('search-preparing-status');
 const hide = () => {
  if (typeof hideSimpleBuffering === 'function') hideSimpleBuffering();
  else {
   window._preparingCorpus = false;
   if (banner) banner.hidden = true;
  }
 };
 let progress = {};
 try {
  progress = await apiCall('/api/progress');
 } catch (e) {
  hide();
  return stats;
 }
 const fetchJob = (progress && progress.fetch) || {};
 const embed = (progress && progress.embed) || {};

 if (fetchJob.active && typeof showSimpleBuffering === 'function') {
  showSimpleBuffering('fetch');
  if (typeof syncSimpleOnePageState === 'function') syncSimpleOnePageState(stats || {});
  if (typeof waitForJob === 'function') {
   try {
    await waitForJob(
     'fetch',
     'search-buffering-fill',
     'search-buffering-label',
     'search-buffering-progress',
     (done, totalN, _pct, p) => {
      const arts = (p && p.articles_so_far) || 0;
      return `${done} of ${totalN} source(s) · ${arts} paper(s) so far`;
     },
     typeof simpleWaitMapOpts === 'function' ? simpleWaitMapOpts(0, 60) : undefined
    );
   } catch (e) {
    if (status) status.textContent = 'Fetch did not finish. Try again from Get papers.';
    hide();
    return stats;
   }
  }
  // Client auto-chain may still be running on the original tab; this tab
  // only waits if prepare has already started.
  try {
   progress = await apiCall('/api/progress');
  } catch (e) { /* continue */ }
 }

 const embedNow = (progress && progress.embed) || embed;
 if (!embedNow.active) {
  hide();
  return stats;
 }
 if (typeof showSimpleBuffering === 'function') {
  showSimpleBuffering('prepare');
 } else {
  window._preparingCorpus = true;
  if (banner) banner.hidden = false;
  if (status) status.textContent = 'Preparing papers for search…';
 }
 if (typeof syncSimpleOnePageState === 'function') {
  syncSimpleOnePageState(stats || {});
 }
 if (typeof waitForJob === 'function') {
  try {
   await waitForJob(
    'embed',
    'search-buffering-fill',
    'search-buffering-label',
    'search-buffering-progress',
    (done, totalN, pct) => (
      totalN > 0 ? `Getting papers ready… ${done} / ${totalN} (${pct}%)` : 'Getting your papers ready…'
     ),
    typeof simpleWaitMapOpts === 'function' ? simpleWaitMapOpts(60, 90) : undefined
   );
  } catch (e) {
   if (status) status.textContent = 'Could not finish preparing. Use Re-prepare.';
   hide();
   return stats;
  }
 }
 if (typeof holdSimpleWait === 'function') {
  holdSimpleWait();
  if (typeof refreshSimpleScreeningCard === 'function') {
   await refreshSimpleScreeningCard();
  }
  return stats;
 }
 hide();
 return loadSearchEmptyState();
}

function refreshStarredCount(known) {
 libraryStarredCount = Math.max(0, Math.trunc(Number(known) || 0));
 syncSimpleResultChips();
 const el = document.getElementById('starred-count');
 if (!el) return;
 const n = Number(known);
 if (known == null || Number.isNaN(n)) {
  el.textContent = '?';
  return;
 }
 el.textContent = String(Math.max(0, Math.trunc(n)));
}

function bumpStarredCount(delta) {
 libraryStarredCount = Math.max(0, libraryStarredCount + delta);
 syncSimpleResultChips();
 const el = document.getElementById('starred-count');
 if (!el) return;
 const cur = parseInt(el.textContent, 10);
 if (Number.isNaN(cur)) {
  el.textContent = '?';
  return;
 }
 el.textContent = String(Math.max(0, cur + delta));
}

async function applyAvailableSources() {
 let sources = {};
 try {
 const stats = await apiCall('/api/statistics');
 sources = stats.sources || {};
 refreshStarredCount(stats.starred);
 } catch (e) {
 return;
 }
 const previous = Object.keys(librarySourceCounts);
 const includedAll = previous.every((id) => searchState.filters.source_filter.includes(id));
 librarySourceCounts = Object.fromEntries(Object.entries(sources).filter(([, n]) => Number(n) > 0));
 searchState.filters.source_filter = includedAll ? Object.keys(librarySourceCounts)
  : searchState.filters.source_filter.filter((id) => id in librarySourceCounts);

 let anyAvailable = Object.values(sources).some((n) => Number(n) > 0);
 document.querySelectorAll('input[name="search-source"]').forEach(cb => {
 const count = sources[cb.value] || 0;
 const label = cb.closest('.radio-label');
 cb.disabled = count === 0;
 cb.checked = count > 0 && searchState.filters.source_filter.includes(cb.value);
 if (count > 0) anyAvailable = true;

 if (label) {
 label.classList.toggle('source-empty', count === 0);
 let badge = label.querySelector('.src-count');
 if (count > 0) {
 if (!badge) {
 badge = document.createElement('span');
 badge.className = 'src-count';
 label.appendChild(badge);
 }
 badge.textContent = `(${count})`;
 } else if (badge) {
 badge.remove();
 }
 }
 });
 syncSearchFiltersFromForm();
 syncSimpleResultChips();
 updateSimpleSearchPanel(!!(lastResults && lastResults.length));

 const hint = document.getElementById('source-availability-hint');
 if (hint) {
 hint.textContent = anyAvailable
 ? ''
 : 'No articles yet - use More to get papers on Search.';
 }
}

function buildQueryText() {
 const method = document.querySelector('input[name="input_method"]:checked').value;
 if (method === 'text') {
 return document.getElementById('query-text').value.trim();
 }
 if (method === 'seed') {
 return document.getElementById('seed-query').value.trim();
 }
 const parts = [];
 const pop = document.getElementById('pico-population').value.trim();
 const int_ = document.getElementById('pico-intervention').value.trim();
 const comp = document.getElementById('pico-comparison').value.trim();
 const out = document.getElementById('pico-outcome').value.trim();
 if (pop) parts.push(`Population: ${pop}`);
 if (int_) parts.push(`Intervention: ${int_}`);
 if (comp) parts.push(`Comparison: ${comp}`);
 if (out) parts.push(`Outcome: ${out}`);
 return parts.join('. ');
}

function tokensFromQuery(text) {
 const stop = new Set([
 'population', 'intervention', 'comparison', 'outcome', 'with', 'from',
 'that', 'this', 'have', 'been', 'were', 'their', 'about', 'into', 'over',
 ]);
 return (text || '')
 .toLowerCase()
 .match(/[a-zA-Z]{4,}/g)
 ?.filter(t => !stop.has(t)) || [];
}

function highlightText(text, tokens) {
 const raw = text || '';
 if (!tokens.length) return escapeHtml(raw);
 // Longest first; word boundaries so "model" does not paint inside "models".
 const sorted = [...new Set(tokens)].sort((a, b) => b.length - a.length);
 const pattern = new RegExp(
  '\\b(' + sorted.map(escapeRegExp).join('|') + ')\\b',
  'gi'
 );
 return escapeHtml(raw).replace(pattern, '<mark class="query-hl">$1</mark>');
}

function escapeRegExp(s) {
 return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function promptSimpleSearchScope(kind = 'text') {
 if (typeof openSiteForm !== 'function') return true;
 const topkEl = document.getElementById('top-k');
 const yminEl = document.getElementById('year-min');
 const ymaxEl = document.getElementById('year-max');
 const result = await openSiteForm({
  title: 'Search options',
  message: kind === 'starred' ? 'Choose how many papers to show and the years.'
   : 'Choose how many papers to show, the years, and how to rank them.',
  confirmLabel: 'Search',
  fields: [
   {
    id: 'count',
    label: 'How many papers',
    type: 'number',
    value: (topkEl && topkEl.value) || '10',
    min: 1,
    max: 50,
    step: 1,
   },
   {
    id: 'year_min',
    label: 'From year (optional)',
    type: 'number',
    value: yminEl ? yminEl.value : '',
    placeholder: 'e.g. 2015',
    min: 1900,
    max: 2100,
    step: 1,
   },
   {
    id: 'year_max',
    label: 'To year (optional)',
    type: 'number',
    value: ymaxEl ? ymaxEl.value : '',
    placeholder: 'e.g. 2024',
    min: 1900,
    max: 2100,
    step: 1,
   },
   ...(kind !== 'starred' ? [{
    id: 'lexical_boost', section: 'Ranking', label: 'Prefer exact words', type: 'choice',
    value: searchState.filters.lexical_boost ? 'on' : 'off',
    options: [{ value: 'on', label: 'On', hint: 'Blend meaning with matching words' },
     { value: 'off', label: 'Off', hint: 'Rank by meaning' }],
   }] : []),
   ...(kind !== 'starred' && kind !== 'seed' && hasPicoText() ? [{
     id: 'pico_boost', label: 'Prefer PICO matches', type: 'choice',
     value: searchState.filters.pico_boost ? 'on' : 'off',
     options: [{ value: 'on', label: 'On' }, { value: 'off', label: 'Off' }],
    }] : []),
  ],
  validate: (vals) => {
   const n = parseInt(vals.count, 10);
   if (!Number.isFinite(n) || n < 1 || n > 50) {
    return 'Choose how many papers to show (1–50).';
   }
   const yminRaw = String(vals.year_min || '').trim();
   const ymaxRaw = String(vals.year_max || '').trim();
   const ymin = yminRaw === '' ? null : parseInt(yminRaw, 10);
   const ymax = ymaxRaw === '' ? null : parseInt(ymaxRaw, 10);
   if (yminRaw && !Number.isFinite(ymin)) return 'From year must be a number.';
   if (ymaxRaw && !Number.isFinite(ymax)) return 'To year must be a number.';
   if (ymin != null && (ymin < 1900 || ymin > 2100)) return 'From year must be between 1900 and 2100.';
   if (ymax != null && (ymax < 1900 || ymax > 2100)) return 'To year must be between 1900 and 2100.';
   if (ymin != null && ymax != null && ymin > ymax) return 'From year must be before To year.';
   return null;
  },
 });
 if (result == null) return false;
 const n = parseInt(result.count, 10);
 if (topkEl) {
  topkEl.value = String(n);
  const topkDisplay = document.getElementById('topk-display');
  if (topkDisplay) topkDisplay.textContent = String(n);
  if (typeof updateRangeFill === 'function') updateRangeFill(topkEl);
 }
 if (yminEl) yminEl.value = String(result.year_min || '').trim();
 if (ymaxEl) ymaxEl.value = String(result.year_max || '').trim();
 if (result.lexical_boost != null) document.getElementById('lexical-boost').checked = result.lexical_boost === 'on';
 if (result.pico_boost != null) document.getElementById('pico-boost').checked = result.pico_boost === 'on';
 syncSearchFiltersFromForm();
 return true;
}

const SIMPLE_SORT_LABELS = {
 similarity: 'Similarity', year: 'Newest first', journal: 'Journal A–Z', title: 'Title A–Z',
};

function syncSimpleResultChips() {
 ['simple-sort-chip', 'simple-sources-chip', 'simple-starred-chip'].forEach((id) => {
  const chip = document.getElementById(id);
  if (chip) chip.disabled = searchState.requestPending;
 });
 const sort = document.getElementById('simple-sort-chip');
 if (sort) sort.textContent = `Sort: ${SIMPLE_SORT_LABELS[searchState.filters.sort_by] || 'Similarity'}`;
 const sources = document.getElementById('simple-sources-chip');
 if (sources) {
  const all = Object.keys(librarySourceCounts).length;
  const selected = searchState.filters.source_filter.length;
  sources.textContent = selected === all ? 'Sources: All' : `Sources: ${selected} of ${all}`;
 }
 const starred = document.getElementById('simple-starred-chip');
 if (starred) {
  starred.classList.toggle('is-on', displayFilterState.starred);
  starred.setAttribute('aria-pressed', String(displayFilterState.starred));
 }
}

async function promptSimpleSort() {
 if (searchState.requestPending) return;
 const values = await openSiteForm({
  title: 'Sort papers', confirmLabel: 'Apply', fields: [{
   id: 'sort', label: 'Order these results', type: 'choice', value: searchState.filters.sort_by,
   options: Object.entries(SIMPLE_SORT_LABELS).map(([value, label]) => ({ value, label })),
  }],
 });
 if (!values || searchState.requestPending) return;
 searchState.filters.sort_by = values.sort;
 syncSearchFilterControls();
 showSearchResults();
 await saveSearchSession();
}

async function promptSimpleSources() {
 if (searchState.requestPending) return;
 const ids = Object.keys(librarySourceCounts).sort((a, b) => getSourceName(a).localeCompare(getSourceName(b)));
 const values = await openSiteForm({
  title: 'Sources', message: 'Counts are papers in your library, including papers set aside or not yet prepared. Search uses the selected sources before ranking.',
  confirmLabel: 'Search these sources', fields: [{
   id: 'sources', label: 'Include sources', type: 'multi-choice', value: searchState.filters.source_filter,
   options: ids.map((value) => ({ value, label: getSourceName(value), hint: `${librarySourceCounts[value]} papers in your library` })),
  }], validate: (vals) => vals.sources.length ? null : 'Please select at least one source.',
 });
 if (!values || searchState.requestPending) return;
 searchState.filters.source_filter = values.sources;
 syncSearchFilterControls();
 if (!lastSearchParams) return;
 const replay = { skipOptions: true, replay: true };
 if (lastSearchParams.mode === 'starred') await doStarredSearch(replay);
 else if (lastSearchParams.mode === 'seed' && lastSearchParams.include_seed) {
  await doMoreLikeThisPaper({ article_id: lastSearchParams.query_text }, replay);
 } else await doSearch(replay);
}

async function promptSimpleStarred() {
 if (searchState.requestPending) return;
 const choices = [{ label: displayFilterState.starred ? 'Show all current hits' : 'Show starred current hits', value: 'show' }];
 if (libraryStarredCount > 0) choices.push({ label: 'Find more like these', value: 'find', primary: true });
 choices.push({ label: 'Cancel', value: null, cancel: true });
 const value = await openSiteChoice({
  title: 'Starred papers', message: libraryStarredCount > 0
   ? 'Show starred papers among the current hits, or rank your library by your starred papers. Starred papers stay in the ranked list.'
   : 'Show starred papers among the current hits. Star a paper to find more like it.', choices,
 });
 if (searchState.requestPending) return;
 if (value === 'find') {
  await doStarredSearch({ clearStarred: true });
 } else if (value === 'show') {
  displayFilterState.starred = !displayFilterState.starred;
  showSearchResults();
  await saveSearchSession();
 }
}

async function doSearch(opts) {
 if (searchState.requestPending) return;
 const fromRestore = !!(opts && opts.fromRestore);
 const method = opts?.replay ? lastSearchParams.mode : document.querySelector('input[name="input_method"]:checked').value;
 const queryText = opts?.replay ? lastSearchParams.query_text : buildQueryText();
 if (!queryText) {
 if (!fromRestore) {
  showNotification(method === 'seed' ? 'Enter a seed id or title.' : 'Please enter a search query.', 'error');
 }
 return;
 }
 if (!fromRestore && !opts?.skipOptions) {
  const scoped = await promptSimpleSearchScope(method);
  if (!scoped) return;
 }

 const filters = collectSearchFilters();
 if (searchState.requestPending) return;
 if (!requireSelectedSources(filters, fromRestore)) return;
 setSearchRequestPending(true);
 const btn = document.getElementById('search-btn');
 setLoading(btn, true);
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 showResultSkeletons(6);

 const searchParams = {
 query_text: queryText,
 top_k: filters.top_k,
 sort_by: filters.sort_by,
 source_filter: filters.source_filter,
 pico_boost: filters.pico_boost,
 lexical_boost: filters.lexical_boost,
 year_min: filters.year_min,
 year_max: filters.year_max,
 mode: method,
 };
 const session = opts?.replay ? lastSuccessfulSession : captureSearchSession(method);
 lastQueryTokens = tokensFromQuery(queryText);

 try {
 let data;
 if (method === 'seed') {
 data = await apiCall('/api/search/seed', {
 method: 'POST',
 body: {
 seed: queryText,
 top_k: filters.top_k,
 source_filter: filters.source_filter,
 year_min: filters.year_min,
 year_max: filters.year_max,
 lexical_boost: filters.lexical_boost,
 },
 });
 const seed = data.seed;
 const banner = document.getElementById('seed-banner');
 const bannerText = document.getElementById('seed-banner-text');
 if (seed && banner && bannerText) {
 banner.style.display = 'block';
 bannerText.textContent =
 `Starting from “${seed.title || seed.article_id}” (${getSourceName(seed.source)} · ${seed.year || 'n.d.'}). Showing papers most like this one.`;
 lastQueryTokens = tokensFromQuery(`${seed.title || ''} ${seed.abstract || ''}`);
 }
 } else {
 document.getElementById('seed-banner').style.display = 'none';
 data = await apiCall('/api/search', {
 method: 'POST',
 body: {
 query_text: queryText,
 top_k: filters.top_k,
 sort_by: 'similarity',
 source_filter: filters.source_filter,
 pico_boost: filters.pico_boost,
 lexical_boost: filters.lexical_boost,
 year_min: filters.year_min,
 year_max: filters.year_max,
 },
 });
 }

 const results = data.results || [];
 lastSearchParams = searchParams;
 lastSuccessfulSession = session;
 lastResults = results;
 showSearchResults(results);
 // Persist query + filters so a browser refresh restores this search.
 await saveSearchSession(method);
 } catch (e) {
 if (!fromRestore) showNotification(`Search failed: ${e.message}`, 'error');
 // Drop loading skeletons so a failed search does not look stuck mid-load.
 clearResultSkeletonsOnError(fromRestore);
 } finally {
 setSearchRequestPending(false);
 setLoading(btn, false);
 }
}

async function doStarredSearch(opts) {
 if (searchState.requestPending) return;
 const fromRestore = !!(opts && opts.fromRestore);
 if (!fromRestore && !opts?.skipOptions) {
  const scoped = await promptSimpleSearchScope('starred');
  if (!scoped) return;
 }
 const filters = collectSearchFilters();
 if (searchState.requestPending) return;
 if (!requireSelectedSources(filters, fromRestore)) return;
 setSearchRequestPending(true);
 const btn = document.getElementById('starred-search-btn');
 setLoading(btn, true);
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 showResultSkeletons(6);
 const searchParams = {
 query_text: '',
 top_k: filters.top_k,
 sort_by: filters.sort_by,
 source_filter: filters.source_filter,
 pico_boost: false,
 lexical_boost: false,
 year_min: filters.year_min,
 year_max: filters.year_max,
 mode: 'starred',
 };
 const session = opts?.replay ? lastSuccessfulSession : captureSearchSession('starred');
 lastQueryTokens = [];
 try {
 document.getElementById('seed-banner').style.display = 'none';
 const data = await apiCall('/api/search/starred', {
 method: 'POST',
 body: {
 top_k: filters.top_k,
 source_filter: filters.source_filter,
 year_min: filters.year_min,
 year_max: filters.year_max,
 },
 });
 const banner = document.getElementById('seed-banner');
 const bannerText = document.getElementById('seed-banner-text');
 if (banner && bannerText) {
 banner.style.display = 'block';
 bannerText.textContent =
 `More like your starred papers (${data.seed_count || 0} star${(data.seed_count || 0) === 1 ? '' : 's'}). Starred papers stay in the list (usually near the top).`;
 }
 let results = data.results || [];
 lastSearchParams = searchParams;
 lastSuccessfulSession = session;
 lastResults = results;
 if (opts?.clearStarred) displayFilterState.starred = false;
 showSearchResults(results);
 refreshStarredCount(data.seed_count);
 await saveSearchSession('starred');
 } catch (e) {
 if (!fromRestore) showNotification(`Starred search failed: ${e.message}`, 'error');
 clearResultSkeletonsOnError(fromRestore);
 } finally {
 setSearchRequestPending(false);
 setLoading(btn, false);
 }
}

async function doMoreLikeThisPaper(article, opts) {
 if (searchState.requestPending) return;
 const fromRestore = !!(opts && opts.fromRestore);
 const seedId = article && article.article_id ? String(article.article_id).trim() : '';
 if (!seedId) return;
 if (!fromRestore && !opts?.skipOptions) {
  const scoped = await promptSimpleSearchScope('seed');
  if (!scoped) return;
 }
 const filters = collectSearchFilters();
 if (searchState.requestPending) return;
 if (!requireSelectedSources(filters, fromRestore)) return;
 setSearchRequestPending(true);
 const seedField = document.getElementById('seed-query');
 if (seedField && !opts?.replay) seedField.value = seedId;
 const btn = document.getElementById('search-btn');
 setLoading(btn, true);
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 showResultSkeletons(6);
 const searchParams = {
 query_text: seedId,
 top_k: filters.top_k,
 sort_by: filters.sort_by,
 source_filter: filters.source_filter,
 pico_boost: false,
 lexical_boost: filters.lexical_boost,
 year_min: filters.year_min,
 year_max: filters.year_max,
 mode: 'seed',
 include_seed: true,
 };
 const session = opts?.replay ? lastSuccessfulSession : captureSearchSession('seed', { include_seed: true });
 lastQueryTokens = tokensFromQuery(`${article.title || ''} ${article.abstract || ''}`);
 try {
 const data = await apiCall('/api/search/seed', {
 method: 'POST',
 body: {
 seed: seedId,
 top_k: filters.top_k,
 source_filter: filters.source_filter,
 year_min: filters.year_min,
 year_max: filters.year_max,
 lexical_boost: filters.lexical_boost,
 include_seed: true,
 },
 });
 const seed = data.seed || article;
 const banner = document.getElementById('seed-banner');
 const bannerText = document.getElementById('seed-banner-text');
 if (banner && bannerText) {
 banner.classList.remove('u-hidden');
 banner.style.display = 'block';
 bannerText.textContent =
 `Starting from “${seed.title || seed.article_id}” (${getSourceName(seed.source)} · ${seed.year || 'n.d.'}). Showing papers most like this one.`;
 lastQueryTokens = tokensFromQuery(`${seed.title || ''} ${seed.abstract || ''}`);
 }
 let results = data.results || [];
 lastSearchParams = searchParams;
 lastSuccessfulSession = session;
 lastResults = results;
 showSearchResults(results);
 await saveSearchSession('seed');
 } catch (e) {
 if (!fromRestore) showNotification(`Search failed: ${e.message}`, 'error');
 clearResultSkeletonsOnError(fromRestore);
 } finally {
 setSearchRequestPending(false);
 setLoading(btn, false);
 }
}

function setSearchRequestPending(pending) {
 searchState.requestPending = pending;
 syncSimpleResultChips();
}

function clientSort(results, sortBy) {
 const arr = results.slice();
 // Similarity keeps the server's order, which is the order of the shown score.
 if (sortBy === 'year') {
 arr.sort((a, b) => (parseYear(b.year) - parseYear(a.year)));
 } else if (sortBy === 'journal') {
 arr.sort((a, b) => (a.journal || '').localeCompare(b.journal || ''));
 } else if (sortBy === 'title') {
 arr.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
 }
 // Under a year range, papers with no usable year stay in their own group
 // after the dated ones, whatever the sort (audit 19.16).
 return arr.filter((a) => !a.no_year).concat(arr.filter((a) => a.no_year));
}

function parseYear(y) {
 const m = String(y || '').match(/(?:19|20)\d{2}/);
 return m ? parseInt(m[0], 10) : 0;
}

function renderPicoBlock(pico) {
 if (!pico) return '';
 const keys = [
 ['population', 'pop', 'Population'],
 ['intervention', 'int', 'Intervention'],
 ['comparison', 'comp', 'Comparison'],
 ['outcome', 'out', 'Outcome'],
 ];
 const parts = [];
 keys.forEach(([k, cls, label]) => {
 const list = pico[k] || [];
 if (!list.length) return;
 const quote = list[0];
 const short = quote.length > 140 ? quote.slice(0, 138) + '…' : quote;
 parts.push(
 `<div class="pico-snippet">
 <span class="pico-tag ${cls}">${label}</span>
 <span class="pico-quote">“${highlightText(short, lastQueryTokens)}”</span>
 </div>`
 );
 });
 if (!parts.length) return '';
 return `<div class="pico-detail">${parts.join('')}</div>`;
}

/** Study-type badge from search-time heuristics (may be wrong — show warning).
 *  Plain-language label + optional “what this means” line for younger students.
 */
function renderStudyTypeBadge(article) {
 if (typeof uiFlag === 'function' && !uiFlag('show_study_type_tags', true)) return '';
 const label = article.study_type_label;
 if (!label) return '';
 const band = article.study_type_confidence_band || 'none';
 const conf = article.study_type_confidence != null
 ? Number(article.study_type_confidence).toFixed(2)
 : '?';
 const warn = article.study_type_warning || '';
 const meaning = article.study_type_meaning || '';
 const formal = article.study_type_label_formal || '';
 const disc = article.study_type_disclaimer
 || 'Automated guess from title and abstract only. May be wrong.';
 const matched = article.study_type_source === 'laya'
 ? ' Tagged by Laya, a local AI model, because the wording patterns were unsure.'
 : (article.study_type_matched ? ` Matched: “${article.study_type_matched}”.` : '');
 const formalBit = formal && formal !== label ? ` Formal name: ${formal}.` : '';
 const title = `${disc}${formalBit}${matched}${warn ? ' ' + warn : ''} Confidence: ${conf}.`;
 const warnMark = (band === 'high') ? '' : ' <span class="study-type-warn" aria-hidden="true">!</span>';
 const meaningLine = meaning
 ? `<span class="study-type-meaning">${escapeHtml(meaning)}</span>`
 : '';
 return `<span class="study-type-wrap">`
 + `<span class="study-type-badge band-${escapeHtml(band)}" data-tip="${escapeHtml(title)}">`
 + `${escapeHtml(label)}${warnMark}</span>`
 + meaningLine
 + `</span>`;
}

/** Star control label: inline SVG (never an emoji glyph) + text. */
function starLabelHtml(on) {
 const fill = on ? 'currentColor' : 'none';
 return '<svg class="ico star-ico" viewBox="0 0 24 24" aria-hidden="true" fill="' + fill + '"'
  + ' stroke="currentColor" stroke-width="1.8" stroke-linejoin="round">'
  + '<path d="M12 2l3 6.5 7 .9-5 4.9 1.2 7L12 18l-6.2 3.3L7 14.3 2 9.4l7-.9z"/></svg>'
  + '<span>' + (on ? 'Starred' : 'Star') + '</span>';
}

// Rows render compact and one opens in place. The toggle is a
// real button so the keyboard gets the same contract as a click on the row.
// In the grid layouts the open paper reads in a side panel instead, and a
// placeholder keeps its cell, so the grid never reflows under the reader.
function resultsUseReaderPanel() {
 return ['columns', 'index'].includes(document.documentElement.getAttribute('data-layout'));
}

function setResultRowOpen(card, open) {
 // Measured while the card still sits in its grid cell.
 const cell = card.getBoundingClientRect();
 card.classList.toggle('is-open', open);
 const prev = card.previousElementSibling;
 const ghost = prev && prev.classList.contains('result-ghost') ? prev : null;
 if (!open && ghost) ghost.remove();
 if (!open) card.classList.remove('is-reading-left');
 if (open && !ghost && resultsUseReaderPanel()) {
  // The panel opens on the side away from the paper, so its placeholder
  // stays in view.
  card.classList.toggle('is-reading-left', cell.left + cell.width / 2 > window.innerWidth / 2);
  const holder = document.createElement('button');
  holder.type = 'button';
  holder.className = 'result-ghost';
  const title = card.querySelector('.result-row-title');
  holder.innerHTML = '<span class="result-ghost-label">Reading</span>'
   + `<span class="result-ghost-title">${escapeHtml(title ? title.textContent : '')}</span>`
   + '<span class="result-ghost-hint">Close</span>';
  // Exactly the cell the paper left, so nothing around it moves.
  if (cell.height) holder.style.setProperty('min-height', `${Math.round(cell.height)}px`);
  holder.addEventListener('click', () => {
   setResultRowOpen(card, false);
   const toggle = card.querySelector('.result-toggle');
   if (toggle) toggle.focus({ preventScroll: true });
  });
  card.before(holder);
 }
 const toggle = card.querySelector('.result-toggle');
 if (toggle) {
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  toggle.textContent = open ? 'Close' : 'Open';
 }
 // The reading column opens a paper straight to its whole abstract.
 if (open && document.documentElement.getAttribute('data-layout') === 'reading') {
  const abstract = card.querySelector('.result-abstract');
  if (abstract) abstract.open = true;
  card.querySelectorAll('.abstract-wrap:not(.is-expanded)').forEach((wrap) => {
   wrap.classList.add('is-expanded');
   const text = wrap.querySelector('.article-abstract');
   if (text && typeof _syncAbstractClamp === 'function') _syncAbstractClamp(text);
  });
 }
}

function openResultRow(card, scrollIntoView) {
 if (!card) return;
 document.querySelectorAll('#results-list .result-row.is-open').forEach((row) => {
  if (row !== card) setResultRowOpen(row, false);
 });
 setResultRowOpen(card, true);
 if (resultsUseReaderPanel()) {
  card.scrollTop = 0;
  const toggle = card.querySelector('.result-toggle');
  if (toggle && scrollIntoView) toggle.focus({ preventScroll: true });
  return;
 }
 if (scrollIntoView) {
  const top = card.getBoundingClientRect().top;
  const clear = searchTileClearance();
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (top < clear) window.scrollBy({ top: top - clear, behavior: reduce ? 'auto' : 'smooth' });
 }
}

document.addEventListener('keydown', (e) => {
 if (e.key !== 'Escape' || e.defaultPrevented) return;
 if (e.target.closest && e.target.closest('input, textarea, select, .settings-panel, dialog')) return;
 if (document.querySelector('.settings-panel:not([hidden])')) return;
 if (document.body.classList.contains('lra-modal-open') || document.querySelector('dialog[open]')) return;
 const open = document.querySelector('#results-list .result-row.is-open');
 if (!open) return;
 setResultRowOpen(open, false);
 const toggle = open.querySelector('.result-toggle');
 if (toggle) toggle.focus({ preventScroll: true });
});

// A layout change never leaves a paper in a panel the student did not open
// there, nor a placeholder for a panel that is gone.
function watchLayoutForOpenPapers() {
 if (typeof MutationObserver !== 'function') return;
 new MutationObserver(() => {
  const list = document.getElementById('results-list');
  if (!list) return;
  if (resultsUseReaderPanel()) {
   list.querySelectorAll('.result-row.is-open').forEach((row) => {
    const prev = row.previousElementSibling;
    if (!prev || !prev.classList.contains('result-ghost')) setResultRowOpen(row, false);
   });
  } else {
   list.querySelectorAll('.result-ghost').forEach((ghost) => ghost.remove());
  }
 }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-layout'] });
}

function toggleResultRow(card) {
 if (card.classList.contains('is-open')) setResultRowOpen(card, false);
 else openResultRow(card, true);
}

function buildResultCard(article, idx) {
 // Phase 8: scannable row with numeric 0–1 score meter (not Low/Medium/High details).
 const card = document.createElement('article');
 card.className = 'article-card result-row';
 card.dataset.resultIndex = String(idx);
 // Catalog draws its index tab from this; it is the real source, not a topic.
 card.dataset.sourceName = getSourceName(article.source);

 const sim = Number(article.similarity_score) || 0;
 const simPct = Math.max(0, Math.min(100, Math.round(sim * 1000) / 10));
 const simLabel = sim.toFixed(3);
 // Hover definition: 0–1 rank of meaning match vs the query (not a quality grade).
 const scoreHelp =
  'Similarity score (0–1): mostly how closely this paper matches your query by meaning, '
  + 'plus a smaller share for the exact words it shares with it. The list is sorted '
  + 'by this number. Not a quality or evidence grade.';

 const url = getArticleUrl(article.article_id, article.source);
 const idText = escapeHtml(article.article_id || '');
 const idLink = url
 ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="article-link">${idText}</a>`
 : idText;
 const openLink = url
 ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="result-open-link"
  data-tip="Open this paper at its source (new tab)">View paper \u2197</a>`
 : '';

 const authors = (article.authors || []).join('; ');
 const abstractHtml = highlightText(article.abstract || '', lastQueryTokens);
 const picoHtml = renderPicoBlock(article.pico);
 const keyPointsHtml = typeof renderKeyPointsHtml === 'function'
 ? renderKeyPointsHtml(article.key_points, {
 articleId: article.article_id,
 source: article.source,
 origin: article.key_points_origin || 'extractive',
 abstractLen: String(article.abstract || '').length,
 compactAid: true,
 })
 : '';
 const studyTypeHtml = renderStudyTypeBadge(article);
 const starred = !!article.starred;
 const noteVal = article.note || '';
 const clusterBit = article.cluster_label
 ? `<span><strong>Cluster:</strong> ${escapeHtml(String(article.cluster_label))}</span>`
 : '';

 const journal = escapeHtml(article.journal || '');
 const year = escapeHtml(article.year || '');
 const venueBits = [];
 if (journal) venueBits.push(journal);
 if (year) venueBits.push(year);
 const venue = venueBits.join(' · ');
 const byline = authors
  ? `${escapeHtml(authors)}${journal ? ' — ' + journal : ''}`
  : journal;

 // A short opening for layouts that lead with one paper; the full abstract
 // is always one click away in the open paper.
 const abstractText = String(article.abstract || '').replace(/\s+/g, ' ').trim();
 const teaser = abstractText.length > 320
  ? `${abstractText.slice(0, 320).replace(/\s+\S*$/, '')}\u2026`
  : abstractText;

 const headHtml = `
 <div class="result-row-head result-row-meta">
 <div class="score-meter" role="img" aria-label="Similarity ${simLabel} of 1. Higher is a closer match to your query." data-tip="${escapeHtml(scoreHelp)}">
  <span class="score-meter-value">${escapeHtml(simLabel)}</span>
  <span class="score-meter-track"><span class="score-meter-fill"></span></span>
 </div>
 <span class="result-venue">${venue}</span>
 <span class="result-year">${year}</span>
 <span class="result-tags">
  <span class="tag">${escapeHtml(getSourceName(article.source))}</span>
 </span>
 </div>
 <h3 class="article-title result-row-title">${escapeHtml(article.title || '')}</h3>
 <div class="byline result-byline">${byline}</div>
 ${teaser ? `<p class="result-teaser">${escapeHtml(teaser)}</p>` : ''}`;

 const noteRowHtml = `
 <div class="note-row" ${noteVal ? '' : 'hidden'}>
 <label class="help-text">Private note</label>
 <textarea class="note-field" rows="2" placeholder="Optional study note (saved to your account)…"></textarea>
 <button type="button" class="btn btn-sm btn-secondary note-save">Save note</button>
 </div>`;

 {
  card.innerHTML = `
  <div class="result-row-main">
  ${headHtml}
  <button type="button" class="result-toggle" aria-expanded="false" aria-controls="result-body-${idx}">Open</button>
  <div class="article-body result-row-body" id="result-body-${idx}">
  ${keyPointsHtml}
  <details class="result-abstract">
  <summary>Show abstract</summary>
  <div class="article-meta result-row-ids">
  <span><strong>ID:</strong> ${idLink}</span>
  ${clusterBit}
  </div>
  ${studyTypeHtml}
  <div class="article-abstract">${abstractHtml}</div>
  </details>
  ${picoHtml}
  <div class="article-actions-row result-row-inline-actions">
  ${openLink}
  <button type="button" class="more-like-this-btn"
   data-tip="Rank the rest of your collection by how similar they are to this paper">More like this</button>
  </div>
  ${noteRowHtml}
  </div>
  </div>
  <div class="result-row-rail" aria-label="Article actions">
  <button type="button" class="star-btn ${starred ? 'is-starred' : ''}" data-tip="${starred ? 'Remove star' : 'Star article'}" aria-label="${starred ? 'Remove star' : 'Star article'}" aria-pressed="${starred ? 'true' : 'false'}">${starLabelHtml(starred)}</button>
  <button type="button" class="note-toggle" ${noteVal ? 'hidden' : ''}><span class="result-rail-label">Note</span></button>
  <button type="button" class="not-relevant-btn"
   data-tip="Screen this paper out as not about your topic"><span class="result-rail-label">Not relevant</span></button>
  </div>
  `;
 }

 // CSP: no style= attributes — set the score via a CSS variable.
 // The ring (.score-meter) and the fill both read --score-pct.
 const fill = card.querySelector('.score-meter-fill');
 if (fill) fill.style.setProperty('--score-pct', `${simPct}%`);
 const meter = card.querySelector('.score-meter');
 if (meter) meter.style.setProperty('--score-pct', `${simPct}%`);

 const noteField = card.querySelector('.note-field');
 noteField.value = noteVal;

 const noteToggle = card.querySelector('.note-toggle');
 const noteRow = card.querySelector('.note-row');
 noteToggle.addEventListener('click', (e) => {
 e.preventDefault();
 noteToggle.hidden = true;
 noteRow.hidden = false;
 noteField.focus();
 });

 if (typeof bindAiArticleActions === 'function') {
 bindAiArticleActions(card, article);
 }

 const moreBtn = card.querySelector('.more-like-this-btn');
 if (moreBtn) {
  moreBtn.addEventListener('click', async (e) => {
   e.preventDefault();
   e.stopPropagation();
   await doMoreLikeThisPaper(article);
  });
 }

 const starBtn = card.querySelector('.star-btn');
 starBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 e.stopPropagation();
 const next = !starBtn.classList.contains('is-starred');
 // Flip before saving; roll back on failure.
 starBtn.classList.toggle('is-starred', next);
 starBtn.innerHTML = starLabelHtml(next);
 starBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
 starBtn.dataset.tip = next ? 'Remove star' : 'Star article';
 starBtn.setAttribute('aria-label', starBtn.dataset.tip);
 if (next) {
  starBtn.classList.remove('pop');
  void starBtn.offsetWidth;
  starBtn.classList.add('pop');
 }
 try {
 await apiCall('/api/notes', {
 method: 'POST',
 body: withPageLibrary({
 article_id: article.article_id,
 source: article.source,
 starred: next,
 }),
 });
 patchLastResult(article, { starred: next });
 bumpStarredCount(next ? 1 : -1);
 if (displayFilterState.starred) showSearchResults();
 } catch (err) {
 starBtn.classList.toggle('is-starred', !next);
 starBtn.innerHTML = starLabelHtml(!next);
 starBtn.setAttribute('aria-pressed', next ? 'false' : 'true');
 starBtn.dataset.tip = next ? 'Star article' : 'Remove star';
 starBtn.setAttribute('aria-label', starBtn.dataset.tip);
 showNotification(`Could not save star: ${err.message}`, 'error');
 }
 });

 const saveBtn = card.querySelector('.note-save');
 saveBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 const prev = saveBtn.textContent;
 saveBtn.disabled = true;
 saveBtn.textContent = 'Saved';
 try {
 await apiCall('/api/notes', {
 method: 'POST',
 body: withPageLibrary({
 article_id: article.article_id,
 source: article.source,
 note: noteField.value,
 }),
 });
 patchLastResult(article, { note: noteField.value });
 showNotification('Note saved.', 'success');
 if (displayFilterState.noted) showSearchResults();
 } catch (err) {
 saveBtn.textContent = prev;
 showNotification(`Could not save note: ${err.message}`, 'error');
 } finally {
 saveBtn.disabled = false;
 if (saveBtn.textContent === 'Saved') {
  setTimeout(() => { if (saveBtn.textContent === 'Saved') saveBtn.textContent = prev; }, 1200);
 }
 }
 });

 const notRelBtn = card.querySelector('.not-relevant-btn');
 if (notRelBtn) {
 notRelBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 e.stopPropagation();
 notRelBtn.disabled = true;
 // Optimistic remove; restore card if the write fails.
 // Keep the strip returned for *this* row — never look up the first pending strip.
 const parent = card.parentNode;
 const nextSibling = card.nextSibling;
 const strip = replaceCardWithUndo(card, article, { pending: true, why: true });
 try {
 await apiCall('/api/screening', {
 method: 'POST',
 body: withPageLibrary({
 items: [{ article_id: article.article_id, source: article.source }],
 action: 'exclude',
 reason: 'off_topic',
 }),
 });
 if (strip) {
  strip.classList.remove('is-pending');
  const undoBtn = strip.querySelector('.undo-not-relevant');
  // Undo stays disabled until exclude finishes (avoids include-before-exclude race).
  if (undoBtn) {
   undoBtn.disabled = false;
   undoBtn.removeAttribute('aria-disabled');
  }
  const whyBtn = strip.querySelector('.why-not-relevant');
  if (whyBtn) {
   whyBtn.disabled = false;
   whyBtn.removeAttribute('aria-disabled');
  }
 }
 showNotification('Marked not relevant (screened out).', 'success');
 lastResults = lastResults.filter(
 (a) => !(a.article_id === article.article_id && a.source === article.source)
 );
 // Leave the undo strip in place. Rebuilding the list would remove Why? and Undo.
 syncResultCountAfterScreen();
 } catch (err) {
 if (strip && parent && strip.parentNode === parent) {
  parent.replaceChild(card, strip);
 } else if (parent) {
  parent.insertBefore(card, nextSibling);
 }
 notRelBtn.disabled = false;
 showNotification(`Could not screen out: ${err.message}`, 'error');
 }
 });
 }

 {
  card.style.setProperty('--i', String(idx));
  const toggle = card.querySelector('.result-toggle');
  if (toggle) {
   toggle.addEventListener('click', (e) => { e.stopPropagation(); toggleResultRow(card); });
  }
  // Tabbing past the reading panel's last control moves on to the next
  // paper, which would sit hidden under the panel: close it instead.
  card.addEventListener('focusout', (e) => {
   const next = e.relatedTarget;
   if (!next || !card.classList.contains('is-open') || !resultsUseReaderPanel()) return;
   if (card.contains(next) || !next.closest('#results-list') || next.classList.contains('result-ghost')) return;
   setResultRowOpen(card, false);
  });
  card.addEventListener('click', (e) => {
   if (card.classList.contains('is-open')) return;
   if (e.target.closest('button, a, summary, textarea, input, select, details[open]')) return;
   openResultRow(card, true);
  });
 }
 return card;
}

/** One list of reasons: the chips in #simple-set-aside-reasons. */
function fillWhyReasonChips(host) {
 const src = document.getElementById('simple-set-aside-reasons');
 if (!src || !host) return;
 src.querySelectorAll('[data-reason]').forEach((btn) => {
  const reason = btn.getAttribute('data-reason');
  if (!reason || reason === 'low_relevance' || reason === 'duplicate' || reason === 'cluster') return;
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = btn.className;
  copy.setAttribute('data-reason', reason);
  const current = reason === 'off_topic';
  copy.setAttribute('aria-pressed', current ? 'true' : 'false');
  copy.textContent = btn.textContent.trim();
  host.appendChild(copy);
 });
}

/** Keep the result count honest without rebuilding the list (that would drop the undo strip). */
function syncResultCountAfterScreen() {
 const hasHits = !!(lastResults && lastResults.length);
 const countEl = document.getElementById('result-count');
 if (countEl && !displayFiltersActive()) {
  countEl.textContent = String(hasHits ? lastResults.length : 0);
 }
 const exportSec = document.getElementById('export-results-section');
 if (exportSec && !displayFiltersActive()) {
  exportSec.hidden = !hasHits;
  exportSec.style.display = hasHits ? 'block' : 'none';
 }
 if (typeof updateSimpleSearchPanel === 'function') updateSimpleSearchPanel(hasHits);
 refreshRailStats();
}

/** Swap a result card for a short-lived undo strip after Not relevant. Returns the strip. */
function replaceCardWithUndo(cardEl, article, opts) {
 const parent = cardEl.parentNode;
 if (!parent) return null;
 setResultRowOpen(cardEl, false);
 const pending = !!(opts && opts.pending);
 const why = !!(opts && opts.why);
 const whyBtnHtml = why
  ? ` <button type="button" class="btn btn-sm btn-secondary why-not-relevant"${
   pending ? ' disabled aria-disabled="true"' : ''
  }>Why?</button>`
  : '';
 const strip = document.createElement('div');
 strip.className = 'article-card not-relevant-undo' + (pending ? ' is-pending' : '');
 strip.innerHTML =
 `<span class="info-text">Screened out: <em>${escapeHtml(article.title || 'paper')}</em></span>`
 + whyBtnHtml
 + ` <button type="button" class="btn btn-sm btn-secondary undo-not-relevant"${
  pending ? ' disabled aria-disabled="true"' : ''
 }>Undo</button>`
 + (why ? '<div class="set-aside-reason-chips why-reason-chips" hidden></div>' : '');
 parent.replaceChild(strip, cardEl);
 const undoBtn = strip.querySelector('.undo-not-relevant');
 undoBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 if (strip.classList.contains('is-pending') || undoBtn.disabled) return;
 undoBtn.disabled = true;
 try {
 await apiCall('/api/screening', {
 method: 'POST',
 body: withPageLibrary({
 items: [{ article_id: article.article_id, source: article.source }],
 action: 'include',
 }),
 });
 if (strip.parentNode === parent) {
  parent.replaceChild(cardEl, strip);
 }
 const nr = cardEl.querySelector('.not-relevant-btn');
 if (nr) nr.disabled = false;
 showNotification('Restored to included set.', 'success');
 if (!lastResults.some(
 (a) => a.article_id === article.article_id && a.source === article.source
 )) {
 lastResults.push(article);
 }
 syncResultCountAfterScreen();
 } catch (err) {
 undoBtn.disabled = false;
 showNotification(`Undo failed: ${err.message}`, 'error');
 }
 });
 if (why) {
  const whyButton = strip.querySelector('.why-not-relevant');
  const chips = strip.querySelector('.why-reason-chips');
  whyButton.addEventListener('click', (e) => {
   e.preventDefault();
   if (strip.classList.contains('is-pending') || whyButton.disabled) return;
   if (!chips.childElementCount) fillWhyReasonChips(chips);
   if (!chips.childElementCount) {
    showNotification('Could not load reasons.', 'error');
    return;
   }
   chips.hidden = !chips.hidden;
   if (!chips.hidden) {
    const current = chips.querySelector('[aria-pressed="true"]') || chips.querySelector('button');
    if (current) current.focus();
   }
  });
  chips.addEventListener('click', async (e) => {
   const chip = e.target.closest('[data-reason]');
   if (!chip || chip.disabled) return;
   e.preventDefault();
   const reason = chip.getAttribute('data-reason');
   if (!reason || reason === 'low_relevance' || reason === 'duplicate' || reason === 'cluster') return;
   const buttons = chips.querySelectorAll('button');
   buttons.forEach((b) => { b.disabled = true; });
   try {
    await apiCall('/api/screening', {
     method: 'POST',
     body: withPageLibrary({
      items: [{ article_id: article.article_id, source: article.source }],
      action: 'exclude',
      reason: reason,
     }),
    });
    buttons.forEach((b) => {
     b.setAttribute('aria-pressed', b === chip ? 'true' : 'false');
    });
    const info = strip.querySelector('.info-text');
    if (info) {
     info.innerHTML = `Screened out (${escapeHtml(chip.textContent.trim())}): <em>${escapeHtml(article.title || 'paper')}</em>`;
    }
   } catch (err) {
    showNotification(`Could not save the reason: ${err.message}`, 'error');
   } finally {
    buttons.forEach((b) => { b.disabled = false; });
   }
  });
 }
 return strip;
}

/** Skeleton rows matching .article-card geometry (prevents layout jump). */
function showResultSkeletons(n) {
 const container = document.getElementById('results-list');
 if (!container) return;
 const count = Math.max(1, Math.min(n || 5, 10));
 const bits = [];
 for (let i = 0; i < count; i++) {
  bits.push(
   '<div class="skeleton-card" aria-hidden="true">'
   + '<div class="skeleton-line skeleton-line-title"></div>'
   + '<div class="skeleton-line skeleton-line-meta"></div>'
   + '<div class="skeleton-line skeleton-line-body"></div>'
   + '</div>'
  );
 }
 container.innerHTML = bits.join('');
}

/**
 * After a failed search, remove skeleton rows so the UI does not look mid-load.
 * Prefer restoring the previous hit list when we still have one.
 */
function clearResultSkeletonsOnError(fromRestore) {
 const container = document.getElementById('results-list');
 if (!container) return;
 const hasSkeletons = !!container.querySelector('.skeleton-card');
 if (!hasSkeletons && lastResults && lastResults.length) return;
 if (lastResults && lastResults.length) {
  showSearchResults();
  return;
 }
 container.innerHTML = fromRestore
  ? ''
  : '<p class="info-text">Search failed. Try again.</p>';
 const countEl = document.getElementById('result-count');
 if (countEl) countEl.textContent = '0';
}

function displayFiltersActive() {
 if (displayFilterState.starred || displayFilterState.noted || displayFilterState.recent) {
  return true;
 }
 return Object.keys(displayFilterState.sources).some((k) => displayFilterState.sources[k]);
}

function visibleResults() {
 const srcOn = Object.keys(displayFilterState.sources).filter(
  (k) => displayFilterState.sources[k]
 );
 const recentYear = displayRecentYear();
 return clientSort((lastResults || []).filter((a) => {
  if (displayFilterState.starred && !a.starred) return false;
  if (displayFilterState.noted && !String(a.note || '').trim()) return false;
  if (displayFilterState.recent && parseYear(a.year) < recentYear) return false;
  if (srcOn.length && srcOn.indexOf(a.source) === -1) return false;
  return true;
 }), searchState.filters.sort_by);
}

function showSearchResults(fullList) {
 const fresh = Array.isArray(fullList);
 if (fresh) lastResults = fullList;
 const bar = document.getElementById('display-filters');
 const hasHits = !!(lastResults && lastResults.length);
 if (bar) bar.hidden = !hasHits;
 syncDisplayFilterSourceChips();
 syncDisplayFilterChipState();
 syncSimpleResultChips();
 const shown = visibleResults();
 renderResults(shown);
 const countEl = document.getElementById('result-count');
 if (countEl) {
  countEl.textContent = displayFiltersActive() && hasHits
   ? `${shown.length} of ${lastResults.length}`
   : String(hasHits ? lastResults.length : 0);
 }
 const countLine = document.getElementById('results-count-line');
 if (countLine) countLine.hidden = !hasHits;
 const status = document.getElementById('display-filter-status');
 if (status) {
  status.textContent = displayFiltersActive() && hasHits
   ? (shown.length
    ? `Showing ${shown.length} of ${lastResults.length} on this page.`
    : 'No papers match these filters. Click All to show everything.')
   : '';
 }
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 const exportSec = document.getElementById('export-results-section');
 if (exportSec) {
  exportSec.hidden = !shown.length;
  exportSec.style.display = shown.length ? 'block' : 'none';
 }
 updateSimpleSearchPanel(hasHits);
 // A new ranking (a search, More like this) starts at its top, even when the
 // student asked for it from far down the old list.
 if (fresh && hasHits) scrollToFreshRanking();
}

/** Bring the top of a new ranking into view, under the pinned tile. A dialog
 * (Search options) pins the page while it is open and scrolls it back to the
 * old spot when it closes, so wait until it has let go. */
function scrollToFreshRanking() {
 const list = document.getElementById('results-list');
 if (!list || typeof list.getBoundingClientRect !== 'function') return;
 if (document.body.classList.contains('lra-modal-open')) {
  if (typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(scrollToFreshRanking);
  return;
 }
 const target = list.getBoundingClientRect().top + window.scrollY - searchTileClearance();
 if (target < window.scrollY) window.scrollTo({ top: Math.max(0, target), behavior: 'auto' });
}

/** Pixels from the window top that the pinned Search tile and its soft edge
 * cover; what is scrolled into view lands below this. */
function searchTileClearance() {
 const band = typeof getComputedStyle === 'function'
  ? Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--search-band-h'))
  : 0;
 return (band || 96) + 40;
}

function syncDisplayFilterSourceChips() {
 const host = document.getElementById('display-filter-chips');
 if (!host) return;
 host.querySelectorAll('[data-filter-source]').forEach((el) => el.remove());
 const seen = {};
 (lastResults || []).forEach((a) => {
  if (a && a.source) seen[a.source] = true;
 });
 const ids = Object.keys(seen).sort();
 if (ids.length < 2) {
  Object.keys(displayFilterState.sources).forEach((k) => {
   if (!seen[k]) delete displayFilterState.sources[k];
  });
  return;
 }
 ids.forEach((id) => {
  if (!(id in displayFilterState.sources)) displayFilterState.sources[id] = false;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'display-filter-chip';
  btn.setAttribute('data-filter-source', id);
  btn.setAttribute('aria-pressed', 'false');
  const name = typeof getSourceName === 'function' ? getSourceName(id) : id;
  btn.textContent = name;
  host.appendChild(btn);
 });
 Object.keys(displayFilterState.sources).forEach((k) => {
  if (!seen[k]) delete displayFilterState.sources[k];
 });
}

function syncDisplayFilterChipState() {
 const host = document.getElementById('display-filter-chips');
 if (!host) return;
 const any = displayFiltersActive();
 host.querySelectorAll('[data-filter]').forEach((btn) => {
  const key = btn.getAttribute('data-filter');
  const on = key === 'all' ? !any : !!displayFilterState[key];
  btn.classList.toggle('is-on', on);
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
 });
 host.querySelectorAll('[data-filter-source]').forEach((btn) => {
  const id = btn.getAttribute('data-filter-source');
  const on = !!displayFilterState.sources[id];
  btn.classList.toggle('is-on', on);
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
 });
}

function wireDisplayFilters() {
 const recentBtn = document.getElementById('display-filter-recent');
 if (recentBtn) recentBtn.textContent = `Since ${displayRecentYear()}`;
 const host = document.getElementById('display-filter-chips');
 if (!host || host.dataset.wired === '1') return;
 host.dataset.wired = '1';
 host.addEventListener('click', (ev) => {
  const btn = ev.target && ev.target.closest
   ? ev.target.closest('[data-filter], [data-filter-source]')
   : null;
  if (!btn || !host.contains(btn)) return;
  ev.preventDefault();
  const src = btn.getAttribute('data-filter-source');
  const key = btn.getAttribute('data-filter');
  if (key === 'all' || (!src && !key)) {
   displayFilterState.starred = false;
   displayFilterState.noted = false;
   displayFilterState.recent = false;
   Object.keys(displayFilterState.sources).forEach((k) => {
    displayFilterState.sources[k] = false;
   });
  } else if (src) {
   displayFilterState.sources[src] = !displayFilterState.sources[src];
  } else if (key === 'starred' || key === 'noted' || key === 'recent') {
   displayFilterState[key] = !displayFilterState[key];
  }
  showSearchResults();
  saveSearchSession();
 });
}

function patchLastResult(article, patch) {
 if (!article || !lastResults) return;
 lastResults.forEach((a) => {
  if (a.article_id === article.article_id && a.source === article.source) {
   Object.assign(a, patch);
  }
 });
}

function renderResults(results) {
 const container = document.getElementById('results-list');
 container.innerHTML = '';

 if (results.length === 0) {
 // Filters that hide every paper already say so in the filter bar.
 if (!(lastResults && lastResults.length)) {
  container.innerHTML = '<p class="info-text">No results found. Try a different query or check that embeddings have been created.</p>';
 }
 return;
 }

 const renderItem = (article, idx) => buildResultListItem(results, article, idx);
 if (typeof renderPaginatedList === 'function') {
 renderPaginatedList(container, results, renderItem, { noun: 'results' });
 } else {
 results.forEach((article, idx) => container.appendChild(renderItem(article, idx)));
 }
 // The grid layouts start closed: an open paper there is a side panel.
 if (!resultsUseReaderPanel()) {
  openResultRow(container.querySelector('.result-row'), false);
 }

 if (typeof enhanceAbstracts === 'function') {
 enhanceAbstracts(container);
 }
}

/** A result card; the first undated paper under a year range starts the "No year listed" group. */
function buildResultListItem(results, article, idx) {
 const card = buildResultCard(article, idx);
 if (!article.no_year || (idx > 0 && results[idx - 1].no_year)) return card;
 const group = document.createDocumentFragment();
 const heading = document.createElement('h3');
 heading.className = 'results-group-heading';
 heading.textContent = 'No year listed';
 const note = document.createElement('p');
 note.className = 'results-group-note';
 note.textContent = 'These papers give no publication year, so the year range cannot place them.';
 group.append(heading, note, card);
 return group;
}

/**
 * Download exactly the papers currently on screen (lastResults), in that order.
 * Primary path for RIS → Zotero File → Import.
 */
/** Phase 6 Simple: show export/report panel once results exist (left rail). */
function updateSimpleSearchPanel(hasResults) {
 const panel = document.getElementById('search-simple-panel');
 const resultsSec = document.getElementById('results-section');
 if (!panel) return;
 const hasLibraryPapers = Object.values(librarySourceCounts).some((n) => Number(n) > 0);
 const show = !!((hasResults || hasLibraryPapers));
 if (show) {
  panel.removeAttribute('hidden');
  panel.hidden = false;
 } else {
  panel.setAttribute('hidden', '');
  panel.hidden = true;
 }
 if (resultsSec) resultsSec.classList.toggle('has-simple-panel', show);
 syncSimplePanelClearance();
}

async function promptSimpleExportScope() {
 const pageLibrary = typeof pageLibraryId === 'function' ? pageLibraryId() : '';
 if (!pageLibrary) {
  showNotification('Reload this page before exporting your library.', 'error');
  return;
 }
 const hasResults = visibleResults().length > 0;
 const scopes = [];
 if (hasResults) scopes.push({ value: 'results', label: 'These visible results', primary: true });
 scopes.push(
  { value: 'all', label: 'All library papers' },
  { value: 'included', label: 'Kept papers' },
  { value: 'excluded', label: 'Set-aside papers' },
  { value: 'starred', label: 'Starred papers' },
  { value: null, label: 'Cancel', cancel: true },
 );
 const scope = await openSiteChoice({
  title: 'Save your work',
  message: 'Choose which papers to export.',
  choices: scopes,
  cancelLabel: 'Cancel',
  onReady: (root) => {
   const actions = root.querySelector('.lra-modal-actions');
   if (actions) actions.id = 'simple-export-scope';
  },
 });
 if (!scope) return;
 const formats = scope === 'results'
  ? ['ris', 'bibtex', 'csv', 'txt']
  : ['ris', 'bibtex', 'csv', 'txt', 'apa'];
 const format = await openSiteChoice({
  title: 'Export format',
  message: 'Choose a file format.',
  choices: [...formats.map((value, index) => ({
   value, label: value === 'bibtex' ? 'BibTeX' : value.toUpperCase(), primary: index === 0,
  })), { value: null, label: 'Cancel', cancel: true }],
  cancelLabel: 'Cancel',
 });
 if (!format) return;
 const currentLibrary = typeof pageLibraryId === 'function' ? pageLibraryId() : '';
 if (pageLibrary && currentLibrary !== pageLibrary) {
  const status = document.getElementById('simple-export-status');
  if (status) status.textContent = 'Your library changed. Reload this page before exporting.';
  showNotification('Your library changed. Reload this page before exporting.', 'error');
  return;
 }
 if (scope === 'results') {
  await doExportResults(format, pageLibrary);
 } else {
  await doExportLibrary(scope, format, pageLibrary);
 }
}

async function doExportLibrary(scope, format, libraryId) {
 const status = document.getElementById('simple-export-status');
 if (status) status.textContent = 'Preparing download…';
 try {
  const params = new URLSearchParams({ scope, format });
  if (libraryId) params.set('library_id', libraryId);
  const response = await fetch(`/api/export/library?${params.toString()}`, {
   credentials: 'same-origin',
  });
  if (!response.ok) {
   const err = await response.json().catch(() => ({ detail: response.statusText }));
   throw new Error(err.detail || 'Export failed');
  }
  const blob = await response.blob();
  const cd = response.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(cd);
  const fallback = `library_${scope}.${format === 'bibtex' ? 'bib' : format === 'apa' ? 'txt' : format}`;
  const filename = (match && match[1]) || fallback;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  if (status) status.textContent = `Downloaded ${filename}.`;
  showNotification(`Downloaded ${filename}`, 'success');
 } catch (e) {
  if (status) status.textContent = e.message || 'Export failed';
  showNotification(`Export failed: ${e.message}`, 'error');
 }
}

function syncSimplePanelClearance() {
 const panel = document.getElementById('search-simple-panel');
 const resultsSec = document.getElementById('results-section');
 if (!resultsSec) return;
 if (!panel || panel.hidden || !resultsSec.classList.contains('has-simple-panel')) {
  resultsSec.style.removeProperty('--simple-panel-h');
  return;
 }
 const pos = window.getComputedStyle(panel).position;
 if (pos !== 'fixed') {
  resultsSec.style.removeProperty('--simple-panel-h');
  return;
 }
 resultsSec.style.setProperty('--simple-panel-h', `${panel.offsetHeight}px`);
}

function watchSimplePanelClearance() {
 const panel = document.getElementById('search-simple-panel');
 if (!panel || panel.dataset.clearanceWired === '1') return;
 panel.dataset.clearanceWired = '1';
 if (typeof ResizeObserver === 'function') {
  const ro = new ResizeObserver(() => syncSimplePanelClearance());
  ro.observe(panel);
 }
 window.addEventListener('resize', syncSimplePanelClearance);
}

/** Desktop: keep the Save-your-work rail under the sticky Search tile. */
function syncSimpleRailAnchor() {
 const root = document.documentElement;
 const query = document.getElementById('search-query-top');
 if (!query || query.hidden) {
  root.style.removeProperty('--simple-rail-top');
  return;
 }
 const qStyle = window.getComputedStyle(query);
 if (qStyle.position !== 'sticky') {
  root.style.removeProperty('--simple-rail-top');
  return;
 }
 const stickyTop = Number.parseFloat(qStyle.top) || 0;
 const gap = 12;
 const top = Math.ceil(stickyTop + query.getBoundingClientRect().height + gap);
 root.style.setProperty('--simple-rail-top', `${top}px`);
}

function watchSimpleRailAnchor() {
 if (watchSimpleRailAnchor._wired) return;
 watchSimpleRailAnchor._wired = true;
 const query = document.getElementById('search-query-top');
 if (query && typeof ResizeObserver === 'function') {
  new ResizeObserver(() => syncSimpleRailAnchor()).observe(query);
 }
 window.addEventListener('resize', syncSimpleRailAnchor);
 syncSimpleRailAnchor();
}

/** The scope note stays collapsed until the reader asks for it. */
function syncSearchScopeNote() {
 const note = document.querySelector('.search-scope-note');
 if (!note) return;
 {
  note.removeAttribute('open');
 }
}

/** While the Search tile is pinned, a strip of the page backdrop fills from
 * the top of the window to just under it, edge to edge, then fades over a
 * blur, so results scrolling up soften and disappear beneath it instead of
 * showing in the gap above or beside it. */
function watchSearchTileScroll() {
 const tile = document.getElementById('search-query-top');
 if (!tile || watchSearchTileScroll._wired) return;
 watchSearchTileScroll._wired = true;
 const marker = document.createElement('div');
 marker.setAttribute('aria-hidden', 'true');
 tile.before(marker);
 const band = document.createElement('div');
 band.className = 'search-band';
 band.setAttribute('aria-hidden', 'true');
 const blur = document.createElement('div');
 blur.className = 'search-band-blur';
 blur.setAttribute('aria-hidden', 'true');
 document.body.append(blur, band);
 let queued = false;

 function update() {
  queued = false;
  const style = window.getComputedStyle(tile);
  const stickyTop = Number.parseFloat(style.top) || 0;
  const pinned = !tile.hidden && style.position === 'sticky'
   && marker.getBoundingClientRect().top < stickyTop
   && tile.getBoundingClientRect().top <= stickyTop + 0.5;
  tile.classList.toggle('is-stuck', pinned);
  band.classList.toggle('is-on', pinned);
  blur.classList.toggle('is-on', pinned);
  const root = document.documentElement;
  if (pinned) {
   const gap = 12;
   root.style.setProperty('--search-band-h', `${Math.ceil(stickyTop + tile.offsetHeight + gap)}px`);
  } else {
   root.style.removeProperty('--search-band-h');
  }
  // The grid reading panel starts under whatever is on top: the nav (and any
  // banner above it) or the Search tile while it is on screen.
  const nav = document.getElementById('site-navbar');
  const tileRect = tile.getBoundingClientRect();
  const tileBottom = !tile.hidden && tileRect.height && tileRect.bottom > 0 ? tileRect.bottom : 0;
  const navBottom = nav ? nav.getBoundingClientRect().bottom : 0;
  root.style.setProperty('--reader-top', `${Math.ceil(Math.max(navBottom, tileBottom) + 12)}px`);
 }
 window.addEventListener('scroll', () => {
  if (!queued) {
   queued = true;
   window.requestAnimationFrame(update);
  }
 }, { passive: true });
 window.addEventListener('resize', update);
 if (typeof ResizeObserver === 'function') new ResizeObserver(update).observe(tile);
 update();
}

document.addEventListener('DOMContentLoaded', () => {
 watchSimplePanelClearance();
 watchSimpleRailAnchor();
 watchSearchTileScroll();
 watchLayoutForOpenPapers();
 syncSearchScopeNote();

});

async function doExportResults(format, libraryId = '') {
 const exportRows = visibleResults();
 if (!exportRows.length) {
  showNotification('Run a search first, then export the results shown on screen.', 'error');
  return;
 }
 const status = document.getElementById('export-results-status');
 const simpleStatus = document.getElementById('simple-export-status');
 if (status) {
  status.textContent = 'Preparing download…';
  status.className = 'status-indicator loading';
 }
 if (simpleStatus) simpleStatus.textContent = 'Preparing download…';
 const items = exportRows.map((a) => ({
  article_id: a.article_id,
  source: a.source,
 }));
 try {
  const headers = {
   Accept: '*/*',
   'Content-Type': 'application/json',
  };
  if (typeof getCsrfToken === 'function') {
   headers['X-CSRF-Token'] = getCsrfToken();
  }
  const endpoint = libraryId ? `/api/export/selection?${new URLSearchParams({ library_id: libraryId })}` : '/api/export/selection';
  const response = await fetch(endpoint, {
   method: 'POST',
   headers,
   credentials: 'same-origin',
   body: JSON.stringify({ format: format || 'ris', items }),
  });
  if (!response.ok) {
   const err = await response.json().catch(() => ({ detail: response.statusText }));
   throw new Error(err.detail || 'Export failed');
  }
  const blob = await response.blob();
  const cd = response.headers.get('Content-Disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(cd);
  const fallback = {
   ris: 'search_results.ris',
   bibtex: 'search_results.bib',
   csv: 'search_results.csv',
   txt: 'search_results.txt',
  }[format] || 'search_results.bin';
  const filename = (match && match[1]) || fallback;
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  if (status) {
   status.textContent = `Downloaded ${filename} (${items.length} paper${items.length === 1 ? '' : 's'}). Import with Zotero → File → Import…`;
   status.className = 'status-indicator success';
  }
  if (simpleStatus) {
   simpleStatus.textContent = `Downloaded ${filename} (${items.length} paper${items.length === 1 ? '' : 's'}).`;
  }
  showNotification(`Downloaded ${filename}`, 'success');
 } catch (e) {
  if (status) {
   status.textContent = e.message || 'Export failed';
   status.className = 'status-indicator error';
  }
  if (simpleStatus) simpleStatus.textContent = e.message || 'Export failed';
  showNotification(`Export failed: ${e.message}`, 'error');
 }
}
