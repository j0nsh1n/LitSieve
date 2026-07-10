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
});

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
