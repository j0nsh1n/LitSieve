// Applies the saved theme / reading mode to <html> BEFORE first paint.
//
// Must stay a plain blocking <script src> in <head> — no defer, no async, no
// module. Deferring it means the browser paints the default theme first and a
// dark-mode user sees a white flash on every page load.
//
// Lives in a file (not inline) so the CSP can be `script-src 'self'` with no
// 'unsafe-inline'. Auth/landing pages load only this; they must not load
// common.js, which calls authenticated APIs.
(function () {
    var root = document.documentElement;
    try {
        var saved = localStorage.getItem('theme');
        if (saved) root.setAttribute('data-theme', saved);
        if (localStorage.getItem('readingMode') === 'on') {
            root.setAttribute('data-reading', 'on');
        }
    } catch (e) {
        // localStorage can throw in private mode / with cookies blocked.
        // Falling back to the default theme is fine; never break the page.
    }
    root.classList.add('js-ready');
})();
