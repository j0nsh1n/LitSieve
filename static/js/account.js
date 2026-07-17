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
 <button type="button" class="btn btn-sm btn-danger lib-delete" ${libs.length <= 1 ? 'disabled' : ''}>Delete</button>
 `;
 li.querySelector('.lib-rename').addEventListener('click', () => doRenameLibrary(L));
 li.querySelector('.lib-switch').addEventListener('click', () => doSwitchLibrary(L.id));
 li.querySelector('.lib-delete').addEventListener('click', () => doDeleteLibrary(L, libs.length));
 list.appendChild(li);
 });
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
