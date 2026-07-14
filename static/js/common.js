// === HTML escaping (shared) ===
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : text;
    return div.innerHTML;
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
        core: 'CORE',
    };
    return names[source] || source;
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
