// Operator admin console. common.js provides apiCall, escapeHtml, escapeAttr,
// openSiteForm and showNotification.

const TABS = ['overview', 'accounts', 'tickets', 'site', 'host'];
const TICKET_STATUSES = ['open', 'waiting_on_student', 'investigating', 'resolved'];
const TICKET_WORDS = { open: 'open', waiting_on_student: 'waiting on student', investigating: 'investigating', resolved: 'resolved' };
const PAGE = 25;

let _selected = null;
let _queue = null;
let _ticket = null;
let _ticketFilter = null;
let _pages = { timeline: 0, notes: 0, activity: 0 };
let _overviewTimer = null;
let _activeTab = null;
let _overviewLoaded = false;

document.addEventListener('DOMContentLoaded', () => {
 document.querySelectorAll('.tab[data-tab]').forEach((btn) => {
  btn.addEventListener('click', () => { location.hash = btn.dataset.tab; });
 });
 document.getElementById('admin-tabs')?.addEventListener('keydown', onTabKey);
 document.addEventListener('visibilitychange', onOverviewVisibilityChange);
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
 document.querySelectorAll('[data-ticket-status]').forEach((btn) => {
  btn.addEventListener('click', () => { location.hash = 'tickets/' + btn.dataset.ticketStatus; });
 });
 bind('ticket-reply-send', sendTicketReply);
 bind('ticket-status-set', setTicketStatus);
 bind('banner-save', () => bannerAct('save'));
 bind('banner-publish', () => bannerAct('publish'));
 bind('banner-disable', () => bannerAct('disable'));
 bind('banner-rollback', () => bannerAct('rollback'));
 bind('content-save', saveContent);
 bind('ollama-start', () => ollamaAct('start'));
 bind('ollama-stop', () => ollamaAct('stop'));
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
 } else if (tab === 'tickets' && parts[1] === 't' && parts[2]) {
  openTicket(parts[2]);
 } else if (tab === 'tickets') {
  listTickets(parts[1] || 'open');
 }
}

function showTab(name) {
 TABS.forEach((t) => {
  const btn = document.getElementById('tab-' + t);
  const panel = document.getElementById('panel-' + t);
  if (btn) btn.setAttribute('aria-selected', t === name ? 'true' : 'false');
  if (panel) panel.hidden = t !== name;
 });
 if (name === 'overview') {
  if (_overviewLoaded && _activeTab !== 'overview') refreshOverviewCards();
  syncOverviewTimer();
 } else if (_overviewTimer) {
  clearInterval(_overviewTimer);
  _overviewTimer = null;
 }
 _activeTab = name;
}

function onOverviewVisibilityChange() {
 if (document.visibilityState === 'visible' && _activeTab === 'overview') refreshOverviewCards();
 syncOverviewTimer();
}

function syncOverviewTimer() {
 if (_overviewTimer) clearInterval(_overviewTimer);
 _overviewTimer = null;
 const panel = document.getElementById('panel-overview');
 if (panel && !panel.hidden && document.visibilityState === 'visible') {
  _overviewTimer = setInterval(refreshOverviewCards, 60000);
 }
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
 _overviewLoaded = true;
 const status = document.getElementById('admin-overview-status');
 const set = (id, v) => {
  const el = document.getElementById(id);
  if (el) el.textContent = String(v);
 };
 try {
  const d = await apiCall('/api/admin/overview');
  const c = d.counts || {};
  set('ov-accounts', c.accounts ?? '—');
  set('ov-guests', c.guests ?? '—');
  const jc = d.jobs || {};
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
 await refreshOverviewCards();
 loadBanner();
 loadContentKey();
 loadHost();
}

async function refreshOverviewCards() {
 const tile = (key, v) => {
  const el = document.querySelector(`[data-count="${key}"]`);
  if (!el) return;
  el.textContent = String(v);
  el.classList.toggle('is-zero', !Number(v));
 };
 try {
  const d = await apiCall('/api/admin/queue-counts');
  const counts = d.counts || {};
  document.querySelectorAll('#admin-tiles [data-count]').forEach((el) => {
   const kind = el.dataset.count;
   tile(kind, counts[kind] ?? 0);
  });
  setTicketBadge(counts.tickets || 0);
 } catch (e) {
  document.querySelectorAll('#admin-tiles [data-count]').forEach((el) => { el.textContent = '?'; });
 }
 try {
  const d = await apiCall('/api/admin/activity?limit=50');
  renderAdminActivity(d.items || []);
 } catch (e) {
  renderAdminActivity([], e.message || 'Could not load recent admin activity.');
 }
}

const ACTIVITY_WORDS = {
 unlock: 'unlocked',
 enable: 're-enabled',
 disable: 'disabled',
 'revoke-sessions': 'revoked all sessions for',
 'resend-verification': 'resent verification to',
 'send-reset': 'emailed a password reset to',
 'send-login-link': 'emailed a one-time sign-in to',
 'set-email': 'set the email for',
 'cancel-job': 'cancelled a job for',
 'clear-job': 'cleared a stale job for',
 'retry-embed': 'retried prepare for',
 'retry-fetch': 'retried fetch for',
 'quota-bump': 'bumped quota for',
 'delete-library': 'deleted a library for',
 note: 'left a note on',
 'ticket-open': 'opened a ticket',
 'ticket-student-reply': 'replied to their own ticket',
 'ticket-reply': 'replied to a ticket for',
 'ticket-status': 'changed a ticket status for',
 view: 'viewed as student',
 'support-view-start': 'viewed as student',
 'banner-save': 'saved a banner draft',
 'banner-publish': 'published the banner',
 'banner-disable': 'took the banner down',
 'banner-rollback': 'rolled back the banner',
 'content-save': 'saved student-facing copy',
 'content-rollback': 'rolled back student-facing copy',
};
const SITE_WIDE = /^(banner|content)-/;

function renderAdminActivity(items, error = '') {
 const list = document.getElementById('admin-activity-list');
 if (!list) return;
 if (!items.length) {
  const message = error || 'No admin activity yet.';
  list.innerHTML = `<li class="info-text">${escapeHtml(message)}</li>`;
  return;
 }
 list.innerHTML = items.map((item) => {
  const action = ACTIVITY_WORDS[item.action] || String(item.action || '').replaceAll('-', ' ');
  const own = item.admin_username && item.admin_username === item.student_username;
  const who = SITE_WIDE.test(String(item.action || ''))
   ? (item.new_value ? ` (${escapeHtml(item.new_value)})` : '')
   : (own ? '' : ` <a href="#accounts/u/${escapeAttr(item.student_id)}">${escapeHtml(item.student_username || 'an account')}</a>`);
  return `<li><span class="library-manage-name">${escapeHtml(item.admin_username)} ${escapeHtml(action)}${who}</span>`
   + `<span class="help-text">${escapeHtml(item.created_at)}</span>`
   + `<p class="info-text">${escapeHtml(item.reason)}</p></li>`;
 }).join('');
}

// --- host --------------------------------------------------------------------

function mb(bytes) {
 const n = Number(bytes || 0);
 return n < 1024 * 1024 ? `${Math.round(n / 1024)} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function gb(bytes) {
 return `${(Number(bytes || 0) / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

async function loadHost() {
 const set = (id, v) => {
  const el = document.getElementById(id);
  if (el) el.textContent = String(v);
 };
 try {
  const h = await apiCall('/api/admin/host');
  const b = h.backup;
  set('host-backup', b ? `${b.age_hours < 48 ? `${Math.round(b.age_hours)} h ago` : `${Math.round(b.age_hours / 24)} days ago`} · ${mb(b.size_bytes)}` : 'none found');
  const w = h.watchdog;
  set('host-watchdog', w ? (w.healthy ? `OK · ${w.checked_at}` : `UNHEALTHY · ${w.checked_at}`) : 'no state file');
  set('host-watchdog-summary', w && w.summary ? w.summary : '');
  const d = h.disk;
  set('host-disk', d ? `${gb(d.free_bytes)} of ${gb(d.total_bytes)}` : '—');
  const l = h.laya || {};
  set('host-laya', l.state === 'up' ? (l.loaded ? 'up, model loaded' : 'up, idle') : (l.state === 'down' ? 'not answering' : 'not configured'));
  renderAi(h.ai || {});
 } catch (e) {
  set('host-status', e.message || 'Could not read host facts.');
 }
 try {
  const s = await apiCall('/api/ops/deploy-state');
  const r = s.record;
  set('host-ship', r
   ? `Last deploy ${String(r.sha || '').slice(0, 8)}${r.actor_username ? ` by ${r.actor_username}` : ''} at ${r.started_at || '?'} · ${s.in_flight ? `in flight (${s.phase})` : (r.result || s.phase || 'done')}${r.detail ? ` · ${r.detail}` : ''}`
   : 'No deploys recorded on this host.');
 } catch (e) {
  set('host-ship', e.message || 'Could not read the deploy state.');
 }
}

function renderAi(ai) {
 const line = document.getElementById('host-ai');
 if (line) {
  const models = (ai.ollama_models || []).join(', ');
  const running = `Ollama ${ai.ollama_running ? 'running' : 'stopped'}${models ? ` (${models})` : ''}`;
  line.textContent = ai.provider
   ? `${ai.provider === 'ollama' ? 'Built-in study aid' : `Cloud provider ${ai.provider}`} · ${running}${ai.detail ? ` · ${ai.detail}` : ''}`
   : `${ai.detail || 'No study aid configured.'} ${running}.`;
 }
 const start = document.getElementById('ollama-start');
 const stop = document.getElementById('ollama-stop');
 if (start) start.disabled = !ai.control_allowed || !!ai.ollama_running;
 if (stop) stop.disabled = !ai.control_allowed || !ai.ollama_running;
 const status = document.getElementById('host-ai-status');
 if (status && !ai.control_allowed) status.textContent = 'Process control is off on this host (AI_ALLOW_SETTINGS_WRITE / AI_ALLOW_OLLAMA_CONTROL).';
}

async function ollamaAct(kind) {
 const ok = await openSiteModal({
  mode: 'confirm',
  title: kind === 'start' ? 'Start the built-in study aid?' : 'Stop the built-in study aid?',
  message: kind === 'start'
   ? 'Starts Ollama on this host. Students can use Refine and Ask once it is up.'
   : 'Stops Ollama and frees its memory. A student\u2019s next Refine or Ask starts it again.',
  confirmLabel: kind === 'start' ? 'Start' : 'Stop',
 });
 if (!ok) return;
 const status = document.getElementById('host-ai-status');
 if (status) status.textContent = 'Working…';
 try {
  const d = await apiCall(`/api/ai/ollama/${kind}`, { method: 'POST', body: {} });
  const said = d.message || (d.ok ? 'Done.' : 'Failed.');
  if (status) status.textContent = said;
  showNotification(said, d.ok ? 'success' : 'error');
  await loadHost();
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
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
   ? d.tickets.map((t) => `<li><a class="library-manage-name" href="#tickets/t/${escapeAttr(t.id)}">${escapeHtml(TICKET_WORDS[t.status] || t.status)}</a>`
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

// --- tickets ---------------------------------------------------------------

function setTicketBadge(n) {
 const el = document.getElementById('tab-tickets-count');
 if (!el) return;
 el.textContent = String(n);
 el.hidden = !n;
}

async function listTickets(filter) {
 const status = document.getElementById('ticket-list-status');
 _ticketFilter = filter;
 document.querySelectorAll('[data-ticket-status]').forEach((btn) => {
  btn.classList.toggle('is-on', btn.dataset.ticketStatus === filter);
 });
 if (status) status.textContent = 'Loading…';
 try {
  const q = filter === 'all' ? '' : '?status=' + encodeURIComponent(filter);
  const d = await apiCall('/api/admin/tickets' + q);
  renderTicketList(d.tickets || []);
  if (filter === 'open') setTicketBadge((d.tickets || []).length);
  if (status) {
   status.textContent = (d.tickets || []).length
    ? `${d.tickets.length} ${filter === 'all' ? 'tickets' : TICKET_WORDS[filter] || filter}`
    : 'No tickets here.';
  }
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not list tickets';
 }
}

function renderTicketList(tickets) {
 const list = document.getElementById('ticket-list');
 if (!list) return;
 if (!tickets.length) {
  list.innerHTML = '<li class="info-text">No tickets in this list.</li>';
  return;
 }
 list.innerHTML = tickets.map((t) => {
  const active = _ticket && _ticket.id === t.id ? ' is-active' : '';
  const first = String(t.body || '').split('\n')[0].slice(0, 90);
  return `<li><button type="button" class="btn btn-secondary btn-block admin-user-btn${active}" data-ticket-id="${escapeAttr(t.id)}">`
   + `<span class="library-manage-name">${escapeHtml(t.student_username)}<br><span class="help-text">${escapeHtml(first)}</span></span>`
   + `<span class="help-text">${escapeHtml([TICKET_WORDS[t.status] || t.status, t.updated_at].filter(Boolean).join(' · '))}</span></button></li>`;
 }).join('');
 list.querySelectorAll('[data-ticket-id]').forEach((btn) => {
  btn.addEventListener('click', () => { location.hash = 'tickets/t/' + btn.getAttribute('data-ticket-id'); });
 });
}

async function openTicket(id) {
 const status = document.getElementById('ticket-action-status');
 if (status) status.textContent = 'Loading…';
 if (!_ticketFilter) listTickets('open');
 try {
  const t = await apiCall('/api/admin/tickets/' + encodeURIComponent(id));
  _ticket = t;
  renderTicket(t);
  if (status) status.textContent = '';
  document.querySelectorAll('#ticket-list [data-ticket-id]').forEach((btn) => {
   btn.classList.toggle('is-active', btn.getAttribute('data-ticket-id') === t.id);
  });
 } catch (e) {
  if (status) status.textContent = e.message || 'Could not load ticket';
 }
}

function renderTicket(t) {
 const panel = document.getElementById('ticket-detail');
 if (panel) panel.hidden = false;
 const title = document.getElementById('ticket-title');
 if (title) title.textContent = `${t.student_username}: ${String(t.body || '').split('\n')[0].slice(0, 70)}`;
 const badges = document.getElementById('ticket-badges');
 if (badges) {
  const cls = t.status === 'resolved' ? 'is-ok' : (t.status === 'open' ? 'is-warn' : '');
  badges.innerHTML = `<span class="admin-badge ${cls}">${escapeHtml(TICKET_WORDS[t.status] || t.status)}</span>`;
 }
 const meta = document.getElementById('ticket-meta');
 if (meta) {
  const ctx = t.context || {};
  const bits = [
   `opened ${t.created_at}`,
   ctx.route ? `on ${ctx.route}` : '',
   ctx.article_count != null ? `${ctx.article_count} papers, ${ctx.embedding_count || 0} prepared` : '',
   ctx.quota_limit_mb ? `${ctx.quota_used_mb || 0} of ${ctx.quota_limit_mb} MB` : '',
   ctx.job_fetch && ctx.job_fetch !== 'idle' ? `fetch ${ctx.job_fetch}` : '',
   ctx.job_embed && ctx.job_embed !== 'idle' ? `prepare ${ctx.job_embed}` : '',
   ctx.last_error ? `last error: ${ctx.last_error}` : '',
   ctx.app_version ? `v${ctx.app_version}` : '',
  ].filter(Boolean).join(' · ');
  meta.innerHTML = `${escapeHtml(bits)} · <a href="#accounts/u/${escapeAttr(t.student_id)}">open account</a>`;
 }
 const thread = document.getElementById('ticket-thread');
 if (thread) {
  const rows = [{ author_username: t.student_username, author_role: 'student', body: t.body, created_at: t.created_at }]
   .concat(t.replies || []);
  thread.innerHTML = rows.map((r) => `<li class="${r.author_role === 'admin' ? 'is-admin' : ''}">`
   + `<span class="admin-thread-who">${escapeHtml(r.author_username)} · ${escapeHtml(r.created_at)}</span>`
   + `<p>${escapeHtml(r.body)}</p></li>`).join('');
 }
 const sel = document.getElementById('ticket-status-select');
 if (sel) sel.value = t.status;
}

async function sendTicketReply() {
 if (!_ticket) return;
 const field = document.getElementById('ticket-reply-body');
 const text = String((field && field.value) || '').trim();
 if (!text) {
  showNotification('Write the reply first.', 'error');
  return;
 }
 const vals = await promptAction('Send reply', 'Emailed if the student has a verified address. The ticket moves to waiting on student.', {});
 if (!vals) return;
 await ticketPost(`/api/admin/tickets/${encodeURIComponent(_ticket.id)}/reply`, { reason: vals.reason, body: text }, (d) => {
  if (field) field.value = '';
  return d.emailed ? 'Reply sent and emailed.' : 'Reply sent.';
 });
}

async function setTicketStatus() {
 if (!_ticket) return;
 const sel = document.getElementById('ticket-status-select');
 const next = sel ? sel.value : '';
 if (!TICKET_STATUSES.includes(next)) return;
 if (next === _ticket.status) {
  showNotification(`Already ${TICKET_WORDS[next]}.`, 'info');
  return;
 }
 const vals = await promptAction('Set ticket status', `Marks this ticket ${TICKET_WORDS[next]}.`, {});
 if (!vals) return;
 await ticketPost(`/api/admin/tickets/${encodeURIComponent(_ticket.id)}/status`, { reason: vals.reason, status: next }, () => `Marked ${TICKET_WORDS[next]}.`);
}

async function ticketPost(url, body, said) {
 const status = document.getElementById('ticket-action-status');
 if (status) status.textContent = 'Working…';
 try {
  const d = await apiCall(url, { method: 'POST', body });
  const text = said(d);
  if (status) status.textContent = text;
  showNotification(text, 'success');
  await openTicket(_ticket.id);
  if (_ticketFilter) listTickets(_ticketFilter);
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
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
  renderRevisions(key, item);
 } catch (e) {
  const status = document.getElementById('content-status');
  if (status) status.textContent = e.message || 'Could not load copy.';
 }
}

function renderRevisions(key, item) {
 const current = document.getElementById('content-current');
 if (current) {
  current.textContent = item.revision
   ? `Revision ${item.revision} · ${item.updated_by || '?'} · ${item.updated_at || ''}`
   : 'Never set; students see the built-in default.';
 }
 const list = document.getElementById('content-revisions');
 if (!list) return;
 const revs = item.revisions || [];
 if (!revs.length) {
  list.innerHTML = '<li class="info-text">No revisions yet.</li>';
  return;
 }
 list.innerHTML = revs.map((r, i) => {
  const first = String(r.body || '').split('\n')[0].slice(0, 80);
  const tag = i === 0
   ? '<span class="admin-badge is-ok">current</span>'
   : `<button type="button" class="btn btn-secondary btn-sm" data-revision="${escapeAttr(r.id)}">Roll back to this</button>`;
  return `<li><span class="library-manage-name">${escapeHtml(r.created_at)} · ${escapeHtml(r.actor || '?')}<br><span class="help-text">${escapeHtml(first)}</span></span>${tag}</li>`;
 }).join('');
 list.querySelectorAll('[data-revision]').forEach((btn) => {
  btn.addEventListener('click', () => rollbackContent(key, btn.getAttribute('data-revision')));
 });
}

async function rollbackContent(key, revisionId) {
 const status = document.getElementById('content-status');
 const vals = await promptAction('Roll back student-facing copy', `Restores an earlier revision of ${key} as a new revision. Students see it at once.`, {});
 if (!vals) return;
 try {
  await apiCall(`/api/admin/content/${encodeURIComponent(key)}/rollback`, {
   method: 'POST',
   body: { reason: vals.reason, revision_id: revisionId },
  });
  if (status) status.textContent = 'Rolled back.';
  showNotification('Copy rolled back.', 'success');
  await loadContentKey();
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
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
  await loadContentKey();
 } catch (e) {
  if (status) status.textContent = e.message || 'Failed';
  showNotification(e.message || 'Failed', 'error');
 }
}
