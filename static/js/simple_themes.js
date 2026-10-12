// Human-reviewed theme grouping for Simple Search. This file is loaded by the
// Search page integration; it intentionally has no effect until invoked.
var _simpleThemeUndoState = {libraryId: '', items: []};
var _simpleThemeLaunchBusy = false;

function _themeEl(tag, text, className) {
 const node = document.createElement(tag);
 if (text != null) node.textContent = String(text);
 if (className) node.className = className;
 return node;
}

function _themeKey(article) {
 return JSON.stringify([String(article.article_id || ''), String(article.source || '')]);
}

function _themeLibraryStillCurrent(libraryId) {
 const now = typeof pageLibraryId === 'function' ? pageLibraryId() : '';
 return !!libraryId && now === libraryId;
}

function _themeApiUrl(path, libraryId) {
 return path + (path.includes('?') ? '&' : '?') + 'library_id=' + encodeURIComponent(libraryId);
}

function _themeEnsurePanel() {
 let panel = document.getElementById('simple-theme-tools');
 if (panel) return panel;
 panel = _themeEl('dialog', null, 'card simple-theme-tools');
 panel.id = 'simple-theme-tools';
 panel.setAttribute('aria-labelledby', 'simple-theme-tools-heading');
 const heading = _themeEl('h2', 'Group papers by theme'); heading.id = 'simple-theme-tools-heading';
 panel.append(heading);
 panel.append(_themeEl('p', 'Explore groups suggested by your papers. Nothing is set aside until you choose papers and confirm.', 'info-text'));
 const browser = _themeEl('div'); browser.id = 'simple-theme-browser'; browser.setAttribute('aria-live', 'polite');
 const status = _themeEl('p', null, 'info-text'); status.id = 'simple-theme-status'; status.setAttribute('role', 'status');
 const undo = _themeEl('button', 'Undo setting aside', 'btn btn-secondary'); undo.id = 'simple-theme-undo'; undo.type = 'button'; undo.hidden = true;
 const close = _themeEl('button', 'Close themes', 'btn btn-secondary'); close.type = 'button';
 close.addEventListener('click', () => panel.close());
 panel.append(browser, status, undo, close);
 document.body.append(panel);
 return panel;
}

function _themeSetStatus(message, isError) {
 const panel = _themeEnsurePanel();
 const status = document.getElementById('simple-theme-status');
 if (!status) return;
 status.textContent = message;
 status.classList.toggle('is-error', !!isError);
 if (isError && !panel.open && typeof showNotification === 'function') showNotification(message, 'error');
}

function _themeRenderBrowser(clusters, libraryId) {
 const host = document.getElementById('simple-theme-browser');
 if (!host) return;
 host.replaceChildren();
 const undoButton = document.getElementById('simple-theme-undo');
 const undo = async () => {
  if (!_simpleThemeUndoState.items.length) return;
  if (undoButton) undoButton.disabled = true;
  if (!_themeLibraryStillCurrent(_simpleThemeUndoState.libraryId)) {
   _themeSetStatus('Your selected library changed. Reload Search before undoing.', true);
   if (undoButton) undoButton.disabled = false;
   return;
  }
  const items = _simpleThemeUndoState.items.slice();
  try {
    const current = await apiCall(_themeApiUrl('/api/screening/excluded?reason=cluster', _simpleThemeUndoState.libraryId));
    const stillClusterExcluded = new Set((current.items || []).map(_themeKey));
    const restoreItems = items.filter((item) => stillClusterExcluded.has(_themeKey(item)));
    if (!restoreItems.length) {
     _simpleThemeUndoState = {libraryId: '', items: []};
     undoButton.hidden = true;
     _themeSetStatus('Those papers no longer have the cluster set-aside reason. Nothing was restored.');
     return;
    }
    await apiCall('/api/screening', {
    method: 'POST',
    body: {action: 'include', items: restoreItems, library_id: _simpleThemeUndoState.libraryId},
   });
   _simpleThemeUndoState = {libraryId: '', items: []};
   undoButton.hidden = true;
   _themeSetStatus('Those papers are back in Search.');
  } catch (error) {
   _themeSetStatus('Could not undo. Try again.', true);
  } finally {
   if (undoButton) undoButton.disabled = false;
  }
 };
 if (undoButton) {
  undoButton.hidden = !(_simpleThemeUndoState.libraryId === libraryId && _simpleThemeUndoState.items.length);
  undoButton.onclick = undo;
 }

 const rows = Array.isArray(clusters) ? clusters : [];
 if (!rows.length) {
  host.append(_themeEl('p', 'No themes were found. Try preparing more papers or choosing another grouping method.', 'info-text'));
 }
 rows.forEach((cluster) => {
  const section = _themeEl('section', null, 'simple-theme-row');
  const heading = _themeEl('h3', cluster.cluster_label || cluster.label || `Theme ${cluster.cluster_id + 1}`);
  const detail = _themeEl('details');
  const summary = _themeEl('summary', 'Read this theme');
  const content = _themeEl('div', null, 'simple-theme-content');
  const loadState = _themeEl('p', 'Open to load the papers in this theme.', 'help-text');
  const papers = _themeEl('div', null, 'simple-theme-papers');
  const preview = _themeEl('div', null, 'simple-theme-preview');
  preview.hidden = true;
  let loaded = false;
  let articles = [];

  const drawArticles = () => {
   papers.replaceChildren();
   articles.forEach((article) => {
    const paper = _themeEl('article', null, 'simple-theme-paper');
    const title = _themeEl('h4', article.title || 'Untitled paper');
    const meta = [article.year, article.journal, article.source].filter(Boolean).join(' · ');
    paper.append(title);
    if (meta) paper.append(_themeEl('p', meta, 'help-text'));
    if (article.abstract) paper.append(_themeEl('p', article.abstract));
    if (Array.isArray(article.key_points) && article.key_points.length) {
     const list = _themeEl('ul');
     article.key_points.forEach((point) => list.append(_themeEl('li', point)));
     paper.append(list);
    }
    papers.append(paper);
   });
  };

  detail.addEventListener('toggle', async () => {
   if (!detail.open || loaded) return;
   if (!_themeLibraryStillCurrent(libraryId)) {
    loadState.textContent = 'Your selected library changed. Reload Search to continue.';
    return;
   }
   loadState.textContent = 'Loading papers…';
   try {
    const data = await apiCall(_themeApiUrl(`/api/clusters/${encodeURIComponent(cluster.cluster_id)}/articles?include_abstract=true`, libraryId));
    if (!_themeLibraryStillCurrent(libraryId)) throw new Error('Library changed');
    articles = Array.isArray(data.articles) ? data.articles : [];
    loaded = true;
    loadState.textContent = `${articles.length} paper(s) in this theme. Papers already set aside are shown but cannot be selected.`;
    drawArticles();
   } catch (error) {
    loadState.textContent = 'Could not load this theme. Close and open it to retry.';
   }
  });

  const previewButton = _themeEl('button', 'Preview papers to set aside', 'btn btn-secondary');
  previewButton.type = 'button';
  previewButton.addEventListener('click', () => {
   if (!loaded) {
    detail.open = true;
    _themeSetStatus('Open the theme and wait for its papers to load first.');
    return;
   }
   preview.replaceChildren();
   preview.hidden = false;
   preview.append(_themeEl('p', 'Review the selected papers. Nothing changes until you confirm.'));
   const candidates = articles.filter((article) => !article.excluded);
   const selected = [];
   candidates.forEach((article) => {
    const label = _themeEl('label', null, 'radio-label simple-theme-select-row');
    const checkbox = _themeEl('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.value = _themeKey(article);
    label.append(checkbox, document.createTextNode(` ${article.title || 'Untitled paper'}`));
    if (article.abstract) label.append(_themeEl('span', article.abstract, 'help-text'));
    selected.push({checkbox, article});
    preview.append(label);
   });
   if (!candidates.length) preview.append(_themeEl('p', 'Every paper in this theme is already set aside.'));
   const actions = _themeEl('div', null, 'simple-theme-actions');
   const apply = _themeEl('button', 'Set selected papers aside', 'btn btn-primary');
   apply.type = 'button';
   apply.disabled = !candidates.length;
   apply.addEventListener('click', async () => {
    if (apply.disabled) return;
    apply.disabled = true;
    if (!_themeLibraryStillCurrent(libraryId)) {
     _themeSetStatus('Your selected library changed. Reload Search before applying.', true);
     apply.disabled = false;
     return;
    }
    let exclusions;
    try {
     exclusions = await apiCall(_themeApiUrl('/api/screening/excluded?reason=all', libraryId));
    } catch (error) {
     apply.disabled = false;
     _themeSetStatus('Could not refresh set-aside papers. Try again before applying.', true);
     return;
    }
    if (!_themeLibraryStillCurrent(libraryId)) {
     apply.disabled = false;
     _themeSetStatus('Your selected library changed. Reload Search before applying.', true);
     return;
    }
    const excludedKeys = new Set((exclusions.items || []).map(_themeKey));
    const items = selected.filter((entry) => entry.checkbox.checked && !excludedKeys.has(_themeKey(entry.article))).map((entry) => ({
     article_id: entry.article.article_id, source: entry.article.source,
    }));
    if (!items.length) {
     _themeSetStatus('Choose at least one paper to set aside.', true);
     apply.disabled = false;
     return;
    }
    try {
     await apiCall('/api/screening', {
      method: 'POST',
      body: {action: 'exclude', reason: 'cluster', items, library_id: libraryId},
     });
     if (_simpleThemeUndoState.libraryId !== libraryId) _simpleThemeUndoState = {libraryId, items: []};
     const known = new Set(_simpleThemeUndoState.items.map(_themeKey));
     items.forEach((item) => { if (!known.has(_themeKey(item))) _simpleThemeUndoState.items.push(item); });
     if (undoButton) undoButton.hidden = false;
     preview.hidden = true;
     _themeSetStatus(`${items.length} paper(s) set aside. You can undo this change.`);
    } catch (error) {
     apply.disabled = false;
     _themeSetStatus('Could not set those papers aside. Try again.', true);
    }
   });
   const cancel = _themeEl('button', 'Cancel', 'btn btn-secondary');
   cancel.type = 'button';
   cancel.addEventListener('click', () => { preview.hidden = true; });
   actions.append(apply, cancel);
   preview.append(actions);
  });
  content.append(loadState, papers, previewButton, preview);
  detail.append(summary, content);
  section.append(heading, _themeEl('p', `${Number(cluster.article_count) || 0} paper(s)`, 'help-text'), detail);
  host.append(section);
 });
}

async function launchSimpleThemeGrouping() {
 if (_simpleThemeLaunchBusy) return;
 _simpleThemeLaunchBusy = true;
 const retry = document.getElementById('simple-group-by-theme');
 if (retry) retry.disabled = true;
 let waitShown = false;
 try {
 if (typeof openSiteForm !== 'function' || typeof apiCall !== 'function') return;
 const libraryId = typeof pageLibraryId === 'function' ? pageLibraryId() : '';
 if (!libraryId) {
  _themeSetStatus('Could not identify the selected library. Reload Search and try again.', true);
  return;
 }
 const options = await openSiteForm({
  title: 'Group by theme',
  message: 'Grouping suggests themes for you to inspect. It does not set papers aside.',
  confirmLabel: 'Group papers',
  cancelLabel: 'Cancel',
  fields: [
   {id: 'method', label: 'Grouping method', type: 'choice', value: 'hdbscan', options: [
    {value: 'hdbscan', label: 'Density', hint: 'Find natural groups automatically'},
    {value: 'kmeans', label: 'K-Means'},
    {value: 'hierarchical', label: 'Hierarchical'},
   ]},
   {id: 'count_mode', label: 'Theme count', type: 'choice', value: 'auto', options: [
    {value: 'auto', label: 'Choose automatically'},
    {value: 'fixed', label: 'Choose a count'},
   ]},
   {id: 'n_clusters', label: 'Number of themes', type: 'number', value: 4, min: 2, max: 30, step: 1},
  ],
  onReady: (root) => {
   const methodInputs = root.querySelectorAll('input[name="site-modal-field-method"]');
   const countInputs = root.querySelectorAll('input[name="site-modal-field-count_mode"]');
   const methodField = root.querySelector('[data-field="method"]');
   const countField = root.querySelector('[data-field="count_mode"]');
   const numberField = root.querySelector('[data-field="n_clusters"]');
   const update = () => {
    const method = Array.from(methodInputs).find((input) => input.checked)?.value || 'hdbscan';
    const mode = Array.from(countInputs).find((input) => input.checked)?.value || 'auto';
    if (methodField) methodField.hidden = false;
    if (countField) countField.hidden = method === 'hdbscan';
    if (numberField) numberField.hidden = method === 'hdbscan' || mode !== 'fixed';
   };
   [...methodInputs, ...countInputs].forEach((input) => input.addEventListener('change', update));
   update();
  },
  validate: (values) => {
   if (!['hdbscan', 'kmeans', 'hierarchical'].includes(values.method)) return 'Choose a grouping method.';
   if (values.count_mode === 'fixed' && values.method !== 'hdbscan') {
    const count = Number(values.n_clusters);
    if (!Number.isInteger(count) || count < 2 || count > 30) return 'Choose a theme count from 2 to 30.';
   }
   return '';
  },
 });
 if (!options) return;
 _themeEnsurePanel();
 if (!_themeLibraryStillCurrent(libraryId)) {
  _themeSetStatus('Your selected library changed. Reload Search before grouping.', true);
  return;
 }
 const method = options.method;
 const nClusters = method !== 'hdbscan' && options.count_mode === 'fixed' ? Number(options.n_clusters) : null;
 const body = {method, n_clusters: nClusters, wait: false, library_id: libraryId};
 _themeSetStatus('Grouping papers…');
 if (typeof showSimpleBuffering === 'function') {
  showSimpleBuffering('prepare');
  waitShown = true;
 }
 const started = await apiCall('/api/create-clusters', {method: 'POST', body});
 if (!_themeLibraryStillCurrent(libraryId)) throw new Error('Library changed');
 let result = started;
 if (started && started.status === 'started') {
  if (typeof waitForJob !== 'function') throw new Error('Job progress is unavailable');
  result = await waitForJob('cluster', 'search-buffering-fill', 'search-buffering-label', 'search-buffering-progress', null, 600000,
   typeof simpleWaitMapOpts === 'function' ? simpleWaitMapOpts(0, 90) : undefined);
 }
 if (waitShown && typeof hideSimpleBuffering === 'function') {
  hideSimpleBuffering();
  waitShown = false;
 }
 if (!_themeLibraryStillCurrent(libraryId)) throw new Error('Library changed');
 if (!result || result.status !== 'success') throw new Error('Grouping did not complete');
 _themeRenderBrowser(result.clusters || [], libraryId);
 const dialog = document.getElementById('simple-theme-tools');
 if (dialog && !dialog.open) dialog.showModal();
 _themeSetStatus(`${(result.clusters || []).length} theme(s) ready to browse. No papers have been set aside.`);
 } catch (error) {
  if (waitShown && typeof hideSimpleBuffering === 'function') hideSimpleBuffering();
  _themeSetStatus('Grouping could not finish. Try again.', true);
  if (retry) retry.hidden = false;
 } finally {
  _simpleThemeLaunchBusy = false;
  if (retry) retry.disabled = false;
 }
}

document.addEventListener('DOMContentLoaded', () => {
 const button = document.getElementById('simple-group-by-theme');
 if (button) button.addEventListener('click', launchSimpleThemeGrouping);
});
