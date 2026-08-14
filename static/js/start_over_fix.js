// Start over option B: keep starred/noted papers via POST /api/start-over.
// Loaded after simple_tools.js so this definition wins.
async function simpleToolsStartOver() {
 if (typeof resolveSimpleFetchModeBeforeRequest !== 'function') {
  window.location.href = '/search?collect=1';
  return;
 }
 const proceed = await resolveSimpleFetchModeBeforeRequest();
 if (!proceed) return;
 const status = document.getElementById('simple-tools-status');
 const btn = document.getElementById('simple-tools-startover-btn');
 if (status) status.textContent = 'Keeping starred and noted papers…';
 if (btn) btn.disabled = true;
 try {
  const result = await apiCall('/api/start-over', { method: 'POST', body: {} });
  const kept = Number(result && result.remaining) || 0;
  const deleted = Number(result && result.deleted) || 0;
  _lastTotalArticles = kept;
  if (typeof updateNavStats === 'function') updateNavStats();
  await resetSearchAndNarrowingForStartOver();
  if (status) {
   status.textContent = deleted
    ? `Kept ${kept} annotated paper${kept === 1 ? '' : 's'}; removed ${deleted}.`
    : (kept ? `Kept ${kept} annotated paper${kept === 1 ? '' : 's'}.` : 'Collection cleared.');
  }
  showNotification(
   deleted
    ? `Start over: kept ${kept} starred/noted paper${kept === 1 ? '' : 's'}, removed ${deleted}.`
    : (kept ? `Start over: kept ${kept} annotated paper${kept === 1 ? '' : 's'}.` : 'Collection cleared for a new search.'),
   'success'
  );
  if (_onSearchPage()) {
   setCollectQueryOnUrl();
   if (typeof _simpleFetchUnlocked !== 'undefined') {
    _simpleFetchUnlocked = true;
    _simpleFetchModePicked = true;
   }
   if (typeof updateSimpleFetchLock === 'function') updateSimpleFetchLock();
   try {
    const stats = await apiCall('/api/statistics');
    _lastTotalArticles = Number(stats.total_articles) || kept;
    syncSimpleOnePageState(stats);
    if (typeof updateSimpleToolsStrip === 'function') updateSimpleToolsStrip(stats);
    if (typeof updatePrepareSectionVisibility === 'function') {
     updatePrepareSectionVisibility(_lastTotalArticles, {
      readyArticles: Number(stats.articles_with_embeddings) || 0,
     });
    }
   } catch (e) {
    syncSimpleOnePageState({
     total_articles: kept,
     articles_with_embeddings: 0,
    });
   }
   const q = document.getElementById('fetch-query');
   if (q) {
    q.focus();
    if (typeof q.select === 'function') q.select();
   }
   return;
  }
  window.location.href = '/search?collect=1';
 } catch (e) {
  if (status) status.textContent = '';
  showNotification(`Could not start over: ${e.message}`, 'error');
 } finally {
  if (btn) btn.disabled = false;
 }
}
