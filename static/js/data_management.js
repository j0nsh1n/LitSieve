// === Data Management page logic ===

document.addEventListener('DOMContentLoaded', () => {
    loadPageData();

    // Source radio change
    document.querySelectorAll('input[name="source"]').forEach(radio => {
        radio.addEventListener('change', () => {
            // Email field is useful for PubMed and OpenAlex
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
    const source = document.querySelector('input[name="source"]:checked').value;
    const query = document.getElementById('fetch-query').value.trim();
    const maxResults = parseInt(document.getElementById('fetch-max').value);
    const email = document.getElementById('fetch-email').value.trim();

    if (!query) {
        showNotification('Please enter a search query.', 'error');
        return;
    }

    const btn = document.getElementById('fetch-btn');
    setLoading(btn, true);
    setStatus('fetch-status', `Fetching articles from ${getSourceName(source)}...`, 'info');

    try {
        const data = await apiCall('/api/fetch-articles', {
            method: 'POST',
            body: { source, query, max_results: maxResults, email: email || null }
        });

        setStatus('fetch-status', `Fetched ${data.articles_fetched} articles from ${getSourceName(data.source)}.`, 'success');
        showNotification(`Fetched ${data.articles_fetched} articles!`, 'success');
        updateNavStats();
        loadPageData();
    } catch (e) {
        setStatus('fetch-status', `Error: ${e.message}`, 'error');
        showNotification(`Fetch failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
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
