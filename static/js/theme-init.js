// Applies the saved theme to <html> before first paint.
//
// Must stay a plain blocking <script src> in <head> — no defer, no async, no
// module. A dark-theme user would otherwise see a white flash on every page load.
//
// Lives in a file (not inline) so the CSP can be `script-src 'self'` with no
// 'unsafe-inline'. Auth/landing pages load only this; they must not load
// common.js, which calls authenticated APIs.
(function () {
    var root = document.documentElement;
    try {
        var saved = localStorage.getItem('theme');
        if (saved) root.setAttribute('data-theme', saved);

    } catch (e) { /* Browser storage can be unavailable. */ }

    // Cookie wins so a just-signed-in account is not stuck with the previous
    // visitor's localStorage look on a shared computer.
    var LOOKS = {workshop:1, broadsheet:1, lab:1, night:1, catalog:1, observatory:1, reading:1};
    window.LRA_LOOKS = LOOKS;
    window.LRA_LOOK_CARDS = [
        {id: 'workshop', title: 'Workshop', blurb: 'Warm paper and a clay accent. The current LitSieve look.'},
        {id: 'broadsheet', title: 'Broadsheet', blurb: 'Ink on newsprint. A lead paper and editorial columns under a double rule.'},
        {id: 'lab', title: 'Lab', blurb: 'Cool light and a blue accent. Results as a source and year table.'},
        {id: 'night', title: 'Night', blurb: 'Low light and a lamp glow. Amber on charcoal.'},
        {id: 'catalog', title: 'Catalog', blurb: 'Library card stock and a maroon stamp. Index cards with source tabs.'},
        {id: 'observatory', title: 'Observatory', blurb: 'Deep blue and a green signal. A year, title and source register.'},
        {id: 'reading', title: 'Reading room', blurb: 'Quiet blue on white. A book serif and a wide reading column.'}
    ];
    var look = '';
    var lookFromCookie = false;
    try {
        var lookCookie = document.cookie.match(/(?:^|;\s*)ui_look=([^;]*)/);
        if (lookCookie) look = decodeURIComponent(lookCookie[1]);
        lookFromCookie = !!LOOKS[look];
        if (!lookFromCookie) look = localStorage.getItem('uiLook') || '';
    } catch (eLook) { look = ''; }
    function writeCookie(name, value) {
        try {
            var secure = location.protocol === 'https:' ? '; Secure' : '';
            document.cookie = name + '=' + value + '; Path=/; SameSite=Lax; Max-Age=31536000' + secure;
        } catch (eCookie) { /* ignore */ }
    }

    // Mirrors app/content/appearance.py (SETTINGS values and PRESETS).
    var APPEARANCE = {
        layout: ['cards', 'list', 'register', 'table', 'columns', 'index', 'reading'],
        text: ['small', 'standard', 'large', 'larger'],
        measure: ['narrow', 'standard', 'wide'],
        titles: ['sans', 'serif', 'book'],
        reading: ['sans', 'serif', 'book'],
        accent: ['look', 'green', 'blue', 'clay', 'teal', 'ochre', 'maroon'],
        density: ['compact', 'standard', 'roomy'],
        corners: ['square', 'small', 'medium', 'round'],
        edges: ['hairline', 'bordered', 'offset']
    };
    var BASE = {text: 'standard', measure: 'standard', accent: 'look', density: 'standard'};
    var PRESETS = {
        workshop: {layout: 'cards', titles: 'serif', reading: 'sans', corners: 'round', edges: 'bordered'},
        broadsheet: {layout: 'columns', titles: 'serif', reading: 'serif', corners: 'square', edges: 'hairline'},
        lab: {layout: 'table', titles: 'sans', reading: 'sans', density: 'compact', corners: 'small', edges: 'hairline'},
        night: {layout: 'list', titles: 'book', reading: 'book', density: 'roomy', corners: 'medium', edges: 'hairline'},
        catalog: {layout: 'index', titles: 'serif', reading: 'serif', corners: 'small', edges: 'offset'},
        observatory: {layout: 'register', titles: 'sans', reading: 'sans', density: 'roomy', corners: 'medium', edges: 'hairline'},
        reading: {layout: 'reading', titles: 'book', reading: 'book', measure: 'wide', corners: 'medium', edges: 'hairline'}
    };
    var DARK_FIRST = {night: 1, observatory: 1};
    window.LRA_APPEARANCE = APPEARANCE;

    function preset(id) {
        var out = {};
        var k;
        for (k in BASE) out[k] = BASE[k];
        for (k in PRESETS[id]) out[k] = PRESETS[id][k];
        return out;
    }
    // Only allowlisted values that differ from the look's preset survive.
    function cleanOverrides(raw, id) {
        var base = preset(id);
        var out = {};
        for (var k in APPEARANCE) {
            var v = raw && raw[k];
            if (typeof v === 'string' && APPEARANCE[k].indexOf(v) !== -1 && v !== base[k]) out[k] = v;
        }
        return out;
    }
    function parseCookieOverrides(text) {
        var raw = {};
        (text || '').split('~').forEach(function (pair) {
            var dot = pair.indexOf('.');
            if (dot > 0) raw[pair.slice(0, dot)] = pair.slice(dot + 1);
        });
        return raw;
    }
    function cookieText(overrides) {
        return Object.keys(overrides).map(function (k) { return k + '.' + overrides[k]; }).join('~');
    }

    // Light or dark as painted: Night and Observatory are dark unless the
    // student chose light; the rest follow the toggle, then the system.
    function effectiveTone() {
        var theme = root.getAttribute('data-theme');
        if (theme === 'light' || theme === 'dark') return theme;
        if (DARK_FIRST[root.getAttribute('data-look')]) return 'dark';
        return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    function paintTone() { root.setAttribute('data-tone', effectiveTone()); }
    window.lraEffectiveTone = effectiveTone;

    var overrides = {};
    function paintAppearance() {
        var id = root.getAttribute('data-look');
        var eff = preset(id);
        for (var k in overrides) eff[k] = overrides[k];
        for (var key in eff) root.setAttribute('data-' + key, eff[key]);
        paintTone();
        return eff;
    }
    function applyUiAppearance(next) {
        overrides = cleanOverrides(next, root.getAttribute('data-look'));
        var text = cookieText(overrides);
        try { localStorage.setItem('uiAppearance', text); } catch (eStore) { /* ignore */ }
        writeCookie('ui_appearance', text);
        return {overrides: overrides, effective: paintAppearance()};
    }
    window.applyUiAppearance = applyUiAppearance;
    window.lraAppearancePreset = preset;

    // A look is a preset: choosing one starts its settings fresh. A preview
    // (the look prompt before Continue) keeps them, so Not now loses nothing.
    function applyUiLook(id, opts) {
        if (!LOOKS[id]) id = 'workshop';
        root.setAttribute('data-look', id);
        // A preview paints only: nothing is stored until the look is chosen.
        if (opts && opts.preview) {
            paintAppearance();
            return id;
        }
        try { localStorage.setItem('uiLook', id); } catch (eApply) { /* ignore */ }
        writeCookie('ui_look', id);
        applyUiAppearance({});
        return id;
    }
    window.applyUiLook = applyUiLook;

    if (!LOOKS[look]) look = 'workshop';
    root.setAttribute('data-look', look);
    var appearanceText = '';
    try {
        var appearanceCookie = document.cookie.match(/(?:^|;\s*)ui_appearance=([^;]*)/);
        // Another account's settings must not ride along on a shared computer:
        // storage only stands in when the look itself came from storage.
        if (appearanceCookie) appearanceText = decodeURIComponent(appearanceCookie[1]);
        else if (!lookFromCookie) appearanceText = localStorage.getItem('uiAppearance') || '';
    } catch (eAppearance) { appearanceText = ''; }
    overrides = cleanOverrides(parseCookieOverrides(appearanceText), look);
    paintAppearance();
    try {
        localStorage.setItem('uiLook', look);
        localStorage.setItem('uiAppearance', cookieText(overrides));
    } catch (eSync) { /* ignore */ }
    writeCookie('ui_look', look);
    writeCookie('ui_appearance', cookieText(overrides));
    if (window.matchMedia) {
        var media = window.matchMedia('(prefers-color-scheme: dark)');
        if (media.addEventListener) media.addEventListener('change', paintTone);
    }
    if (window.MutationObserver) {
        new MutationObserver(paintTone).observe(root, {attributes: true, attributeFilter: ['data-theme', 'data-look']});
    }
    root.classList.add('js-ready');
})();

// Theme toggle for every page that has #theme-toggle — including public
// landing / learn pages, which must not load common.js.
document.addEventListener('DOMContentLoaded', function () {
    var root = document.documentElement;
    var btn = document.getElementById('theme-toggle');
    if (!btn || btn.getAttribute('data-theme-bound') === '1') return;
    btn.setAttribute('data-theme-bound', '1');

    function getEffectiveTheme() {
        return window.lraEffectiveTone();
    }

    function updateButton(theme) {
        var label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
        btn.dataset.tip = label;
        btn.setAttribute('aria-label', label);
    }

    function applyTheme(next) {
        try {
            localStorage.setItem('theme', next);
        } catch (e2) { /* ignore */ }
        root.setAttribute('data-theme', next);
        updateButton(next);
    }

    function setWipeOrigin(el) {
        var r = el.getBoundingClientRect();
        var x = r.left + r.width / 2;
        var y = r.top + r.height / 2;
        var reach = Math.hypot(
            Math.max(x, window.innerWidth - x),
            Math.max(y, window.innerHeight - y)
        );
        root.style.setProperty('--tx', x + 'px');
        root.style.setProperty('--ty', y + 'px');
        root.style.setProperty('--tr', reach + 'px');
    }

    updateButton(getEffectiveTheme());
    if (window.MutationObserver) {
        new MutationObserver(function () { updateButton(getEffectiveTheme()); })
            .observe(root, {attributes: true, attributeFilter: ['data-tone']});
    }

    btn.addEventListener('click', function () {
        var next = getEffectiveTheme() === 'dark' ? 'light' : 'dark';
        var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (reduce) {
            applyTheme(next);
            return;
        }
        if (typeof document.startViewTransition === 'function') {
            setWipeOrigin(btn);
            document.startViewTransition(function () {
                applyTheme(next);
            });
            return;
        }
        root.classList.add('theme-animating');
        applyTheme(next);
        setTimeout(function () {
            root.classList.remove('theme-animating');
        }, 450);
    });
});
