// === Account page logic ===

document.addEventListener('DOMContentLoaded', () => {
 const confirmCb = document.getElementById('delete-confirm');
 const btn = document.getElementById('delete-account-btn');

 // The delete button stays disabled until the user ticks the acknowledgement.
 confirmCb.addEventListener('change', () => { btn.disabled = !confirmCb.checked; });

 // Show/hide the password field.
 document.getElementById('show-delete-pw').addEventListener('change', function () {
 const el = document.getElementById('delete-password');
 el.type = this.checked ? 'text' : 'password';
 });

 btn.addEventListener('click', doDeleteAccount);

 const changeBtn = document.getElementById('change-password-btn');
 if (changeBtn) {
 changeBtn.addEventListener('click', doChangePassword);
 }
 const showChange = document.getElementById('show-change-pw');
 if (showChange) {
 showChange.addEventListener('change', function () {
 ['pw-current', 'pw-new', 'pw-confirm'].forEach(id => {
 const el = document.getElementById(id);
 if (el) el.type = this.checked ? 'text' : 'password';
 });
 });
 }

 loadLibraryManager();
 loadSharesList();
 const createBtn = document.getElementById('library-create-btn');
 if (createBtn) createBtn.addEventListener('click', doCreateLibrary);
 const nameInput = document.getElementById('library-new-name');
 if (nameInput) {
 nameInput.addEventListener('keydown', (e) => {
 if (e.key === 'Enter') {
 e.preventDefault();
 doCreateLibrary();
 }
 });
 }

 const joinPreviewBtn = document.getElementById('account-join-preview-btn');
 const joinBtn = document.getElementById('account-join-btn');
 const joinInput = document.getElementById('account-join-code');
 if (joinPreviewBtn) joinPreviewBtn.addEventListener('click', doAccountJoinPreview);
 if (joinBtn) joinBtn.addEventListener('click', doAccountJoin);

 // Optional AI study aid: Built-in (auto start/stop) vs Cloud API key.
 // Classroom deployers can hide this card with HIDE_AI_BUTTONS=true.
 const aiSection = document.getElementById('ai-settings-section');
 if (aiSection) {
 const wireAi = () => {
 if (typeof uiFlag === 'function' && !uiFlag('show_ai_buttons', true)) {
 aiSection.hidden = true;
 return;
 }
 aiSection.hidden = false;
 loadAiSettings();
 const modeSel = document.getElementById('ai-study-mode');
 if (modeSel) modeSel.addEventListener('change', syncAiModePanels);
 const refreshBtn = document.getElementById('ai-status-refresh');
 const saveBtn = document.getElementById('ai-settings-save');
 if (refreshBtn) refreshBtn.addEventListener('click', loadAiSettings);
 if (saveBtn) saveBtn.addEventListener('click', saveAiSettings);
 };
 if (window.LRA_UI && window.LRA_UI._loaded) {
 wireAi();
 } else if (typeof loadUiFlags === 'function') {
 loadUiFlags().finally(wireAi);
 } else {
 wireAi();
 }
 }
 if (joinInput) {
 joinInput.addEventListener('keydown', (e) => {
 if (e.key === 'Enter') {
 e.preventDefault();
 doAccountJoinPreview();
 }
 });
 }
});

async function loadLibraryManager() {
 const list = document.getElementById('library-manage-list');
 if (!list) return;
 try {
 const data = await apiCall('/api/libraries');
 renderLibraryManager(data);
 } catch (e) {
 list.innerHTML = `<li class="info-text">Could not load libraries: ${escapeHtml(e.message)}</li>`;
 }
}

function renderLibraryManager(data) {
 const list = document.getElementById('library-manage-list');
 if (!list) return;
 const libs = data.libraries || [];
 const active = data.active_id;
 list.innerHTML = '';
 if (!libs.length) {
 list.innerHTML = '<li class="info-text">No libraries yet.</li>';
 return;
 }
 libs.forEach(L => {
 const li = document.createElement('li');
 const isActive = L.id === active;
 li.innerHTML = `
 <span class="library-manage-name">${escapeHtml(L.name || 'Library')}</span>
 ${isActive ? '<span class="library-manage-badge">Active</span>' : ''}
 <button type="button" class="btn btn-sm btn-secondary lib-rename">Rename</button>
 <button type="button" class="btn btn-sm btn-secondary lib-switch" ${isActive ? 'disabled' : ''}>Switch to</button>
 <button type="button" class="btn btn-sm btn-primary lib-share">Share</button>
 <button type="button" class="btn btn-sm btn-danger lib-delete" ${libs.length <= 1 ? 'disabled' : ''}>Delete</button>
 `;
 li.querySelector('.lib-rename').addEventListener('click', () => doRenameLibrary(L));
 li.querySelector('.lib-switch').addEventListener('click', () => doSwitchLibrary(L.id));
 li.querySelector('.lib-share').addEventListener('click', () => doShareLibrary(L));
 li.querySelector('.lib-delete').addEventListener('click', () => doDeleteLibrary(L, libs.length));
 list.appendChild(li);
 });
}

function normalizeJoinCode(raw) {
 let c = (raw || '').trim().toUpperCase().replace(/\s+/g, '');
 if (c.length === 8 && c.indexOf('-') < 0) {
  c = c.slice(0, 4) + '-' + c.slice(4);
 }
 return c;
}

async function doShareLibrary(lib) {
 // R6: class share wording + optional expiry / max uses.
 if (!confirm(
  `Create a class share code for "${lib.name}"?\n\n` +
  'CLASS SHARE (clone, not live view):\n' +
  '• Students join with the code and get their own copy of papers + screening.\n' +
  '• Suggested student steps after join: Clusters → Duplicates → Search (export RIS).\n' +
  '• Notes/stars are NOT copied (private to each student).\n\n' +
  'Continue to set expiry and options?'
 )) {
  return;
 }
 let expiresDays = 14;
 const daysRaw = window.prompt('Days until the code expires (1–90). Blank = 14.', '14');
 if (daysRaw === null) return;
 if (String(daysRaw).trim() !== '') {
  const n = parseInt(daysRaw, 10);
  if (!Number.isFinite(n) || n < 1 || n > 90) {
   showNotification('Expiry must be between 1 and 90 days.', 'error');
   return;
  }
  expiresDays = n;
 }
 let maxUses = null;
 const usesRaw = window.prompt(
  'Max student joins for this code (e.g. class size). Blank = unlimited.',
  ''
 );
 if (usesRaw === null) return;
 if (String(usesRaw).trim() !== '') {
  const n = parseInt(usesRaw, 10);
  if (!Number.isFinite(n) || n < 1 || n > 500) {
   showNotification('Max uses must be between 1 and 500, or blank for unlimited.', 'error');
   return;
  }
  maxUses = n;
 }
 const emb = confirm(
  'Include embeddings so students can search immediately without Prepare papers?\n\n' +
  'OK = yes (recommended). Cancel = papers only (no embeddings).'
 );
 setStatus('library-manage-status', 'Creating share code…', 'info');
 try {
  const body = {
   library_id: lib.id,
   expires_days: expiresDays,
   include_embeddings: emb,
  };
  if (maxUses != null) body.max_uses = maxUses;
  const data = await apiCall('/api/shares', {
   method: 'POST',
   body,
  });
  const share = data.share || {};
  const code = share.code || '';
  const path = share.join_path || (`/join?code=${code}`);
  const expLabel = share.expires_at
   ? `Expires: ${String(share.expires_at).slice(0, 10)}`
   : `Expires in ~${expiresDays} days`;
  const useLabel = maxUses != null ? `Max joins: ${maxUses}` : 'Max joins: unlimited';
  const msg = [
   'CLASS SHARE CODE',
   '',
   `Code: ${code}`,
   `Link: ${path}`,
   expLabel,
   useLabel,
   '',
   'Tell students:',
   '1) Open Join (or /join) and enter the code while logged in.',
   '2) Switch to the new library in the nav Library menu.',
   '3) Clusters → Duplicates → Search; export RIS; optional screening report on Duplicates.',
   '',
   'Starting point only (public databases) — finish important work with the school library.',
  ].join('\n');
  if (navigator.clipboard && code) {
   try { await navigator.clipboard.writeText(code); } catch (_) { /* ignore */ }
  }
  alert(msg);
  setStatus('library-manage-status', `Share code ${code} created (copied if clipboard allowed).`, 'success');
  showNotification(`Share code ${code}`, 'success');
  loadSharesList();
 } catch (e) {
  setStatus('library-manage-status', e.message, 'error');
  showNotification(e.message, 'error');
 }
}

async function loadSharesList() {
 const list = document.getElementById('shares-list');
 if (!list) return;
 try {
  const data = await apiCall('/api/shares');
  renderSharesList(data.shares || []);
 } catch (e) {
  list.innerHTML = `<li class="info-text">Could not load shares: ${escapeHtml(e.message)}</li>`;
 }
}

function renderSharesList(shares) {
 const list = document.getElementById('shares-list');
 if (!list) return;
 list.innerHTML = '';
 if (!shares.length) {
  list.innerHTML = '<li class="info-text">No share codes yet. Click Share on a library above.</li>';
  return;
 }
 shares.forEach(s => {
  const li = document.createElement('li');
  const revoked = !!s.revoked_at;
  const active = !!s.active && !revoked;
  const badge = revoked
   ? '<span class="library-manage-badge" style="color:var(--danger,#c44);">Revoked</span>'
   : (active
    ? '<span class="library-manage-badge">Active</span>'
    : '<span class="library-manage-badge">Expired / full</span>');
  const useCount = s.use_count != null ? Number(s.use_count) : 0;
  const uses = s.max_uses != null
   ? `${useCount} / ${s.max_uses} joins used`
   : `${useCount} join${useCount === 1 ? '' : 's'} (no max)`;
  const exp = s.expires_at
   ? `Expires ${escapeHtml(String(s.expires_at).slice(0, 10))}`
   : 'No expiry date';
  li.innerHTML = `
   <span class="library-manage-name"><code>${escapeHtml(s.code || '')}</code>
    · ${escapeHtml(s.title_snapshot || 'Library')}</span>
   ${badge}
   <span class="info-text share-usage-line" style="margin:0;">${escapeHtml(uses)} · ${exp}</span>
   <button type="button" class="btn btn-sm btn-secondary share-copy" ${revoked ? 'disabled' : ''}>Copy code</button>
   <button type="button" class="btn btn-sm btn-secondary share-copy-brief" ${revoked ? 'disabled' : ''}>Copy student brief</button>
   <button type="button" class="btn btn-sm btn-danger share-revoke" ${revoked ? 'disabled' : ''}>Revoke</button>
  `;
  const copyBtn = li.querySelector('.share-copy');
  if (copyBtn) {
   copyBtn.addEventListener('click', async () => {
    try {
     if (navigator.clipboard) await navigator.clipboard.writeText(s.code || '');
     showNotification(`Copied ${s.code}`, 'success');
    } catch (_) {
     prompt('Copy this code:', s.code || '');
    }
   });
  }
  const briefBtn = li.querySelector('.share-copy-brief');
  if (briefBtn) {
   briefBtn.addEventListener('click', async () => {
    const brief = [
     `Class code: ${s.code || ''}`,
     `Library: ${s.title_snapshot || 'shared library'}`,
     '',
     'Steps:',
     '1. Log in → Join (or open /join) and enter the code.',
     '2. Switch to the new library in the nav Library menu.',
     '3. Clusters (screen) → Duplicates → Search; export RIS for Zotero.',
     '4. Optional: Duplicates → screening report for process counts.',
     '',
     'This is a starting point from public databases — finish with your school library when needed.',
    ].join('\n');
    try {
     if (navigator.clipboard) await navigator.clipboard.writeText(brief);
     showNotification('Student brief copied', 'success');
    } catch (_) {
     prompt('Copy this brief for students:', brief);
    }
   });
  }
  const revBtn = li.querySelector('.share-revoke');
  if (revBtn) {
   revBtn.addEventListener('click', () => doRevokeShare(s));
  }
  list.appendChild(li);
 });
}

async function doRevokeShare(share) {
 if (!confirm(`Revoke code ${share.code}? New students will not be able to join. Existing copies stay.`)) {
  return;
 }
 try {
  await apiCall(`/api/shares/${encodeURIComponent(share.id)}`, { method: 'DELETE' });
  showNotification('Share revoked.', 'success');
  loadSharesList();
 } catch (e) {
  showNotification(e.message, 'error');
 }
}

function renderAccountJoinPreview(data) {
 const card = document.getElementById('account-join-preview');
 if (!card) return;
 const emb = data.include_embeddings && data.has_embeddings
  ? 'Embeddings included (search ready)'
  : (data.include_embeddings ? 'No embeddings yet' : 'Embeddings not included');
 card.hidden = false;
 card.innerHTML = `
  <h3 class="join-preview-title">${escapeHtml(data.title || 'Shared library')}</h3>
  <p class="info-text" style="margin:0.35rem 0;">From <strong>${escapeHtml(data.owner_username || 'teacher')}</strong>
   · <code>${escapeHtml(data.code || '')}</code>
   · ${Number(data.article_count) || 0} papers · ${escapeHtml(emb)}</p>
 `;
}

async function doAccountJoinPreview() {
 const input = document.getElementById('account-join-code');
 const joinBtn = document.getElementById('account-join-btn');
 const code = normalizeJoinCode(input && input.value);
 if (input) input.value = code;
 if (!code) {
  setStatus('account-join-status', 'Enter a class code first.', 'error');
  return;
 }
 setStatus('account-join-status', 'Loading preview…', 'info');
 if (joinBtn) joinBtn.disabled = true;
 try {
  const data = await apiCall(`/api/shares/preview?code=${encodeURIComponent(code)}`);
  renderAccountJoinPreview(data);
  setStatus(
   'account-join-status',
   data.can_join ? 'Looks good — confirm to add a copy.' : (data.block_reason || 'Cannot join.'),
   data.can_join ? 'success' : 'error'
  );
  if (joinBtn) joinBtn.disabled = !data.can_join;
 } catch (e) {
  const card = document.getElementById('account-join-preview');
  if (card) { card.hidden = true; card.innerHTML = ''; }
  setStatus('account-join-status', e.message, 'error');
  if (joinBtn) joinBtn.disabled = true;
 }
}

async function doAccountJoin() {
 const input = document.getElementById('account-join-code');
 const btn = document.getElementById('account-join-btn');
 const code = normalizeJoinCode(input && input.value);
 if (!code) {
  setStatus('account-join-status', 'Enter a class code first.', 'error');
  return;
 }
 setLoading(btn, true);
 setStatus('account-join-status', 'Copying library into your account…', 'info');
 try {
  const data = await apiCall('/api/shares/join', { method: 'POST', body: { code } });
  const name = (data.library && data.library.name) || 'library';
  setStatus('account-join-status', `Added "${name}". Opening Data Management…`, 'success');
  showNotification(`Joined: ${name}`, 'success');
  window.location.href = '/data-management';
 } catch (e) {
  setStatus('account-join-status', e.message, 'error');
  showNotification(e.message, 'error');
  setLoading(btn, false);
 }
}

async function doCreateLibrary() {
 const input = document.getElementById('library-new-name');
 const name = (input && input.value || '').trim() || 'New library';
 const btn = document.getElementById('library-create-btn');
 setLoading(btn, true);
 setStatus('library-manage-status', 'Creating library…', 'info');
 try {
 await apiCall('/api/libraries', { method: 'POST', body: { name } });
 if (input) input.value = '';
 setStatus('library-manage-status', 'Library created and set as active.', 'success');
 showNotification('Library created.', 'success');
 if (typeof refreshLibrarySwitcher === 'function') await refreshLibrarySwitcher();
 // New library is active and empty; reload so Data Management reflects it.
 window.location.reload();
 } catch (e) {
 setStatus('library-manage-status', e.message, 'error');
 showNotification(e.message, 'error');
 setLoading(btn, false);
 }
}

async function doRenameLibrary(lib) {
 const name = prompt('Rename library:', lib.name || '');
 if (name == null) return;
 const trimmed = name.trim();
 if (!trimmed) {
 showNotification('Name cannot be empty.', 'error');
 return;
 }
 try {
 const data = await apiCall(`/api/libraries/${encodeURIComponent(lib.id)}`, {
 method: 'PATCH',
 body: { name: trimmed },
 });
 renderLibraryManager(data);
 if (typeof refreshLibrarySwitcher === 'function') await refreshLibrarySwitcher();
 showNotification('Library renamed.', 'success');
 } catch (e) {
 showNotification(e.message, 'error');
 }
}

async function doSwitchLibrary(id) {
 try {
 await apiCall('/api/libraries/switch', {
 method: 'POST',
 body: { library_id: id },
 });
 window.location.reload();
 } catch (e) {
 showNotification(e.message, 'error');
 }
}

async function doDeleteLibrary(lib, count) {
 if (count <= 1) {
 showNotification('You must keep at least one library.', 'error');
 return;
 }
 if (!confirm(`Delete library "${lib.name}" and all of its papers? This cannot be undone.`)) {
 return;
 }
 try {
 await apiCall(`/api/libraries/${encodeURIComponent(lib.id)}`, {
 method: 'DELETE',
 });
 if (typeof refreshLibrarySwitcher === 'function') await refreshLibrarySwitcher();
 // If we deleted the active library, server switched active; reload.
 window.location.reload();
 } catch (e) {
 showNotification(e.message, 'error');
 }
}

async function doChangePassword() {
 const current = document.getElementById('pw-current').value;
 const next = document.getElementById('pw-new').value;
 const confirm = document.getElementById('pw-confirm').value;
 if (!current || !next) {
 showNotification('Enter your current and new passwords.', 'error');
 return;
 }
 const btn = document.getElementById('change-password-btn');
 setLoading(btn, true);
 setStatus('change-password-status', 'Updating password…', 'info');
 try {
 await apiCall('/api/change-password', {
 method: 'POST',
 body: {
 current_password: current,
 new_password: next,
 new_password_confirm: confirm,
 },
 });
 setStatus('change-password-status', 'Password updated. Other sessions were signed out.', 'success');
 showNotification('Password updated.', 'success');
 document.getElementById('pw-current').value = '';
 document.getElementById('pw-new').value = '';
 document.getElementById('pw-confirm').value = '';
 } catch (e) {
 setStatus('change-password-status', `Error: ${e.message}`, 'error');
 showNotification(`Could not change password: ${e.message}`, 'error');
 } finally {
 setLoading(btn, false);
 }
}

async function doDeleteAccount() {
 const password = document.getElementById('delete-password').value;
 if (!password) {
 showNotification('Enter your password to confirm deletion.', 'error');
 return;
 }
 if (!confirm('Permanently delete your account and all of its data? This cannot be undone.')) {
 return;
 }

 const btn = document.getElementById('delete-account-btn');
 setLoading(btn, true);
 setStatus('delete-status', 'Deleting your account...', 'info');

 try {
 await apiCall('/api/delete-account', { method: 'POST', body: { password } });
 // Account gone + cookies cleared server-side; bounce to login.
 window.location.href = '/login';
 } catch (e) {
 setStatus('delete-status', `Error: ${e.message}`, 'error');
 showNotification(`Could not delete account: ${e.message}`, 'error');
 setLoading(btn, false);
 }
}

function syncAiModePanels() {
 const mode = (document.getElementById('ai-study-mode') || {}).value || 'built_in';
 const builtin = document.getElementById('ai-builtin-panel');
 const apikey = document.getElementById('ai-apikey-panel');
 if (builtin) builtin.hidden = mode !== 'built_in';
 if (apikey) apikey.hidden = mode !== 'api_key';
 const hiddenProv = document.getElementById('ai-llm-provider');
 if (hiddenProv) {
  hiddenProv.value = mode === 'api_key' ? 'openai' : 'ollama';
 }
}

function applyAiStatus(st) {
 const detail = document.getElementById('ai-status-detail');
 if (detail) {
  detail.textContent = st.detail || '—';
 }
}

function applyAiWriteGate(settings) {
 const allowed = !settings || settings.settings_write_allowed !== false;
 const saveBtn = document.getElementById('ai-settings-save');
 const note = document.getElementById('ai-settings-write-note');
 const modeSel = document.getElementById('ai-study-mode');
 if (saveBtn) {
  saveBtn.disabled = !allowed;
  saveBtn.title = allowed
   ? ''
   : 'Saving AI settings is disabled on this server (AI_ALLOW_SETTINGS_WRITE=false)';
 }
 if (note) note.hidden = allowed;
 if (modeSel) modeSel.disabled = !allowed;
 ['ai-openai-key', 'ai-openai-model', 'ai-openai-base',
  'ai-anthropic-key', 'ai-anthropic-model'].forEach((id) => {
  const el = document.getElementById(id);
  if (el) el.disabled = !allowed;
 });
}

function fillAiSettingsForm(settings, status) {
 if (!settings) return;
 const set = (id, val) => {
  const el = document.getElementById(id);
  if (el && val != null && val !== '') el.value = val;
 };
 const modeSel = document.getElementById('ai-study-mode');
 const mode = (status && status.study_aid_mode)
  || (settings.study_aid_mode)
  || ((settings.llm_provider === 'openai' || settings.llm_provider === 'anthropic')
   ? 'api_key' : 'built_in');
 if (modeSel) modeSel.value = mode === 'api_key' ? 'api_key' : 'built_in';
 // Do not touch ollama host/model/dir here — deployer env only (no UI fields).
 set('ai-openai-model', settings.openai_model || '');
 set('ai-openai-base', settings.openai_base_url || '');
 set('ai-anthropic-model', settings.llm_model || '');
 const oh = document.getElementById('ai-openai-key-hint');
 if (oh) {
  oh.textContent = settings.openai_api_key_set
   ? `Saved key: ${settings.openai_api_key_masked || '••••'}`
   : 'No OpenAI-compatible key saved yet.';
 }
 const ah = document.getElementById('ai-anthropic-key-hint');
 if (ah) {
  ah.textContent = settings.anthropic_api_key_set
   ? `Saved key: ${settings.anthropic_api_key_masked || '••••'}`
   : 'No Anthropic key saved yet.';
 }
 syncAiModePanels();
 applyAiWriteGate(settings);
}

async function loadAiSettings() {
 try {
  const data = await apiCall('/api/ai/settings');
  fillAiSettingsForm(data.settings || {}, data.status || {});
  applyAiStatus(data.status || {});
 } catch (e) {
  const detail = document.getElementById('ai-status-detail');
  if (detail) detail.textContent = `Could not load AI status: ${e.message}`;
 }
}

async function saveAiSettings() {
 const btn = document.getElementById('ai-settings-save');
 if (btn && btn.disabled) {
  showNotification('Saving AI settings is disabled on this server.', 'warning');
  return;
 }
 setLoading(btn, true);
 setStatus('ai-settings-status', 'Saving…', 'info');
 const mode = (document.getElementById('ai-study-mode') || {}).value || 'built_in';
 let llmProvider = 'ollama';
 if (mode === 'api_key') {
  // Prefer OpenAI-compatible when a key is typed or already saved; else Anthropic.
  const oaiTyped = ((document.getElementById('ai-openai-key') || {}).value || '').trim();
  const antTyped = ((document.getElementById('ai-anthropic-key') || {}).value || '').trim();
  const oh = document.getElementById('ai-openai-key-hint');
  const ah = document.getElementById('ai-anthropic-key-hint');
  const oaiSaved = oh && /Saved key/i.test(oh.textContent || '');
  const antSaved = ah && /Saved key/i.test(ah.textContent || '');
  if (antTyped || (antSaved && !oaiTyped && !oaiSaved)) {
   llmProvider = 'anthropic';
  } else {
   llmProvider = 'openai';
  }
 }
 // Only send fields the user can edit. Never wipe deployer ollama host/model/dir.
 const body = {
  llm_provider: llmProvider,
  openai_model: (document.getElementById('ai-openai-model') || {}).value || '',
  openai_base_url: (document.getElementById('ai-openai-base') || {}).value || '',
  llm_model: (document.getElementById('ai-anthropic-model') || {}).value || '',
 };
 const oai = (document.getElementById('ai-openai-key') || {}).value;
 const ant = (document.getElementById('ai-anthropic-key') || {}).value;
 if (oai) body.openai_api_key = oai;
 if (ant) body.anthropic_api_key = ant;
 try {
  const data = await apiCall('/api/ai/settings', { method: 'POST', body });
  setStatus('ai-settings-status', 'AI settings saved.', 'success');
  showNotification('AI settings saved.', 'success');
  fillAiSettingsForm(data.settings || {}, data.status_detail || {});
  if (data.status_detail) applyAiStatus(data.status_detail);
  if (document.getElementById('ai-openai-key')) document.getElementById('ai-openai-key').value = '';
  if (document.getElementById('ai-anthropic-key')) document.getElementById('ai-anthropic-key').value = '';
 } catch (e) {
  setStatus('ai-settings-status', `Error: ${e.message}`, 'error');
  showNotification(`Could not save AI settings: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}
