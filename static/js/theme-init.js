// Applies the saved theme / UI mode to <html> BEFORE first paint.
//
// Must stay a plain blocking <script src> in <head> — no defer, no async, no
// module. Deferring it means the browser paints the default theme first and a
// dark-mode user sees a white flash on every page load. Same for data-mode:
// without a pre-paint set, Simple-mode users flash Advanced layout.
//
// Lives in a file (not inline) so the CSP can be `script-src 'self'` with no
// 'unsafe-inline'. Auth/landing pages load only this; they must not load
// common.js, which calls authenticated APIs.
(function () {
    var root = document.documentElement;
    try {
        var saved = localStorage.getItem('theme');
        if (saved) root.setAttribute('data-theme', saved);

        // uiMode: "simple" | "advanced". Unset → advanced (existing accounts
        // keep today's full UI). New registrations set a one-shot cookie
        // ui_mode_seed=simple so first paint is Simple, then we persist.
        var mode = localStorage.getItem('uiMode');
        if (mode !== 'simple' && mode !== 'advanced') {
            mode = null;
            var seed = document.cookie.match(/(?:^|;\s*)ui_mode_seed=([^;]*)/);
            if (seed && decodeURIComponent(seed[1]) === 'simple') {
                mode = 'simple';
                try {
                    localStorage.setItem('uiMode', 'simple');
                } catch (e2) { /* ignore */ }
                // Clear the one-shot seed so later visits use localStorage only.
                document.cookie = 'ui_mode_seed=; Max-Age=0; Path=/; SameSite=Lax'
                    + (location.protocol === 'https:' ? '; Secure' : '');
            } else {
                mode = 'advanced';
            }
        }
        root.setAttribute('data-mode', mode);
        try {
            var secure = location.protocol === 'https:' ? '; Secure' : '';
            document.cookie = 'ui_mode=' + mode + '; Path=/; SameSite=Lax; Max-Age=31536000' + secure;
        } catch (e3) { /* ignore */ }
    } catch (e) {
        // localStorage can throw in private mode / with cookies blocked.
        // Falling back to the default theme/mode is fine; never break the page.
        root.setAttribute('data-mode', 'advanced');
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
        try {
            var saved = localStorage.getItem('theme');
            if (saved) return saved;
        } catch (e) { /* private mode */ }
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function updateButton(theme) {
        btn.textContent = theme === 'dark' ? '🌙' : '☀';
        btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
        btn.setAttribute('aria-label', btn.title);
    }

    updateButton(getEffectiveTheme());

    btn.addEventListener('click', function () {
        var next = getEffectiveTheme() === 'dark' ? 'light' : 'dark';
        var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (!reduce) {
            root.classList.add('theme-animating');
            setTimeout(function () {
                root.classList.remove('theme-animating');
            }, 180);
        }
        try {
            localStorage.setItem('theme', next);
        } catch (e2) { /* ignore */ }
        root.setAttribute('data-theme', next);
        updateButton(next);
    });
});
