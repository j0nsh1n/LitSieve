// === Statistics page logic ===

document.addEventListener('DOMContentLoaded', () => {
    loadStatistics();

    const slider = document.getElementById('threshold');
    const display = document.getElementById('threshold-display');
    slider.addEventListener('input', () => {
        display.textContent = parseFloat(slider.value).toFixed(2);
    });

    document.getElementById('detect-btn').addEventListener('click', doDetectDuplicates);
});

async function loadStatistics() {
    try {
        const stats = await apiCall('/api/statistics');

        document.getElementById('stat-total').textContent = stats.total_articles;
        document.getElementById('stat-embeddings').textContent = stats.articles_with_embeddings;

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
                    <span class="source-name">${getSourceName(source)}</span>
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
        body.appendChild(buildCompareTable(articles));
        details.appendChild(body);

        container.appendChild(details);
    });
}

// === Side-by-side compare table ===
function buildCompareTable(articles) {
    const n = articles.length;
    const fields = [
        { key: 'title',    label: 'Title' },
        { key: 'year',     label: 'Year' },
        { key: 'journal',  label: 'Journal' },
        { key: 'authors',  label: 'Authors',  format: a => (a.authors || []).join('; ') },
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

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
