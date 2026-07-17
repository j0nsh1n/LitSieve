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
 if (!confirm(
  `Create a share code for "${lib.name}"?\n\n` +
  'Students who join get a full copy of papers and screening (not live access to yours). ' +
  'Code expires in 14 days by default.'
 )) {
  return;
 }
 const emb = confirm(
  'Include embeddings so students can search immediately without Prepare papers?\n\n' +
  'OK = yes (recommended). Cancel = papers only (no embeddings).'
 );
 setStatus('library-manage-status', 'Creating share code…', 'info');
 try {
  const data = await apiCall('/api/shares', {
   method: 'POST',
   body: {
    library_id: lib.id,
    expires_days: 14,
    include_embeddings: emb,
   },
  });
  const share = data.share || {};
  const code = share.code || '';
  const path = share.join_path || (`/join?code=${code}`);
  const msg = `Share code: ${code}\n\nLink path: ${path}\n\nCopy the code and share it with your class.`;
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
  const uses = s.max_uses != null
   ? `${s.use_count || 0}/${s.max_uses} uses`
   : `${s.use_count || 0} uses`;
  li.innerHTML = `
   <span class="library-manage-name"><code>${escapeHtml(s.code || '')}</code>
    · ${escapeHtml(s.title_snapshot || 'Library')}</span>
   ${badge}
   <span class="info-text" style="margin:0;">${escapeHtml(uses)}</span>
   <button type="button" class="btn btn-sm btn-secondary share-copy" ${revoked ? 'disabled' : ''}>Copy code</button>
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
