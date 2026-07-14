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
});

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
