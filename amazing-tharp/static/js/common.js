// === API wrapper ===
async function apiCall(url, options = {}) {
    const defaults = {
        headers: { 'Content-Type': 'application/json' }
    };
    const config = { ...defaults, ...options };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);
    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || 'Request failed');
    }
    return response.json();
}

// === Notification system ===
function showNotification(message, type = 'info') {
    const area = document.getElementById('notification-area');
    const toast = document.createElement('div');
    toast.className = `notification notification-${type}`;
    toast.textContent = message;
    area.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 4500);
}

// === Loading helper ===
function setLoading(buttonEl, loading) {
    if (!buttonEl) return;
    if (!buttonEl.dataset.originalText) {
        buttonEl.dataset.originalText = buttonEl.textContent;
    }
    buttonEl.disabled = loading;
    buttonEl.textContent = loading ? 'Processing...' : buttonEl.dataset.originalText;
}

// === Status indicator helper ===
function setStatus(elementId, message, type = 'info') {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.textContent = message;
    el.className = 'status-indicator ' + (type === 'info' ? 'loading' : type);
}

// === Build article link based on source ===
function getArticleUrl(articleId, source) {
    switch (source) {
        case 'pubmed':
            return `https://pubmed.ncbi.nlm.nih.gov/${articleId}/`;
        case 'europepmc':
            return `https://europepmc.org/article/MED/${articleId}`;
        case 'clinicaltrials':
            return `https://clinicaltrials.gov/study/${articleId}`;
        case 'openalex':
            return `https://openalex.org/${articleId}`;
        case 'arxiv':
            return `https://arxiv.org/abs/${articleId}`;
        case 'semanticscholar':
            return `https://www.semanticscholar.org/paper/${articleId}`;
        case 'eric':
            return `https://eric.ed.gov/?id=${articleId}`;
        case 'zenodo':
            return `https://zenodo.org/record/${articleId}`;
        case 'crossref':
            return `https://doi.org/${articleId}`;
        case 'doaj':
            return `https://doaj.org/article/${articleId}`;
        case 'nasa_ads':
            return `https://ui.adsabs.harvard.edu/abs/${articleId}`;
        default:
            return null;
    }
}

// === Source display name ===
function getSourceName(source) {
    const names = {
        pubmed: 'PubMed',
        europepmc: 'Europe PMC',
        clinicaltrials: 'ClinicalTrials.gov',
        openalex: 'OpenAlex',
        arxiv: 'arXiv',
        semanticscholar: 'Semantic Scholar',
        eric: 'ERIC',
        zenodo: 'Zenodo',
        crossref: 'CrossRef',
        doaj: 'DOAJ',
        nasa_ads: 'NASA ADS',
    };
    return names[source] || source;
}

// === Update nav article count ===
async function updateNavStats() {
    try {
        const stats = await apiCall('/api/statistics');
        const el = document.getElementById('nav-article-count');
        if (el) {
            el.textContent = `${stats.total_articles} articles`;
        }
    } catch (e) {
        // silent
    }
}

document.addEventListener('DOMContentLoaded', updateNavStats);

// === Range input fill ===
function updateRangeFill(input) {
    const min = parseFloat(input.min) || 0;
    const max = parseFloat(input.max) || 100;
    const pct = ((parseFloat(input.value) - min) / (max - min)) * 100;
    input.style.setProperty('--range-fill', pct + '%');
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('input[type="range"]').forEach(input => {
        updateRangeFill(input);
        input.addEventListener('input', () => updateRangeFill(input));
    });
});

// === Theme toggle ===
document.addEventListener('DOMContentLoaded', function() {
    const root = document.documentElement;
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function getEffectiveTheme() {
        const saved = localStorage.getItem('theme');
        if (saved) return saved;
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function updateButton(theme) {
        btn.textContent = theme === 'dark' ? '☀' : '🌙';
        btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    }

    updateButton(getEffectiveTheme());

    btn.addEventListener('click', function() {
        const next = getEffectiveTheme() === 'dark' ? 'light' : 'dark';
        localStorage.setItem('theme', next);
        root.setAttribute('data-theme', next);
        updateButton(next);
    });
});
