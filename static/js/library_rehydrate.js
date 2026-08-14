// Rehydrate nav library select after long idle (visibility/focus).
function rehydrateActiveLibrary() {
    const sel = document.getElementById('nav-library-select');
    if (!sel || !document.querySelector('nav.navbar')) return;
    if (sel.value && sel.options && sel.options.length > 1) return;
    if (typeof refreshLibrarySwitcher === 'function') {
        refreshLibrarySwitcher().catch(() => { /* ignore */ });
    }
}

document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') rehydrateActiveLibrary();
});
window.addEventListener('focus', () => {
    rehydrateActiveLibrary();
});
