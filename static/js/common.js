// === HTML escaping (shared) ===
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
}

// === Classroom UI flags (env: HIDE_STUDY_TYPE_TAGS, HIDE_AI_BUTTONS) ===
// Defaults keep features on until /api/ui-flags loads.
window.LRA_UI = window.LRA_UI || {
    show_study_type_tags: true,
    show_ai_buttons: true,
    _loaded: false,
};

function uiFlag(name, fallback) {
    if (fallback === undefined) fallback = true;
    const v = window.LRA_UI && window.LRA_UI[name];
    return v === undefined ? fallback : !!v;
}

async function loadUiFlags() {
    try {
        const data = await fetch('/api/ui-flags', {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        }).then((r) => (r.ok ? r.json() : null));
        if (data && typeof data === 'object') {
            window.LRA_UI.show_study_type_tags = data.show_study_type_tags !== false;
            window.LRA_UI.show_ai_buttons = data.show_ai_buttons !== false;
        }
    } catch (e) {
        // Keep defaults (features visible).
    }
    window.LRA_UI._loaded = true;
    document.documentElement.dataset.showAi = uiFlag('show_ai_buttons') ? '1' : '0';
    document.documentElement.dataset.showStudyTypes = uiFlag('show_study_type_tags') ? '1' : '0';
    // Hide Account AI card without waiting for account.js if already in DOM.
    if (!uiFlag('show_ai_buttons')) {
        const aiSec = document.getElementById('ai-settings-section');
        if (aiSec) aiSec.hidden = true;
    }
    return window.LRA_UI;
}

// === CSRF token (double-submit cookie) ===
function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

// === API wrapper ===
async function apiCall(url, options = {}) {
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
    const method = (options.method || 'GET').toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
        headers['X-CSRF-Token'] = getCsrfToken();
    }
    const config = { ...options, headers };
    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }

    const response = await fetch(url, config);
    if (!response.ok) {
        if (response.status === 401) {
            // Only bounce to login from the authenticated app shell (has the
            // main navbar). Never redirect public pages (landing / learn / auth).
            const inAppShell = !!document.querySelector('nav.navbar');
            if (inAppShell) {
                window.location.href = '/login';
            }
            throw new Error('Not authenticated');
        }
        const error = await response.json().catch(() => ({ detail: response.statusText }));
        throw new Error(error.detail || 'Request failed');
    }
    return response.json();
}

// === Notification system ===
function showNotification(message, type = 'info') {
    const area = document.getElementById('notification-area');
    if (!area) return;
    const toast = document.createElement('div');
    toast.className = `notification notification-${type}`;
    toast.setAttribute('role', 'status');
    toast.textContent = message;
    area.appendChild(toast);

    const dismiss = () => {
        if (toast.classList.contains('is-leaving')) return;
        toast.classList.add('is-leaving');
        setTimeout(() => toast.remove(), 280);
    };

    const timer = setTimeout(dismiss, 4500);
    toast.addEventListener('click', () => {
        clearTimeout(timer);
        dismiss();
    });
}

// === Loading helper ===
function setLoading(buttonEl, loading) {
    if (!buttonEl) return;
    if (!buttonEl.dataset.originalText) {
        buttonEl.dataset.originalText = buttonEl.textContent;
    }
    buttonEl.disabled = loading;
    buttonEl.classList.toggle('is-loading', loading);
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
// Keep in sync with SOURCE_URL in citations.py
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
        case 'core':
            return `https://core.ac.uk/works/${articleId}`;
        case 'biorxiv':
            return `https://www.biorxiv.org/content/${articleId}`;
        case 'medrxiv':
            return `https://www.medrxiv.org/content/${articleId}`;
        case 'dblp':
            return `https://dblp.org/rec/${articleId}`;
        case 'openaire':
            return String(articleId).startsWith('http')
                ? String(articleId)
                : `https://doi.org/${articleId}`;
        case 'plos':
            return `https://doi.org/${articleId}`;
        case 'hal':
            return String(articleId).startsWith('10.')
                ? `https://doi.org/${articleId}`
                : `https://hal.science/${articleId}`;
        case 'sample':
            return null; // demo corpus — no external page
        default:
            return null;
    }
}

// === Source display name ===
// Prefer names from GET /api/sources (source_catalog.py) when loaded.
window.LRA_SOURCE_NAMES = window.LRA_SOURCE_NAMES || {
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
    core: 'CORE',
    biorxiv: 'bioRxiv',
    medrxiv: 'medRxiv',
    dblp: 'DBLP',
    openaire: 'OpenAIRE',
    plos: 'PLOS',
    hal: 'HAL',
    sample: 'Sample demo',
};

function getSourceName(source) {
    if (window.LRA_SOURCE_NAMES && window.LRA_SOURCE_NAMES[source]) {
        return window.LRA_SOURCE_NAMES[source];
    }
    return source;
}

/** Load display names (and optional tips) from the server catalog. */
async function loadSourceNames() {
    try {
        const data = await fetch('/api/sources', {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        }).then((r) => (r.ok ? r.json() : null));
        if (!data || !Array.isArray(data.sources)) return;
        data.sources.forEach((s) => {
            if (s && s.id) window.LRA_SOURCE_NAMES[s.id] = s.name || s.id;
        });
        window.LRA_SOURCE_NAMES.sample = window.LRA_SOURCE_NAMES.sample || 'Sample demo';
    } catch (e) { /* keep defaults */ }
}

// === First-run / empty-state helpers ===
const GS_DISMISS_KEY = 'lra_dismiss_getting_started';

function isGettingStartedDismissed() {
    try { return localStorage.getItem(GS_DISMISS_KEY) === '1'; } catch (e) { return false; }
}

function dismissGettingStarted() {
    try { localStorage.setItem(GS_DISMISS_KEY, '1'); } catch (e) { /* ignore */ }
    const el = document.getElementById('getting-started-card');
    if (el) el.hidden = true;
}

/**
 * Show a contextual empty-state card when the collection is missing a prerequisite.
 * @param {string} cardId
 * @param {object} stats - from /api/statistics
 * @param {'articles'|'embeddings'} need
 * @param {string} msgId - element for the message text
 */
function applyEmptyState(cardId, stats, need, msgId) {
    const card = document.getElementById(cardId);
    if (!card) return;
    const total = stats.total_articles || 0;
    const emb = stats.articles_with_embeddings || 0;
    let show = false;
    let msg = '';
    if (need === 'articles' && total === 0) {
        show = true;
        msg = 'No papers in your collection yet. Start on Data Management: pick topics, type a question, and fetch.';
    } else if (need === 'embeddings' && total === 0) {
        show = true;
        msg = 'No papers yet. Fetch on Data Management first; preparing for search runs automatically afterward.';
    } else if (need === 'embeddings' && emb === 0) {
        show = true;
        msg = `You have ${total} paper(s), but none are prepared for search yet. Open Data Management and press “Prepare papers for search” (or wait if a job is still running).`;
    }
    card.hidden = !show;
    const msgEl = msgId ? document.getElementById(msgId) : null;
    if (msgEl && msg) msgEl.textContent = msg;
}

// === List pagination (large collections) ===
// Render PAGE_SIZE items at a time with a "Show N more" control. Counts stay
// accurate via the total length of the source array.
const LIST_PAGE_SIZE = 50;

/**
 * Progressive list renderer.
 * @param {HTMLElement} container - parent to append items + button into
 * @param {Array} items - full ordered list
 * @param {function(item, index): HTMLElement} renderItem - builds one DOM node
 * @param {object} [opts]
 * @param {number} [opts.pageSize=LIST_PAGE_SIZE]
 * @param {string} [opts.noun='items'] - for the button label
 */
function renderPaginatedList(container, items, renderItem, opts) {
    const pageSize = (opts && opts.pageSize) || LIST_PAGE_SIZE;
    const noun = (opts && opts.noun) || 'items';
    let shown = 0;

    function appendBatch() {
        const end = Math.min(shown + pageSize, items.length);
        for (let i = shown; i < end; i++) {
            container.appendChild(renderItem(items[i], i));
        }
        shown = end;
        updateMoreBtn();
    }

    let moreBtn = null;
    function updateMoreBtn() {
        if (moreBtn) {
            moreBtn.remove();
            moreBtn = null;
        }
        const remaining = items.length - shown;
        if (remaining <= 0) return;
        const next = Math.min(pageSize, remaining);
        moreBtn = document.createElement('button');
        moreBtn.type = 'button';
        moreBtn.className = 'btn btn-secondary btn-sm show-more-btn';
        moreBtn.textContent = `Show ${next} more (${shown} of ${items.length} ${noun})`;
        moreBtn.addEventListener('click', () => appendBatch());
        container.appendChild(moreBtn);
    }

    appendBatch();
}

/** HTML for extractive key points (honest "from the abstract" label). */
function renderKeyPointsHtml(bullets, options) {
    options = options || {};
    if (!bullets || !bullets.length) {
        // Still allow AI actions when there are no extractive bullets yet.
        if (!options.articleId) return '';
    }
    const label = options.aiLabel
        ? 'Key points (AI rewrite — from the abstract only)'
        : 'Key points (from the abstract)';
    const items = (bullets || [])
        .map(b => `<li>${escapeHtml(String(b))}</li>`)
        .join('');
    const list = items ? `<ul class="key-points-list">${items}</ul>` : '';
    const aid = options.articleId ? escapeHtml(String(options.articleId)) : '';
    const src = options.source ? escapeHtml(String(options.source)) : '';
    // Extractive key points always show; AI buttons are optional (classroom toggle).
    const showAi = typeof uiFlag === 'function' ? uiFlag('show_ai_buttons', true) : true;
    const actions = (aid && src && showAi)
        ? `<div class="ai-actions" data-article-id="${aid}" data-source="${src}">
            <button type="button" class="btn btn-secondary btn-sm ai-refine-btn" title="Optional AI rewrite of summary and bullets from this abstract only">Refine with AI</button>
            <button type="button" class="btn btn-secondary btn-sm ai-ask-btn" title="Ask a question answered only from this abstract">Ask about this paper</button>
            <span class="ai-status-line help-text" hidden></span>
           </div>
           <div class="ai-panel" hidden></div>`
        : '';
    return `<div class="key-points">
      <div class="key-points-label">${escapeHtml(label)}</div>
      ${list}
      ${actions}
    </div>`;
}

/**
 * Site-styled modal for Ask about this paper (replaces window.prompt).
 * Resolves with trimmed question string, or null if cancelled.
 */
function openAiAskModal(paperTitle) {
    return new Promise((resolve) => {
        const existing = document.getElementById('ai-ask-modal-root');
        if (existing) existing.remove();

        const root = document.createElement('div');
        root.id = 'ai-ask-modal-root';
        root.className = 'lra-modal-root';
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.setAttribute('aria-labelledby', 'ai-ask-modal-title');
        const titleBit = paperTitle
            ? `<p class="lra-modal-paper info-text">About: <strong>${escapeHtml(String(paperTitle).slice(0, 160))}</strong></p>`
            : '';
        root.innerHTML = `
          <div class="lra-modal-backdrop" data-ai-ask-dismiss></div>
          <div class="lra-modal-card card">
            <h2 id="ai-ask-modal-title" class="lra-modal-title">Ask about this paper</h2>
            <p class="info-text">Answered only from this paper’s <strong>title and abstract</strong>
              (not the full text). The study aid starts for this question, then stops.</p>
            ${titleBit}
            <div class="form-group">
              <label for="ai-ask-modal-input">Your question</label>
              <textarea id="ai-ask-modal-input" class="lra-modal-textarea" rows="3"
                placeholder="e.g. Who was studied? What was the main finding?"
                maxlength="500"></textarea>
            </div>
            <div class="lra-modal-actions">
              <button type="button" class="btn btn-secondary" data-ai-ask-dismiss>Cancel</button>
              <button type="button" class="btn btn-primary" id="ai-ask-modal-submit">Ask</button>
            </div>
          </div>
        `;
        document.body.appendChild(root);
        document.body.classList.add('lra-modal-open');

        const input = root.querySelector('#ai-ask-modal-input');
        const submit = root.querySelector('#ai-ask-modal-submit');
        let settled = false;

        const close = (value) => {
            if (settled) return;
            settled = true;
            document.body.classList.remove('lra-modal-open');
            root.remove();
            document.removeEventListener('keydown', onKey);
            resolve(value);
        };

        const onKey = (ev) => {
            if (ev.key === 'Escape') {
                ev.preventDefault();
                close(null);
            }
        };
        document.addEventListener('keydown', onKey);

        root.querySelectorAll('[data-ai-ask-dismiss]').forEach((el) => {
            el.addEventListener('click', (ev) => {
                ev.preventDefault();
                close(null);
            });
        });

        const doSubmit = () => {
            const q = (input && input.value || '').trim();
            if (!q || q.length < 3) {
                showNotification('Type a slightly longer question (at least a few words).', 'error');
                if (input) input.focus();
                return;
            }
            close(q);
        };

        if (submit) submit.addEventListener('click', (ev) => {
            ev.preventDefault();
            doSubmit();
        });
        if (input) {
            input.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter' && !ev.shiftKey) {
                    ev.preventDefault();
                    doSubmit();
                }
            });
            setTimeout(() => input.focus(), 30);
        }
    });
}

/**
 * Wire Refine + Ask on a result card.
 * Built-in mode (both): start study aid → work on selected paper → stop when done.
 */
function bindAiArticleActions(rootEl, article) {
    if (!rootEl || !article) return;
    if (typeof uiFlag === 'function' && !uiFlag('show_ai_buttons', true)) return;
    const wrap = rootEl.querySelector('.ai-actions');
    if (!wrap || wrap.dataset.bound === '1') return;
    wrap.dataset.bound = '1';
    const panel = rootEl.querySelector('.ai-panel');
    const statusEl = wrap.querySelector('.ai-status-line');
    const aid = article.article_id;
    const source = article.source;

    const setStatus = (msg, show) => {
        if (!statusEl) return;
        statusEl.hidden = !show;
        statusEl.textContent = msg || '';
    };

    const showPanel = (html) => {
        if (!panel) return;
        panel.hidden = false;
        panel.innerHTML = html;
    };

    const softAiError = (msg, verb) => {
        const soft = /503|unavailable|not running|not configured|study aid|api key/i.test(msg);
        showNotification(
            soft
                ? `${msg} Extractive key points still work without AI.`
                : `AI ${verb} failed: ${msg}`,
            soft ? 'warning' : 'error'
        );
    };

    const refineBtn = wrap.querySelector('.ai-refine-btn');
    if (refineBtn) {
        refineBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            setStatus('Starting study aid and refining this paper…', true);
            refineBtn.disabled = true;
            try {
                const data = await apiCall('/api/ai/refine-article', {
                    method: 'POST',
                    body: {
                        article_id: aid,
                        source: source,
                        save_key_points: false,
                    },
                });
                const lim = data.limitations
                    ? `<p class="ai-limitations"><strong>Limitations (AI):</strong> ${escapeHtml(data.limitations)}</p>`
                    : '';
                const bullets = (data.key_points || [])
                    .map(b => `<li>${escapeHtml(String(b))}</li>`)
                    .join('');
                showPanel(`
                  <div class="ai-label help-text">${escapeHtml(data.label || 'AI rewrite (from the abstract only)')}</div>
                  <p class="ai-summary">${escapeHtml(data.summary || '')}</p>
                  ${lim}
                  ${bullets ? `<ul class="key-points-list">${bullets}</ul>
                  <button type="button" class="btn btn-secondary btn-sm ai-save-kp">Save these as key points</button>` : ''}
                `);
                const saveBtn = panel.querySelector('.ai-save-kp');
                if (saveBtn) {
                    saveBtn.addEventListener('click', async (ev) => {
                        ev.preventDefault();
                        saveBtn.disabled = true;
                        try {
                            // Save exactly the bullets on screen - never
                            // re-run the model (a second generation could
                            // differ from what the student approved). The
                            // server may trim/cap bullets, so render what it
                            // actually stored, not what we submitted.
                            const savedResp = await apiCall('/api/ai/key-points', {
                                method: 'POST',
                                body: {
                                    article_id: aid,
                                    source: source,
                                    key_points: data.key_points || [],
                                },
                            });
                            const savedPoints = (savedResp && savedResp.key_points) || data.key_points || [];
                            showNotification('Key points updated (AI rewrite saved).', 'success');
                            const lab = rootEl.querySelector('.key-points-label');
                            if (lab) lab.textContent = 'Key points (AI rewrite — from the abstract only)';
                            if (savedPoints.length) {
                                const savedHtml = savedPoints
                                    .map(b => `<li>${escapeHtml(String(b))}</li>`)
                                    .join('');
                                // Update every rendered copy (result card +
                                // AI panel preview) to match what was stored.
                                rootEl.querySelectorAll('.key-points-list').forEach(ul => {
                                    ul.innerHTML = savedHtml;
                                });
                            }
                            saveBtn.textContent = 'Saved';
                        } catch (err) {
                            showNotification(`Could not save: ${err.message}`, 'error');
                            saveBtn.disabled = false;
                        }
                    });
                }
                setStatus('', false);
            } catch (err) {
                setStatus('', false);
                softAiError(err && err.message ? String(err.message) : 'AI refine failed', 'refine');
            } finally {
                refineBtn.disabled = false;
            }
        });
    }

    const askBtn = wrap.querySelector('.ai-ask-btn');
    if (askBtn) {
        askBtn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const question = await openAiAskModal(article.title || '');
            if (!question) return;
            setStatus('Starting study aid and answering…', true);
            askBtn.disabled = true;
            try {
                // Same ephemeral lifecycle as Refine: start → answer → stop.
                const data = await apiCall('/api/ai/ask-article', {
                    method: 'POST',
                    body: {
                        article_id: aid,
                        source: source,
                        question: question,
                    },
                });
                const quotes = (data.quotes || [])
                    .map(q => `<blockquote class="ai-quote">${escapeHtml(String(q))}</blockquote>`)
                    .join('');
                showPanel(`
                  <div class="ai-label help-text">${escapeHtml(data.label || 'AI answer (abstract only)')}</div>
                  <p class="ai-question"><strong>Q:</strong> ${escapeHtml(question)}</p>
                  <p class="ai-answer">${escapeHtml(data.answer || '')}</p>
                  ${quotes}
                `);
                setStatus('', false);
            } catch (err) {
                setStatus('', false);
                softAiError(err && err.message ? String(err.message) : 'AI ask failed', 'ask');
            } finally {
                askBtn.disabled = false;
            }
        });
    }
}

// === Update nav article count ===
// Raw fetch (not apiCall) so a missing session never triggers a redirect loop
// if this somehow runs outside the app shell.
async function updateNavStats() {
    const el = document.getElementById('nav-article-count');
    if (!el || !document.querySelector('nav.navbar')) return;
    try {
        const response = await fetch('/api/statistics', {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin',
        });
        if (!response.ok) return;
        const stats = await response.json();
        el.textContent = `${stats.total_articles} articles`;
    } catch (e) {
        // silent
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // Flags + source names first so Search/Account match server catalog.
    Promise.all([
        typeof loadUiFlags === 'function' ? loadUiFlags() : Promise.resolve(),
        typeof loadSourceNames === 'function' ? loadSourceNames() : Promise.resolve(),
    ]).finally(() => {
        updateNavStats();
        initLibrarySwitcher();
    });
});

// === Multi-library switcher (nav) ===
async function initLibrarySwitcher() {
    const sel = document.getElementById('nav-library-select');
    if (!sel || !document.querySelector('nav.navbar')) return;
    try {
        const data = await apiCall('/api/libraries');
        populateLibrarySelect(sel, data);
        sel.addEventListener('change', async () => {
            const id = sel.value;
            if (!id) return;
            sel.disabled = true;
            try {
                await apiCall('/api/libraries/switch', {
                    method: 'POST',
                    body: { library_id: id },
                });
                // Reload so every page reflects the new library's data.
                window.location.reload();
            } catch (e) {
                showNotification(`Could not switch library: ${e.message}`, 'error');
                sel.disabled = false;
                // Restore previous selection from a data attribute if set
                if (sel.dataset.activeId) sel.value = sel.dataset.activeId;
            }
        });
    } catch (e) {
        sel.innerHTML = '<option value="">—</option>';
    }
}

function populateLibrarySelect(sel, data) {
    const libs = (data && data.libraries) || [];
    const active = (data && data.active_id) || '';
    sel.innerHTML = '';
    if (!libs.length) {
        sel.innerHTML = '<option value="">No libraries</option>';
        return;
    }
    libs.forEach(L => {
        const opt = document.createElement('option');
        opt.value = L.id;
        opt.textContent = L.name || 'Library';
        if (L.id === active) opt.selected = true;
        sel.appendChild(opt);
    });
    sel.dataset.activeId = active;
}

/** Refresh library dropdown after create/rename/delete on Account page. */
async function refreshLibrarySwitcher() {
    const sel = document.getElementById('nav-library-select');
    if (!sel) return;
    try {
        const data = await apiCall('/api/libraries');
        populateLibrarySelect(sel, data);
    } catch (e) { /* ignore */ }
}

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

// === Theme toggle (with smooth crossfade) ===
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
        // Icon = current mode (moon while dark, sun while light).
        // Title describes the action of the next click.
        btn.textContent = theme === 'dark' ? '🌙' : '☀';
        btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
        btn.setAttribute('aria-label', btn.title);
    }

    updateButton(getEffectiveTheme());

    btn.addEventListener('click', function() {
        const next = getEffectiveTheme() === 'dark' ? 'light' : 'dark';
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduce) {
            root.classList.add('theme-animating');
            setTimeout(() => root.classList.remove('theme-animating'), 320);
        }
        localStorage.setItem('theme', next);
        root.setAttribute('data-theme', next);
        updateButton(next);
    });
});

// === Sticky nav elevation on scroll ===
document.addEventListener('DOMContentLoaded', function() {
    const nav = document.querySelector('.navbar');
    if (!nav) return;

    const onScroll = () => {
        nav.classList.toggle('scrolled', window.scrollY > 4);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
});

// === Mobile nav dropdown (workflow steps) ===
// Uses body.nav-menu-open + .navbar.nav-open so CSS can force the panel open
// even when other display rules fight. Outside-close is deferred one tick so
// the same tap that opens the menu does not immediately close it.
document.addEventListener('DOMContentLoaded', function() {
    const nav = document.getElementById('site-navbar') || document.querySelector('.navbar');
    const toggle = document.getElementById('nav-menu-toggle');
    const panel = document.getElementById('nav-links-panel');
    if (!nav || !toggle || !panel) return;

    let open = false;

    function setOpen(next) {
        open = !!next;
        nav.classList.toggle('nav-open', open);
        document.body.classList.toggle('nav-menu-open', open);
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        toggle.title = open ? 'Close steps menu' : 'Open steps menu';
        // Keep panel in tab order only when open on mobile (desktop always shows it)
        if (window.matchMedia('(max-width: 900px)').matches) {
            panel.setAttribute('aria-hidden', open ? 'false' : 'true');
        } else {
            panel.removeAttribute('aria-hidden');
        }
    }

    setOpen(false);

    toggle.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        setOpen(!open);
    });

    panel.querySelectorAll('a.nav-link').forEach(function(link) {
        link.addEventListener('click', function() {
            setOpen(false);
        });
    });

    // Outside click: listen on pointerdown so it feels instant; ignore the toggle.
    document.addEventListener('pointerdown', function(e) {
        if (!open) return;
        if (nav.contains(e.target)) return;
        setOpen(false);
    }, true);

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && open) {
            setOpen(false);
            toggle.focus();
        }
    });

    const mq = window.matchMedia('(min-width: 901px)');
    function onMq() {
        if (mq.matches) setOpen(false);
    }
    if (mq.addEventListener) mq.addEventListener('change', onMq);
    else if (mq.addListener) mq.addListener(onMq);
});

// === Prefers-reduced-motion helper ===
function prefersReducedMotion() {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// === Reading mode (denser chrome, optimized abstracts) ===
function isReadingMode() {
    return document.documentElement.getAttribute('data-reading') === 'on';
}

function setReadingMode(on) {
    const root = document.documentElement;
    if (on) {
        root.setAttribute('data-reading', 'on');
        localStorage.setItem('readingMode', 'on');
    } else {
        root.removeAttribute('data-reading');
        localStorage.setItem('readingMode', 'off');
    }
    const btn = document.getElementById('reading-toggle');
    if (btn) {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        btn.classList.toggle('is-active', on);
        btn.title = on
            ? 'Exit reading mode'
            : 'Reading mode — denser layout, better abstracts';
    }
    // Re-apply abstract clamps so they respect the new mode.
    enhanceAbstracts(document);
}

document.addEventListener('DOMContentLoaded', function() {
    const btn = document.getElementById('reading-toggle');
    if (!btn) return;
    setReadingMode(isReadingMode());
    btn.addEventListener('click', function() {
        setReadingMode(!isReadingMode());
    });
});

// === Long-abstract clamp + expand (Search results, etc.) ===
// Abstracts longer than this get a collapse with "Show full abstract".
const ABSTRACT_CLAMP_CHARS = 420;

function enhanceAbstracts(root) {
    const scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll('.article-abstract').forEach((el) => {
        if (el.dataset.enhanced === '1') {
            // Reading mode always shows full text.
            _syncAbstractClamp(el);
            return;
        }
        el.dataset.enhanced = '1';
        const full = (el.textContent || '').trim();
        el.dataset.fullText = full;
        if (full.length <= ABSTRACT_CLAMP_CHARS) return;

        const wrap = document.createElement('div');
        wrap.className = 'abstract-wrap';
        el.parentNode.insertBefore(wrap, el);
        wrap.appendChild(el);

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = 'abstract-toggle';
        wrap.appendChild(toggle);

        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const expanded = wrap.classList.toggle('is-expanded');
            toggle.textContent = expanded ? 'Show less' : 'Show full abstract';
            toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        });

        _syncAbstractClamp(el);
    });
}

function _syncAbstractClamp(el) {
    const wrap = el.closest('.abstract-wrap');
    if (!wrap) return;
    const toggle = wrap.querySelector('.abstract-toggle');
    const full = el.dataset.fullText || el.textContent || '';
    if (full.length <= ABSTRACT_CLAMP_CHARS) return;

    // In reading mode, default to expanded (full abstract always visible).
    if (isReadingMode()) {
        wrap.classList.add('is-expanded');
        el.classList.remove('is-clamped');
        if (toggle) {
            toggle.textContent = 'Show less';
            toggle.setAttribute('aria-expanded', 'true');
            // Keep a way to collapse if desired.
            toggle.hidden = false;
        }
        return;
    }

    if (!wrap.classList.contains('is-expanded')) {
        el.classList.add('is-clamped');
        if (toggle) {
            toggle.textContent = 'Show full abstract';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.hidden = false;
        }
    } else {
        el.classList.remove('is-clamped');
        if (toggle) {
            toggle.textContent = 'Show less';
            toggle.setAttribute('aria-expanded', 'true');
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    enhanceAbstracts(document);
});

// === Page transitions (internal same-origin navigations) ===
// Uses the View Transitions API when available; otherwise a short fade-out
// before navigating. Skips new tabs, downloads, anchors, external links,
// and logout (so cookies clear without a weird half-fade).
const PAGE_EXIT_MS = 170;

function isInternalNavLink(a) {
    if (!a || !a.href) return false;
    if (a.target && a.target !== '_self') return false;
    if (a.hasAttribute('download')) return false;
    if (a.dataset.noTransition === '1') return false;
    // Don't animate away on logout / destructive account flows.
    const path = a.pathname || '';
    if (path === '/logout' || path.endsWith('/logout')) return false;

    try {
        const url = new URL(a.href, window.location.href);
        if (url.origin !== window.location.origin) return false;
        if (url.pathname === window.location.pathname && url.search === window.location.search) {
            // Same page — only hash change; let the browser handle it.
            if (url.hash) return false;
        }
        // Only same-origin http(s) navigations.
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return false;
        return true;
    } catch (_) {
        return false;
    }
}

function supportsCrossDocViewTransition() {
    // Chromium MPA view transitions are driven by `@view-transition { navigation: auto }`.
    // When available, skip the JS fade-out so we don't double-animate.
    try {
        return typeof CSS !== 'undefined' && CSS.supports('(view-transition-name: none)');
    } catch (_) {
        return false;
    }
}

function navigateWithTransition(url) {
    if (prefersReducedMotion() || supportsCrossDocViewTransition()) {
        window.location.href = url;
        return;
    }

    // Fallback for browsers without cross-document view transitions.
    document.body.classList.add('page-exit');
    window.setTimeout(function() {
        window.location.href = url;
    }, PAGE_EXIT_MS);
}

document.addEventListener('click', function(e) {
    // Ignore modified clicks (new tab, etc.).
    if (e.defaultPrevented || e.button !== 0) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;

    const a = e.target.closest && e.target.closest('a[href]');
    if (!isInternalNavLink(a)) return;

    e.preventDefault();
    navigateWithTransition(a.href);
});

// Enter animation once the page is interactive.
// Content is visible even without this class — it only enables a soft fade-up.
function markPageEntered() {
    if (!document.body) return;
    document.body.classList.add('page-enter');
    document.body.classList.remove('page-exit');
}

document.addEventListener('DOMContentLoaded', function() {
    // Double-rAF: paint first frame fully visible, then run enter animation.
    requestAnimationFrame(function() {
        requestAnimationFrame(markPageEntered);
    });
});

// bfcache restore: clear any stuck exit state from a prior navigation.
window.addEventListener('pageshow', function(e) {
    document.body.classList.remove('page-exit');
    if (e.persisted) {
        markPageEntered();
    }
});
