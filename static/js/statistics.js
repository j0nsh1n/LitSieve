// === Statistics page logic ===

document.addEventListener('DOMContentLoaded', () => {
 loadStatistics();

 const slider = document.getElementById('threshold');
 const display = document.getElementById('threshold-display');
 slider.addEventListener('input', () => {
 display.textContent = parseFloat(slider.value).toFixed(2);
 });

 document.getElementById('detect-btn').addEventListener('click', doDetectDuplicates);
 document.getElementById('resolve-btn').addEventListener('click', doResolveAll);

 const reportBtn = document.getElementById('screening-report-btn');
 if (reportBtn) {
 reportBtn.addEventListener('click', loadScreeningReport);
 }
});

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

async function loadStatistics() {
 try {
 const stats = await apiCall('/api/statistics');

 document.getElementById('stat-total').textContent = stats.total_articles;
 document.getElementById('stat-embeddings').textContent = stats.articles_with_embeddings;
 document.getElementById('stat-excluded').textContent = stats.excluded_articles ?? 0;

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
 } catch (e) {
 showNotification('Failed to load statistics.', 'error');
 }
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
function renderDuplicates(groups) {
 const container = document.getElementById('duplicates-list');
 container.innerHTML = '';

 groups.forEach(group => {
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

 container.appendChild(details);
 });
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
