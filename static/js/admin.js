// Operator admin console. common.js provides apiCall, escapeHtml, escapeAttr,
// openSiteForm and showNotification.

const TABS = ['overview', 'accounts', 'site', 'host'];
const PAGE = 25;

let _selected = null;
let _queue = null;
let _pages = { timeline: 0, notes: 0, activity: 0 };

document.addEventListener('DOMContentLoaded', () => {
 document.querySelectorAll('.tab[data-tab]').forEach((btn) => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.tab; });
 });
 document.getElementById('admin-tabs')?.addEventListener('keydown', onTabKey);
 window.addEventListener('hashchange', route);
 route();
 loadOverview();

 const form = document.getElementById('helpdesk-search-form');
 if (form) {
  form.addEventListener('submit', (e) => {
   e.preventDefault();
   runSearch();
  });
 }
 document.querySelectorAll('[data-queue]').forEach((btn) => {
  btn.addEventListener('click', () => { location.hash = 'accounts/' + btn.dataset.queue; });
 });
 document.querySelectorAll('[data-action]').forEach((btn) => {
  btn.addEventListener('click', () => runAction(btn.dataset.action, btn.dataset.task || null));
 });
 document.querySelectorAll('[data-more]').forEach((btn) => {
  btn.addEventListener('click', () => loadMore(btn.dataset.more));
 });
 bind('hd-note', saveNote);
 bind('hd-ticket-reply', replyLatestTicket);
 bind('banner-save', () => bannerAct('save'));
 bind('banner-publish', () => bannerAct('publish'));
 bind('banner-disable', () => bannerAct('disable'));
 bind('banner-rollback', () => bannerAct('rollback'));
 bind('content-save', saveContent);
 const keySel = document.getElementById('content-key');
 if (keySel) keySel.addEventListener('change', loadContentKey);
});

function bind(id, fn) {
 const el = document.getElementById(id);
 if (el) el.addEventListener('click', fn);
}

// --- tabs and the hash ---------------------------------------------------

function route() {
 const parts = (location.hash || '#overview').slice(1).split('/');
 const tab = TABS.includes(parts[0]) ? parts[0] : 'overview';
 showTab(tab);
 if (tab === 'accounts' && parts[1] === 'u' && parts[2]) {
  openStudent(parts[2]);
 } else if (tab === 'accounts' && parts[1]) {
  runQueue(parts[1]);
 }
}

function showTab(name) {
 TABS.forEach((t) => {
  const btn = document.getElementById('tab-' + t);
  const panel = document.getElementById('panel-' + t);
  if (btn) btn.setAttribute('aria-selected', t === name ? 'true' : 'false');
  if (panel) panel.hidden = t !== name;
 });
}

function onTabKey(ev) {
 if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
 const current = document.activeElement?.dataset?.tab;
 if (!current) return;
 const i = TABS.indexOf(current);
 const next = TABS[(i + (ev.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length];
 ev.preventDefault();
 document.getElementById('tab-' + next)?.focus();
 location.hash = next;
}

// --- overview ------------------------------------------------------------

async function loadOverview() {
 const status = document.getElementById('admin-overview-status');
 const set = (id, v) => {
  const el = document.getElementById(id);
  if (el) el.textContent = String(v);
 };
 const tile = (key, v) => {
  const el = document.querySelector(`[data-count="${key}"]`);
  if (!el) return;
  el.textContent = String(v);
  el.classList.toggle('is-zero', !Number(v));
 };
 try {
  const d = await apiCall('/api/admin/overview');
  const c = d.counts || {};
  set('ov-accounts', c.accounts ?? '—');
  set('ov-guests', c.guests ?? '—');
  tile('locked', c.locked ?? 0);
  tile('unverified', c.unverified ?? 0);
  const jc = d.jobs || {};
  tile('active', jc.active || 0);
  tile('stalled', jc.stalled || 0);
  tile('failed', jc.failed || 0);
  set('ov-smtp', d.smtp ? 'on' : 'off');
  set('ov-ai', d.ai ? 'on' : 'off');
  set('ov-quota', d.quota_mb ? `${d.quota_mb} MB` : 'off');
  set('ov-version', d.version || '—');
  const up = Number(d.uptime_seconds || 0);
  set('ov-uptime', up ? `${Math.floor(up / 3600)}h ${Math.floor((up % 3600) / 60)}m` : 'just started');
  set('ov-jobs', `${jc.active || 0} active · ${jc.stalled || 0} stalled · ${jc.failed || 0} failed`);
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
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not load host snapshot.';
 }
 try {
  const q = await apiCall('/api/admin/queue?filter=tickets');
  tile('tickets', (q.tickets || []).length);
 } catch (e) {
  tile('tickets', '?');
 }
 loadBanner();
 loadContentKey();
}

// --- accounts: find one ----------------------------------------------------

async function runSearch() {
 const q = (document.getElementById('helpdesk-q')?.value || '').trim();
 const status = document.getElementById('helpdesk-list-status');
 setQueueChip(null);
 if (location.hash !== '#accounts') history.replaceState(null, '', '#accounts');
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

function setQueueChip(kind) {
 _queue = kind;
 document.querySelectorAll('[data-queue]').forEach((btn) => {
  btn.classList.toggle('is-on', btn.dataset.queue === kind);
 });
}

async function runQueue(kind) {
 const status = document.getElementById('helpdesk-list-status');
 setQueueChip(kind);
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

// --- accounts: one account -------------------------------------------------

async function openStudent(id) {
 const status = document.getElementById('helpdesk-action-status');
 if (status) status.textContent = 'Loading…';
 try {
  const d = await apiCall('/api/admin/users/' + encodeURIComponent(id));
  _selected = d;
  renderDetail(d);
  if (status) status.textContent = '';
  const wanted = '#accounts/u/' + encodeURIComponent(d.id);
  if (location.hash !== wanted) history.replaceState(null, '', wanted);
  document.querySelectorAll('#helpdesk-results [data-id]').forEach((btn) => {
   btn.classList.toggle('is-active', btn.getAttribute('data-id') === d.id);
  });
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not load student';
 }
}

function renderDetail(d) {
 const panel = document.getElementById('helpdesk-detail');
 if (panel) panel.hidden = false;
 const title = document.getElementById('helpdesk-title');
 if (title) title.textContent = d.username;
 const badges = document.getElementById('helpdesk-badges');
 if (badges) {
  const list = [
   d.disabled ? ['disabled', 'is-err'] : null,
   d.locked ? ['locked', 'is-err'] : null,
   d.email_verified ? null : (d.email ? ['email unverified', 'is-warn'] : ['no email', 'is-warn']),
   d.quota && d.quota.over_limit ? ['over quota', 'is-warn'] : null,
   d.role && d.role !== 'student' ? [d.role, ''] : null,
  ].filter(Boolean);
  badges.innerHTML = list.map(([text, cls]) => `<span class="admin-badge ${cls}">${escapeHtml(text)}</span>`).join('');
 }
 const ident = document.getElementById('helpdesk-identity');
 if (ident) {
  ident.textContent = [
   d.email || 'no email',
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
   + pair('Password changed', d.password_changed_at || '—')
   + pair('Last login', d.last_login_at || '—')
   + pair('Last seen', d.last_seen_at || '—')
   + pair('Failed sign-ins', d.failed_logins || 0);
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
  jobList.innerHTML = ['fetch', 'embed', 'cluster'].map((k) => {
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
 const pack = document.getElementById('hd-packet');
 if (pack) pack.href = '/api/admin/users/' + encodeURIComponent(d.id) + '/packet';
 const tickets = document.getElementById('helpdesk-tickets');
 if (tickets) {
  tickets.innerHTML = (d.tickets || []).length
   ? d.tickets.map((t) => `<li><span class="library-manage-name">${escapeHtml(t.status)}</span>`
    + `<span class="help-text">${escapeHtml([t.created_at, t.body].filter(Boolean).join(' · '))}</span></li>`).join('')
   : '<li class="info-text">No tickets.</li>';
 }
 renderHistory('notes', d.support_notes || [], true);
 renderHistory('activity', d.activity || [], true);
 renderHistory('timeline', d.timeline || [], true);
}

function pair(label, value) {
 return `<div><dt>${escapeHtml(String(label))}</dt><dd>${escapeHtml(String(value == null ? '—' : value))}</dd></div>`;
}

function setJobButtons(d) {
 const jobs = d.jobs || {};
 const can = {
  'cancel-job:fetch': !!(jobs.fetch || {}).can_cancel,
  'cancel-job:embed': !!(jobs.embed || {}).can_cancel,
  'clear-job:fetch': !!(jobs.fetch || {}).can_clear,
  'clear-job:embed': !!(jobs.embed || {}).can_clear,
  'retry-embed': !!(jobs.embed || {}).can_retry,
  'retry-fetch': !!(jobs.fetch || {}).can_retry_fetch,
 };
 document.querySelectorAll('[data-action]').forEach((btn) => {
  const key = btn.dataset.task ? `${btn.dataset.action}:${btn.dataset.task}` : btn.dataset.action;
  if (key in can) btn.disabled = !can[key];
 });
}

function sourceFailBits(j) {
 const kinds = j.error_kinds || {};
 const bits = Object.keys(kinds).filter((k) => kinds[k] && kinds[k] !== 'ok' && kinds[k] !== 'no_results')
  .map((k) => `${k}:${kinds[k]}`);
 return bits.length ? bits.join(' ') : '';
}

// --- history lists: the first page comes with the account, the rest on demand

const HISTORY = {
 notes: {
  list: 'helpdesk-notes',
  empty: 'No notes yet.',
  row: (n) => `<li><span class="library-manage-name">${escapeHtml(n.admin_username)}</span>`
   + `<span class="help-text">${escapeHtml(n.created_at)}</span>`
   + `<p class="info-text">${escapeHtml(n.body)}</p></li>`,
 },
 activity: {
  list: 'helpdesk-activity',
  empty: 'No recent sign-in events.',
  row: (e) => `<li><span class="library-manage-name">${escapeHtml(e.kind)}</span>`
   + `<span class="help-text">${escapeHtml([e.created_at, e.ip, e.detail].filter(Boolean).join(' · '))}</span></li>`,
 },
 timeline: {
  list: 'helpdesk-timeline',
  empty: 'No admin actions yet.',
  row: (a) => `<li><span class="library-manage-name">${escapeHtml(a.action)}</span>`
   + `<span class="help-text">${escapeHtml([a.created_at, a.admin_username, a.reason].filter(Boolean).join(' · '))}</span></li>`,
 },
};

function renderHistory(kind, rows, reset) {
 const spec = HISTORY[kind];
 const list = document.getElementById(spec.list);
 if (!list) return;
 if (reset) {
  _pages[kind] = 0;
  list.innerHTML = rows.length ? '' : `<li class="info-text">${escapeHtml(spec.empty)}</li>`;
 }
 list.insertAdjacentHTML('beforeend', rows.map(spec.row).join(''));
 _pages[kind] += rows.length;
 const more = document.querySelector(`[data-more="${kind}"]`);
 if (more) more.hidden = rows.length < PAGE;
}

async function loadMore(kind) {
 if (!_selected) return;
 const more = document.querySelector(`[data-more="${kind}"]`);
 if (more) more.disabled = true;
 try {
  const d = await apiCall(`/api/admin/users/${encodeURIComponent(_selected.id)}/history?kind=${kind}&offset=${_pages[kind]}&limit=${PAGE}`);
  renderHistory(kind, d.items || [], false);
  if (more) more.hidden = !d.more;
 } catch (e) {
  showNotification(e.message || 'Could not load more', 'error');
 } finally {
  if (more) more.disabled = false;
 }
}

// --- actions: one dialog, one post, one report -----------------------------

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
 const vals = await openSiteForm({
  title,
  message,
  confirmLabel: 'Continue',
  danger: !!confirmName,
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

// What each action asks beyond the reason, and what it sends. Actions missing
// here ask for the reason (and the username when destructive) and send that.
const ACTION_FORMS = {
 'set-email': {
  title: 'Set email and send verification',
  message: 'Replaces the recovery address and emails a verification link. This does not mark the address verified.',
  fields: (s) => [{ id: 'email', label: 'New email', type: 'email', value: s.email || '', placeholder: 'name@school.edu' }],
  validate: (v) => (String(v.email || '').includes('@') ? null : 'Enter an email address.'),
  body: (v) => ({ email: v.email }),
 },
 'quota-bump': {
  title: 'Temporary quota bump',
  message: 'Raises the storage cap for this account only, until the expiry. Everyone else keeps the host default.',
  fields: (s) => [
   { id: 'limit_mb', label: 'Temporary cap (MB)', type: 'number', value: String((s.quota && (s.quota.default_limit_mb || s.quota.limit_mb)) || 500) },
   { id: 'until', label: 'Expires (UTC date)', type: 'date', value: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10) },
  ],
  validate: (v) => {
   const n = Number(v.limit_mb);
   if (!Number.isFinite(n) || n < 1) return 'Enter a cap in megabytes.';
   if (!String(v.until || '').trim()) return 'Pick an expiry date.';
   return null;
  },
  body: (v) => ({ limit_mb: Number(v.limit_mb), until: v.until }),
 },
 'delete-library': {
  title: 'Delete one library',
  before: (s) => (libraries(s).length < 2 ? 'This account has only one library. You cannot wipe the last collection.' : null),
  message: (s) => `Deletes a single collection. Remaining: ${libraries(s).map((l) => l.name).join(', ')}. Type the library name exactly.`,
  fields: (s) => [{ id: 'library_name', label: 'Library name to delete', type: 'text', value: '', placeholder: libraries(s).map((l) => l.name).join(', ') }],
  validate: (v, s) => {
   const name = String(v.library_name || '').trim();
   if (!name) return 'Type the library name.';
   if (!libraries(s).some((l) => l.name === name)) return 'That name does not match a library on this account.';
   return null;
  },
  body: (v, s) => {
   const match = libraries(s).find((l) => l.name === String(v.library_name || '').trim());
   return { library_id: match.id, library_name: match.name };
  },
 },
 disable: {
  title: 'Disable account',
  message: 'They will not be able to sign in. Type their username. The explanation is shown to them.',
  fields: () => [
   { id: 'message', label: 'Student-facing explanation', type: 'text', value: '' },
   { id: 'until', label: 'Expires (UTC date, optional)', type: 'date', value: '' },
  ],
  validate: (v) => (String(v.message || '').trim().length >= 3 ? null : 'Write a short explanation.'),
  body: (v) => ({ message: v.message, until: v.until }),
 },
 view: {
  title: 'View as student (read-only)',
  message: 'Re-enter your password. This is a 15-minute read-only view. It does not sign you in as them.',
  fields: () => [{ id: 'password', label: 'Your admin password', type: 'password', value: '' }],
  validate: (v) => (String(v.password || '') ? null : 'Password is required.'),
  body: (v) => ({ password: v.password }),
  after: (data) => { window.location.href = data.redirect || '/search'; },
 },
 'retry-embed': {
  title: 'Retry prepare',
  message: 'Starts prepare (embeddings, missing only) on this student’s current library. It does not load their collection into your session.',
 },
 'retry-fetch': {
  title: 'Retry fetch',
  message: 'Re-runs the last fetch on this student’s current library.',
 },
};

function libraries(s) {
 return (s && s.libraries && s.libraries.libraries) || [];
}

async function runAction(name, task) {
 if (!_selected) return;
 const btn = document.querySelector(task
  ? `[data-action="${name}"][data-task="${task}"]`
  : `[data-action="${name}"]`);
 const destructive = !!(btn && btn.dataset.destructive);
 const form = ACTION_FORMS[name] || {};
 if (form.before) {
  const stop = form.before(_selected);
  if (stop) {
   showNotification(stop, 'error');
   return;
  }
 }
 const title = form.title || (btn ? btn.textContent.trim() : name.replace(/-/g, ' '));
 const message = typeof form.message === 'function' ? form.message(_selected) : (form.message || (destructive
  ? 'This changes the student’s access. Type their username and a reason.'
  : 'Add a short reason for the timeline.'));
 const vals = await promptAction(title, message, {
  confirmName: destructive ? _selected.username : null,
  fields: form.fields ? form.fields(_selected) : [],
  validate: form.validate ? (v) => form.validate(v, _selected) : null,
 });
 if (!vals) return;
 const body = { reason: vals.reason, confirm: vals.confirm, ...(task ? { task } : {}), ...(form.body ? form.body(vals, _selected) : {}) };
 const status = document.getElementById('helpdesk-action-status');
 if (status) status.textContent = 'Working…';
 try {
  const data = await apiCall(`/api/admin/users/${encodeURIComponent(_selected.id)}/${name}`, { method: 'POST', body });
  const said = data.emailed_to ? `Emailed ${data.emailed_to}` : (data.detail || (data.status && data.status !== 'ok' ? data.status : 'Done.'));
  if (status) status.textContent = said;
  showNotification(said, 'success');
  if (form.after) {
   form.after(data);
   return;
  }
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
  showNotification('Note saved.', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not save note';
  showNotification(e.message || 'Could not save note', 'error');
 }
}

async function replyLatestTicket() {
 if (!_selected) return;
 const ticket = (_selected.tickets || [])[0];
 if (!ticket) {
  showNotification('No ticket on this account.', 'error');
  return;
 }
 const vals = await promptAction(
  'Reply to ticket',
  'This is emailed if they have a verified address. It also lands on the timeline.',
  { fields: [{ id: 'body', label: 'Reply', type: 'text', value: '' }] },
 );
 if (!vals) return;
 const status = document.getElementById('helpdesk-action-status');
 try {
  await apiCall(`/api/admin/tickets/${encodeURIComponent(ticket.id)}/reply`, {
   method: 'POST',
   body: { reason: vals.reason, body: vals.body },
  });
  if (status) status.textContent = 'Reply sent.';
  showNotification('Reply sent.', 'success');
  await openStudent(_selected.id);
 } catch (e) {
  if (status) status.textContent = e.message || 'Reply failed';
  showNotification(e.message || 'Reply failed', 'error');
 }
}

// --- site: banner and copy -------------------------------------------------

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

const BANNER_WORDS = {
 save: ['Save banner draft', 'Saves the text without showing it to anyone.'],
 publish: ['Publish banner', 'Every student sees this at the top of every page. Type publish to confirm.'],
 disable: ['Take the banner down', 'Removes it from every page. Type publish to confirm.'],
 rollback: ['Roll back the banner', 'Restores the previous revision.'],
};

async function bannerAct(kind) {
 const field = document.getElementById('banner-body');
 const status = document.getElementById('banner-status');
 const [title, message] = BANNER_WORDS[kind];
 const confirmName = (kind === 'publish' || kind === 'disable') ? 'publish' : null;
 const vals = await promptAction(title, message, { confirmName });
 if (!vals) return;
 const body = { reason: vals.reason, confirm: vals.confirm };
 try {
  if (kind === 'save') {
   const d = await apiCall('/api/admin/banner', {
    method: 'POST',
    body: { ...body, body: (field && field.value) || '', status: 'draft' },
   });
   _bannerId = d.banner && d.banner.id;
  } else if (!_bannerId) {
   throw new Error('Save a draft first.');
  } else if (kind === 'rollback') {
   if (!_bannerRev) throw new Error('No revision to roll back to.');
   await apiCall(`/api/admin/banner/${encodeURIComponent(_bannerId)}/rollback`, {
    method: 'POST', body: { ...body, revision_id: _bannerRev },
   });
  } else {
   await apiCall(`/api/admin/banner/${encodeURIComponent(_bannerId)}/${kind}`, { method: 'POST', body });
  }
  if (status) status.textContent = 'Done.';
  showNotification(`Banner: ${kind === 'disable' ? 'taken down' : kind + 'd'}.`, 'success');
  await loadBanner();
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
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
 const vals = await promptAction('Save student-facing copy', 'Plain text or JSON only. No HTML.', {});
 if (!vals || !key) return;
 try {
  await apiCall(`/api/admin/content/${encodeURIComponent(key)}`, {
   method: 'POST',
   body: { reason: vals.reason, body: (field && field.value) || '' },
  });
  if (status) status.textContent = 'Saved.';
  showNotification('Copy saved.', 'success');
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}
