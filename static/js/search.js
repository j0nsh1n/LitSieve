// === Search page logic ===

let lastSearchParams = null;
let lastQueryTokens = [];
/** Last on-screen result list (export “these results” uses this exact order). */
let lastResults = [];

/** sessionStorage key: refresh keeps query + filters; re-runs search on load. */
const SEARCH_SESSION_KEY = 'lra_search_session_v1';
/** Skip auto-restore while applying form (avoids loops). */
let _restoringSearch = false;

document.addEventListener('DOMContentLoaded', () => {
 // Empty state + hide search UI until papers are prepared; only then restore.
 loadSearchEmptyState()
  .then((stats) => {
   const ready = !!(stats && (stats.articles_with_embeddings || 0) > 0);
   return applyAvailableSources().then(() => {
    if (ready) return restoreSearchSession();
   });
  })
  .catch(() => { /* ignore */ });
 refreshStarredCount();

 document.querySelectorAll('input[name="input_method"]').forEach(radio => {
 radio.addEventListener('change', () => {
 const v = radio.value;
 document.getElementById('text-input-panel').style.display = v === 'text' ? 'block' : 'none';
 document.getElementById('pico-input-panel').style.display = v === 'pico' ? 'block' : 'none';
 document.getElementById('seed-input-panel').style.display = v === 'seed' ? 'block' : 'none';
 });
 });

 const topkSlider = document.getElementById('top-k');
 const topkDisplay = document.getElementById('topk-display');
 topkSlider.addEventListener('input', () => {
 topkDisplay.textContent = topkSlider.value;
 });

 document.getElementById('search-btn').addEventListener('click', doSearch);
 const starredBtn = document.getElementById('starred-search-btn');
 if (starredBtn) starredBtn.addEventListener('click', doStarredSearch);

 // Phase 8: one summonable Help panel (replaces inline help-details on Search).
 const helpToggle = document.getElementById('page-help-toggle');
 const helpPanel = document.getElementById('page-help');
 if (helpToggle && helpPanel) {
  helpToggle.addEventListener('click', () => {
   const open = helpPanel.hasAttribute('hidden');
   if (open) helpPanel.removeAttribute('hidden');
   else helpPanel.setAttribute('hidden', '');
   helpToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
 }

 const risBtn = document.getElementById('export-results-ris');
 if (risBtn) risBtn.addEventListener('click', () => doExportResults('ris'));

 // Phase 6 Simple side panel (same export path; Advanced never shows the panel).
 const simpleExportBtn = document.getElementById('simple-export-results-btn');
 if (simpleExportBtn) {
  simpleExportBtn.addEventListener('click', () => doExportResults('ris'));
 }

 document.querySelectorAll('[data-lib-export-format]').forEach(btn => {
 btn.addEventListener('click', () => {
 const format = btn.getAttribute('data-lib-export-format') || 'ris';
 const scopeEl = document.getElementById('lib-export-scope');
 const scope = scopeEl ? scopeEl.value : 'all';
 window.location.href =
 `/api/export/library?scope=${encodeURIComponent(scope)}&format=${encodeURIComponent(format)}`;
 });
 });

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

function captureSearchSession(kind) {
 // kind: 'text' | 'pico' | 'seed' | 'starred'
 const mode = kind === 'starred'
  ? 'starred'
  : (document.querySelector('input[name="input_method"]:checked') || {}).value || 'text';
 const filters = collectSearchFilters();
 return {
  v: 1,
  library_id: activeLibraryId(),
  mode,
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
  saved_at: Date.now(),
 };
}

async function saveSearchSession(kind) {
 if (_restoringSearch) return;
 try {
  const state = captureSearchSession(kind);
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
 } finally {
  _restoringSearch = false;
 }
}

async function restoreSearchSession() {
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

function collectSearchFilters() {
 const topK = parseInt(document.getElementById('top-k').value, 10);
 const sortBy = document.getElementById('sort-by').value;
 const picoBoost = document.getElementById('pico-boost').checked;
 const lexicalEl = document.getElementById('lexical-boost');
 const lexicalBoost = lexicalEl ? lexicalEl.checked : true;
 const selectedSources = Array.from(
 document.querySelectorAll('input[name="search-source"]:checked')
 ).map(cb => cb.value);
 return {
 top_k: topK,
 sort_by: sortBy,
 pico_boost: picoBoost,
 lexical_boost: lexicalBoost,
 source_filter: selectedSources,
 year_min: parseOptionalYear('year-min'),
 year_max: parseOptionalYear('year-max'),
 };
}

function updateSearchWorkVisibility(stats) {
 // Hide query/controls/export until papers are prepared (same gate as empty-state).
 const emb = (stats && stats.articles_with_embeddings) || 0;
 const ready = emb > 0;
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

async function loadSearchEmptyState() {
 try {
 const stats = await apiCall('/api/statistics');
 if (typeof applyEmptyState === 'function') {
 applyEmptyState('search-empty-state', stats, 'embeddings', 'search-empty-msg');
 }
 updateSearchWorkVisibility(stats);
 return stats;
 } catch (e) {
 updateSearchWorkVisibility({ articles_with_embeddings: 0 });
 return null;
 }
}

async function refreshStarredCount() {
 const el = document.getElementById('starred-count');
 if (!el) return;
 try {
 // Library export rows for starred scope is heavy; use screening report + notes via statistics if needed.
 // Cheap path: open a tiny search is wrong; count from export library is ok for small corpora.
 const r = await apiCall('/api/screening-report?format=json');
 el.textContent = String(r.starred || 0);
 } catch (e) {
 el.textContent = '?';
 }
}

async function applyAvailableSources() {
 let sources = {};
 try {
 const stats = await apiCall('/api/statistics');
 sources = stats.sources || {};
 } catch (e) {
 return;
 }

 let anyAvailable = false;
 document.querySelectorAll('input[name="search-source"]').forEach(cb => {
 const count = sources[cb.value] || 0;
 const label = cb.closest('.radio-label');
 cb.disabled = count === 0;
 cb.checked = count > 0;
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

 const hint = document.getElementById('source-availability-hint');
 if (hint) {
 hint.textContent = anyAvailable
 ? ''
 : 'No articles yet - fetch some on the Data Management page first.';
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

async function doSearch(opts) {
 const fromRestore = !!(opts && opts.fromRestore);
 const method = document.querySelector('input[name="input_method"]:checked').value;
 const queryText = buildQueryText();
 if (!queryText) {
 if (!fromRestore) {
  showNotification(method === 'seed' ? 'Enter a seed id or title.' : 'Please enter a search query.', 'error');
 }
 return;
 }

 const filters = collectSearchFilters();
 if (filters.source_filter.length === 0) {
 if (!fromRestore) showNotification('Please select at least one source.', 'error');
 return;
 }
 const btn = document.getElementById('search-btn');
 setLoading(btn, true);
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 showResultSkeletons(6);

 lastSearchParams = {
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
 if (filters.sort_by !== 'similarity') {
 data.results = clientSort(data.results || [], filters.sort_by);
 }
 } else {
 document.getElementById('seed-banner').style.display = 'none';
 data = await apiCall('/api/search', {
 method: 'POST',
 body: {
 query_text: queryText,
 top_k: filters.top_k,
 sort_by: filters.sort_by,
 source_filter: filters.source_filter,
 pico_boost: filters.pico_boost,
 lexical_boost: filters.lexical_boost,
 year_min: filters.year_min,
 year_max: filters.year_max,
 },
 });
 }

 const results = data.results || [];
 lastResults = results;
 renderResults(results);
 document.getElementById('result-count').textContent = results.length;
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 const exportSec = document.getElementById('export-results-section');
 if (exportSec) {
  exportSec.hidden = !results.length;
  exportSec.style.display = results.length ? 'block' : 'none';
 }
 updateSimpleSearchPanel(results.length > 0);
 // Persist query + filters so a browser refresh restores this search.
 await saveSearchSession(method);
 } catch (e) {
 if (!fromRestore) showNotification(`Search failed: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

async function doStarredSearch(opts) {
 const fromRestore = !!(opts && opts.fromRestore);
 const filters = collectSearchFilters();
 if (filters.source_filter.length === 0) {
 if (!fromRestore) showNotification('Please select at least one source.', 'error');
 return;
 }
 const btn = document.getElementById('starred-search-btn');
 setLoading(btn, true);
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 showResultSkeletons(6);
 lastSearchParams = {
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
 if (filters.sort_by !== 'similarity') {
 results = clientSort(results, filters.sort_by);
 }
 lastResults = results;
 renderResults(results);
 document.getElementById('result-count').textContent = results.length;
 const resultsSec = document.getElementById('results-section');
 if (resultsSec) {
  resultsSec.classList.remove('u-hidden');
  resultsSec.style.display = 'block';
 }
 const exportSec = document.getElementById('export-results-section');
 if (exportSec) {
  exportSec.hidden = !results.length;
  exportSec.style.display = results.length ? 'block' : 'none';
 }
 updateSimpleSearchPanel(results.length > 0);
 await refreshStarredCount();
 await saveSearchSession('starred');
 } catch (e) {
 if (!fromRestore) showNotification(`Starred search failed: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

function clientSort(results, sortBy) {
 const arr = results.slice();
 if (sortBy === 'year') {
 arr.sort((a, b) => (parseYear(b.year) - parseYear(a.year)));
 } else if (sortBy === 'journal') {
 arr.sort((a, b) => (a.journal || '').localeCompare(b.journal || ''));
 } else if (sortBy === 'title') {
 arr.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
 }
 return arr;
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
 const matched = article.study_type_matched
 ? ` Matched: “${article.study_type_matched}”.`
 : '';
 const formalBit = formal && formal !== label ? ` Formal name: ${formal}.` : '';
 const title = `${disc}${formalBit}${matched}${warn ? ' ' + warn : ''} Confidence: ${conf}.`;
 const warnMark = (band === 'high') ? '' : ' <span class="study-type-warn" aria-hidden="true">!</span>';
 const meaningLine = meaning
 ? `<span class="study-type-meaning">${escapeHtml(meaning)}</span>`
 : '';
 return `<span class="study-type-wrap">`
 + `<span class="study-type-badge band-${escapeHtml(band)}" title="${escapeHtml(title)}">`
 + `${escapeHtml(label)}${warnMark}</span>`
 + meaningLine
 + `</span>`;
}

function buildResultCard(article, idx) {
 // Phase 8: scannable row with numeric 0–1 score meter (not Low/Medium/High details).
 const card = document.createElement('article');
 card.className = 'article-card result-row';
 card.dataset.resultIndex = String(idx);

 const sim = Number(article.similarity_score) || 0;
 const simPct = Math.max(0, Math.min(100, Math.round(sim * 1000) / 10));
 const simLabel = sim.toFixed(3);

 const url = getArticleUrl(article.article_id, article.source);
 const idText = escapeHtml(article.article_id || '');
 const idLink = url
 ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="article-link">${idText}</a>`
 : idText;

 const authors = (article.authors || []).join('; ');
 const abstractHtml = highlightText(article.abstract || '', lastQueryTokens);
 const picoHtml = renderPicoBlock(article.pico);
 const keyPointsHtml = typeof renderKeyPointsHtml === 'function'
 ? renderKeyPointsHtml(article.key_points, {
 articleId: article.article_id,
 source: article.source,
 origin: article.key_points_origin || 'extractive',
 })
 : '';
 const studyTypeHtml = renderStudyTypeBadge(article);
 const starred = !!article.starred;
 const noteVal = article.note || '';
 const clusterBit = article.cluster_label
 ? `<span><strong>Cluster:</strong> ${escapeHtml(String(article.cluster_label))}</span>`
 : '';

 card.innerHTML = `
 <div class="result-row-head">
 <div class="score-meter" role="img" aria-label="Similarity ${simLabel} of 1">
  <span class="score-meter-track"><span class="score-meter-fill"></span></span>
  <span class="score-meter-value">${escapeHtml(simLabel)}</span>
 </div>
 <h3 class="article-title result-row-title">${escapeHtml(article.title || '')}</h3>
 <button type="button" class="star-btn ${starred ? 'is-starred' : ''}" title="Bookmark" aria-label="Star article">${starred ? '★' : '☆'}</button>
 </div>
 <div class="article-body result-row-body">
 <div class="article-meta">
 <span><strong>Year:</strong> ${escapeHtml(article.year || '')}</span>
 <span><strong>Journal:</strong> ${escapeHtml(article.journal || '')}</span>
 <span><strong>Source:</strong> ${escapeHtml(getSourceName(article.source))}</span>
 <span><strong>ID:</strong> ${idLink}</span>
 ${clusterBit}
 ${studyTypeHtml}
 </div>
 <div class="article-meta meta-authors">
 <span><strong>Authors:</strong> ${escapeHtml(authors)}</span>
 </div>
 ${keyPointsHtml}
 <div class="article-abstract">${abstractHtml}</div>
 ${picoHtml}
 <div class="article-actions-row">
 <button type="button" class="note-toggle" ${noteVal ? 'hidden' : ''}>✎ Add note</button>
 <button type="button" class="btn btn-sm btn-secondary not-relevant-btn"
  title="Screen this paper out as not about your topic">Not relevant</button>
 </div>
 <div class="note-row" ${noteVal ? '' : 'hidden'}>
 <label class="help-text">Private note</label>
 <textarea class="note-field" rows="2" placeholder="Optional study note (saved to your account)…"></textarea>
 <button type="button" class="btn btn-sm btn-secondary note-save">Save note</button>
 </div>
 </div>
 `;

 // CSP: no style= attributes — set bar width via CSS variable on the fill.
 const fill = card.querySelector('.score-meter-fill');
 if (fill) fill.style.setProperty('--score-pct', `${simPct}%`);

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

 const starBtn = card.querySelector('.star-btn');
 starBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 e.stopPropagation();
 const next = !starBtn.classList.contains('is-starred');
 // Optimistic: flip immediately; roll back on failure.
 starBtn.classList.toggle('is-starred', next);
 starBtn.textContent = next ? '★' : '☆';
 try {
 await apiCall('/api/notes', {
 method: 'POST',
 body: {
 article_id: article.article_id,
 source: article.source,
 starred: next,
 },
 });
 refreshStarredCount();
 } catch (err) {
 starBtn.classList.toggle('is-starred', !next);
 starBtn.textContent = next ? '☆' : '★';
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
 body: {
 article_id: article.article_id,
 source: article.source,
 note: noteField.value,
 },
 });
 showNotification('Note saved.', 'success');
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
 const parent = card.parentNode;
 const nextSibling = card.nextSibling;
 replaceCardWithUndo(card, article, { pending: true });
 const strip = parent && parent.querySelector('.not-relevant-undo.is-pending');
 try {
 await apiCall('/api/screening', {
 method: 'POST',
 body: {
 items: [{ article_id: article.article_id, source: article.source }],
 action: 'exclude',
 reason: 'off_topic',
 },
 });
 if (strip) strip.classList.remove('is-pending');
 showNotification('Marked not relevant (screened out).', 'success');
 lastResults = lastResults.filter(
 (a) => !(a.article_id === article.article_id && a.source === article.source)
 );
 const countEl = document.getElementById('result-count');
 if (countEl) countEl.textContent = String(lastResults.length);
 } catch (err) {
 if (strip && parent) {
  parent.replaceChild(card, strip);
 } else if (parent) {
  parent.insertBefore(card, nextSibling);
 }
 notRelBtn.disabled = false;
 showNotification(`Could not screen out: ${err.message}`, 'error');
 }
 });
 }

 return card;
}

/** Swap a result card for a short-lived undo strip after Not relevant. */
function replaceCardWithUndo(cardEl, article, opts) {
 const parent = cardEl.parentNode;
 if (!parent) return;
 const strip = document.createElement('div');
 strip.className = 'article-card not-relevant-undo' + (opts && opts.pending ? ' is-pending' : '');
 strip.innerHTML =
 `<span class="info-text">Screened out: <em>${escapeHtml(article.title || 'paper')}</em></span>`
 + ` <button type="button" class="btn btn-sm btn-secondary undo-not-relevant">Undo</button>`;
 parent.replaceChild(strip, cardEl);
 const undoBtn = strip.querySelector('.undo-not-relevant');
 undoBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 undoBtn.disabled = true;
 try {
 await apiCall('/api/screening', {
 method: 'POST',
 body: {
 items: [{ article_id: article.article_id, source: article.source }],
 action: 'include',
 },
 });
 parent.replaceChild(cardEl, strip);
 const nr = cardEl.querySelector('.not-relevant-btn');
 if (nr) nr.disabled = false;
 showNotification('Restored to included set.', 'success');
 if (!lastResults.some(
 (a) => a.article_id === article.article_id && a.source === article.source
 )) {
 lastResults.push(article);
 }
 const countEl = document.getElementById('result-count');
 if (countEl) countEl.textContent = String(lastResults.length);
 } catch (err) {
 undoBtn.disabled = false;
 showNotification(`Undo failed: ${err.message}`, 'error');
 }
 });
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

function renderResults(results) {
 const container = document.getElementById('results-list');
 container.innerHTML = '';

 if (results.length === 0) {
 container.innerHTML = '<p class="info-text">No results found. Try a different query or check that embeddings have been created.</p>';
 return;
 }

 if (typeof renderPaginatedList === 'function') {
 renderPaginatedList(container, results, buildResultCard, { noun: 'results' });
 } else {
 results.forEach((article, idx) => container.appendChild(buildResultCard(article, idx)));
 }

 if (typeof enhanceAbstracts === 'function') {
 enhanceAbstracts(container);
 }
}

/**
 * Download exactly the papers currently on screen (lastResults), in that order.
 * Primary path for RIS → Zotero File → Import.
 */
/** Phase 6 Simple: show sticky export/report panel once results exist. */
function updateSimpleSearchPanel(hasResults) {
 const panel = document.getElementById('search-simple-panel');
 const resultsSec = document.getElementById('results-section');
 if (!panel) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const show = !!(simple && hasResults);
 panel.hidden = !show;
 if (resultsSec) resultsSec.classList.toggle('has-simple-panel', show);
}

async function doExportResults(format) {
 if (!lastResults || !lastResults.length) {
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
 const items = lastResults.map((a) => ({
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
  const response = await fetch('/api/export/selection', {
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
