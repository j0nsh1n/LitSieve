// === Topic and source definitions ===
const TOPICS = [
 { id: 'health', name: 'Health & Medicine', icon: '🏥', sources: ['pubmed', 'europepmc', 'clinicaltrials', 'openalex', 'semanticscholar', 'doaj', 'zenodo', 'core'] },
 { id: 'biology', name: 'Biology', icon: '🧬', sources: ['pubmed', 'europepmc', 'openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj', 'core'] },
 { id: 'chemistry', name: 'Chemistry', icon: '⚗️', sources: ['openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj', 'core'] },
 { id: 'physics', name: 'Physics', icon: '⚛️', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'nasa_ads', 'core'] },
 { id: 'math', name: 'Mathematics', icon: '📐', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'core'] },
 { id: 'cs', name: 'Computer Science', icon: '💻', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'doaj', 'core'] },
 { id: 'earth', name: 'Earth & Environment', icon: '🌍', sources: ['openalex', 'semanticscholar', 'zenodo', 'crossref', 'doaj', 'nasa_ads', 'core'] },
 { id: 'history', name: 'History', icon: '📜', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'core'] },
 { id: 'economics', name: 'Economics', icon: '📊', sources: ['arxiv', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'core'] },
 { id: 'psychology', name: 'Psychology', icon: '🧠', sources: ['pubmed', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'core'] },
 { id: 'polisci', name: 'Political Science', icon: '🏛️', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'core'] },
 { id: 'literature', name: 'Literature & Language',icon: '📖', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'core'] },
 { id: 'education', name: 'Education', icon: '🎓', sources: ['eric', 'openalex', 'semanticscholar', 'crossref', 'doaj', 'core'] },
];

const ALL_SOURCES = {
 pubmed: { name: 'PubMed', desc: 'Biomedical & life sciences' },
 europepmc: { name: 'Europe PMC', desc: 'European biomedical literature' },
 clinicaltrials: { name: 'ClinicalTrials.gov', desc: 'Clinical trial registrations' },
 openalex: { name: 'OpenAlex', desc: 'Broad multi-discipline academic' },
 arxiv: { name: 'arXiv', desc: 'Physics, math, CS, econ preprints' },
 semanticscholar: { name: 'Semantic Scholar', desc: 'AI-curated cross-discipline research' },
 eric: { name: 'ERIC', desc: 'Education, psychology, social sciences' },
 zenodo: { name: 'Zenodo', desc: 'Open science: all fields + datasets' },
 crossref: { name: 'CrossRef', desc: 'Broad academic metadata registry' },
 doaj: { name: 'DOAJ', desc: 'Peer-reviewed open access journals' },
 nasa_ads: { name: 'NASA ADS', desc: 'Astronomy, astrophysics & geosciences' },
 core: { name: 'CORE', desc: 'Open-access full text, all disciplines' },
};

const FETCH_PREFS_KEY = 'lra_fetch_prefs_v1';

let selectedTopics = new Set();

document.addEventListener('DOMContentLoaded', () => {
 renderTopicGrid();
 renderSourceGrid();
 restoreFetchPrefs();
 loadPageData();
 refreshCoverage();
 document.getElementById('fetch-btn').addEventListener('click', doFetch);
 document.getElementById('embeddings-btn').addEventListener('click', doCreateEmbeddings);
 document.getElementById('coverage-refresh').addEventListener('click', refreshCoverage);

    // Persist prefs as the user edits.
 ['fetch-query', 'fetch-max', 'fetch-email', 'embedding-model'].forEach(id => {
 const el = document.getElementById(id);
 if (el) el.addEventListener('change', saveFetchPrefs);
 });
 document.querySelectorAll('input[name="fetch-mode"]').forEach(el => {
 el.addEventListener('change', () => {
            // Append → prefer only-new; Replace → re-embed all by default.
 syncOnlyMissingFromFetchMode();
 saveFetchPrefs();
 });
 });
 const onlyMissingEl = document.getElementById('only-missing');
 if (onlyMissingEl) {
 onlyMissingEl.addEventListener('change', saveFetchPrefs);
 }
    // Initial state from default (or restored) fetch mode.
 syncOnlyMissingFromFetchMode();
});

/**
 * Auto-check "Only embed new papers" only when fetch mode is append
 * ("Add to collection"). Replace mode unchecks it so a clean corpus
 * gets fully embedded. User can still toggle manually afterward.
 */
function syncOnlyMissingFromFetchMode() {
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const box = document.getElementById('only-missing');
 if (!box) return;
 box.checked = mode === 'append';
 const hint = document.getElementById('only-missing-hint');
 if (hint) {
 hint.textContent = mode === 'append'
 ? 'On because you chose “Add to collection” - existing vectors are kept.'
 : 'Off for “Replace collection” - all papers will be embedded. Switch to Add to auto-check this.';
 }
}

function renderTopicGrid() {
 const grid = document.getElementById('topic-grid');
 TOPICS.forEach(topic => {
 const card = document.createElement('div');
 card.className = 'topic-card';
 card.dataset.topicId = topic.id;
 card.innerHTML = `<span class="topic-icon">${topic.icon}</span><span class="topic-name">${topic.name}</span>`;
 card.addEventListener('click', () => toggleTopic(topic.id, card));
 grid.appendChild(card);
 });
}

function toggleTopic(topicId, card) {
 if (selectedTopics.has(topicId)) {
 selectedTopics.delete(topicId);
 card.classList.remove('selected');
 } else {
 selectedTopics.add(topicId);
 card.classList.add('selected');
 }
 updateRecommendedSources();
 saveFetchPrefs();
 refreshCoverage();
}

function updateRecommendedSources() {
 const recommended = new Set();
 selectedTopics.forEach(topicId => {
 const topic = TOPICS.find(t => t.id === topicId);
 if (topic) topic.sources.forEach(s => recommended.add(s));
 });

 const hint = document.getElementById('source-hint');
 hint.textContent = selectedTopics.size === 0
 ? 'Select topics above to see recommended sources, or choose manually below.'
 : 'Sources recommended for your selected topics are checked. Adjust as needed.';

 Object.keys(ALL_SOURCES).forEach(sourceId => {
 const checkbox = document.getElementById(`source-${sourceId}`);
 if (!checkbox) return;
 if (selectedTopics.size > 0) {
 checkbox.checked = recommended.has(sourceId);
 }
 const card = checkbox.closest('.source-option');
 if (card) card.classList.toggle('recommended', selectedTopics.size > 0 && recommended.has(sourceId));
 });
}

function renderSourceGrid() {
 const grid = document.getElementById('source-option-grid');
 Object.entries(ALL_SOURCES).forEach(([id, info]) => {
 const label = document.createElement('label');
 label.className = 'source-option';
 label.innerHTML = `
 <input type="checkbox" id="source-${id}" value="${id}">
 <div class="source-info">
 <span class="source-name-label">${info.name}</span>
 <span class="source-desc">${info.desc}</span>
 </div>
 `;
 label.querySelector('input').addEventListener('change', saveFetchPrefs);
 grid.appendChild(label);
 });
}

function saveFetchPrefs() {
 const sources = Array.from(
 document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
 ).map(cb => cb.value);
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const prefs = {
 query: document.getElementById('fetch-query').value,
 max: document.getElementById('fetch-max').value,
 email: document.getElementById('fetch-email').value,
 sources,
 mode,
 topics: [...selectedTopics],
 model: document.getElementById('embedding-model').value,
 onlyMissing: document.getElementById('only-missing').checked,
 };
 try { localStorage.setItem(FETCH_PREFS_KEY, JSON.stringify(prefs)); } catch (e) { /* ignore */ }
}

function restoreFetchPrefs() {
 let prefs;
 try { prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null'); } catch (e) { prefs = null; }
 if (!prefs) return;
 if (prefs.query) document.getElementById('fetch-query').value = prefs.query;
 if (prefs.max) document.getElementById('fetch-max').value = prefs.max;
 if (prefs.email) document.getElementById('fetch-email').value = prefs.email;
 if (prefs.model) document.getElementById('embedding-model').value = prefs.model;
 if (prefs.mode) {
 const radio = document.querySelector(`input[name="fetch-mode"][value="${prefs.mode}"]`);
 if (radio) radio.checked = true;
 }
    // Derive only-missing from fetch mode (append → on, replace → off).
    // Do this after mode restore so it stays consistent.
 syncOnlyMissingFromFetchMode();
 if (Array.isArray(prefs.topics)) {
 prefs.topics.forEach(tid => {
 selectedTopics.add(tid);
 const card = document.querySelector(`.topic-card[data-topic-id="${tid}"]`);
 if (card) card.classList.add('selected');
 });
 updateRecommendedSources();
 }
 if (Array.isArray(prefs.sources) && prefs.sources.length) {
 Object.keys(ALL_SOURCES).forEach(id => {
 const cb = document.getElementById(`source-${id}`);
 if (cb) cb.checked = prefs.sources.includes(id);
 });
 }
}

async function loadPageData() {
 try {
 const stats = await apiCall('/api/statistics');
 const model = stats.embedding_model || ' - ';
 const missing = stats.missing_embeddings ?? Math.max(0, (stats.total_articles || 0) - (stats.articles_with_embeddings || 0));
 document.getElementById('embedding-info').textContent =
 `${stats.articles_with_embeddings} of ${stats.total_articles} articles have embeddings` +
 (stats.articles_with_embeddings ? ` (model: ${model})` : '') +
 (missing ? ` · ${missing} still need embedding` : '') + '.';
 if (stats.embedding_model) {
 const sel = document.getElementById('embedding-model');
 if ([...sel.options].some(o => o.value === stats.embedding_model)) {
 sel.value = stats.embedding_model;
 }
 }
 } catch (e) {
 document.getElementById('embedding-info').textContent = 'Unable to load article info.';
 }
}

async function refreshCoverage() {
 const bars = document.getElementById('coverage-bars');
 const sug = document.getElementById('coverage-suggestions');
 try {
 const data = await apiCall('/api/coverage', {
 method: 'POST',
 body: { topics: [...selectedTopics] },
 });
 const sources = data.sources || {};
 const keys = Object.keys(sources);
 bars.innerHTML = '';
 if (!keys.length) {
 bars.innerHTML = '<p class="info-text">No articles yet - run a fetch to fill the map.</p>';
 } else {
 const maxCount = Math.max(...Object.values(sources), 1);
 keys.sort((a, b) => sources[b] - sources[a]).forEach(src => {
 const count = sources[src];
 const pct = (count / maxCount) * 100;
 const div = document.createElement('div');
 div.className = 'source-bar';
 div.innerHTML = `
 <span class="source-name">${escapeHtml(getSourceName(src))}</span>
 <div class="source-bar-fill">
 <div class="source-track">
 <div class="source-bar-inner" style="width: ${pct}%"></div>
 </div>
 </div>
 <span class="source-count">${count}</span>
 `;
 bars.appendChild(div);
 });
 }
 const suggestions = data.suggestions || [];
 if (suggestions.length) {
 sug.innerHTML = '<strong>Suggested sources you are missing:</strong> ' +
 suggestions.map(s => escapeHtml(getSourceName(s.source))).join(' · ') +
 '. Consider adding them on the next fetch.';
 } else if (keys.length) {
 sug.textContent = selectedTopics.size
 ? 'Coverage looks good for your selected topics - recommended sources each have at least one paper.'
 : 'Select topics above for more specific coverage suggestions.';
 } else {
 sug.textContent = '';
 }
 } catch (e) {
 bars.innerHTML = '<p class="info-text">Could not load coverage.</p>';
 sug.textContent = '';
 }
}

// === Progress polling (jobs return 202; UI waits on /api/progress) ===
function waitForJob(task, fillId, labelId, wrapId, formatLabel, timeoutMs = 600000) {
 return new Promise((resolve, reject) => {
 const fill = document.getElementById(fillId);
 const label = document.getElementById(labelId);
 const wrap = document.getElementById(wrapId);
 wrap.style.display = 'block';
 fill.style.width = '0%';
 const started = Date.now();

 const interval = setInterval(async () => {
 try {
 if (Date.now() - started > timeoutMs) {
 clearInterval(interval);
 reject(new Error('Timed out waiting for the job to finish'));
 return;
 }
 const data = await apiCall('/api/progress');
 const p = data[task];
 if (!p) return;
 if (p.active) {
 const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
 fill.style.width = pct + '%';
 label.textContent = formatLabel(p.done, p.total, pct);
 return;
 }
 clearInterval(interval);
 fill.style.width = '100%';
 setTimeout(() => { wrap.style.display = 'none'; fill.style.width = '0%'; }, 800);
 if (p.error) {
 reject(new Error(p.error));
 } else {
 resolve(p.result || {});
 }
 } catch (e) {
 clearInterval(interval);
 reject(e);
 }
 }, 500);
 });
}

function applyFetchResult(data, sources) {
 syncOnlyMissingFromFetchMode();
 saveFetchPrefs();
 updateNavStats();
 loadPageData();
 refreshCoverage();

 const okLines = Object.entries(data.by_source || {})
 .filter(([src]) => !(data.errors || {})[src])
 .map(([src, count]) => `✓ ${getSourceName(src)}: ${count}`);
 const errLines = Object.entries(data.errors || {})
 .map(([src, msg]) => `✗ ${getSourceName(src)}: ${msg}`);
 const report = document.getElementById('fetch-source-report');
 report.style.display = 'block';
 report.innerHTML = [...okLines, ...errLines].map(escapeHtml).join('<br>');

 const errorCount = Object.keys(data.errors || {}).length;
 const breakdown = Object.entries(data.by_source || {})
 .map(([src, count]) => `${getSourceName(src)}: ${count}`)
 .join(' · ');

 if (errorCount === 0) {
 setStatus('fetch-status', `Fetched ${data.total_fetched} articles - ${breakdown}`, 'success');
 showNotification(`Fetched ${data.total_fetched} articles!`, 'success');
 } else if (errorCount < sources.length) {
 setStatus('fetch-status', `Fetched ${data.total_fetched} articles with some source errors (see list).`, 'warning');
 showNotification(`Fetched ${data.total_fetched} articles with some errors.`, 'warning');
 } else {
 setStatus('fetch-status', 'All fetches failed.', 'error');
 showNotification('Fetch failed for all selected sources.', 'error');
 }
}

async function doFetch() {
 const sources = Array.from(
 document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
 ).map(cb => cb.value);
 const query = document.getElementById('fetch-query').value.trim();
 const maxResults = parseInt(document.getElementById('fetch-max').value, 10);
 const email = document.getElementById('fetch-email').value.trim();
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const clearFirst = mode === 'replace';

 if (!query) { showNotification('Please enter a search query.', 'error'); return; }
 if (sources.length === 0) { showNotification('Please select at least one source.', 'error'); return; }

 saveFetchPrefs();

 const btn = document.getElementById('fetch-btn');
 setLoading(btn, true);
 document.getElementById('fetch-source-report').style.display = 'none';
 setStatus(
 'fetch-status',
 clearFirst
 ? `Starting fresh: clearing collection, then fetching from ${sources.length} source(s)…`
 : `Adding to collection from ${sources.length} source(s)…`,
 'info'
 );

 try {
 const started = await apiCall('/api/fetch-articles-multi', {
 method: 'POST',
 body: {
 sources,
 query,
 max_results: maxResults,
 email: email || null,
 clear_first: clearFirst,
 },
 });
 // 202 → {status: started}; poll for result. (wait=true legacy returns full body.)
 let data = started;
 if (started && started.status === 'started') {
 data = await waitForJob(
 'fetch', 'fetch-progress-fill', 'fetch-progress-label', 'fetch-progress-wrap',
 (done, total) => `${done} of ${total} source(s) done`
 );
 }
 applyFetchResult(data, sources);
 } catch (e) {
 const msg = e.message || '';
 if (msg.toLowerCase().includes('already running')) {
 setStatus('fetch-status', 'A fetch is already running.', 'warning');
 showNotification('A fetch is already running.', 'warning');
 } else {
 setStatus('fetch-status', `Fetch failed: ${msg}`, 'error');
 showNotification(`Fetch failed: ${msg}`, 'error');
 }
 } finally {
 setLoading(btn, false);
 }
}

async function doCreateEmbeddings() {
 const model = document.getElementById('embedding-model').value;
 const onlyMissing = document.getElementById('only-missing').checked;
 const btn = document.getElementById('embeddings-btn');
 saveFetchPrefs();
 setLoading(btn, true);
 setStatus('embeddings-status', 'Creating embeddings… this may take a few minutes on large collections.', 'info');

 try {
 const started = await apiCall('/api/create-embeddings', {
 method: 'POST',
 body: { model, only_missing: onlyMissing },
 });
 let data = started;
 if (started && started.status === 'started') {
 data = await waitForJob(
 'embed', 'embed-progress-fill', 'embed-progress-label', 'embed-progress-wrap',
 (done, total, pct) => total > 0 ? `${done} / ${total} articles (${pct}%)` : 'Loading model…'
 );
 }
 const secs = data.seconds != null ? `${data.seconds}s` : '?';
 const device = data.device || 'cpu';
 const created = data.embeddings_created ?? data.articles_processed;
 const skipped = data.skipped_existing || 0;
 setStatus(
 'embeddings-status',
 `Done: ${created} embedded, ${skipped} skipped (already had vectors). ` +
 `Model ${data.model || model} on ${device} in ${secs}. ` +
 `Corpus total with embeddings: ${data.articles_processed}.`,
 'success'
 );
 showNotification('Embeddings created successfully!', 'success');
 loadPageData();
 } catch (e) {
 const msg = e.message || '';
 if (msg.toLowerCase().includes('already running')) {
 setStatus('embeddings-status', 'Embedding is already running.', 'warning');
 showNotification('An embedding job is already running.', 'warning');
 } else {
 setStatus('embeddings-status', `Error: ${msg}`, 'error');
 showNotification(`Embeddings failed: ${msg}`, 'error');
 }
 } finally {
 setLoading(btn, false);
 }
}
