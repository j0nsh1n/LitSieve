// === Join shared library page ===

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('join-code-input');
  const previewBtn = document.getElementById('join-preview-btn');
  const confirmBtn = document.getElementById('join-confirm-btn');
  if (previewBtn) previewBtn.addEventListener('click', doPreview);
  if (confirmBtn) confirmBtn.addEventListener('click', doJoin);
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        doPreview();
      }
    });
    // Auto-preview when opened with ?code=
    if ((input.value || '').trim()) {
      doPreview();
    }
  }
});

function normalizeCodeLocal(raw) {
  let c = (raw || '').trim().toUpperCase().replace(/\s+/g, '');
  if (c.length === 8 && c.indexOf('-') < 0) {
    c = c.slice(0, 4) + '-' + c.slice(4);
  }
  return c;
}

async function doPreview() {
  const input = document.getElementById('join-code-input');
  const card = document.getElementById('join-preview-card');
  const confirmBtn = document.getElementById('join-confirm-btn');
  const code = normalizeCodeLocal(input && input.value);
  if (input) input.value = code;
  if (!code) {
    setStatus('join-status', 'Enter a class code first.', 'error');
    return;
  }
  setStatus('join-status', 'Loading preview…', 'info');
  if (confirmBtn) confirmBtn.disabled = true;
  try {
    const data = await apiCall(`/api/shares/preview?code=${encodeURIComponent(code)}`);
    renderPreview(data);
    setStatus('join-status', data.can_join ? 'Looks good — confirm to add a copy to your account.' : (data.block_reason || 'Cannot join.'), data.can_join ? 'success' : 'error');
    if (confirmBtn) confirmBtn.disabled = !data.can_join;
  } catch (e) {
    if (card) {
      card.hidden = true;
      card.innerHTML = '';
    }
    setStatus('join-status', e.message, 'error');
    if (confirmBtn) confirmBtn.disabled = true;
  }
}

function renderPreview(data) {
  const card = document.getElementById('join-preview-card');
  if (!card) return;
  const emb = data.include_embeddings && data.has_embeddings
    ? 'Embeddings included (search ready)'
    : (data.include_embeddings ? 'No embeddings yet (you may need Prepare papers)' : 'Embeddings not included');
  const exp = data.expires_at
    ? `Expires ${escapeHtml(String(data.expires_at).replace('T', ' ').replace('Z', ' UTC'))}`
    : 'No expiry';
  const uses = data.max_uses != null
    ? `${data.use_count || 0} / ${data.max_uses} uses`
    : `${data.use_count || 0} joins so far`;
  card.hidden = false;
  card.innerHTML = `
    <h3 class="join-preview-title">${escapeHtml(data.title || 'Shared library')}</h3>
    <p class="info-text" style="margin:0.35rem 0;">From <strong>${escapeHtml(data.owner_username || 'teacher')}</strong>
      · code <code>${escapeHtml(data.code || '')}</code></p>
    <ul class="join-preview-stats">
      <li><strong>${Number(data.article_count) || 0}</strong> papers</li>
      <li><strong>${Number(data.excluded_count) || 0}</strong> screened out (kept in copy)</li>
      <li>${escapeHtml(emb)}</li>
      <li>${escapeHtml(exp)} · ${escapeHtml(uses)}</li>
    </ul>
  `;
}

async function doJoin() {
  const input = document.getElementById('join-code-input');
  const btn = document.getElementById('join-confirm-btn');
  const code = normalizeCodeLocal(input && input.value);
  if (!code) {
    setStatus('join-status', 'Enter a class code first.', 'error');
    return;
  }
  setLoading(btn, true);
  setStatus('join-status', 'Copying library into your account…', 'info');
  try {
    const data = await apiCall('/api/shares/join', {
      method: 'POST',
      body: { code },
    });
    const name = (data.library && data.library.name) || 'library';
    const n = (data.counts && data.counts.articles) || 0;
    setStatus('join-status', `Added "${name}" (${n} papers). Opening Data Management…`, 'success');
    showNotification(`Joined: ${name}`, 'success');
    window.location.href = '/data-management';
  } catch (e) {
    setStatus('join-status', e.message, 'error');
    showNotification(e.message, 'error');
    setLoading(btn, false);
  }
}
