// === Statistics page logic ===

document.addEventListener('DOMContentLoaded', () => {
    loadStatistics();

    // Threshold slider
    const slider = document.getElementById('threshold');
    const display = document.getElementById('threshold-display');
    slider.addEventListener('input', () => {
        display.textContent = parseFloat(slider.value).toFixed(2);
    });

    // Detect button
    document.getElementById('detect-btn').addEventListener('click', doDetectDuplicates);
});

async function loadStatistics() {
    try {
        const stats = await apiCall('/api/statistics');

        document.getElementById('stat-total').textContent = stats.total_articles;
        document.getElementById('stat-embeddings').textContent = stats.articles_with_embeddings;
        document.getElementById('stat-clusters').textContent = stats.num_clusters;

        // Source breakdown
        const sources = stats.sources || {};
        const sourceKeys = Object.keys(sources);
        if (sourceKeys.length > 0) {
            const maxCount = Math.max(...Object.values(sources), 1);
            const container = document.getElementById('source-breakdown');
            container.innerHTML = '';

            const sourceNames = {
                pubmed: 'PubMed',
                europepmc: 'Europe PMC',
                clinicaltrials: 'ClinicalTrials.gov',
                openalex: 'OpenAlex'
            };

            sourceKeys.forEach(source => {
                const count = sources[source];
                const pct = (count / maxCount) * 100;
                const div = document.createElement('div');
                div.className = 'source-bar';
                div.innerHTML = `
                    <span class="source-name">${sourceNames[source] || source}</span>
                    <div class="source-bar-fill">
                        <div class="source-bar-inner" style="width: ${pct}%"></div>
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
            setStatus('duplicates-status',
                `Found ${data.total} potential duplicate pair(s). Showing up to 20.`, 'success');
            renderDuplicates(data.duplicates);
        }
    } catch (e) {
        setStatus('duplicates-status', `Error: ${e.message}`, 'error');
        showNotification(`Detection failed: ${e.message}`, 'error');
    } finally {
        setLoading(btn, false);
    }
}

function renderDuplicates(duplicates) {
    const container = document.getElementById('duplicates-list');
    container.innerHTML = '';

    duplicates.forEach((dup, idx) => {
        const details = document.createElement('details');
        details.className = 'duplicate-item';

        const a1 = dup.article1;
        const a2 = dup.article2;

        details.innerHTML = `
            <summary>
                <span class="sim-badge sim-high">${dup.similarity.toFixed(3)}</span>
                <span>${escapeHtml(truncate(a1.title, 40))} &harr; ${escapeHtml(truncate(a2.title, 40))}</span>
            </summary>
            <div class="dup-body">
                <p><strong>Article 1:</strong> ${escapeHtml(a1.title)}<br>
                   <em>${a1.source} | ${a1.article_id}</em></p>
                <p><strong>Article 2:</strong> ${escapeHtml(a2.title)}<br>
                   <em>${a2.source} | ${a2.article_id}</em></p>
            </div>
        `;

        container.appendChild(details);
    });
}

function truncate(text, len) {
    if (!text) return '';
    return text.length > len ? text.substring(0, len) + '...' : text;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
