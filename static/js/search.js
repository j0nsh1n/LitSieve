// === Search page logic ===

let lastSearchParams = null;
let lastQueryTokens = [];

document.addEventListener('DOMContentLoaded', () => {
 applyAvailableSources();

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
 document.getElementById('export-csv').addEventListener('click', () => doExport('csv'));
 document.getElementById('export-txt').addEventListener('click', () => doExport('txt'));

 document.querySelectorAll('[data-lib-export-format]').forEach(btn => {
 btn.addEventListener('click', () => {
 const format = btn.getAttribute('data-lib-export-format') || 'csv';
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
    // Longest first so multi-word-ish tokens win when overlapping.
 const sorted = [...new Set(tokens)].sort((a, b) => b.length - a.length);
 const pattern = new RegExp('(' + sorted.map(escapeRegExp).join('|') + ')', 'gi');
 return escapeHtml(raw).replace(pattern, '<mark class="query-hl">$1</mark>');
}

function escapeRegExp(s) {
 return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function doSearch() {
 const method = document.querySelector('input[name="input_method"]:checked').value;
 const queryText = buildQueryText();
 if (!queryText) {
 showNotification(method === 'seed' ? 'Enter a seed id or title.' : 'Please enter a search query.', 'error');
 return;
 }

 const topK = parseInt(document.getElementById('top-k').value, 10);
 const sortBy = document.getElementById('sort-by').value;
 const picoBoost = document.getElementById('pico-boost').checked;
 const selectedSources = Array.from(
 document.querySelectorAll('input[name="search-source"]:checked')
 ).map(cb => cb.value);
 if (selectedSources.length === 0) {
 showNotification('Please select at least one source.', 'error');
 return;
 }
    // Topic pool is managed via screening (checkboxes above) — no separate
    // cluster_filter. Backend already skips screened-out papers.
 const btn = document.getElementById('search-btn');
 setLoading(btn, true);

 lastSearchParams = {
 query_text: queryText,
 top_k: topK,
 sort_by: sortBy,
 source_filter: selectedSources,
 pico_boost: picoBoost,
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
 top_k: topK,
 source_filter: selectedSources,
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
 if (sortBy !== 'similarity') {
 data.results = clientSort(data.results || [], sortBy);
 }
 } else {
 document.getElementById('seed-banner').style.display = 'none';
 data = await apiCall('/api/search', {
 method: 'POST',
 body: {
 query_text: queryText,
 top_k: topK,
 sort_by: sortBy,
 source_filter: selectedSources,
 pico_boost: picoBoost,
 },
 });
 }

 renderResults(data.results || []);
 document.getElementById('result-count').textContent = (data.results || []).length;
 document.getElementById('results-section').style.display = 'block';
 } catch (e) {
 showNotification(`Search failed: ${e.message}`, 'error');
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

function renderResults(results) {
 const container = document.getElementById('results-list');
 container.innerHTML = '';

 if (results.length === 0) {
 container.innerHTML = '<p class="info-text">No results found. Try a different query or check that embeddings have been created.</p>';
 return;
 }

 results.forEach((article, idx) => {
 const details = document.createElement('details');
 details.className = 'article-card';
 if (idx < 3) details.setAttribute('open', '');

 const sim = article.similarity_score || 0;
 let simClass = 'sim-low';
 if (sim >= 0.7) simClass = 'sim-high';
 else if (sim >= 0.4) simClass = 'sim-med';

 const url = getArticleUrl(article.article_id, article.source);
 const idText = escapeHtml(article.article_id || '');
 const idLink = url
 ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="article-link">${idText}</a>`
 : idText;

 const authors = (article.authors || []).join('; ');
 const abstractHtml = highlightText(article.abstract || '', lastQueryTokens);
 const picoHtml = renderPicoBlock(article.pico);
 const starred = !!article.starred;
 const noteVal = article.note || '';
 const clusterBit = article.cluster_label
 ? `<span><strong>Cluster:</strong> ${escapeHtml(String(article.cluster_label))}</span>`
 : '';

 details.innerHTML = `
 <summary>
 <span class="sim-badge ${simClass}">${Number(sim).toFixed(3)}</span>
 <span class="article-title">${escapeHtml(article.title || '')}</span>
 <button type="button" class="star-btn ${starred ? 'is-starred' : ''}" title="Bookmark" aria-label="Star article">${starred ? '★' : '☆'}</button>
 </summary>
 <div class="article-body">
 <div class="article-meta">
 <span><strong>Year:</strong> ${escapeHtml(article.year || '')}</span>
 <span><strong>Journal:</strong> ${escapeHtml(article.journal || '')}</span>
 <span><strong>Source:</strong> ${escapeHtml(getSourceName(article.source))}</span>
 <span><strong>ID:</strong> ${idLink}</span>
 ${clusterBit}
 </div>
 <div class="article-meta meta-authors">
 <span><strong>Authors:</strong> ${escapeHtml(authors)}</span>
 </div>
 <div class="article-abstract">${abstractHtml}</div>
 ${picoHtml}
 <div class="note-row">
 <label class="help-text">Private note</label>
 <textarea class="note-field" rows="2" placeholder="Optional study note (saved to your account)…"></textarea>
 <button type="button" class="btn btn-sm btn-secondary note-save">Save note</button>
 </div>
 </div>
 `;

 const noteField = details.querySelector('.note-field');
 noteField.value = noteVal;

 const starBtn = details.querySelector('.star-btn');
 starBtn.addEventListener('click', async (e) => {
 e.preventDefault();
 e.stopPropagation();
 const next = !starBtn.classList.contains('is-starred');
 try {
 await apiCall('/api/notes', {
 method: 'POST',
 body: {
 article_id: article.article_id,
 source: article.source,
 starred: next,
 },
 });
 starBtn.classList.toggle('is-starred', next);
 starBtn.textContent = next ? '★' : '☆';
 } catch (err) {
 showNotification(`Could not save star: ${err.message}`, 'error');
 }
 });

 const saveBtn = details.querySelector('.note-save');
 saveBtn.addEventListener('click', async (e) => {
 e.preventDefault();
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
 showNotification(`Could not save note: ${err.message}`, 'error');
 }
 });

 container.appendChild(details);
 });

 if (typeof enhanceAbstracts === 'function') {
 enhanceAbstracts(container);
 }
}

function doExport(format) {
 if (!lastSearchParams || lastSearchParams.mode === 'seed') {
 if (lastSearchParams && lastSearchParams.mode === 'seed') {
 showNotification('For seed search, use the library export buttons above, or search with Text/PICO to export ranked results.', 'info');
 return;
 }
 showNotification('Please perform a search first.', 'error');
 return;
 }

 const params = new URLSearchParams({
 query_text: lastSearchParams.query_text,
 top_k: lastSearchParams.top_k,
 sort_by: lastSearchParams.sort_by,
 source_filter: (lastSearchParams.source_filter || []).join(','),
 format: format,
 pico_boost: lastSearchParams.pico_boost ? 'true' : 'false',
 });
 window.location.href = `/api/search/export?${params.toString()}`;
}
