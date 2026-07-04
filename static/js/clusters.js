// === Clusters page logic ===

document.addEventListener('DOMContentLoaded', () => {
    const slider = document.getElementById('n-clusters');
    const display = document.getElementById('nclusters-display');
    slider.addEventListener('input', () => { display.textContent = slider.value; });

    document.getElementById('cluster-btn').addEventListener('click', doGenerateClusters);

    loadClusters();
});

async function loadClusters() {
    try {
        const data = await apiCall('/api/clusters');
        renderClusters(data.clusters || []);
    } catch (e) {
        // silent — page still usable for generating clusters
    }
}

async function doGenerateClusters() {
    const nClusters = parseInt(document.getElementById('n-clusters').value);
    const method = document.getElementById('cluster-method').value;
    const btn = document.getElementById('cluster-btn');

    setLoading(btn, true);
    setStatus('cluster-status', 'Clustering articles… this can take a moment.', 'info');

    try {
        const data = await apiCall('/api/create-clusters', {
            method: 'POST',
            body: { n_clusters: nClusters, method }
        });
        const clusters = data.clusters || [];
        renderClusters(clusters);
        setStatus('cluster-status', `Created ${clusters.length} cluster(s).`, 'success');
        showNotification('Clusters generated successfully!', 'success');
    } catch (e) {
        setStatus('cluster-status', `Error: ${e.message}`, 'error');
        showNotification(`Clustering failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
    }
}

function renderClusters(clusters) {
    const container = document.getElementById('clusters-list');
    document.getElementById('cluster-count').textContent = clusters.length;
    container.innerHTML = '';

    if (clusters.length === 0) {
        container.innerHTML = '<p class="info-text">No clusters yet. Generate them above to see them here.</p>';
        return;
    }

    clusters
        .slice()
        .sort((a, b) => a.cluster_id - b.cluster_id)
        .forEach(cluster => {
            const details = document.createElement('details');
            details.className = 'article-card cluster-card';

            const label = cluster.cluster_label || `Cluster ${cluster.cluster_id}`;
            details.innerHTML = `
                <summary>
                    <span class="cluster-badge">#${cluster.cluster_id}</span>
                    <span class="article-title">${escapeHtml(label)}</span>
                    <span class="cluster-count">${cluster.article_count} article(s)</span>
                </summary>
                <div class="article-body">
                    <p class="loading-text">Loading articles…</p>
                </div>
            `;

            // Lazily fetch the cluster's articles the first time it's expanded.
            details.addEventListener('toggle', () => {
                if (details.open && !details.dataset.loaded) {
                    details.dataset.loaded = '1';
                    loadClusterArticles(cluster.cluster_id, details.querySelector('.article-body'));
                }
            });

            container.appendChild(details);
        });
}

async function loadClusterArticles(clusterId, bodyEl) {
    try {
        const data = await apiCall(`/api/clusters/${clusterId}/articles`);
        renderClusterArticles(data.articles || [], bodyEl);
    } catch (e) {
        bodyEl.innerHTML = `<p class="info-text">Failed to load articles: ${escapeHtml(e.message)}</p>`;
    }
}

function renderClusterArticles(articles, bodyEl) {
    bodyEl.innerHTML = '';

    if (articles.length === 0) {
        bodyEl.innerHTML = '<p class="info-text">No articles in this cluster.</p>';
        return;
    }

    articles.forEach(article => {
        const url = getArticleUrl(article.article_id, article.source);
        const idText = escapeHtml(article.article_id || '');
        const idLink = url
            ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener" class="article-link">${idText}</a>`
            : idText;
        const authors = (article.authors || []).join('; ');

        const item = document.createElement('div');
        item.className = 'cluster-article';
        item.innerHTML = `
            <div class="article-title">${escapeHtml(article.title || '')}</div>
            <div class="article-meta">
                <span><strong>Year:</strong> ${escapeHtml(article.year || '')}</span>
                <span><strong>Journal:</strong> ${escapeHtml(article.journal || '')}</span>
                <span><strong>Source:</strong> ${escapeHtml(getSourceName(article.source))}</span>
                <span><strong>ID:</strong> ${idLink}</span>
            </div>
            <div class="article-meta meta-authors">
                <span><strong>Authors:</strong> ${escapeHtml(authors)}</span>
            </div>
        `;
        bodyEl.appendChild(item);
    });
}
