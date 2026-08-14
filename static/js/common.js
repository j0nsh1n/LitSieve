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

/** HTML for key points (extractive or student-saved AI rewrite).
 *
 * When the full abstract is already on the card (options.abstractShown), skip
 * listing extractive bullets — they restate the abstract and look like a
 * duplicate. AI-saved rewrites still show their bullet list once.
 */
function renderKeyPointsHtml(bullets, options) {
    options = options || {};
    const isAi = !!(options.aiLabel || options.origin === 'ai');
    const hasBullets = !!(bullets && bullets.length);
    // Abstract already visible: only surface AI-saved bullets or the AI action row.
    const hideExtractiveList = !!options.abstractShown && !isAi;
    if (!hasBullets && !options.articleId) return '';
    if (hideExtractiveList && !options.articleId) return '';

    const label = isAi
        ? 'Key points (AI rewrite — from the abstract only)'
        : 'Key points (from the abstract)';
    const showList = hasBullets && !hideExtractiveList;
    const items = showList
        ? (bullets || []).map(b => `<li>${escapeHtml(String(b))}</li>`).join('')
        : '';
    const list = items ? `<ul class="key-points-list">${items}</ul>` : '';
    const aid = options.articleId ? escapeHtml(String(options.articleId)) : '';
    const src = options.source ? escapeHtml(String(options.source)) : '';
    const showAi = typeof uiFlag === 'function' ? uiFlag('show_ai_buttons', true) : true;
    const actions = (aid && src && showAi)
        ? `<div class="ai-actions" data-article-id="${aid}" data-source="${src}">
            <button type="button" class="btn btn-secondary btn-sm ai-refine-btn" title="Optional AI rewrite of summary and bullets from this abstract only">Refine with AI</button>
            <button type="button" class="btn btn-secondary btn-sm ai-ask-btn" title="Ask a question answered only from this abstract">Ask about this paper</button>
            <span class="ai-status-line help-text" hidden></span>
           </div>
           <div class="ai-panel" hidden></div>`
        : '';
    // Nothing to show (no list, no AI chrome).
    if (!list && !actions) return '';
    // Extractive + abstract shown: only AI chrome (no empty "Key points" header).
    if (hideExtractiveList && actions) {
        return `<div class="key-points key-points-actions-only" data-kp-origin="extractive">
      ${actions}
    </div>`;
    }
    return `<div class="key-points" data-kp-origin="${isAi ? 'ai' : 'extractive'}">
      <div class="key-points-label">${escapeHtml(label)}</div>
      ${list}
      ${actions}
    </div>`;
}

/**
 * Shared site modal shell (confirm / prompt / alert / choice). Replaces browser popups.
 * opts: {
 *   title, message, mode: 'confirm'|'prompt'|'alert'|'choice',
 *   defaultValue, placeholder, inputType, multiline, selectAll,
 *   confirmLabel, cancelLabel, danger, requireNonEmpty,
 *   choices: [{ label, value, primary?, danger?, cancel? }]  // mode 'choice'
 * }
 * confirm → Promise<boolean>
 * prompt  → Promise<string|null>  (null = cancelled)
 * alert   → Promise<void>
 * choice  → Promise<any>  (value from chosen button; cancel buttons use value null)
 *
 * Accessibility (Phase 8): focus trap, restore focus to opener, body scroll lock
 * with scroll-position restore. Mobile (≤640px): bottom-sheet card layout in CSS.
 */
function openSiteModal(opts) {
    const o = opts || {};
    const mode = o.mode || 'alert';
    const opener = (typeof document !== 'undefined'
        && document.activeElement instanceof HTMLElement)
        ? document.activeElement
        : null;
    return new Promise((resolve) => {
        const existing = document.getElementById('site-modal-root');
        if (existing) existing.remove();

        const root = document.createElement('div');
        root.id = 'site-modal-root';
        root.className = 'lra-modal-root';
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.setAttribute('aria-labelledby', 'site-modal-title');

        const title = o.title || (mode === 'confirm' ? 'Please confirm' : mode === 'prompt' ? 'Input needed' : mode === 'form' ? 'Options' : 'Notice');
        const confirmLabel = o.confirmLabel || (mode === 'confirm' ? 'Confirm' : 'OK');
        const cancelLabel = o.cancelLabel || 'Cancel';
        const confirmClass = o.danger ? 'btn btn-danger' : 'btn btn-primary';
        const msgHtml = o.message
            ? `<p class="lra-modal-message info-text">${escapeHtml(String(o.message)).replace(/\n/g, '<br>')}</p>`
            : '';

        let fieldHtml = '';
        const formFields = Array.isArray(o.fields) ? o.fields : [];
        const isForm = mode === 'form' && formFields.length > 0;
        // prompt mode always shows an input; choice mode can opt in via withInput
        // (e.g. Simple re-prepare: verify research question in the same dialog).
        const showInput = !isForm && (mode === 'prompt' || !!(mode === 'choice' && o.withInput));
        if (showInput) {
            const fieldLabel = o.inputLabel
                ? escapeHtml(String(o.inputLabel))
                : escapeHtml(title);
            const labelClass = o.inputLabel ? 'help-text' : 'u-visually-hidden';
            if (o.multiline) {
                fieldHtml = `
            <div class="form-group lra-modal-input-group">
              <label class="${labelClass}" for="site-modal-input">${fieldLabel}</label>
              <textarea id="site-modal-input" class="lra-modal-textarea" rows="6"
                placeholder="${escapeHtml(o.placeholder || '')}"></textarea>
            </div>`;
            } else {
                fieldHtml = `
            <div class="form-group lra-modal-input-group">
              <label class="${labelClass}" for="site-modal-input">${fieldLabel}</label>
              <input id="site-modal-input" class="lra-modal-input" type="${escapeHtml(o.inputType || 'text')}"
                placeholder="${escapeHtml(o.placeholder || '')}" autocomplete="off">
            </div>`;
            }
        }
        if (isForm) {
            fieldHtml = `<div class="lra-modal-fields">${formFields.map((f) => {
                const fid = escapeHtml(String(f.id || ''));
                const label = escapeHtml(String(f.label || f.id || ''));
                const typ = escapeHtml(String(f.type || 'text'));
                const ph = escapeHtml(String(f.placeholder || ''));
                const min = f.min != null ? ` min="${escapeHtml(String(f.min))}"` : '';
                const max = f.max != null ? ` max="${escapeHtml(String(f.max))}"` : '';
                const step = f.step != null ? ` step="${escapeHtml(String(f.step))}"` : '';
                return `<div class="form-group lra-modal-input-group" data-field="${fid}">
              <label class="help-text" for="site-modal-field-${fid}">${label}</label>
              <input id="site-modal-field-${fid}" class="lra-modal-input" type="${typ}"
                placeholder="${ph}"${min}${max}${step} autocomplete="off">
            </div>`;
            }).join('')}</div>`;
        }

        let actionsHtml = '';
        if (mode === 'choice' && Array.isArray(o.choices) && o.choices.length) {
            actionsHtml = o.choices.map((c, i) => {
                const label = escapeHtml(String(c.label != null ? c.label : 'OK'));
                let cls = 'btn btn-secondary';
                if (c.danger) cls = 'btn btn-danger';
                else if (c.primary) cls = 'btn btn-primary';
                const cancelAttr = c.cancel ? ' data-site-modal-cancel="1"' : '';
                return `<button type="button" class="${cls}" data-site-modal-choice="${i}"${cancelAttr}>${label}</button>`;
            }).join('');
        } else {
            const cancelBtn = mode === 'alert'
                ? ''
                : `<button type="button" class="btn btn-secondary" data-site-modal-cancel>${escapeHtml(cancelLabel)}</button>`;
            actionsHtml = `${cancelBtn}
              <button type="button" class="${confirmClass}" id="site-modal-confirm">${escapeHtml(confirmLabel)}</button>`;
        }

        root.innerHTML = `
          <div class="lra-modal-backdrop" data-site-modal-cancel></div>
          <div class="lra-modal-card card" data-site-modal-card>
            <h2 id="site-modal-title" class="lra-modal-title">${escapeHtml(title)}</h2>
            ${msgHtml}
            ${fieldHtml}
            <div class="lra-modal-actions">
              ${actionsHtml}
            </div>
          </div>
        `;

        // Body scroll lock — pin page so background cannot scroll under the dialog.
        const scrollY = window.scrollY || window.pageYOffset || 0;
        document.body.dataset.lraScrollY = String(scrollY);
        document.body.style.top = `-${scrollY}px`;
        document.body.classList.add('lra-modal-open');
        document.body.appendChild(root);

        const input = root.querySelector('#site-modal-input');
        const confirmBtn = root.querySelector('#site-modal-confirm');
        let settled = false;

        const focusableSelector = [
            'button:not([disabled])',
            '[href]',
            'input:not([disabled]):not([type="hidden"])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
        ].join(',');

        const getFocusable = () => {
            const card = root.querySelector('[data-site-modal-card]') || root;
            return Array.from(card.querySelectorAll(focusableSelector)).filter((el) => {
                if (el.hasAttribute('disabled') || el.getAttribute('aria-hidden') === 'true') {
                    return false;
                }
                // offsetParent is null for fixed/absolute in some cases; use size instead.
                const r = el.getBoundingClientRect();
                return r.width > 0 || r.height > 0;
            });
        };

        const close = (value) => {
            if (settled) return;
            settled = true;
            document.body.classList.remove('lra-modal-open');
            document.body.style.top = '';
            const y = parseInt(document.body.dataset.lraScrollY || '0', 10) || 0;
            delete document.body.dataset.lraScrollY;
            root.remove();
            document.removeEventListener('keydown', onKey, true);
            window.scrollTo(0, y);
            if (opener && typeof opener.focus === 'function') {
                try {
                    opener.focus({ preventScroll: true });
                } catch (_e) {
                    try { opener.focus(); } catch (_e2) { /* ignore */ }
                }
            }
            resolve(value);
        };

        const cancelValue = () => {
            if (mode === 'confirm') return false;
            if (mode === 'prompt' || mode === 'choice' || mode === 'form') return null;
            return undefined;
        };

        const onKey = (ev) => {
            if (ev.key === 'Escape') {
                ev.preventDefault();
                ev.stopPropagation();
                close(cancelValue());
                return;
            }
            if (ev.key !== 'Tab') return;
            const list = getFocusable();
            if (!list.length) {
                ev.preventDefault();
                return;
            }
            const first = list[0];
            const last = list[list.length - 1];
            const active = document.activeElement;
            if (ev.shiftKey) {
                if (active === first || !root.contains(active)) {
                    ev.preventDefault();
                    last.focus();
                }
            } else if (active === last || !root.contains(active)) {
                ev.preventDefault();
                first.focus();
            }
        };
        // Capture phase so Tab is trapped even if children stop bubbling.
        document.addEventListener('keydown', onKey, true);

        root.querySelectorAll('[data-site-modal-cancel]').forEach((el) => {
            el.addEventListener('click', (ev) => {
                // Choice buttons with cancel:true also carry data-site-modal-choice;
                // let the choice handler run instead when both are present.
                if (el.hasAttribute('data-site-modal-choice') && mode === 'choice') {
                    return;
                }
                ev.preventDefault();
                close(cancelValue());
            });
        });

        if (mode === 'choice') {
            root.querySelectorAll('[data-site-modal-choice]').forEach((btn) => {
                btn.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    const idx = parseInt(btn.getAttribute('data-site-modal-choice'), 10);
                    const choice = (o.choices || [])[idx];
                    if (!choice) {
                        close(null);
                        return;
                    }
                    if (choice.cancel) {
                        close(choice.value !== undefined ? choice.value : null);
                        return;
                    }
                    // Optional input in the same dialog (Simple re-prepare prompt verify).
                    if (o.withInput) {
                        const val = input ? input.value : '';
                        const trimmed = String(val).trim();
                        if (o.requireNonEmpty && !trimmed) {
                            showNotification(
                                o.emptyMessage || 'Please confirm your research question.',
                                'error'
                            );
                            if (input) input.focus();
                            return;
                        }
                        close({ value: choice.value, input: val });
                        return;
                    }
                    close(choice.value);
                });
            });
        }

        if (confirmBtn) {
            confirmBtn.addEventListener('click', (ev) => {
                ev.preventDefault();
                if (mode === 'confirm') {
                    close(true);
                    return;
                }
                if (mode === 'alert') {
                    close(undefined);
                    return;
                }
                if (isForm) {
                    const values = {};
                    formFields.forEach((f) => {
                        const el = root.querySelector('#site-modal-field-' + f.id);
                        values[f.id] = el ? el.value : '';
                    });
                    if (typeof o.validate === 'function') {
                        const err = o.validate(values);
                        if (err) {
                            showNotification(String(err), 'error');
                            return;
                        }
                    }
                    close(values);
                    return;
                }
                // prompt
                const val = input ? input.value : '';
                const trimmed = String(val).trim();
                if (o.requireNonEmpty && !trimmed) {
                    showNotification('Please enter a value.', 'error');
                    if (input) input.focus();
                    return;
                }
                const minLen = o.minLength != null ? Number(o.minLength) : 0;
                if (minLen > 0 && trimmed.length < minLen) {
                    showNotification(
                        o.minLengthMessage
                            || `Please enter at least ${minLen} characters.`,
                        'error'
                    );
                    if (input) input.focus();
                    return;
                }
                close(val);
            });
        }

        if (isForm) {
            formFields.forEach((f) => {
                const el = root.querySelector('#site-modal-field-' + f.id);
                if (el && f.value != null) el.value = String(f.value);
            });
            root.querySelectorAll('.lra-modal-fields .lra-modal-input').forEach((el) => {
                el.addEventListener('keydown', (ev) => {
                    if (ev.key === 'Enter' && !ev.shiftKey) {
                        ev.preventDefault();
                        confirmBtn && confirmBtn.click();
                    }
                });
            });
            const firstField = root.querySelector('.lra-modal-fields .lra-modal-input');
            setTimeout(() => {
                if (firstField) firstField.focus();
            }, 30);
        } else if (input) {
            input.value = o.defaultValue != null ? String(o.defaultValue) : '';
            input.addEventListener('keydown', (ev) => {
                if (ev.key === 'Enter' && !ev.shiftKey) {
                    ev.preventDefault();
                    // Choice+input: Enter should not auto-pick a scope button.
                    if (mode === 'choice' && o.withInput) {
                        return;
                    }
                    confirmBtn && confirmBtn.click();
                }
            });
            setTimeout(() => {
                input.focus();
                if (o.selectAll && typeof input.select === 'function') input.select();
            }, 30);
        } else {
            setTimeout(() => {
                const list = getFocusable();
                const preferred = root.querySelector('.btn-primary') || list[0];
                if (preferred) preferred.focus();
            }, 30);
        }
    });
}

function openSiteConfirm(opts) {
    return openSiteModal(Object.assign({}, opts, { mode: 'confirm' }));
}

function openSitePrompt(opts) {
    return openSiteModal(Object.assign({}, opts, { mode: 'prompt' }));
}

function openSiteAlert(opts) {
    return openSiteModal(Object.assign({}, opts, { mode: 'alert' }));
}

/** Multi-button dialog. Resolves to the chosen `value`, or null if cancelled. */
function openSiteChoice(opts) {
    return openSiteModal(Object.assign({}, opts, { mode: 'choice' }));
}

/** Multi-field dialog. Resolves to `{ id: value, … }` or null if cancelled. */
function openSiteForm(opts) {
    return openSiteModal(Object.assign({}, opts, { mode: 'form' }));
}

/**
 * Site-styled modal for Ask about this paper (replaces window.prompt).
 * Resolves with trimmed question string, or null if cancelled.
 */
function openAiAskModal(paperTitle) {
    return openSitePrompt({
        title: 'Ask about this paper',
        message: paperTitle
            ? `About: ${String(paperTitle).slice(0, 160)}\n\nAnswered only from this paper’s title and abstract (not the full text).`
            : 'Answered only from this paper’s title and abstract (not the full text). The study aid starts for this question, then stops.',
        placeholder: 'e.g. Who was studied? What was the main finding?',
        confirmLabel: 'Ask',
        cancelLabel: 'Cancel',
        multiline: true,
        requireNonEmpty: true,
        minLength: 3,
        minLengthMessage: 'Type a slightly longer question (at least a few words).',
    }).then((q) => (q == null ? null : String(q).trim()));
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
                            // Promote the main card block to a single AI list;
                            // hide the refine panel so bullets are not shown twice.
                            const kpRoot = rootEl.querySelector('.key-points');
                            if (kpRoot && savedPoints.length) {
                                kpRoot.dataset.kpOrigin = 'ai';
                                kpRoot.classList.remove('key-points-actions-only');
                                let lab = kpRoot.querySelector('.key-points-label');
                                if (!lab) {
                                    lab = document.createElement('div');
                                    lab.className = 'key-points-label';
                                    kpRoot.insertBefore(lab, kpRoot.firstChild);
                                }
                                lab.textContent = 'Key points (AI rewrite — from the abstract only)';
                                const savedHtml = savedPoints
                                    .map(b => `<li>${escapeHtml(String(b))}</li>`)
                                    .join('');
                                let ul = kpRoot.querySelector(':scope > .key-points-list');
                                if (!ul) {
                                    ul = document.createElement('ul');
                                    ul.className = 'key-points-list';
                                    const acts = kpRoot.querySelector('.ai-actions');
                                    kpRoot.insertBefore(ul, acts || null);
                                }
                                ul.innerHTML = savedHtml;
                            }
                            if (panel) {
                                panel.hidden = true;
                                panel.innerHTML = '';
                            }
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
// Public pages bind this in theme-init.js (they cannot load common.js).
// App pages load both scripts; skip if theme-init already bound the button.
document.addEventListener('DOMContentLoaded', function() {
    const root = document.documentElement;
    const btn = document.getElementById('theme-toggle');
    if (!btn || btn.getAttribute('data-theme-bound') === '1') return;
    btn.setAttribute('data-theme-bound', '1');

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
            setTimeout(() => root.classList.remove('theme-animating'), 180);
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

// === Simple / Advanced UI mode (client preference, like theme) ===
function isSimpleMode() {
    return document.documentElement.getAttribute('data-mode') === 'simple';
}

function updateModeToggleButton() {
    const btn = document.getElementById('mode-toggle');
    if (!btn) return;
    const simple = isSimpleMode();
    // Highlight when Advanced is active (not Simple) — power mode reads as "on".
    btn.setAttribute('aria-pressed', simple ? 'false' : 'true');
    btn.classList.toggle('is-active', !simple);
    btn.textContent = simple ? 'Simple' : 'Advanced';
    btn.title = simple
        ? 'Switch to Advanced mode — full controls'
        : 'Switch to Simple mode — fewer options';
    btn.setAttribute('aria-label', btn.title);
}

function _collectQueryOn() {
    return /(?:\?|&|#)collect=1(?:&|$)/.test((location.search || '') + (location.hash || ''));
}

function updateNavStepNumbers() {
    const simple = isSimpleMode();
    // Phase 10: Simple "Get papers" is /search?collect=1 (real collect state),
    // not /data-management (which 302s back to /search).
    document.querySelectorAll('.nav-link[data-href-simple], .nav-link[data-href-advanced]').forEach((a) => {
        const hrefAdv = a.getAttribute('data-href-advanced');
        const hrefSim = a.getAttribute('data-href-simple');
        const next = simple ? (hrefSim || hrefAdv) : (hrefAdv || hrefSim);
        if (next) a.setAttribute('href', next);
    });
    document.querySelectorAll('.nav-link[data-step-advanced]').forEach((a) => {
        const num = a.querySelector('.nav-step-num');
        if (!num) return;
        const next = simple ? (a.getAttribute('data-step-simple') || '') : (a.getAttribute('data-step-advanced') || '');
        if (next) {
            num.textContent = next;
            num.hidden = false;
        } else if (simple) {
            // Hidden Simple steps (Clusters, Clean up) — no number when opened by URL.
            num.hidden = true;
        } else {
            num.hidden = false;
            const adv = a.getAttribute('data-step-advanced') || '';
            if (adv) num.textContent = adv;
        }
    });
    const menuStep = document.querySelector('.nav-menu-step');
    if (menuStep) {
        const adv = menuStep.getAttribute('data-step-advanced') || '';
        const sim = menuStep.getAttribute('data-step-simple') || '';
        const next = simple ? sim : adv;
        if (next) {
            menuStep.textContent = next;
            menuStep.hidden = false;
        } else if (simple && !sim) {
            // e.g. Clusters / Clean up opened by URL in Simple mode — no step number.
            menuStep.hidden = true;
        } else {
            menuStep.hidden = false;
            if (adv) menuStep.textContent = adv;
        }
    }
    const getPapers = document.querySelector('.nav-step-data_management');
    const searchLink = document.querySelector('.nav-step-search');
    if (getPapers && searchLink) {
        const path = location.pathname || '';
        const collecting = simple && (
            _collectQueryOn()
            || !!(document.body && document.body.classList.contains('simple-collecting'))
        );
        if (simple) {
            const onSearch = path.indexOf('/search') !== -1;
            getPapers.classList.toggle('active', collecting);
            searchLink.classList.toggle('active', onSearch && !collecting);
            if (collecting) {
                getPapers.setAttribute('aria-current', 'page');
                searchLink.removeAttribute('aria-current');
            } else if (onSearch) {
                searchLink.setAttribute('aria-current', 'page');
                getPapers.removeAttribute('aria-current');
            }
        } else {
            getPapers.classList.toggle('active', path.indexOf('/data-management') !== -1);
            searchLink.classList.toggle('active', path.indexOf('/search') !== -1);
            if (path.indexOf('/data-management') !== -1) {
                getPapers.setAttribute('aria-current', 'page');
                searchLink.removeAttribute('aria-current');
            } else if (path.indexOf('/search') !== -1) {
                searchLink.setAttribute('aria-current', 'page');
                getPapers.removeAttribute('aria-current');
            }
        }
    }
}

function setUiMode(mode) {
    const m = mode === 'simple' ? 'simple' : 'advanced';
    const root = document.documentElement;
    root.setAttribute('data-mode', m);
    try {
        localStorage.setItem('uiMode', m);
    } catch (e) { /* private mode */ }
    try {
        document.cookie = 'ui_mode=' + m + '; Path=/; SameSite=Lax; Max-Age=31536000';
    } catch (e2) { /* ignore */ }
    updateModeToggleButton();
    updateNavStepNumbers();
}

/** Phase 8: one summonable Help panel per page (`#page-help` + toggle). */
function initPageHelp() {
    const helpToggle = document.getElementById('page-help-toggle');
    const helpPanel = document.getElementById('page-help');
    if (!helpToggle || !helpPanel) return;
    helpToggle.addEventListener('click', () => {
        const open = helpPanel.hasAttribute('hidden');
        if (open) helpPanel.removeAttribute('hidden');
        else helpPanel.setAttribute('hidden', '');
        helpToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
}

document.addEventListener('DOMContentLoaded', function() {
    const btn = document.getElementById('mode-toggle');
    if (btn) {
        // theme-init already set data-mode; sync chrome only.
        updateModeToggleButton();
        updateNavStepNumbers();
        btn.addEventListener('click', function() {
            setUiMode(isSimpleMode() ? 'advanced' : 'simple');
        });
    }
    initPageHelp();
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
            wrap.classList.toggle('is-expanded');
            // Must refresh is-clamped: CSS line-clamp is on .is-clamped alone,
            // so flipping only is-expanded left the abstract still truncated.
            _syncAbstractClamp(el);
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

    // Start collapsed — "Show full abstract" to read more.
    const expanded = wrap.classList.contains('is-expanded');
    if (expanded) {
        el.classList.remove('is-clamped');
        if (toggle) {
            toggle.textContent = 'Show less';
            toggle.setAttribute('aria-expanded', 'true');
            toggle.hidden = false;
        }
    } else {
        el.classList.add('is-clamped');
        if (toggle) {
            toggle.textContent = 'Show full abstract';
            toggle.setAttribute('aria-expanded', 'false');
            toggle.hidden = false;
        }
    }
}

document.addEventListener('DOMContentLoaded', function() {
    enhanceAbstracts(document);
});

document.addEventListener('DOMContentLoaded', function() {
    const endDemo = document.querySelector('.guest-banner-logout');
    if (!endDemo) return;
    endDemo.addEventListener('click', async function(ev) {
        ev.preventDefault();
        const href = endDemo.getAttribute('href') || '/logout';
        if (typeof openSiteConfirm === 'function') {
            const ok = await openSiteConfirm({
                title: 'End this demo?',
                message: 'Notes and screening in this demo will be gone. You can start a new demo from the home page anytime.',
                confirmLabel: 'End demo',
                cancelLabel: 'Keep demo',
                danger: true,
            });
            if (!ok) return;
        }
        window.location.href = href;
    });
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
