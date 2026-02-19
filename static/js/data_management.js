// === Data Management page logic ===

document.addEventListener('DOMContentLoaded', () => {
    loadPageData();

    // Source checkbox change (email field always visible since any source may need it)
    document.querySelectorAll('input[name="source"]').forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            const emailGroup = document.getElementById('email-group');
            emailGroup.style.display = 'block';
        });
    });

    // Fetch button
    document.getElementById('fetch-btn').addEventListener('click', doFetch);

    // Embeddings button
    document.getElementById('embeddings-btn').addEventListener('click', doCreateEmbeddings);

    // Cluster button
    document.getElementById('cluster-btn').addEventListener('click', doCreateClusters);
});

async function loadPageData() {
    try {
        const stats = await apiCall('/api/statistics');
        document.getElementById('embedding-info').textContent =
            `${stats.articles_with_embeddings} of ${stats.total_articles} articles have embeddings.`;
    } catch (e) {
        document.getElementById('embedding-info').textContent = 'Unable to load article info.';
    }

    // Load existing clusters
    loadClusters();
}

async function doFetch() {
    const sources = Array.from(document.querySelectorAll('input[name="source"]:checked')).map(cb => cb.value);
    const query = document.getElementById('fetch-query').value.trim();
    const maxResults = parseInt(document.getElementById('fetch-max').value);
    const email = document.getElementById('fetch-email').value.trim();

    if (!query) {
        showNotification('Please enter a search query.', 'error');
        return;
    }

    if (sources.length === 0) {
        showNotification('Please select at least one source.', 'error');
        return;
    }

    const btn = document.getElementById('fetch-btn');
    setLoading(btn, true);

    // Clear existing articles before fetching new results
    setStatus('fetch-status', 'Clearing existing articles...', 'info');
    try {
        await apiCall('/api/clear-articles', { method: 'POST' });
    } catch (e) {
        setStatus('fetch-status', `Failed to clear articles: ${e.message}`, 'error');
        setLoading(btn, false);
        return;
    }

    let totalFetched = 0;
    const errors = [];

    for (const source of sources) {
        setStatus('fetch-status', `Fetching from ${getSourceName(source)}...`, 'info');
        try {
            const data = await apiCall('/api/fetch-articles', {
                method: 'POST',
                body: { source, query, max_results: maxResults, email: email || null }
            });
            totalFetched += data.articles_fetched;
        } catch (e) {
            errors.push(`${getSourceName(source)}: ${e.message}`);
        }
    }

    setLoading(btn, false);
    updateNavStats();
    loadPageData();

    if (errors.length === 0) {
        setStatus('fetch-status', `Fetched ${totalFetched} articles from ${sources.length} source(s).`, 'success');
        showNotification(`Fetched ${totalFetched} articles!`, 'success');
    } else if (errors.length < sources.length) {
        setStatus('fetch-status', `Fetched ${totalFetched} articles. Errors: ${errors.join('; ')}`, 'warning');
        showNotification(`Fetched ${totalFetched} articles with some errors.`, 'warning');
    } else {
        setStatus('fetch-status', `All fetches failed: ${errors.join('; ')}`, 'error');
        showNotification('Fetch failed for all selected sources.', 'error');
    }
}

async function doCreateEmbeddings() {
    const model = document.getElementById('embedding-model').value;
    const btn = document.getElementById('embeddings-btn');
    setLoading(btn, true);
    setStatus('embeddings-status', 'Creating embeddings... This may take a few minutes.', 'info');

    try {
        const data = await apiCall('/api/create-embeddings', {
            method: 'POST',
            body: { model }
        });

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

async function doCreateClusters() {
    const nClusters = parseInt(document.getElementById('n-clusters').value);
    const method = document.getElementById('cluster-method').value;
    const btn = document.getElementById('cluster-btn');
    setLoading(btn, true);
    setStatus('cluster-status', 'Clustering articles...', 'info');

    try {
        const data = await apiCall('/api/create-clusters', {
            method: 'POST',
            body: { n_clusters: nClusters, method }
        });

        setStatus('cluster-status', `Created ${data.clusters.length} clusters.`, 'success');
        showNotification('Clusters created successfully!', 'success');
        renderClusterList(data.clusters);
    } catch (e) {
        setStatus('cluster-status', `Error: ${e.message}`, 'error');
        showNotification(`Clustering failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
    }
}

async function loadClusters() {
    try {
        const data = await apiCall('/api/clusters');
        if (data.clusters && data.clusters.length > 0) {
            renderClusterList(data.clusters);
        }
    } catch (e) {
        // No clusters yet
    }
}

function renderClusterList(clusters) {
    const container = document.getElementById('cluster-list');
    container.innerHTML = '';

    if (!clusters || clusters.length === 0) {
        document.getElementById('cluster-list-section').style.display = 'none';
        return;
    }

    clusters.forEach(cluster => {
        const details = document.createElement('details');
        details.className = 'cluster-item';
        details.dataset.clusterId = cluster.cluster_id;

        const summary = document.createElement('summary');
        summary.innerHTML = `
            <span class="cluster-label">${escapeHtml(cluster.cluster_label || 'Cluster ' + cluster.cluster_id)}</span>
            <span class="count-badge">${cluster.article_count}</span>
        `;
        details.appendChild(summary);

        const articleDiv = document.createElement('div');
        articleDiv.className = 'cluster-articles';
        articleDiv.innerHTML = '<p class="loading-text">Click to load articles...</p>';
        details.appendChild(articleDiv);

        // Lazy load articles on first expand
        details.addEventListener('toggle', async function () {
            if (this.open && !this.dataset.loaded) {
                articleDiv.innerHTML = '<p class="loading-text">Loading articles...</p>';
                try {
                    const data = await apiCall(`/api/clusters/${cluster.cluster_id}/articles`);
                    if (data.articles.length === 0) {
                        articleDiv.innerHTML = '<p class="loading-text">No articles in this cluster.</p>';
                    } else {
                        articleDiv.innerHTML = data.articles.map(a => {
                            const url = getArticleUrl(a.article_id, a.source);
                            const idLink = url
                                ? `<a href="${url}" target="_blank" rel="noopener" class="article-link">${a.article_id}</a>`
                                : a.article_id;
                            return `
                                <div class="article-mini">
                                    <span class="mini-title">${escapeHtml(a.title)}</span>
                                    <span class="mini-meta">${a.year} | ${getSourceName(a.source)} | ${idLink}</span>
                                </div>
                            `;
                        }).join('');
                    }
                    this.dataset.loaded = 'true';
                } catch (e) {
                    articleDiv.innerHTML = `<p class="loading-text">Error loading articles: ${e.message}</p>`;
                }
            }
        });

        container.appendChild(details);
    });

    document.getElementById('cluster-list-section').style.display = 'block';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
