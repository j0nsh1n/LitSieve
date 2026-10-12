function collectionLibraryId() {
 if (typeof pageLibraryId !== 'function') return '';
 return String(pageLibraryId() || '');
}

function collectionLibraryBody(libraryId, body) {
 if (!libraryId || collectionLibraryId() !== libraryId) {
  throw new Error('The active library changed. Reopen this panel and try again.');
 }
 const scoped = typeof withPageLibrary === 'function'
  ? withPageLibrary({ ...body })
  : { ...body, library_id: libraryId };
 if (scoped.library_id !== libraryId) {
  throw new Error('The active library changed. Reopen this panel and try again.');
 }
 return scoped;
}

function collectionLibraryUrl(path, libraryId, extra) {
 const params = new URLSearchParams({ library_id: libraryId, ...(extra || {}) });
 return `${path}?${params.toString()}`;
}

function collectionTopics() {
 if (typeof selectedTopics !== 'undefined' && selectedTopics instanceof Set) {
  return [...selectedTopics];
 }
 try {
  if (typeof localStorage !== 'undefined' && typeof FETCH_PREFS_KEY !== 'undefined') {
   const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null');
   return Array.isArray(prefs && prefs.topics) ? prefs.topics : [];
  }
 } catch (e) { /* no saved topic preferences */ }
 return [];
}

function appendText(parent, tag, className, value) {
 const element = document.createElement(tag);
 if (className) element.className = className;
 element.textContent = String(value == null ? '' : value);
 parent.appendChild(element);
 return element;
}

function clearElement(element) {
 if (typeof element.replaceChildren === 'function') element.replaceChildren();
 else element.textContent = '';
}

function collectionCountEntries(counts, kind) {
 return Object.entries(counts || {})
  .map(([key, value]) => ({ key: String(key), count: Math.max(0, Number(value) || 0) }))
  .filter((row) => row.count > 0)
  .sort((a, b) => {
   if (kind === 'year') {
    if (a.key === 'unknown') return b.key === 'unknown' ? 0 : 1;
    if (b.key === 'unknown') return -1;
    return Number(b.key) - Number(a.key);
   }
   return b.count - a.count || a.key.localeCompare(b.key);
  });
}

function renderCollectionCountBars(section, rows, kind) {
 if (!rows.length) return false;
 const list = document.createElement('ul');
 const seriesMax = Math.max(...rows.map((row) => row.count));
 rows.forEach(({ key, count }) => {
  const name = kind === 'year' && key === 'unknown' ? 'Year not listed' : key;
  const label = kind === 'source' && typeof getSourceName === 'function'
   ? getSourceName(key) : name;
  const item = document.createElement('li');
  appendText(item, 'span', '', label);
  const bar = document.createElement('progress');
  bar.max = seriesMax;
  bar.value = count;
  bar.setAttribute('aria-label', `Papers: ${label}`);
  item.appendChild(bar);
  appendText(item, 'span', 'help-text', String(count));
  list.appendChild(item);
 });
 section.appendChild(list);
 return true;
}

function renderCollectionReportData(host, stats, coverage) {
 clearElement(host);
 appendText(host, 'p', 'help-text',
  `${Number(stats && stats.total_articles) || 0} papers in this collection.`);

 const sourceSection = document.createElement('section');
 appendText(sourceSection, 'h3', '', 'Papers by source');
 const sources = collectionCountEntries(stats && stats.sources, 'source');
 if (!renderCollectionCountBars(sourceSection, sources, 'source')) {
  appendText(sourceSection, 'p', 'help-text', 'No source counts yet.');
 }
 host.appendChild(sourceSection);

 const yearSection = document.createElement('section');
 appendText(yearSection, 'h3', '', 'Papers by year');
 const years = collectionCountEntries(stats && stats.year_counts, 'year');
 if (!renderCollectionCountBars(yearSection, years, 'year')) {
  appendText(yearSection, 'p', 'help-text', 'No year counts yet.');
 }
 host.appendChild(yearSection);

 const coverageSection = document.createElement('section');
 appendText(coverageSection, 'h3', '', 'Recommended sources with no papers');
 const suggestions = (coverage && coverage.suggestions) || [];
 if (suggestions.length) {
  const list = document.createElement('ul');
  suggestions.forEach((suggestion) => {
   const name = suggestion.name || (typeof getSourceName === 'function'
    ? getSourceName(suggestion.source) : suggestion.source || 'Source');
   const tip = suggestion.tip || suggestion.reason || '';
   appendText(list, 'li', '', tip ? `${name}: ${tip}` : name);
  });
  coverageSection.appendChild(list);
 } else {
  appendText(coverageSection, 'p', 'help-text',
   collectionTopics().length
    ? 'No recommended empty sources for these topics.'
    : 'Choose topics when you fetch to get source recommendations.');
 }
 host.appendChild(coverageSection);
}

function currentLastFetchReport() {
 try {
  return typeof _lastFetchSourceReportText === 'string'
   ? _lastFetchSourceReportText.trim() : '';
 } catch (e) {
  return '';
 }
}

async function refreshCollectionReport(host, status, button) {
 const libraryId = collectionLibraryId();
 if (!libraryId) {
  if (status) status.textContent = 'Could not identify this collection. Reload Search and try again.';
  return;
 }
 if (button) button.disabled = true;
 if (status) status.textContent = 'Refreshing collection counts and coverage…';
 try {
  const [statsResult, coverageResult] = await Promise.allSettled([
   apiCall(collectionLibraryUrl('/api/statistics', libraryId)),
   apiCall('/api/coverage', {
    method: 'POST',
    body: collectionLibraryBody(libraryId, { topics: collectionTopics() }),
   }),
  ]);
  if (collectionLibraryId() !== libraryId) {
   throw new Error('The active library changed. Reopen this panel to refresh it.');
  }
  if (statsResult.status === 'rejected') throw statsResult.reason;
  renderCollectionReportData(host, statsResult.value, coverageResult.status === 'fulfilled'
   ? coverageResult.value : null);
  const lastFetch = currentLastFetchReport();
  if (lastFetch) {
   const section = document.createElement('section');
   appendText(section, 'h3', '', 'Last fetch');
   appendText(section, 'pre', 'simple-collection-last-fetch', lastFetch);
   host.appendChild(section);
  }
  if (coverageResult.status === 'rejected') {
   throw new Error(`Counts loaded, but coverage could not refresh: ${coverageResult.reason.message || 'request failed'}`);
  }
  if (status) status.textContent = '';
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not refresh this report. Try again.';
 } finally {
  if (button) button.disabled = false;
 }
}

function openCollectionReport() {
 if (typeof openSiteAlert !== 'function') return;
 return openSiteAlert({
  title: 'What we fetched',
  message: 'Counts cover every paper in this collection, including papers set aside.',
  onReady: (root) => {
   const card = root.querySelector('[data-site-modal-card]') || root;
   const host = document.createElement('div');
   host.id = 'simple-what-we-fetched';
   host.className = 'simple-collection-report';
   const lastFetch = currentLastFetchReport();
   if (lastFetch) {
    const section = document.createElement('section');
    appendText(section, 'h3', '', 'Last fetch');
    appendText(section, 'pre', 'simple-collection-last-fetch', lastFetch);
    host.appendChild(section);
   }
   const status = document.createElement('p');
   status.id = 'simple-collection-report-status';
   status.className = 'status-indicator';
   status.setAttribute('aria-live', 'polite');
   const refresh = document.createElement('button');
   refresh.id = 'simple-collection-report-refresh';
   refresh.type = 'button';
   refresh.className = 'btn btn-secondary btn-sm';
   refresh.textContent = 'Refresh coverage';
   refresh.addEventListener('click', () => {
    return refreshCollectionReport(host, status, refresh);
   });
   const actions = card.querySelector('.lra-modal-actions');
   if (actions && actions.parentNode) {
    actions.parentNode.insertBefore(host, actions);
    actions.parentNode.insertBefore(status, actions);
    actions.parentNode.insertBefore(refresh, actions);
   } else {
    card.appendChild(host);
    card.appendChild(status);
    card.appendChild(refresh);
   }
   refreshCollectionReport(host, status, refresh);
  },
 });
}

const COLLECTION_DUPLICATE_THRESHOLDS = Object.freeze({ strict: 0.99, normal: 0.98, loose: 0.95 });
let collectionDuplicatePreview = null;
let collectionDuplicateUndo = null;

function duplicateCopyLabel(count) {
 const amount = Number(count) || 0;
 return `${amount} duplicate cop${amount === 1 ? 'y' : 'ies'}`;
}

function collectionDuplicateStatus(message, isError) {
 const status = document.getElementById('simple-duplicate-status');
 if (!status) return;
 status.textContent = message || '';
 status.className = isError ? 'status-indicator is-error' : 'status-indicator';
}

function selectedDuplicateThreshold() {
 const checked = document.querySelector('input[name="simple-duplicate-threshold"]:checked');
 const value = checked ? Number(checked.value) : COLLECTION_DUPLICATE_THRESHOLDS.normal;
 return Object.values(COLLECTION_DUPLICATE_THRESHOLDS).includes(value)
  ? value : COLLECTION_DUPLICATE_THRESHOLDS.normal;
}

function renderDuplicateCandidates(candidates) {
 const host = document.getElementById('simple-duplicate-preview');
 const apply = document.getElementById('simple-duplicate-apply');
 if (!host) return;
 clearElement(host);
 candidates.forEach((candidate, index) => {
  const details = document.createElement('details');
  details.className = 'simple-duplicate-candidate';
  const summary = document.createElement('summary');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.checked = true;
  checkbox.value = String(index);
  checkbox.setAttribute('data-duplicate-candidate', '');
  summary.appendChild(checkbox);
  appendText(summary, 'span', '', `Set aside: ${candidate.title || candidate.article_id}`);
  details.appendChild(summary);
  appendText(details, 'p', 'help-text', [candidate.year, candidate.source]
   .filter(Boolean).join(' · '));
  appendText(details, 'p', '', candidate.abstract || 'No abstract is available.');
  const keeper = candidate.keeper || {};
  appendText(details, 'p', 'help-text', `Keep: ${keeper.title || keeper.article_id || 'the other copy'}`);
  host.appendChild(details);
 });
 host.hidden = candidates.length === 0;
 if (apply) apply.hidden = candidates.length === 0;
}

async function checkCollectionDuplicates() {
 const button = document.querySelector('[data-set-aside-check-duplicates]');
 const libraryId = collectionLibraryId();
 if (!libraryId) {
  collectionDuplicateStatus('Could not identify this collection. Reload Search and try again.', true);
  return;
 }
 if (button) button.disabled = true;
 const threshold = selectedDuplicateThreshold();
 collectionDuplicatePreview = null;
 renderDuplicateCandidates([]);
 collectionDuplicateStatus('Checking for duplicate copies…');
 try {
  const data = await apiCall('/api/resolve-duplicates', {
   method: 'POST',
   body: collectionLibraryBody(libraryId, { threshold, preview: true }),
  });
  if (collectionLibraryId() !== libraryId) {
   throw new Error('The active library changed. Reopen Set aside and try again.');
  }
  const candidates = Array.isArray(data && data.candidates) ? data.candidates : [];
  collectionDuplicatePreview = { libraryId, threshold, candidates };
  renderDuplicateCandidates(candidates);
  collectionDuplicateStatus(candidates.length
   ? `Review ${duplicateCopyLabel(candidates.length)} proposed. Nothing has been set aside yet.`
   : 'No duplicate copies found at this match strictness.');
 } catch (e) {
  collectionDuplicateStatus(e.message || 'Could not check for duplicates. Try again.', true);
 } finally {
  if (button) button.disabled = false;
 }
}

function selectedDuplicateCandidates() {
 const preview = collectionDuplicatePreview;
 if (!preview) return [];
 const checked = new Set(Array.from(
  document.querySelectorAll('[data-duplicate-candidate]:checked')
 ).map((el) => Number(el.value)));
 const seen = new Set();
 return preview.candidates.filter((_candidate, index) => checked.has(index)).map((candidate) => ({
  article_id: String(candidate.article_id),
  source: String(candidate.source),
 })).filter((item) => {
  const key = JSON.stringify([item.article_id, item.source]);
  if (seen.has(key)) return false;
  seen.add(key);
  return true;
 });
}

function collectionKeys(items) {
 return new Set((items || []).map((item) => JSON.stringify([
  String(item.article_id), String(item.source),
 ])));
}

async function applyCollectionDuplicatePreview() {
 const preview = collectionDuplicatePreview;
 const apply = document.getElementById('simple-duplicate-apply');
 const chosen = selectedDuplicateCandidates();
 if (!preview || !chosen.length) {
  collectionDuplicateStatus('Choose at least one proposed copy to set aside.');
  return;
 }
 if (collectionLibraryId() !== preview.libraryId) {
  collectionDuplicateStatus('The active library changed. Reopen Set aside and check again.', true);
  return;
 }
 const confirm = typeof openSiteConfirm === 'function'
  ? await openSiteConfirm({
   title: 'Set aside duplicate copies?',
   message: `Set aside ${chosen.length} selected duplicate ${chosen.length === 1 ? 'copy' : 'copies'}? You can undo this once.`,
   confirmLabel: 'Set aside',
  })
  : (typeof window !== 'undefined' && window.confirm
   ? window.confirm(`Set aside ${chosen.length} selected duplicate copies?`) : false);
 if (!confirm) return;

 if (apply) apply.disabled = true;
 collectionDuplicateStatus('Applying your choices…');
 try {
  const excluded = await apiCall(collectionLibraryUrl(
   '/api/screening/excluded', preview.libraryId, { reason: 'all' },
  ));
  if (collectionLibraryId() !== preview.libraryId) {
   throw new Error('The active library changed. Reopen Set aside and try again.');
  }
  const alreadyExcluded = collectionKeys(excluded && excluded.items);
  const items = chosen.filter((item) => !alreadyExcluded.has(
   JSON.stringify([item.article_id, item.source]),
  ));
  if (!items.length) {
   collectionDuplicateStatus('Those papers were already set aside, so their reasons were left unchanged.');
   return;
  }
  const result = await apiCall('/api/screening', {
   method: 'POST',
   body: collectionLibraryBody(preview.libraryId, {
    items, action: 'exclude', reason: 'duplicate',
   }),
  });
  collectionDuplicateUndo = { libraryId: preview.libraryId, items };
  const undo = document.getElementById('simple-duplicate-undo');
  if (undo) undo.hidden = false;
  collectionDuplicateStatus(`Set aside ${duplicateCopyLabel(Number(result && result.count) || items.length)}. You can undo this once.`);
  if (typeof loadSimpleSetAsideList === 'function') await loadSimpleSetAsideList();
  if (typeof refreshSimpleScreeningCard === 'function') await refreshSimpleScreeningCard();
 } catch (e) {
  collectionDuplicateStatus(e.message || 'Could not set aside those copies. Try again.', true);
 } finally {
  if (apply) apply.disabled = false;
 }
}

async function undoCollectionDuplicateApply() {
 const undo = document.getElementById('simple-duplicate-undo');
 const last = collectionDuplicateUndo;
 if (!last || !last.items.length) return;
 if (collectionLibraryId() !== last.libraryId) {
  collectionDuplicateStatus('Switch back to the collection where you set these aside before undoing.', true);
  return;
 }
 if (undo) undo.disabled = true;
 collectionDuplicateStatus('Undoing your last duplicate check…');
 try {
  const excluded = await apiCall(collectionLibraryUrl(
   '/api/screening/excluded', last.libraryId, { reason: 'duplicate' },
  ));
  if (collectionLibraryId() !== last.libraryId) {
   throw new Error('The active library changed. Reopen Set aside and try again.');
  }
  const stillDuplicate = collectionKeys(excluded && excluded.items);
  const items = last.items.filter((item) => stillDuplicate.has(
   JSON.stringify([item.article_id, item.source]),
  ));
  if (!items.length) {
   collectionDuplicateUndo = null;
   if (undo) undo.hidden = true;
   collectionDuplicateStatus('Nothing from that check is still set aside as a duplicate.');
   return;
  }
  const result = await apiCall('/api/screening', {
   method: 'POST',
   body: collectionLibraryBody(last.libraryId, { items, action: 'include' }),
  });
  collectionDuplicateUndo = null;
  if (undo) undo.hidden = true;
  collectionDuplicateStatus(`Restored ${duplicateCopyLabel(Number(result && result.count) || items.length)}.`);
  if (typeof loadSimpleSetAsideList === 'function') await loadSimpleSetAsideList();
  if (typeof refreshSimpleScreeningCard === 'function') await refreshSimpleScreeningCard();
 } catch (e) {
  collectionDuplicateStatus(e.message || 'Could not undo those copies. Try again.', true);
 } finally {
  if (undo) undo.disabled = false;
 }
}

function bindCollectionDuplicateTools() {
 const check = document.querySelector('[data-set-aside-check-duplicates]');
 const apply = document.getElementById('simple-duplicate-apply');
 const undo = document.getElementById('simple-duplicate-undo');
 if (check && check.dataset.wired !== '1') {
  check.dataset.wired = '1';
  check.addEventListener('click', checkCollectionDuplicates);
 }
 if (apply && apply.dataset.wired !== '1') {
  apply.dataset.wired = '1';
  apply.addEventListener('click', applyCollectionDuplicatePreview);
 }
 if (undo && undo.dataset.wired !== '1') {
  undo.dataset.wired = '1';
  undo.addEventListener('click', undoCollectionDuplicateApply);
 }
}

if (typeof document !== 'undefined') {
 if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bindCollectionDuplicateTools, { once: true });
 } else {
  bindCollectionDuplicateTools();
 }
}
