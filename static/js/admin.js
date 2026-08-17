// Operator admin console. common.js provides apiCall / modals.

document.addEventListener('DOMContentLoaded', () => {
 loadOverview();
 const form = document.getElementById('helpdesk-search-form');
 if (form) {
  form.addEventListener('submit', (e) => {
   e.preventDefault();
   runSearch();
  });
 }
 document.querySelectorAll('[data-queue]').forEach((btn) => {
  btn.addEventListener('click', () => runQueue(btn.getAttribute('data-queue')));
 });
 bind('hd-unlock', () => act('unlock', false));
 bind('hd-revoke', () => act('revoke-sessions', true));
 bind('hd-verify', () => act('resend-verification', false));
 bind('hd-reset', () => act('send-reset', true));
 bind('hd-otl', () => act('send-login-link', true));
 bind('hd-mfa', () => act('reset-mfa', false));
 bind('hd-note', saveNote);
});

let _selected = null;

async function loadOverview() {
 const status = document.getElementById('admin-overview-status');
 try {
  const d = await apiCall('/api/admin/overview');
  const c = d.counts || {};
  const set = (id, v) => {
   const el = document.getElementById(id);
   if (el) el.textContent = String(v);
  };
  set('ov-accounts', c.accounts ?? '—');
  set('ov-guests', c.guests ?? '—');
  set('ov-locked', c.locked ?? '—');
  set('ov-unverified', c.unverified ?? '—');
  set('ov-smtp', d.smtp ? 'on' : 'off');
  set('ov-ai', d.ai ? 'on' : 'off');
  set('ov-quota', d.quota_mb ? `${d.quota_mb} MB` : 'off');
  if (status) {
   status.textContent = d.guest_auto_prepare
    ? 'Guest demo auto-prepares sample papers.'
    : 'Guest auto-prepare is off.';
  }
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not load host snapshot.';
 }
}

function bind(id, fn) {
 const el = document.getElementById(id);
 if (el) el.addEventListener('click', fn);
}

async function runSearch() {
 const q = (document.getElementById('helpdesk-q')?.value || '').trim();
 const status = document.getElementById('helpdesk-list-status');
 if (status) status.textContent = 'Searching…';
 try {
  const data = await apiCall('/api/admin/search?q=' + encodeURIComponent(q));
  renderResults(data.users || []);
  if (status) status.textContent = (data.users || []).length ? '' : 'No matches.';
  if ((data.users || []).length === 1) openStudent(data.users[0].id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Search failed';
 }
}

async function runQueue(kind) {
 const status = document.getElementById('helpdesk-list-status');
 if (status) status.textContent = 'Loading queue…';
 try {
  const data = await apiCall('/api/admin/queue?filter=' + encodeURIComponent(kind));
  renderResults(data.users || []);
  if (status) {
   status.textContent = (data.users || []).length
    ? `${data.users.length} in “${kind}”`
    : `No one in “${kind}”.`;
  }
 } catch (e) {
  if (status) status.textContent = e.message || 'Queue failed';
 }
}

function renderResults(users) {
 const list = document.getElementById('helpdesk-results');
 if (!list) return;
 if (!users.length) {
  list.innerHTML = '<li class="info-text">No accounts in this list.</li>';
  return;
 }
 list.innerHTML = users.map((u) => {
  const bits = [u.role, u.locked ? 'locked' : '', u.email_verified ? 'email ok' : (u.email ? 'unverified' : '')]
   .filter(Boolean).join(' · ');
  const active = _selected && _selected.id === u.id ? ' is-active' : '';
  return `<li><button type="button" class="btn btn-secondary btn-block admin-user-btn${active}" data-id="${escapeAttr(u.id)}">`
   + `<span class="library-manage-name">${escapeHtml(u.username)}</span>`
   + `<span class="help-text">${escapeHtml(bits)}</span></button></li>`;
 }).join('');
 list.querySelectorAll('[data-id]').forEach((btn) => {
  btn.addEventListener('click', () => openStudent(btn.getAttribute('data-id')));
 });
}

async function openStudent(id) {
 const status = document.getElementById('helpdesk-action-status');
 if (status) status.textContent = 'Loading…';
 try {
  const d = await apiCall('/api/admin/users/' + encodeURIComponent(id));
  _selected = d;
  renderDetail(d);
  if (status) status.textContent = '';
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not load student';
 }
}

function renderDetail(d) {
 const panel = document.getElementById('helpdesk-detail');
 if (panel) panel.hidden = false;
 const title = document.getElementById('helpdesk-title');
 if (title) title.textContent = d.username;
 const ident = document.getElementById('helpdesk-identity');
 if (ident) {
  ident.textContent = [
   d.display_name,
   d.email || 'no email',
   d.role,
   d.class_section ? `class ${d.class_section}` : 'no class/section',
   d.created_at ? `created ${d.created_at}` : '',
   `id ${d.id}`,
  ].filter(Boolean).join(' · ');
 }
 const access = document.getElementById('helpdesk-access');
 if (access) {
  const state = d.locked ? `locked until ${d.locked_until || '?'}` : 'active';
  access.innerHTML = pair('Access', state)
   + pair('Email', d.email_verified ? 'verified' : (d.email ? 'unverified' : 'none'))
   + pair('MFA', d.mfa === 'not_available' ? 'not used' : d.mfa)
   + pair('Password changed', d.password_changed_at || '—')
   + pair('Last login', d.last_login_at || '—')
   + pair('Last seen', d.last_seen_at || '—')
   + pair('Failed sign-ins', d.failed_logins || 0);
 }
 const act = document.getElementById('helpdesk-activity');
 if (act) {
  const rows = d.activity || [];
  act.innerHTML = rows.length
   ? rows.map((e) => `<li><span class="library-manage-name">${escapeHtml(e.kind)}</span>`
    + `<span class="help-text">${escapeHtml([e.created_at, e.ip, e.detail].filter(Boolean).join(' · '))}</span></li>`)
    .join('')
   : '<li class="info-text">No recent auth events.</li>';
 }
 const err = document.getElementById('helpdesk-last-error');
 if (err) err.textContent = d.last_error ? `Last error: ${d.last_error}` : '';
 const res = document.getElementById('helpdesk-resources');
 if (res) {
  const q = d.quota || {};
  const st = d.statistics || {};
  const jobs = d.jobs || {};
  const jobBits = ['fetch', 'embed'].map((k) => {
   const j = jobs[k] || {};
   if (j.active) return `${k} running`;
   if (j.error) return `${k} error`;
   return `${k} idle`;
  });
  res.textContent = `${q.used_mb || 0} MB`
   + (q.limit_mb ? ` of ${q.limit_mb} MB` : '')
   + (q.over_limit ? ' — over cap' : '')
   + ` · ${st.total_articles || 0} papers, ${st.articles_with_embeddings || 0} prepared`
   + ` · ${jobBits.join(', ')}`;
 }
 const notes = document.getElementById('helpdesk-notes');
 if (notes) {
  notes.innerHTML = (d.support_notes || []).length
   ? d.support_notes.map((n) => `<li><span class="library-manage-name">${escapeHtml(n.admin_username)}</span>`
    + `<span class="help-text">${escapeHtml(n.created_at)}</span>`
    + `<p class="info-text">${escapeHtml(n.body)}</p></li>`).join('')
   : '<li class="info-text">No notes yet.</li>';
 }
 const tl = document.getElementById('helpdesk-timeline');
 if (tl) {
  tl.innerHTML = (d.timeline || []).length
   ? d.timeline.map((a) => `<li><span class="library-manage-name">${escapeHtml(a.action)}</span>`
    + `<span class="help-text">${escapeHtml([a.created_at, a.admin_username, a.reason].filter(Boolean).join(' · '))}</span></li>`)
    .join('')
   : '<li class="info-text">No admin actions yet.</li>';
 }
 const pack = document.getElementById('hd-packet');
 if (pack) pack.href = '/api/admin/users/' + encodeURIComponent(d.id) + '/packet';
}

function pair(label, value) {
 return `<div><dt>${escapeHtml(String(label))}</dt><dd>${escapeHtml(String(value == null ? '—' : value))}</dd></div>`;
}

async function promptAction(title, message, { confirmName, extra } = {}) {
 const fields = [
  { id: 'reason', label: 'Reason', type: 'text', value: '', placeholder: 'Why are you doing this?' },
 ];
 if (confirmName) {
  fields.push({
   id: 'confirm',
   label: `Type ${confirmName} to confirm`,
   type: 'text',
   value: '',
   placeholder: confirmName,
  });
 }
 if (typeof openSiteForm !== 'function') {
  const reason = window.prompt(message || title);
  if (!reason) return null;
  const body = { reason, ...(extra || {}) };
  if (confirmName) body.confirm = confirmName;
  return body;
 }
 const vals = await openSiteForm({
  title,
  message,
  confirmLabel: 'Continue',
  fields,
  validate: (v) => {
   if (!String(v.reason || '').trim() || String(v.reason).trim().length < 3) {
    return 'Enter a short reason (at least 3 characters).';
   }
   if (confirmName && String(v.confirm || '').trim() !== confirmName) {
    return `Type ${confirmName} exactly to confirm.`;
   }
   return null;
  },
 });
 if (!vals) return null;
 return { reason: vals.reason, confirm: vals.confirm, ...(extra || {}) };
}

async function act(name, destructive) {
 if (!_selected) return;
 const status = document.getElementById('helpdesk-action-status');
 const extra = {};
 if (name === 'cancel-job') extra.task = 'fetch';
 const body = await promptAction(
  name.replace(/-/g, ' '),
  destructive
   ? 'This changes the student’s access. Type their username and a reason.'
   : 'Add a short reason for the timeline.',
  { confirmName: destructive ? _selected.username : null, extra },
 );
 if (!body) return;
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(
   `/api/admin/users/${encodeURIComponent(_selected.id)}/${name}`,
   { method: 'POST', body },
  );
  if (status) {
   status.textContent = data.emailed_to
    ? `Emailed ${data.emailed_to}`
    : (data.detail || data.status || 'Done');
  }
  showNotification(status ? status.textContent : 'Done', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}

async function saveNote() {
 if (!_selected) return;
 const field = document.getElementById('helpdesk-note');
 const body = (field && field.value) || '';
 const status = document.getElementById('helpdesk-action-status');
 try {
  await apiCall(`/api/admin/users/${encodeURIComponent(_selected.id)}/note`, {
   method: 'POST',
   body: { body },
  });
  if (field) field.value = '';
  if (status) status.textContent = 'Note saved.';
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not save note';
 }
}
