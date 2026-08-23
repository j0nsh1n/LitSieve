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
 bind('hd-set-email', setEmail);
 bind('hd-verify', () => act('resend-verification', false));
 bind('hd-reset', () => act('send-reset', true));
 bind('hd-otl', () => act('send-login-link', true));
 bind('hd-mfa', () => act('reset-mfa', false));
 bind('hd-retry-embed', retryEmbed);
 bind('hd-retry-fetch', retryFetch);
 bind('hd-view', startStudentView);
 bind('hd-disable', disableAccount);
 bind('hd-enable', () => act('enable', false));
 bind('hd-quota-bump', quotaBump);
 bind('banner-save', () => bannerAct('save'));
 bind('banner-publish', () => bannerAct('publish'));
 bind('banner-disable', () => bannerAct('disable'));
 bind('banner-rollback', () => bannerAct('rollback'));
 bind('content-save', saveContent);
 const keySel = document.getElementById('content-key');
 if (keySel) keySel.addEventListener('change', loadContentKey);
 bind('hd-delete-library', deleteOneLibrary);
 bind('hd-ticket-reply', replyLatestTicket);
 bind('hd-note', saveNote);
 document.querySelectorAll('[data-job-act]').forEach((btn) => {
  btn.addEventListener('click', () => jobAct(
   btn.getAttribute('data-job-act'),
   btn.getAttribute('data-job-task'),
  ));
 });
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
  set('ov-version', d.version || '—');
  const up = Number(d.uptime_seconds || 0);
  set('ov-uptime', up ? `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m` : 'just started');
  const jc = d.jobs || {};
  set('ov-jobs', `a${jc.active || 0} s${jc.stalled || 0} f${jc.failed || 0}`);
  const health = document.getElementById('admin-source-health');
  if (health) {
   const fails = (d.source_health || []).filter((s) => s.recent_errors).slice(0, 6);
   health.textContent = fails.length
    ? ('Recent source errors: ' + fails.map((s) => `${s.name} ${s.recent_errors}`).join(', '))
    : 'No recent source errors in the job map.';
  }
  if (status) {
   status.textContent = d.guest_auto_prepare
    ? 'Guest demo auto-prepares sample papers.'
    : 'Guest auto-prepare is off.';
  }
  loadBanner();
  loadContentKey();
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
  if (kind === 'tickets') {
   renderTicketQueue(data.tickets || []);
   if (status) {
    status.textContent = (data.tickets || []).length
     ? `${data.tickets.length} open tickets`
     : 'No open tickets.';
   }
   return;
  }
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
  const jobBits = (u.jobs_queue || []).map((j) => `${j.task} ${j.state}`).join(', ');
  const bits = [
   u.role,
   u.locked ? 'locked' : '',
   u.email_verified ? 'email ok' : (u.email ? 'unverified' : ''),
   jobBits,
  ].filter(Boolean).join(' · ');
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
  const state = d.disabled
   ? `disabled until ${d.disabled_until || '?'}`
   : (d.locked ? `locked until ${d.locked_until || '?'}` : 'active');
  access.innerHTML = pair('Access', state)
   + (d.disabled && d.disabled_message ? pair('Disabled note', d.disabled_message) : '')
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
 const stopped = document.getElementById('helpdesk-quota-stopped');
 if (stopped) stopped.hidden = !d.quota_stopped;
 const libs = (d.libraries && d.libraries.libraries) || [];
 const currentLib = document.getElementById('helpdesk-current-library');
 if (currentLib) {
  const name = (d.libraries && d.libraries.active_name) || '—';
  const st = d.statistics || {};
  currentLib.textContent = `Current library: ${name} · ${st.total_articles || 0} papers, ${st.articles_with_embeddings || 0} prepared`;
 }
 const jobList = document.getElementById('helpdesk-jobs');
 if (jobList) {
  const jobs = d.jobs || {};
  jobList.innerHTML = ['fetch', 'embed'].map((k) => {
   const j = jobs[k] || {};
   const state = j.state || (j.active ? 'active' : (j.error ? 'failed' : 'idle'));
   const bits = [
    j.started_at ? `started ${j.started_at}` : '',
    j.updated_at ? `updated ${j.updated_at}` : '',
    j.worker_alive ? 'worker live' : (j.active ? 'no worker' : ''),
    j.result_status || '',
    j.quota_stopped ? 'quota_stopped' : '',
    j.error ? `error: ${j.error}` : '',
    j.message || '',
    sourceFailBits(j),
   ].filter(Boolean).join(' · ');
   return `<li><span class="library-manage-name">${escapeHtml(k)} `
    + `<span class="admin-job-state is-${escapeAttr(state)}">${escapeHtml(state)}</span></span>`
    + `<span class="help-text">${escapeHtml(bits || 'idle')}</span></li>`;
  }).join('');
 }
 const res = document.getElementById('helpdesk-resources');
 if (res) {
  const q = d.quota || {};
  const cap = q.limit_mb ? `${q.used_mb || 0} MB of ${q.limit_mb} MB` : `${q.used_mb || 0} MB (no cap)`;
  const bump = q.quota_override_active
   ? ` · temporary cap ${q.quota_override_mb} MB until ${q.quota_override_until}`
   : '';
  res.textContent = cap
   + (q.over_limit ? ' — over cap' : '')
   + bump
   + (q.default_limit_mb && q.quota_override_active
    ? ` · host default ${q.default_limit_mb} MB`
    : '');
 }
 const libList = document.getElementById('helpdesk-libraries');
 if (libList) {
  libList.innerHTML = libs.length
   ? libs.map((lib) => {
    const tag = lib.active ? 'current' : '';
    return `<li><span class="library-manage-name">${escapeHtml(lib.name || lib.id)}</span>`
     + `<span class="help-text">${escapeHtml([`${lib.size_mb || 0} MB`, tag].filter(Boolean).join(' · '))}</span></li>`;
   }).join('')
   : '<li class="info-text">No libraries.</li>';
 }
 setJobButtons(d);
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
 const tickets = document.getElementById('helpdesk-tickets');
 if (tickets) {
  tickets.innerHTML = (d.tickets || []).length
   ? d.tickets.map((t) => `<li><span class="library-manage-name">${escapeHtml(t.status)}</span>`
    + `<span class="help-text">${escapeHtml([t.created_at, t.body].filter(Boolean).join(' · '))}</span></li>`).join('')
   : '<li class="info-text">No tickets.</li>';
 }
}

function pair(label, value) {
 return `<div><dt>${escapeHtml(String(label))}</dt><dd>${escapeHtml(String(value == null ? '—' : value))}</dd></div>`;
}

function setJobButtons(d) {
 const jobs = d.jobs || {};
 const setEnabled = (id, on) => {
  const el = document.getElementById(id);
  if (el) el.disabled = !on;
 };
 const fetchSlot = jobs.fetch || {};
 const embedSlot = jobs.embed || {};
 setEnabled('hd-cancel-fetch', !!fetchSlot.can_cancel);
 setEnabled('hd-cancel-embed', !!embedSlot.can_cancel);
 setEnabled('hd-clear-fetch', !!fetchSlot.can_clear);
 setEnabled('hd-clear-embed', !!embedSlot.can_clear);
 setEnabled('hd-retry-embed', !!embedSlot.can_retry);
 setEnabled('hd-retry-fetch', !!fetchSlot.can_retry_fetch);
}

function sourceFailBits(j) {
 const kinds = j.error_kinds || {};
 const bits = Object.keys(kinds).filter((k) => kinds[k] && kinds[k] !== 'ok' && kinds[k] !== 'no_results')
  .map((k) => `${k}:${kinds[k]}`);
 return bits.length ? bits.join(' ') : '';
}

function renderTicketQueue(tickets) {
 const list = document.getElementById('helpdesk-results');
 if (!list) return;
 if (!tickets.length) {
  list.innerHTML = '<li class="info-text">No tickets in this list.</li>';
  return;
 }
 list.innerHTML = tickets.map((t) => `<li><button type="button" class="btn btn-secondary btn-block admin-user-btn" data-id="${escapeAttr(t.student_id)}">`
  + `<span class="library-manage-name">${escapeHtml(t.student_username)}</span>`
  + `<span class="help-text">${escapeHtml([t.status, t.body].filter(Boolean).join(' · '))}</span></button></li>`).join('');
 list.querySelectorAll('[data-id]').forEach((btn) => {
  btn.addEventListener('click', () => openStudent(btn.getAttribute('data-id')));
 });
}

async function promptAction(title, message, { confirmName, extra, fields: moreFields, validate } = {}) {
 const fields = [
  { id: 'reason', label: 'Reason', type: 'text', value: '', placeholder: 'Why are you doing this?' },
  ...(moreFields || []),
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
   if (typeof validate === 'function') return validate(v);
   return null;
  },
 });
 if (!vals) return null;
 return { reason: vals.reason, confirm: vals.confirm, ...vals, ...(extra || {}) };
}

async function act(name, destructive, opts) {
 if (!_selected) return;
 const status = document.getElementById('helpdesk-action-status');
 const extra = Object.assign({}, (opts && opts.extra) || {});
 if ((name === 'cancel-job' || name === 'clear-job') && !extra.task) extra.task = 'fetch';
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

async function jobAct(name, task) {
 if (!_selected) return;
 await act(name, true, { extra: { task } });
}

async function retryEmbed() {
 if (!_selected) return;
 const status = document.getElementById('helpdesk-action-status');
 const body = await promptAction(
  'Retry prepare',
  'Starts prepare (embeddings, missing only) on this student’s current library. It does not load their collection into your session.',
  {},
 );
 if (!body) return;
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(
   `/api/admin/users/${encodeURIComponent(_selected.id)}/retry-embed`,
   { method: 'POST', body },
  );
  if (status) status.textContent = data.status || 'Started';
  showNotification(status ? status.textContent : 'Started', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}

async function setEmail() {
 if (!_selected) return;
 if (_selected.is_guest) {
  showNotification('Guest demos cannot change email. They must register.', 'error');
  return;
 }
 const status = document.getElementById('helpdesk-action-status');
 const body = await promptAction(
  'Set email and send verification',
  'Replaces the recovery address and emails a verification link. This does not mark the address verified.',
  {
   confirmName: _selected.username,
   fields: [
    { id: 'email', label: 'New email', type: 'email', value: _selected.email || '', placeholder: 'name@school.edu' },
   ],
   validate: (v) => (String(v.email || '').includes('@') ? null : 'Enter an email address.'),
  },
 );
 if (!body) return;
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(
   `/api/admin/users/${encodeURIComponent(_selected.id)}/set-email`,
   { method: 'POST', body: { reason: body.reason, confirm: body.confirm, email: body.email } },
  );
  if (status) status.textContent = data.emailed_to ? `Verification sent to ${data.emailed_to}` : (data.status || 'Done');
  showNotification(status ? status.textContent : 'Done', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}

async function quotaBump() {
 if (!_selected) return;
 const status = document.getElementById('helpdesk-action-status');
 const tomorrow = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
 const defaultMb = String((_selected.quota && (_selected.quota.default_limit_mb || _selected.quota.limit_mb)) || 500);
 const body = await promptAction(
  'Temporary quota bump',
  'Raises the storage cap for this account only, until the expiry. Everyone else keeps the host default.',
  {
   confirmName: _selected.username,
   fields: [
    { id: 'limit_mb', label: 'Temporary cap (MB)', type: 'number', value: defaultMb },
    { id: 'until', label: 'Expires (UTC date)', type: 'date', value: tomorrow },
   ],
   validate: (v) => {
    const n = Number(v.limit_mb);
    if (!Number.isFinite(n) || n < 1) return 'Enter a cap in megabytes.';
    if (!String(v.until || '').trim()) return 'Pick an expiry date.';
    return null;
   },
  },
 );
 if (!body) return;
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(
   `/api/admin/users/${encodeURIComponent(_selected.id)}/quota-bump`,
   {
    method: 'POST',
    body: {
     reason: body.reason,
     confirm: body.confirm,
     limit_mb: Number(body.limit_mb),
     until: body.until,
    },
   },
  );
  if (status) status.textContent = data.status || 'Done';
  showNotification(status ? status.textContent : 'Done', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}

async function deleteOneLibrary() {
 if (!_selected) return;
 const libs = (_selected.libraries && _selected.libraries.libraries) || [];
 if (libs.length < 2) {
  showNotification('This account has only one library. You cannot wipe the last collection.', 'error');
  return;
 }
 const names = libs.map((lib) => lib.name).join(', ');
 const status = document.getElementById('helpdesk-action-status');
 const body = await promptAction(
  'Delete one library',
  `Deletes a single collection. Remaining: ${names}. Type the library name exactly.`,
  {
   confirmName: _selected.username,
   fields: [
    { id: 'library_name', label: 'Library name to delete', type: 'text', value: '', placeholder: names },
   ],
   validate: (v) => {
    const name = String(v.library_name || '').trim();
    if (!name) return 'Type the library name.';
    if (!libs.some((lib) => lib.name === name)) return 'That name does not match a library on this account.';
    return null;
   },
  },
 );
 if (!body) return;
 const match = libs.find((lib) => lib.name === String(body.library_name || '').trim());
 if (!match) return;
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(
   `/api/admin/users/${encodeURIComponent(_selected.id)}/delete-library`,
   {
    method: 'POST',
    body: {
     reason: body.reason,
     confirm: body.confirm,
     library_id: match.id,
     library_name: match.name,
    },
   },
  );
  if (status) status.textContent = data.status || 'Deleted';
  showNotification(status ? status.textContent : 'Deleted', 'success');
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

async function retryFetch() {
 if (!_selected) return;
 const body = await promptAction('Retry fetch', 'Re-runs the last fetch on this student’s current library.', {});
 if (!body) return;
 await postSelected('retry-fetch', body);
}

async function startStudentView() {
 if (!_selected) return;
 const body = await promptAction(
  'View as student (read-only)',
  'Re-enter your password. This is a 15-minute read-only view. It does not sign you in as them.',
  {
   fields: [
    { id: 'password', label: 'Your admin password', type: 'password', value: '' },
    { id: 'ui_mode', label: 'UI mode (simple or advanced)', type: 'text', value: 'simple' },
   ],
   validate: (v) => (String(v.password || '') ? null : 'Password is required.'),
  },
 );
 if (!body) return;
 const status = document.getElementById('helpdesk-action-status');
 try {
  const data = await apiCall(`/api/admin/users/${encodeURIComponent(_selected.id)}/view`, {
   method: 'POST',
   body: {
    reason: body.reason,
    password: body.password,
    ui_mode: body.ui_mode || 'simple',
   },
  });
  if (status) status.textContent = 'Opening student view…';
  window.location.href = data.redirect || '/search';
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not start view';
  showNotification(e.message || 'Failed', 'error');
 }
}

async function disableAccount() {
 if (!_selected) return;
 const body = await promptAction(
  'Disable account',
  'They will not be able to sign in. Type their username. The explanation is shown to them.',
  {
   confirmName: _selected.username,
   fields: [
    { id: 'message', label: 'Student-facing explanation', type: 'text', value: '' },
    { id: 'until', label: 'Expires (UTC date, optional)', type: 'date', value: '' },
   ],
   validate: (v) => (String(v.message || '').trim().length >= 3 ? null : 'Write a short explanation.'),
  },
 );
 if (!body) return;
 await postSelected('disable', {
  reason: body.reason,
  confirm: body.confirm,
  message: body.message,
  until: body.until,
 });
}

async function replyLatestTicket() {
 if (!_selected) return;
 const ticket = (_selected.tickets || [])[0];
 if (!ticket) {
  showNotification('No ticket on this account.', 'error');
  return;
 }
 const body = await promptAction(
  'Reply to ticket',
  'This is emailed if they have a verified address. It also lands on the timeline.',
  { fields: [{ id: 'body', label: 'Reply', type: 'text', value: '' }] },
 );
 if (!body) return;
 const status = document.getElementById('helpdesk-action-status');
 try {
  await apiCall(`/api/admin/tickets/${encodeURIComponent(ticket.id)}/reply`, {
   method: 'POST',
   body: { reason: body.reason, body: body.body },
  });
  if (status) status.textContent = 'Reply sent.';
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Reply failed';
 }
}

async function postSelected(name, body) {
 const status = document.getElementById('helpdesk-action-status');
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(`/api/admin/users/${encodeURIComponent(_selected.id)}/${name}`, {
   method: 'POST',
   body,
  });
  if (status) status.textContent = data.status || 'Done';
  showNotification(status ? status.textContent : 'Done', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}

let _bannerId = null;
let _bannerRev = null;

async function loadBanner() {
 try {
  const d = await apiCall('/api/admin/banner');
  const b = d.banner || d.published;
  const el = document.getElementById('banner-current');
  const field = document.getElementById('banner-body');
  if (b) {
   _bannerId = b.id;
   _bannerRev = (b.revisions && b.revisions[1] && b.revisions[1].id) || (b.revisions && b.revisions[0] && b.revisions[0].id) || null;
   if (el) el.textContent = `${b.status}: ${b.body}${b.expires_at ? ` (until ${b.expires_at})` : ''}`;
   if (field && !field.value) field.value = b.body || '';
  } else if (el) el.textContent = 'No published banner.';
 } catch (e) {
  const el = document.getElementById('banner-current');
  if (el) el.textContent = e.message || 'Could not load banner.';
 }
}

async function bannerAct(kind) {
 const field = document.getElementById('banner-body');
 const status = document.getElementById('banner-status');
 const body = await promptAction('Banner ' + kind, 'This is site-wide student-facing text. Plain text only.', {});
 if (!body) return;
 try {
  if (kind === 'save') {
   const d = await apiCall('/api/admin/banner', {
    method: 'POST',
    body: { reason: body.reason, body: (field && field.value) || '', status: 'draft' },
   });
   _bannerId = d.banner && d.banner.id;
  } else if (!_bannerId) {
   throw new Error('Save a draft first.');
  } else if (kind === 'publish') {
   await apiCall(`/api/admin/banner/${encodeURIComponent(_bannerId)}/publish`, {
    method: 'POST', body: { reason: body.reason },
   });
  } else if (kind === 'disable') {
   await apiCall(`/api/admin/banner/${encodeURIComponent(_bannerId)}/disable`, {
    method: 'POST', body: { reason: body.reason },
   });
  } else if (kind === 'rollback') {
   if (!_bannerRev) throw new Error('No revision to roll back to.');
   await apiCall(`/api/admin/banner/${encodeURIComponent(_bannerId)}/rollback`, {
    method: 'POST', body: { reason: body.reason, revision_id: _bannerRev },
   });
  }
  if (status) status.textContent = 'Done.';
  await loadBanner();
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
 }
}

async function loadContentKey() {
 const key = document.getElementById('content-key')?.value;
 const field = document.getElementById('content-body');
 if (!key || !field) return;
 try {
  const d = await apiCall('/api/admin/content');
  const item = (d.items || {})[key] || {};
  field.value = item.body || '';
 } catch (e) {
  const status = document.getElementById('content-status');
  if (status) status.textContent = e.message || 'Could not load copy.';
 }
}

async function saveContent() {
 const key = document.getElementById('content-key')?.value;
 const field = document.getElementById('content-body');
 const status = document.getElementById('content-status');
 const body = await promptAction('Save student-facing copy', 'Plain text or JSON only. No HTML.', {});
 if (!body || !key) return;
 try {
  await apiCall(`/api/admin/content/${encodeURIComponent(key)}`, {
   method: 'POST',
   body: { reason: body.reason, body: (field && field.value) || '' },
  });
  if (status) status.textContent = 'Saved.';
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
 }
}
