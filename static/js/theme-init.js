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
                document.cookie = 'ui_mode_seed=; Max-Age=0; Path=/; SameSite=Lax';
            } else {
                mode = 'advanced';
            }
        }
        root.setAttribute('data-mode', mode);
        try {
            document.cookie = 'ui_mode=' + mode + '; Path=/; SameSite=Lax; Max-Age=31536000';
        } catch (e3) { /* ignore */ }
    } catch (e) {
        // localStorage can throw in private mode / with cookies blocked.
        // Falling back to the default theme/mode is fine; never break the page.
        root.setAttribute('data-mode', 'advanced');
    }
    root.classList.add('js-ready');
})();
