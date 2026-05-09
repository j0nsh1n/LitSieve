// === Search page logic ===

let lastSearchParams = null;

document.addEventListener('DOMContentLoaded', () => {
    // Restore last fetched sources
    const savedSources = localStorage.getItem('last_fetched_sources');
    if (savedSources) {
        try {
            const sources = JSON.parse(savedSources);
            document.querySelectorAll('input[name="search-source"]').forEach(cb => {
                cb.checked = sources.includes(cb.value);
            });
        } catch (e) { /* ignore corrupt data */ }
    }

    // Input method toggle
    document.querySelectorAll('input[name="input_method"]').forEach(radio => {
        radio.addEventListener('change', () => {
            document.getElementById('text-input-panel').style.display =
                radio.value === 'text' ? 'block' : 'none';
            document.getElementById('pico-input-panel').style.display =
                radio.value === 'pico' ? 'block' : 'none';
        });
    });

    // Top-k slider
    const topkSlider = document.getElementById('top-k');
    const topkDisplay = document.getElementById('topk-display');
    topkSlider.addEventListener('input', () => {
        topkDisplay.textContent = topkSlider.value;
    });

    // Search button
    document.getElementById('search-btn').addEventListener('click', doSearch);

    // Export buttons
    document.getElementById('export-csv').addEventListener('click', () => doExport('csv'));
    document.getElementById('export-txt').addEventListener('click', () => doExport('txt'));

    // Allow Enter key in textarea to search
    document.getElementById('query-text').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            doSearch();
        }
    });
});

function buildQueryText() {
    const method = document.querySelector('input[name="input_method"]:checked').value;
    if (method === 'text') {
        return document.getElementById('query-text').value.trim();
    } else {
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
}

async function doSearch() {
    const queryText = buildQueryText();
    if (!queryText) {
        showNotification('Please enter a search query.', 'error');
        return;
    }

    const topK = parseInt(document.getElementById('top-k').value);
    const sortBy = document.getElementById('sort-by').value;

    // Get selected source filter
    const selectedSources = Array.from(document.querySelectorAll('input[name="search-source"]:checked')).map(cb => cb.value);
    if (selectedSources.length === 0) {
        showNotification('Please select at least one source.', 'error');
        return;
    }

    const btn = document.getElementById('search-btn');
    setLoading(btn, true);

    lastSearchParams = {
        query_text: queryText,
        top_k: topK,
        sort_by: sortBy,
        source_filter: selectedSources
    };

    try {
        const data = await apiCall('/api/search', {
            method: 'POST',
            body: lastSearchParams
        });

        const filtered = data.results.filter(a => selectedSources.includes(a.source));
        renderResults(filtered);
        document.getElementById('result-count').textContent = filtered.length;
        document.getElementById('results-section').style.display = 'block';
    } catch (e) {
        showNotification(`Search failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
    }
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
        const idLink = url
            ? `<a href="${url}" target="_blank" rel="noopener" class="article-link">${article.article_id}</a>`
            : article.article_id;

        // Build PICO tags
        let picoHtml = '';
        if (article.pico) {
            const tags = [];
            if (article.pico.population && article.pico.population.length)
                tags.push('<span class="pico-tag pop">Population</span>');
            if (article.pico.intervention && article.pico.intervention.length)
                tags.push('<span class="pico-tag int">Intervention</span>');
            if (article.pico.comparison && article.pico.comparison.length)
                tags.push('<span class="pico-tag comp">Comparison</span>');
            if (article.pico.outcome && article.pico.outcome.length)
                tags.push('<span class="pico-tag out">Outcome</span>');
            if (tags.length) picoHtml = `<div class="pico-tags">${tags.join('')}</div>`;
        }

        const authors = (article.authors || []).join('; ');

        details.innerHTML = `
            <summary>
                <span class="sim-badge ${simClass}">${sim.toFixed(3)}</span>
                <span class="article-title">${escapeHtml(article.title || '')}</span>
            </summary>
            <div class="article-body">
                <div class="article-meta">
                    <span><strong>Year:</strong> ${escapeHtml(article.year || '')}</span>
                    <span><strong>Journal:</strong> ${escapeHtml(article.journal || '')}</span>
                    <span><strong>Source:</strong> ${getSourceName(article.source)}</span>
                    <span><strong>ID:</strong> ${idLink}</span>
                </div>
                <div class="article-meta">
                    <span><strong>Authors:</strong> ${escapeHtml(authors)}</span>
                </div>
                <div class="article-abstract">${escapeHtml(article.abstract || '')}</div>
                ${picoHtml}
            </div>
        `;

        container.appendChild(details);
    });
}

function doExport(format) {
    if (!lastSearchParams) {
        showNotification('Please perform a search first.', 'error');
        return;
    }

    const params = new URLSearchParams({
        query_text: lastSearchParams.query_text,
        top_k: lastSearchParams.top_k,
        sort_by: lastSearchParams.sort_by,
        format: format
    });
    window.location.href = `/api/search/export?${params.toString()}`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
