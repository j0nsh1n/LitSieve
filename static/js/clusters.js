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

            const excluded = cluster.excluded_count || 0;
            const total = cluster.article_count;
            const fullyExcluded = excluded >= total;
            const label = cluster.cluster_label || `Cluster ${cluster.cluster_id}`;

            const excludedBadge = excluded > 0
                ? `<span class="excluded-badge">${excluded === total ? 'excluded' : excluded + ' excluded'}</span>`
                : '';
            details.innerHTML = `
                <summary>
                    <span class="cluster-badge">#${cluster.cluster_id}</span>
                    <span class="article-title">${escapeHtml(label)}</span>
                    <span class="cluster-count">${total} article(s)</span>
                    ${excludedBadge}
                    <span class="cluster-actions">
                        <button class="btn btn-sm ${fullyExcluded ? 'btn-secondary' : 'btn-danger'} cluster-screen-btn">
                            ${fullyExcluded ? 'Restore cluster' : 'Exclude cluster'}
                        </button>
                    </span>
                </summary>
                <div class="article-body">
                    <p class="loading-text">Loading articles…</p>
                </div>
            `;

            // Bulk exclude/restore. Stop the click from toggling the <details>.
            details.querySelector('.cluster-screen-btn').addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();
                const btn = e.target;
                setLoading(btn, true);
                try {
                    const action = fullyExcluded ? 'include' : 'exclude';
                    const res = await apiCall(`/api/clusters/${cluster.cluster_id}/screening`, {
                        method: 'POST',
                        body: { action }
                    });
                    showNotification(
                        action === 'exclude'
                            ? `Excluded ${res.count} article(s) — they no longer appear in search results.`
                            : `Restored ${res.count} article(s) to the search pool.`,
                        'success'
                    );
                    loadClusters(); // refresh counts + button states
                } catch (err) {
                    showNotification(`Screening failed: ${err.message}`, 'error');
                    setLoading(btn, false);
                }
            });

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
        item.className = 'cluster-article' + (article.excluded ? ' excluded' : '');
        item.innerHTML = `
            <div class="article-title">${escapeHtml(article.title || '')}</div>
            <div class="article-meta">
                <span><strong>Year:</strong> ${escapeHtml(article.year || '')}</span>
                <span><strong>Journal:</strong> ${escapeHtml(article.journal || '')}</span>
                <span><strong>Source:</strong> ${escapeHtml(getSourceName(article.source))}</span>
                <span><strong>ID:</strong> ${idLink}</span>
                <button class="btn btn-sm ${article.excluded ? 'btn-secondary' : 'btn-danger'} screen-toggle">
                    ${article.excluded ? 'Restore' : 'Exclude'}
                </button>
            </div>
            <div class="article-meta meta-authors">
                <span><strong>Authors:</strong> ${escapeHtml(authors)}</span>
            </div>
        `;

        item.querySelector('.screen-toggle').addEventListener('click', async (e) => {
            const btn = e.target;
            const excluding = !item.classList.contains('excluded');
            btn.disabled = true;
            try {
                await apiCall('/api/screening', {
                    method: 'POST',
                    body: {
                        items: [{ article_id: article.article_id, source: article.source }],
                        action: excluding ? 'exclude' : 'include'
                    }
                });
                article.excluded = excluding;
                item.classList.toggle('excluded', excluding);
                btn.textContent = excluding ? 'Restore' : 'Exclude';
                btn.classList.toggle('btn-danger', !excluding);
                btn.classList.toggle('btn-secondary', excluding);
            } catch (err) {
                showNotification(`Screening failed: ${err.message}`, 'error');
            } finally {
                btn.disabled = false;
            }
        });

        bodyEl.appendChild(item);
    });
}
