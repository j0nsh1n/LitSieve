// === Statistics / Clean up page logic ===

// Last Quick-screen exclusion set (for one-click undo).
let _quickScreenLastItems = null;
// Current preview candidates (titles student can uncheck before apply).
let _quickScreenCandidates = [];

document.addEventListener('DOMContentLoaded', () => {
 loadStatistics();
 initQuickScreen();

 const slider = document.getElementById('threshold');
 const display = document.getElementById('threshold-display');
 if (slider && display) {
 slider.addEventListener('input', () => {
 display.textContent = parseFloat(slider.value).toFixed(2);
 });
 }

 const detectBtn = document.getElementById('detect-btn');
 const resolveBtn = document.getElementById('resolve-btn');
 if (detectBtn) detectBtn.addEventListener('click', doDetectDuplicates);
 if (resolveBtn) resolveBtn.addEventListener('click', doResolveAll);

 const reportBtn = document.getElementById('screening-report-btn');
 if (reportBtn) {
 reportBtn.addEventListener('click', loadScreeningReport);
 }
});

function initQuickScreen() {
 const queryEl = document.getElementById('quick-screen-query');
 if (!queryEl) return;

 // Prefill from last fetch query (browser-local prefs).
 try {
 const prefs = JSON.parse(localStorage.getItem('lra_fetch_prefs_v1') || 'null');
 if (prefs && prefs.query && !queryEl.value) {
 queryEl.value = prefs.query;
 }
 } catch (e) { /* ignore */ }

 const applyNowBtn = document.getElementById('quick-screen-apply-now-btn');
 const previewBtn = document.getElementById('quick-screen-preview-btn');
 const applyBtn = document.getElementById('quick-screen-apply-btn');
 const undoBtn = document.getElementById('quick-screen-undo-btn');
 if (applyNowBtn) applyNowBtn.addEventListener('click', doQuickScreenApplyNow);
 if (previewBtn) previewBtn.addEventListener('click', doQuickScreenPreview);
 if (applyBtn) applyBtn.addEventListener('click', doQuickScreenApply);
 if (undoBtn) undoBtn.addEventListener('click', doQuickScreenUndo);
}

function _quickScreenQueryAndFraction() {
 const queryEl = document.getElementById('quick-screen-query');
 const fracEl = document.getElementById('quick-screen-fraction');
 const query = (queryEl && queryEl.value || '').trim();
 const fraction = parseFloat((fracEl && fracEl.value) || '0.25');
 return { query, fraction };
}

/** Primary path: rank + screen out immediately (no mandatory preview). */
async function doQuickScreenApplyNow() {
 const applyNowBtn = document.getElementById('quick-screen-apply-now-btn');
 const undoBtn = document.getElementById('quick-screen-undo-btn');
 const applyBtn = document.getElementById('quick-screen-apply-btn');
 const panel = document.getElementById('quick-screen-preview');
 const { query, fraction } = _quickScreenQueryAndFraction();

 if (!query) {
 showNotification('Enter a research question first.', 'error');
 return;
 }

 setLoading(applyNowBtn, true);
 if (applyBtn) applyBtn.hidden = true;
 _quickScreenCandidates = [];
 setStatus('quick-screen-status', 'Ranking papers and screening out the least related…', 'info');
 if (panel) {
 panel.classList.add('u-hidden');
 panel.innerHTML = '';
 }

 try {
 const data = await apiCall('/api/screening/quick-preview', {
 method: 'POST',
 body: { query, fraction },
 });
 const candidates = data.candidates || [];
 if (!candidates.length) {
 setStatus(
 'quick-screen-status',
 data.total_ranked
  ? 'Nothing to screen out — every prepared paper already looks related, or only one paper is left.'
  : 'No prepared papers to rank yet. Fetch and prepare papers first.',
 'info'
 );
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
 _quickScreenLastItems = items;
 _quickScreenCandidates = [];
 setStatus(
 'quick-screen-status',
 `Screened out ${applied.count || items.length} of ${data.total_ranked} paper(s) as low relevance. Undo is available once.`,
 'success'
 );
 showNotification(`Screened out ${applied.count || items.length} paper(s).`, 'success');
 if (undoBtn) undoBtn.hidden = false;
 // Show what was removed (read-only list for transparency).
 if (panel) {
 panel.innerHTML = '';
 const list = document.createElement('div');
 list.className = 'quick-screen-list';
 candidates.forEach((c) => {
 const row = document.createElement('div');
 row.className = 'quick-screen-row';
 row.innerHTML =
 `<span class="qs-title">${escapeHtml(c.title || '(no title)')}</span>`
 + `<span class="qs-meta help-text">${escapeHtml(String(c.year || ''))}`
 + ` · ${escapeHtml(getSourceName(c.source))} · screened out</span>`;
 list.appendChild(row);
 });
 panel.appendChild(list);
 panel.classList.remove('u-hidden');
 }
 loadStatistics();
 } catch (e) {
 setStatus('quick-screen-status', `Quick screen failed: ${e.message}`, 'error');
 showNotification(`Quick screen failed: ${e.message}`, 'error');
 } finally {
 setLoading(applyNowBtn, false);
 }
}

/** Optional: preview titles first, then apply selected. */
async function doQuickScreenPreview() {
 const previewBtn = document.getElementById('quick-screen-preview-btn');
 const applyBtn = document.getElementById('quick-screen-apply-btn');
 const panel = document.getElementById('quick-screen-preview');
 const { query, fraction } = _quickScreenQueryAndFraction();

 if (!query) {
 showNotification('Enter a research question first.', 'error');
 return;
 }

 setLoading(previewBtn, true);
 if (applyBtn) applyBtn.hidden = true;
 _quickScreenCandidates = [];
 setStatus('quick-screen-status', 'Ranking papers against your question…', 'info');
 if (panel) {
 panel.classList.add('u-hidden');
 panel.innerHTML = '';
 }

 try {
 const data = await apiCall('/api/screening/quick-preview', {
 method: 'POST',
 body: { query, fraction },
 });
 const candidates = data.candidates || [];
 _quickScreenCandidates = candidates;
 if (!candidates.length) {
 setStatus(
 'quick-screen-status',
 data.total_ranked
  ? 'No suggestions — every prepared paper already looks related, or only one paper is left.'
  : 'No prepared papers to rank yet. Fetch and prepare papers first.',
 'info'
 );
 return;
 }
 setStatus(
 'quick-screen-status',
 `Preview: ${candidates.length} of ${data.total_ranked} paper(s) least related. Uncheck any to keep, then Screen out selected.`,
 'success'
 );
 renderQuickScreenPreview(candidates);
 if (applyBtn) applyBtn.hidden = false;
 } catch (e) {
 setStatus('quick-screen-status', `Preview failed: ${e.message}`, 'error');
 showNotification(`Quick screen preview failed: ${e.message}`, 'error');
 } finally {
 setLoading(previewBtn, false);
 }
}

function renderQuickScreenPreview(candidates) {
 const panel = document.getElementById('quick-screen-preview');
 if (!panel) return;
 panel.innerHTML = '';
 const list = document.createElement('div');
 list.className = 'quick-screen-list';
 candidates.forEach((c, i) => {
 const row = document.createElement('label');
 row.className = 'quick-screen-row radio-label';
 const checked = 'checked';
 row.innerHTML =
 `<input type="checkbox" class="qs-item" data-idx="${i}" ${checked}>`
 + `<span class="qs-title">${escapeHtml(c.title || '(no title)')}</span>`
 + `<span class="qs-meta help-text">${escapeHtml(String(c.year || ''))}`
 + ` · ${escapeHtml(getSourceName(c.source))}</span>`;
 list.appendChild(row);
 });
 panel.appendChild(list);
 panel.classList.remove('u-hidden');
}

function selectedQuickScreenItems() {
 const panel = document.getElementById('quick-screen-preview');
 if (!panel) return [];
 const items = [];
 panel.querySelectorAll('.qs-item:checked').forEach((cb) => {
 const idx = parseInt(cb.getAttribute('data-idx'), 10);
 const c = _quickScreenCandidates[idx];
 if (c) items.push({ article_id: c.article_id, source: c.source });
 });
 return items;
}

async function doQuickScreenApply() {
 const items = selectedQuickScreenItems();
 const applyBtn = document.getElementById('quick-screen-apply-btn');
 const undoBtn = document.getElementById('quick-screen-undo-btn');
 if (!items.length) {
 showNotification('Select at least one paper to screen out, or cancel.', 'error');
 return;
 }
 setLoading(applyBtn, true);
 try {
 const data = await apiCall('/api/screening', {
 method: 'POST',
 body: { items, action: 'exclude', reason: 'low_relevance' },
 });
 _quickScreenLastItems = items;
 setStatus(
 'quick-screen-status',
 `Screened out ${data.count || items.length} paper(s) as low relevance. Undo is available once.`,
 'success'
 );
 showNotification(`Screened out ${data.count || items.length} paper(s).`, 'success');
 if (undoBtn) undoBtn.hidden = false;
 if (applyBtn) applyBtn.hidden = true;
 const panel = document.getElementById('quick-screen-preview');
 if (panel) {
 panel.classList.add('u-hidden');
 panel.innerHTML = '';
 }
 _quickScreenCandidates = [];
 loadStatistics();
 } catch (e) {
 setStatus('quick-screen-status', `Apply failed: ${e.message}`, 'error');
 showNotification(`Could not screen out papers: ${e.message}`, 'error');
 } finally {
 setLoading(applyBtn, false);
 }
}

async function doQuickScreenUndo() {
 const undoBtn = document.getElementById('quick-screen-undo-btn');
 if (!_quickScreenLastItems || !_quickScreenLastItems.length) {
 showNotification('Nothing to undo.', 'info');
 return;
 }
 setLoading(undoBtn, true);
 try {
 const data = await apiCall('/api/screening', {
 method: 'POST',
 body: { items: _quickScreenLastItems, action: 'include' },
 });
 setStatus(
 'quick-screen-status',
 `Restored ${data.count || _quickScreenLastItems.length} paper(s).`,
 'success'
 );
 showNotification('Quick screen undone.', 'success');
 _quickScreenLastItems = null;
 if (undoBtn) undoBtn.hidden = true;
 loadStatistics();
 } catch (e) {
 setStatus('quick-screen-status', `Undo failed: ${e.message}`, 'error');
 showNotification(`Undo failed: ${e.message}`, 'error');
 } finally {
 setLoading(undoBtn, false);
 }
}

async function loadScreeningReport() {
 const btn = document.getElementById('screening-report-btn');
 const panel = document.getElementById('screening-report-panel');
 const body = document.getElementById('screening-report-body');
 if (!panel || !body) return;
 setLoading(btn, true);
 try {
 // Same text as Download (.txt) — one source of truth on the server.
 const response = await fetch('/api/screening-report?format=txt', {
 credentials: 'same-origin',
 });
 if (!response.ok) {
 if (response.status === 401) {
 window.location.href = '/login';
 throw new Error('Not authenticated');
 }
 throw new Error('Request failed');
 }
 body.textContent = (await response.text()).trimEnd();
 panel.hidden = false;
 } catch (e) {
 showNotification(`Screening report failed: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

function updateCleanupWorkVisibility(stats) {
 // Hide dup / quick-screen / report until papers are prepared — empty CTA only.
 const emb = (stats && stats.articles_with_embeddings) || 0;
 const ready = emb > 0;
 document.querySelectorAll('.cleanup-work').forEach((el) => {
  el.hidden = !ready;
 });
}

async function loadStatistics() {
 try {
 const stats = await apiCall('/api/statistics');

 document.getElementById('stat-total').textContent = stats.total_articles;
 document.getElementById('stat-embeddings').textContent = stats.articles_with_embeddings;
 document.getElementById('stat-excluded').textContent = stats.excluded_articles ?? 0;

 if (typeof applyEmptyState === 'function') {
 applyEmptyState('dup-empty-state', stats, 'embeddings', 'dup-empty-msg');
 }
 updateCleanupWorkVisibility(stats);

 const sources = stats.sources || {};
 const sourceKeys = Object.keys(sources);
 if (sourceKeys.length > 0) {
 const maxCount = Math.max(...Object.values(sources), 1);
 const container = document.getElementById('source-breakdown');
 container.innerHTML = '';
 sourceKeys.forEach(source => {
 const count = sources[source];
 const pct = (count / maxCount) * 100;
 const div = document.createElement('div');
 div.className = 'source-bar';
 div.innerHTML = `
 <span class="source-name">${escapeHtml(getSourceName(source))}</span>
 <div class="source-bar-fill">
 <div class="source-track">
 <div class="source-bar-inner" style="width: ${pct}%"></div>
 </div>
 </div>
 <span class="source-count">${count}</span>
 `;
 container.appendChild(div);
 });
 document.getElementById('source-breakdown-section').style.display = 'block';
 }

 renderYearTimeline(stats.year_counts || {});
 } catch (e) {
 showNotification('Failed to load statistics.', 'error');
 }
}

function renderYearTimeline(yearCounts) {
 // Nested under "Articles by Source" as a collapsed disclosure.
 const details = document.getElementById('year-timeline-details');
 const container = document.getElementById('year-timeline');
 if (!details || !container) return;

 const keys = Object.keys(yearCounts || {});
 if (!keys.length) {
 details.hidden = true;
 container.innerHTML = '';
 return;
 }

 // Sort years ascending; "unknown" last.
 keys.sort((a, b) => {
 if (a === 'unknown') return 1;
 if (b === 'unknown') return -1;
 return parseInt(a, 10) - parseInt(b, 10);
 });
 const maxCount = Math.max(...keys.map(k => yearCounts[k]), 1);
 container.innerHTML = '';
 keys.forEach(year => {
 const count = yearCounts[year];
 const pct = Math.max(4, (count / maxCount) * 100);
 const div = document.createElement('div');
 div.className = 'source-bar year-bar';
 div.innerHTML = `
 <span class="source-name">${escapeHtml(year)}</span>
 <div class="source-bar-fill">
 <div class="source-track">
 <div class="source-bar-inner" style="width: ${pct}%"></div>
 </div>
 </div>
 <span class="source-count">${count}</span>
 `;
 container.appendChild(div);
 });
 details.hidden = false;
}

async function doDetectDuplicates() {
 const threshold = parseFloat(document.getElementById('threshold').value);
 const btn = document.getElementById('detect-btn');
 setLoading(btn, true);
 setStatus('duplicates-status', 'Analyzing similarity matrix...', 'info');

 try {
 const data = await apiCall('/api/detect-duplicates', {
 method: 'POST',
 body: { threshold }
 });

 if (data.total === 0) {
 setStatus('duplicates-status', 'No duplicates found at this threshold.', 'success');
 document.getElementById('duplicates-list').innerHTML = '';
 } else {
 const groups = groupDuplicates(data.duplicates);
 setStatus('duplicates-status',
 `Found ${data.total} duplicate pair(s) across ${groups.length} group(s). Showing top 50 pairs.`, 'success');
 renderDuplicates(groups);
 }
 } catch (e) {
 setStatus('duplicates-status', `Error: ${e.message}`, 'error');
 showNotification(`Detection failed: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

// === Auto-resolve all duplicate groups server-side ===
async function doResolveAll() {
 const threshold = parseFloat(document.getElementById('threshold').value);
 const btn = document.getElementById('resolve-btn');
 setLoading(btn, true);
 setStatus('duplicates-status', 'Resolving duplicate groups…', 'info');

 try {
 const data = await apiCall('/api/resolve-duplicates', {
 method: 'POST',
 body: { threshold }
 });
 if (data.groups === 0) {
 setStatus('duplicates-status', 'No duplicate groups to resolve at this threshold.', 'success');
 } else {
 setStatus('duplicates-status',
 `Resolved ${data.groups} group(s): kept the best copy of each, screened out ${data.excluded} redundant article(s).`,
 'success');
 showNotification(`Screened out ${data.excluded} duplicate article(s).`, 'success');
 }
 document.getElementById('duplicates-list').innerHTML = '';
 loadStatistics(); // refresh the Screened Out counter
 } catch (e) {
 setStatus('duplicates-status', `Error: ${e.message}`, 'error');
 showNotification(`Resolve failed: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

// === Resolve ONE group: keep the clicked article, screen out its siblings ===
async function keepArticle(group, keeper, cardEl) {
 const losers = group.articles
 .filter(a => !(a.article_id === keeper.article_id && a.source === keeper.source))
 .map(a => ({ article_id: a.article_id, source: a.source }));
 if (losers.length === 0) return;

 try {
 await apiCall('/api/screening', {
 method: 'POST',
 body: { items: losers, action: 'exclude' }
 });
 cardEl.classList.add('dup-resolved');
 cardEl.querySelectorAll('.keep-btn').forEach(b => b.remove());
 showNotification(`Kept ${getSourceName(keeper.source)} copy; screened out ${losers.length} other(s).`, 'success');
 loadStatistics();
 } catch (e) {
 showNotification(`Failed to resolve group: ${e.message}`, 'error');
 }
}

// === Union-Find grouping ===
function groupDuplicates(pairs) {
 const parent = {};
 const articleMap = {};

 function find(x) {
 if (!(x in parent)) parent[x] = x;
 if (parent[x] !== x) parent[x] = find(parent[x]);
 return parent[x];
 }
 function union(x, y) { parent[find(x)] = find(y); }

 pairs.forEach(pair => {
 const k1 = `${pair.article1.source}::${pair.article1.article_id}`;
 const k2 = `${pair.article2.source}::${pair.article2.article_id}`;
 articleMap[k1] = pair.article1;
 articleMap[k2] = pair.article2;
 union(k1, k2);
 });

 const groups = {};
 Object.keys(articleMap).forEach(k => {
 const root = find(k);
 if (!groups[root]) groups[root] = { articles: [], maxSim: 0, pairs: [] };
 });
 pairs.forEach(pair => {
 const k1 = `${pair.article1.source}::${pair.article1.article_id}`;
 const root = find(k1);
 groups[root].pairs.push(pair);
 if (pair.similarity > groups[root].maxSim) groups[root].maxSim = pair.similarity;
 });
 Object.keys(articleMap).forEach(k => {
 const root = find(k);
 groups[root].articles.push(articleMap[k]);
 });

    // Deduplicate articles within each group
 Object.values(groups).forEach(g => {
 const seen = new Set();
 g.articles = g.articles.filter(a => {
 const k = `${a.source}::${a.article_id}`;
 if (seen.has(k)) return false;
 seen.add(k);
 return true;
 });
 });

 return Object.values(groups).sort((a, b) => b.maxSim - a.maxSim);
}

// === Render grouped duplicate list ===
function buildDupGroupCard(group) {
 const { articles, maxSim } = group;
 const details = document.createElement('details');
 details.className = 'dup-group';

 const label = articles.length === 2
 ? `Pair: ${truncate(articles[0].title, 55)}`
 : `Group of ${articles.length}: ${truncate(articles[0].title, 50)}`;

 const summary = document.createElement('summary');
 summary.innerHTML = `
 <span class="sim-badge sim-high">${maxSim.toFixed(3)}</span>
 <span class="dup-group-label">${escapeHtml(label)}</span>
 <span class="dup-sources">${articles.map(a => escapeHtml(getSourceName(a.source))).join(' · ')}</span>
 `;
 details.appendChild(summary);

 const body = document.createElement('div');
 body.className = 'dup-body';
 body.appendChild(buildCompareTable(articles, group, details));
 details.appendChild(body);
 return details;
}

function renderDuplicates(groups) {
 const container = document.getElementById('duplicates-list');
 container.innerHTML = '';

 if (!groups.length) return;

 if (typeof renderPaginatedList === 'function') {
 renderPaginatedList(container, groups, (g) => buildDupGroupCard(g), {
 noun: 'groups',
 });
 } else {
 groups.forEach((g) => container.appendChild(buildDupGroupCard(g)));
 }
}

// === Side-by-side compare table ===
function buildCompareTable(articles, group, cardEl) {
 const n = articles.length;
 const fields = [
 { key: 'title', label: 'Title' },
 { key: 'year', label: 'Year' },
 { key: 'journal', label: 'Journal' },
 { key: 'authors', label: 'Authors', format: a => (a.authors || []).join('; ') },
 { key: 'abstract', label: 'Abstract', isAbstract: true },
 ];

 const table = document.createElement('div');
 table.className = 'compare-table';
 table.style.gridTemplateColumns = `100px repeat(${n}, 1fr)`;

    // Header row: blank + per-article source/ID
 const blankHeader = document.createElement('div');
 blankHeader.className = 'compare-field-label compare-header-cell';
 table.appendChild(blankHeader);

 articles.forEach(a => {
 const url = getArticleUrl(a.article_id, a.source);
 const idHtml = url
 ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(truncate(a.article_id, 24))}</a>`
 : escapeHtml(truncate(a.article_id, 24));
 const cell = document.createElement('div');
 cell.className = 'compare-cell compare-header-cell';
 cell.innerHTML = `<strong>${escapeHtml(getSourceName(a.source))}</strong><span class="compare-id">${idHtml}</span>`;

 const keepBtn = document.createElement('button');
 keepBtn.className = 'btn btn-sm btn-secondary keep-btn';
 keepBtn.textContent = 'Keep this';
 keepBtn.title = 'Keep this copy and screen out the others in this group';
 keepBtn.addEventListener('click', () => keepArticle(group, a, cardEl));
 cell.appendChild(keepBtn);

 table.appendChild(cell);
 });

    // Field rows
 fields.forEach(field => {
 const values = articles.map(a =>
 field.format ? field.format(a) : String(a[field.key] || '')
 );
 const allSame = values.every(v => v === values[0]);

 const labelCell = document.createElement('div');
 labelCell.className = 'compare-field-label' + (allSame ? '' : ' label-diff');
 labelCell.innerHTML = escapeHtml(field.label) + (allSame ? '' : ' <span class="diff-marker">≠</span>');
 table.appendChild(labelCell);

 values.forEach(val => {
 const cell = document.createElement('div');
 cell.className = 'compare-cell' + (allSame ? '' : ' cell-diff') + (field.isAbstract ? ' abstract-cell' : '');
 cell.textContent = val;
 table.appendChild(cell);
 });
 });

 return table;
}

function truncate(text, len) {
 if (!text) return '';
 return text.length > len ? text.substring(0, len) + '…' : text;
}
