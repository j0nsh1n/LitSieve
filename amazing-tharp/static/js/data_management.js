// === Topic and source definitions ===
const TOPICS = [
    { id: 'health',      name: 'Health & Medicine',    icon: '🏥', sources: ['pubmed', 'europepmc', 'clinicaltrials', 'openalex', 'semanticscholar', 'doaj', 'zenodo'] },
    { id: 'biology',     name: 'Biology',              icon: '🧬', sources: ['pubmed', 'europepmc', 'openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj'] },
    { id: 'chemistry',   name: 'Chemistry',            icon: '⚗️', sources: ['openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj'] },
    { id: 'physics',     name: 'Physics',              icon: '⚛️', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'nasa_ads'] },
    { id: 'math',        name: 'Mathematics',          icon: '📐', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo'] },
    { id: 'cs',          name: 'Computer Science',     icon: '💻', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'doaj'] },
    { id: 'earth',       name: 'Earth & Environment',  icon: '🌍', sources: ['openalex', 'semanticscholar', 'zenodo', 'crossref', 'doaj', 'nasa_ads'] },
    { id: 'history',     name: 'History',              icon: '📜', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj'] },
    { id: 'economics',   name: 'Economics',            icon: '📊', sources: ['arxiv', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj'] },
    { id: 'psychology',  name: 'Psychology',           icon: '🧠', sources: ['pubmed', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj'] },
    { id: 'polisci',     name: 'Political Science',    icon: '🏛️', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj'] },
    { id: 'literature',  name: 'Literature & Language',icon: '📖', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj'] },
    { id: 'education',   name: 'Education',            icon: '🎓', sources: ['eric', 'openalex', 'semanticscholar', 'crossref', 'doaj'] },
];

const ALL_SOURCES = {
    pubmed:          { name: 'PubMed',             desc: 'Biomedical & life sciences' },
    europepmc:       { name: 'Europe PMC',         desc: 'European biomedical literature' },
    clinicaltrials:  { name: 'ClinicalTrials.gov', desc: 'Clinical trial registrations' },
    openalex:        { name: 'OpenAlex',           desc: 'Broad multi-discipline academic' },
    arxiv:           { name: 'arXiv',              desc: 'Physics, math, CS, econ preprints' },
    semanticscholar: { name: 'Semantic Scholar',   desc: 'AI-curated cross-discipline research' },
    eric:            { name: 'ERIC',               desc: 'Education, psychology, social sciences' },
    zenodo:          { name: 'Zenodo',             desc: 'Open science: all fields + datasets' },
    crossref:        { name: 'CrossRef',           desc: 'Broad academic metadata registry' },
    doaj:            { name: 'DOAJ',               desc: 'Peer-reviewed open access journals' },
    nasa_ads:        { name: 'NASA ADS',           desc: 'Astronomy, astrophysics & geosciences' },
};

let selectedTopics = new Set();

document.addEventListener('DOMContentLoaded', () => {
    renderTopicGrid();
    renderSourceGrid();
    loadPageData();
    document.getElementById('fetch-btn').addEventListener('click', doFetch);
    document.getElementById('embeddings-btn').addEventListener('click', doCreateEmbeddings);
});

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
        checkbox.checked = selectedTopics.size > 0 && recommended.has(sourceId);
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
        grid.appendChild(label);
    });
}

async function loadPageData() {
    try {
        const stats = await apiCall('/api/statistics');
        document.getElementById('embedding-info').textContent =
            `${stats.articles_with_embeddings} of ${stats.total_articles} articles have embeddings.`;
    } catch (e) {
        document.getElementById('embedding-info').textContent = 'Unable to load article info.';
    }
}

// === Progress polling ===
function startProgressPolling(task, fillId, labelId, wrapId, formatLabel) {
    const fill = document.getElementById(fillId);
    const label = document.getElementById(labelId);
    const wrap = document.getElementById(wrapId);
    wrap.style.display = 'block';
    fill.style.width = '0%';

    const interval = setInterval(async () => {
        try {
            const data = await apiCall('/api/progress');
            const p = data[task];
            if (!p || !p.active) {
                clearInterval(interval);
                fill.style.width = '100%';
                setTimeout(() => { wrap.style.display = 'none'; fill.style.width = '0%'; }, 800);
                return;
            }
            const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
            fill.style.width = pct + '%';
            label.textContent = formatLabel(p.done, p.total, pct);
        } catch (e) {
            clearInterval(interval);
        }
    }, 500);

    return interval;
}

async function doFetch() {
    const sources = Array.from(
        document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
    ).map(cb => cb.value);
    const query = document.getElementById('fetch-query').value.trim();
    const maxResults = parseInt(document.getElementById('fetch-max').value);
    const email = document.getElementById('fetch-email').value.trim();

    if (!query) { showNotification('Please enter a search query.', 'error'); return; }
    if (sources.length === 0) { showNotification('Please select at least one source.', 'error'); return; }

    const btn = document.getElementById('fetch-btn');
    setLoading(btn, true);
    setStatus('fetch-status', 'Clearing existing articles...', 'info');

    try {
        await apiCall('/api/clear-articles', { method: 'POST' });
    } catch (e) {
        setStatus('fetch-status', `Failed to clear articles: ${e.message}`, 'error');
        setLoading(btn, false);
        return;
    }

    setStatus('fetch-status', `Fetching from ${sources.length} source(s) simultaneously...`, 'info');
    startProgressPolling('fetch', 'fetch-progress-fill', 'fetch-progress-label', 'fetch-progress-wrap',
        (done, total) => `${done} of ${total} source(s) done`);

    let data;
    try {
        data = await apiCall('/api/fetch-articles-multi', {
            method: 'POST',
            body: { sources, query, max_results: maxResults, email: email || null }
        });
    } catch (e) {
        setStatus('fetch-status', `Fetch failed: ${e.message}`, 'error');
        showNotification(`Fetch failed: ${e.message}`, 'error');
        setLoading(btn, false);
        return;
    }

    setLoading(btn, false);
    updateNavStats();
    loadPageData();

    const breakdown = Object.entries(data.by_source)
        .map(([src, count]) => `${getSourceName(src)}: ${count}`)
        .join(' · ');
    const errorCount = Object.keys(data.errors || {}).length;

    if (errorCount === 0) {
        setStatus('fetch-status', `Fetched ${data.total_fetched} articles — ${breakdown}`, 'success');
        showNotification(`Fetched ${data.total_fetched} articles!`, 'success');
    } else if (errorCount < sources.length) {
        const errDetail = Object.entries(data.errors).map(([src, msg]) => `${getSourceName(src)}: ${msg}`).join('; ');
        setStatus('fetch-status', `Fetched ${data.total_fetched} articles — ${breakdown}. Errors: ${errDetail}`, 'warning');
        showNotification(`Fetched ${data.total_fetched} articles with some errors.`, 'warning');
    } else {
        setStatus('fetch-status', `All fetches failed.`, 'error');
        showNotification('Fetch failed for all selected sources.', 'error');
    }
}

async function doCreateEmbeddings() {
    const model = document.getElementById('embedding-model').value;
    const btn = document.getElementById('embeddings-btn');
    setLoading(btn, true);
    setStatus('embeddings-status', 'Creating embeddings... This may take a few minutes.', 'info');
    startProgressPolling('embed', 'embed-progress-fill', 'embed-progress-label', 'embed-progress-wrap',
        (done, total, pct) => total > 0 ? `${done} / ${total} articles embedded (${pct}%)` : 'Loading model...');

    try {
        const data = await apiCall('/api/create-embeddings', { method: 'POST', body: { model } });
        setStatus('embeddings-status', `Embeddings created for ${data.articles_processed} articles.`, 'success');
        showNotification('Embeddings created successfully!', 'success');
        loadPageData();
    } catch (e) {
        setStatus('embeddings-status', `Error: ${e.message}`, 'error');
        showNotification(`Embeddings failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
    }
}
