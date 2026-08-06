// === Topic and source definitions ===
// Fallbacks used if GET /api/sources fails. Canonical data lives in source_catalog.py.
let TOPICS = [
 { id: 'health', name: 'Health & Medicine', icon: '🏥', sources: ['pubmed', 'europepmc', 'clinicaltrials', 'medrxiv', 'plos', 'openalex', 'semanticscholar', 'doaj', 'zenodo'] },
 { id: 'biology', name: 'Biology', icon: '🧬', sources: ['pubmed', 'europepmc', 'biorxiv', 'plos', 'openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj'] },
 { id: 'chemistry', name: 'Chemistry', icon: '⚗️', sources: ['openalex', 'arxiv', 'semanticscholar', 'crossref', 'zenodo', 'doaj', 'openaire'] },
 { id: 'physics', name: 'Physics', icon: '⚛️', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'nasa_ads', 'openaire'] },
 { id: 'math', name: 'Mathematics', icon: '📐', sources: ['arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'openaire'] },
 { id: 'cs', name: 'Computer Science', icon: '💻', sources: ['dblp', 'arxiv', 'openalex', 'semanticscholar', 'crossref', 'zenodo', 'doaj', 'openaire'] },
 { id: 'earth', name: 'Earth & Environment', icon: '🌍', sources: ['openalex', 'semanticscholar', 'zenodo', 'crossref', 'doaj', 'nasa_ads', 'openaire', 'hal'] },
 { id: 'history', name: 'History', icon: '📜', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'hal', 'openaire'] },
 { id: 'economics', name: 'Economics', icon: '📊', sources: ['arxiv', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'openaire'] },
 { id: 'psychology', name: 'Psychology', icon: '🧠', sources: ['pubmed', 'openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'openaire'] },
 { id: 'polisci', name: 'Political Science', icon: '🏛️', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'hal', 'openaire'] },
 { id: 'literature', name: 'Literature & Language',icon: '📖', sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'hal', 'openaire'] },
 { id: 'education', name: 'Education', icon: '🎓', sources: ['eric', 'openalex', 'semanticscholar', 'crossref', 'doaj', 'hal', 'openaire'] },
];

let TOPIC_PACKS = [
 {
 id: 'pack_climate',
 name: 'Climate unit',
 icon: '🌡️',
 blurb: 'Earth & environment sources for climate projects',
 topics: ['earth'],
 sources: ['openalex', 'semanticscholar', 'nasa_ads', 'zenodo', 'crossref', 'doaj', 'openaire'],
 queryHint: 'climate change impacts on ecosystems',
 },
 {
 id: 'pack_health_ed',
 name: 'Health education',
 icon: '❤️',
 blurb: 'Health + classroom education databases',
 topics: ['health', 'education'],
 sources: ['pubmed', 'europepmc', 'eric', 'openalex', 'semanticscholar', 'plos', 'doaj'],
 queryHint: 'school-based health education programs',
 },
 {
 id: 'pack_history',
 name: 'History unit',
 icon: '📜',
 blurb: 'History and social-science open sources',
 topics: ['history'],
 sources: ['openalex', 'semanticscholar', 'eric', 'crossref', 'doaj', 'hal', 'openaire'],
 queryHint: 'civil rights movement oral history',
 },
 {
 id: 'pack_cs_intro',
 name: 'CS intro',
 icon: '💻',
 blurb: 'CS bibliography + arXiv (many DBLP hits lack abstracts)',
 topics: ['cs'],
 sources: ['dblp', 'arxiv', 'openalex', 'semanticscholar', 'crossref', 'doaj'],
 queryHint: 'introductory computer science education',
 },
];

/** @type {Record<string, {name:string, desc:string, tip?:string, good_for?:string, misses?:string, badges?:string[], needs_key?:boolean}>} */
let ALL_SOURCES = {
 pubmed: { name: 'PubMed', desc: 'Biomedical & life sciences', tip: 'Strong for health/biology abstracts.' },
 europepmc: { name: 'Europe PMC', desc: 'European biomedical literature', tip: 'Biomedical; may overlap PubMed.' },
 clinicaltrials: { name: 'ClinicalTrials.gov', desc: 'Clinical trial registrations', tip: 'Trial registries, not journal articles.' },
 openalex: { name: 'OpenAlex', desc: 'Broad multi-discipline academic', tip: 'Best all-round free starter.' },
 arxiv: { name: 'arXiv', desc: 'Physics, math, CS, econ preprints', tip: 'Preprints — not always peer-reviewed yet.', badges: ['preprint'] },
 semanticscholar: { name: 'Semantic Scholar', desc: 'AI-curated cross-discipline research', tip: 'Strong free cross-discipline search.' },
 eric: { name: 'ERIC', desc: 'Education, psychology, social sciences', tip: 'Best free education database.' },
 zenodo: { name: 'Zenodo', desc: 'Open science: all fields + datasets', tip: 'Open deposits (papers + data).' },
 crossref: { name: 'CrossRef', desc: 'Broad academic metadata registry', tip: 'Huge DOI registry; skips no-abstract items.' },
 doaj: { name: 'DOAJ', desc: 'Peer-reviewed open access journals', tip: 'Peer-reviewed open access journals.' },
 nasa_ads: { name: 'NASA ADS', desc: 'Astronomy, astrophysics & geosciences', tip: 'Space & geoscience (token required).', needs_key: true },
 biorxiv: { name: 'bioRxiv', desc: 'Biology preprints', tip: 'Not peer-reviewed; recent window only.', badges: ['preprint', 'not-peer-reviewed'] },
 medrxiv: { name: 'medRxiv', desc: 'Health preprints', tip: 'Not peer-reviewed; recent window only.', badges: ['preprint', 'not-peer-reviewed'] },
 dblp: { name: 'DBLP', desc: 'Computer science papers & conferences', tip: 'Title/venue often; many abstracts skipped.', badges: ['title-only'] },
 openaire: { name: 'OpenAIRE', desc: 'European open research aggregator', tip: 'European open research graph.' },
 plos: { name: 'PLOS', desc: 'Fully open-access science journals', tip: 'Open-access science journals.' },
 hal: { name: 'HAL', desc: 'French national open archive (multi-discipline)', tip: 'French open archive; language mix varies.' },
};

/** Apply server catalog (source_catalog.py) so tips / topics / packs cannot drift. */
async function loadSourceCatalog() {
 try {
 const data = await fetch('/api/sources', {
 headers: { Accept: 'application/json' },
 credentials: 'same-origin',
 }).then((r) => (r.ok ? r.json() : null));
 if (data && Array.isArray(data.sources) && data.sources.length) {
 const next = {};
 const names = window.LRA_SOURCE_NAMES || {};
 data.sources.forEach((s) => {
 if (!s || !s.id) return;
 next[s.id] = {
 name: s.name || s.id,
 desc: s.desc || '',
 tip: s.tip || '',
 good_for: s.good_for || '',
 misses: s.misses || '',
 badges: s.badges || [],
 needs_key: !!s.needs_key,
 };
 names[s.id] = s.name || s.id;
 });
 ALL_SOURCES = next;
 window.LRA_SOURCE_NAMES = names;
 }
 if (data && Array.isArray(data.topics) && data.topics.length) {
 TOPICS = data.topics.map((t) => ({
 id: t.id,
 name: t.name,
 icon: t.icon || '',
 sources: t.sources || [],
 }));
 }
 if (data && Array.isArray(data.packs) && data.packs.length) {
 TOPIC_PACKS = data.packs.map((p) => ({
 id: p.id,
 name: p.name,
 icon: p.icon || '',
 blurb: p.blurb || '',
 topics: p.topics || [],
 sources: p.sources || [],
 queryHint: p.queryHint || p.query_hint || '',
 }));
 }
 } catch (e) {
 // Keep hardcoded fallbacks.
 }
}

// Which analysis model suits each topic. Mixed categories fall back to
// 'general' (fast and neutral). Advanced dropdown always overrides.
const TOPIC_MODEL = {
 health: 'pubmedbert', biology: 'pubmedbert', psychology: 'pubmedbert',
 chemistry: 'specter', physics: 'specter', math: 'specter', cs: 'specter', earth: 'specter',
 history: 'general', economics: 'general', polisci: 'general',
 literature: 'general', education: 'general',
};

const MODEL_LABELS = {
 general: 'general (fast, any topic)',
 mpnet: 'mpnet (best general quality)',
 pubmedbert: 'pubmedbert (biomedical)',
 biosentbert: 'biosentbert (medical)',
 specter: 'specter (scientific papers)',
 multiqa: 'multiqa (question-style queries)',
 multilingual: 'multilingual (non-English collections)',
};

const FETCH_PREFS_KEY = 'lra_fetch_prefs_v1';

let selectedTopics = new Set();
let modelManual = false; // true once the user picks a model under Advanced

document.addEventListener('DOMContentLoaded', () => {
 // Catalog first so tips/topics match source_catalog.py (Phase R4).
 loadSourceCatalog().finally(() => {
 renderTopicGrid();
 renderTopicPacks();
 renderSourceGrid();
 restoreFetchPrefs();
 loadPageData();
 refreshCoverage();
 });
 // Simple: hide optional prepare card until the library has papers.
 // Re-evaluate when the mode toggle flips (common.js sets data-mode first).
 const modeBtn = document.getElementById('mode-toggle');
 if (modeBtn) {
  modeBtn.addEventListener('click', () => {
   queueAnimationFrame(() => updatePrepareSectionVisibility(_lastTotalArticles));
  });
 }
 // Start hidden in Simple until stats load (avoids a flash of step 4 on empty libs).
 updatePrepareSectionVisibility(0);
 document.getElementById('fetch-btn').addEventListener('click', doFetch);
 const cancelBtn = document.getElementById('fetch-cancel-btn');
 if (cancelBtn) cancelBtn.addEventListener('click', cancelFetch);
 document.getElementById('embeddings-btn').addEventListener('click', doCreateEmbeddings);
 document.getElementById('coverage-refresh').addEventListener('click', refreshCoverage);
 const dismissGs = document.getElementById('dismiss-getting-started');
 if (dismissGs) dismissGs.addEventListener('click', () => {
 if (typeof dismissGettingStarted === 'function') dismissGettingStarted();
 });
 const sampleBtn = document.getElementById('load-sample-btn');
 if (sampleBtn) sampleBtn.addEventListener('click', () => loadSampleCorpus(true));
 // Live checklist ticks as the student fills the form.
 ['fetch-query'].forEach(id => {
 const el = document.getElementById(id);
 if (el) el.addEventListener('input', updateGettingStartedChecklist);
 });

    // Persist prefs as the user edits.
 ['fetch-query', 'fetch-max', 'fetch-email', 'embedding-model'].forEach(id => {
 const el = document.getElementById(id);
 if (el) el.addEventListener('change', saveFetchPrefs);
 });
    // A hand-picked model overrides the automatic topic-based choice.
 document.getElementById('embedding-model').addEventListener('change', () => {
 modelManual = true;
 updateModelHint();
 saveFetchPrefs();
 });
 updateModelHint();
 document.querySelectorAll('input[name="fetch-mode"]').forEach(el => {
 el.addEventListener('change', () => {
            // Append → prefer only-new; Replace → re-embed all by default.
 syncOnlyMissingFromFetchMode();
 saveFetchPrefs();
 });
 });
 const onlyMissingEl = document.getElementById('only-missing');
 if (onlyMissingEl) {
 onlyMissingEl.addEventListener('change', saveFetchPrefs);
 }
    // Initial state from default (or restored) fetch mode.
 syncOnlyMissingFromFetchMode();
});

/**
 * Auto-check "Only embed new papers" only when fetch mode is append
 * ("Add to collection"). Replace mode unchecks it so a clean corpus
 * gets fully embedded. User can still toggle manually afterward.
 */
function syncOnlyMissingFromFetchMode() {
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const box = document.getElementById('only-missing');
 if (!box) return;
 box.checked = mode === 'append';
 const hint = document.getElementById('only-missing-hint');
 if (hint) {
 hint.textContent = mode === 'append'
 ? 'On because you chose “Add to collection” - already-prepared papers are kept.'
 : 'Off for “Replace collection” - all papers will be prepared. Switch to Add to auto-check this.';
 }
}

function renderTopicGrid() {
 const grid = document.getElementById('topic-grid');
 if (!grid) return;
 TOPICS.forEach(topic => {
 const card = document.createElement('div');
 card.className = 'topic-card';
 card.dataset.topicId = topic.id;
 card.innerHTML = `<span class="topic-icon">${topic.icon}</span><span class="topic-name">${topic.name}</span>`;
 card.addEventListener('click', () => toggleTopic(topic.id, card));
 grid.appendChild(card);
 });
}

function renderTopicPacks() {
 const grid = document.getElementById('topic-pack-grid');
 if (!grid) return;
 TOPIC_PACKS.forEach(pack => {
 const card = document.createElement('button');
 card.type = 'button';
 card.className = 'topic-pack-card';
 card.dataset.packId = pack.id;
 card.title = pack.blurb || pack.name;
 card.innerHTML = `
 <span class="topic-icon">${pack.icon}</span>
 <span class="topic-pack-text">
 <span class="topic-name">${pack.name}</span>
 <span class="topic-pack-blurb">${pack.blurb || ''}</span>
 </span>
 `;
 card.addEventListener('click', () => applyTopicPack(pack.id));
 grid.appendChild(card);
 });
}

/** One-click classroom pack: select topics + pre-check suggested sources. */
function applyTopicPack(packId) {
 const pack = TOPIC_PACKS.find(p => p.id === packId);
 if (!pack) return;
 selectedTopics = new Set(pack.topics || []);
 document.querySelectorAll('#topic-grid .topic-card').forEach(card => {
 card.classList.toggle('selected', selectedTopics.has(card.dataset.topicId));
 });
 // Pre-check pack sources (replace current checkboxes for a clean unit start).
 Object.keys(ALL_SOURCES).forEach(sourceId => {
 const checkbox = document.getElementById(`source-${sourceId}`);
 if (!checkbox) return;
 const on = (pack.sources || []).includes(sourceId);
 checkbox.checked = on;
 const option = checkbox.closest('.source-option');
 if (option) option.classList.toggle('recommended', on);
 });
 const hint = document.getElementById('source-hint');
 if (hint) {
 hint.textContent = `Pack “${pack.name}”: suggested sources are checked. Adjust as needed.`;
 }
 const q = document.getElementById('fetch-query');
 if (q && !q.value.trim() && pack.queryHint) {
 q.placeholder = `e.g., ${pack.queryHint}`;
 }
 applyModelRecommendation();
 saveFetchPrefs();
 refreshCoverage();
 updateGettingStartedChecklist();
 showNotification(`Applied pack: ${pack.name}`, 'success');
}

function toggleTopic(topicId, card) {
 if (selectedTopics.has(topicId)) {
 selectedTopics.delete(topicId);
 card.classList.remove('selected');
 } else {
 selectedTopics.add(topicId);
 card.classList.add('selected');
 }
 updateRecommendedSources();
 applyModelRecommendation();
 saveFetchPrefs();
 refreshCoverage();
}

/** Model that best matches the selected topics ('general' when mixed or none). */
function recommendModel() {
 if (selectedTopics.size === 0) return 'general';
 const models = new Set([...selectedTopics].map(t => TOPIC_MODEL[t] || 'general'));
 return models.size === 1 ? models.values().next().value : 'general';
}

/** Set the model dropdown from the topic recommendation unless the user chose one by hand. */
function applyModelRecommendation() {
 if (!modelManual) {
 document.getElementById('embedding-model').value = recommendModel();
 }
 updateModelHint();
}

function updateModelHint() {
 const hint = document.getElementById('model-auto-hint');
 if (!hint) return;
 const sel = document.getElementById('embedding-model');
 const current = MODEL_LABELS[sel.value] || sel.value;
 const rec = recommendModel();
 const corpus = window._corpusEmbeddingModel || null;
 hint.innerHTML = '';
 if (modelManual) {
 hint.append(`Analysis model chosen by hand: ${current}. `);
 const reset = document.createElement('a');
 reset.href = '#';
 reset.textContent = 'Switch back to automatic';
 reset.addEventListener('click', (e) => {
 e.preventDefault();
 modelManual = false;
 applyModelRecommendation();
 saveFetchPrefs();
 });
 hint.append(reset, '.');
 } else if (selectedTopics.size) {
 hint.append(`Analysis model for your topics: ${current}. Change it under Advanced if you want.`);
 } else {
 hint.append(`Analysis model: ${current}. Select topics above to pick one automatically, or change it under Advanced.`);
 }
 // Note when prepared papers use a different model (re-prepare will re-embed all).
 if (corpus && corpus !== sel.value) {
 hint.append(
 ` Papers already prepared with ${MODEL_LABELS[corpus] || corpus} — ` +
 `press Prepare Papers to rebuild with ${current} (full re-run).`
 );
 }
}

function updateRecommendedSources() {
 const recommended = new Set();
 selectedTopics.forEach(topicId => {
 const topic = TOPICS.find(t => t.id === topicId);
 if (topic) topic.sources.forEach(s => recommended.add(s));
 });

 const hint = document.getElementById('source-hint');
 hint.textContent = selectedTopics.size === 0
 ? 'Select topics above to see recommended sources, or choose manually below.'
 : 'Sources recommended for your selected topics are checked. Adjust as needed.';

 Object.keys(ALL_SOURCES).forEach(sourceId => {
 const checkbox = document.getElementById(`source-${sourceId}`);
 if (!checkbox) return;
 if (selectedTopics.size > 0) {
 checkbox.checked = recommended.has(sourceId);
 }
 const card = checkbox.closest('.source-option');
 if (card) card.classList.toggle('recommended', selectedTopics.size > 0 && recommended.has(sourceId));
 });
}

function renderSourceGrid() {
 const grid = document.getElementById('source-option-grid');
 if (!grid) return;
 Object.entries(ALL_SOURCES).forEach(([id, info]) => {
 const label = document.createElement('label');
 label.className = 'source-option';
 if (info.badges && info.badges.length) {
 label.classList.add(...info.badges.map(b => `src-badge-${b}`));
 }
 const badges = info.badges || [];
 const chipParts = [];
 if (badges.includes('preprint') || badges.includes('not-peer-reviewed')) {
 chipParts.push(
 '<span class="source-chip source-chip-preprint" title="Not peer-reviewed / recent window only">Not peer-reviewed</span>'
 );
 }
 if (badges.includes('title-only')) {
 chipParts.push(
 '<span class="source-chip source-chip-titleonly" title="Many records are title/venue only">Title/venue</span>'
 );
 }
 const chips = chipParts.join('');
 // Student tip: good for / what it misses (Phase R4).
 let tipText = info.tip || '';
 if (!tipText && (info.good_for || info.misses)) {
 tipText = [info.good_for, info.misses ? `Misses: ${info.misses}` : '']
 .filter(Boolean).join(' ');
 }
 if (info.needs_key && tipText && !/key|token/i.test(tipText)) {
 tipText += ' (free API key may be required on the server.)';
 }
 const tipHtml = tipText
 ? `<span class="source-tip" title="${escapeHtml(tipText)}"><strong>Student tip:</strong> ${escapeHtml(tipText)}</span>`
 : '';
 label.innerHTML = `
 <input type="checkbox" id="source-${id}" value="${id}">
 <div class="source-info">
 <span class="source-name-row">
 <span class="source-name-label">${escapeHtml(info.name)}</span>
 ${chips}
 </span>
 <span class="source-desc">${escapeHtml(info.desc || '')}</span>
 ${tipHtml}
 </div>
 `;
 label.querySelector('input').addEventListener('change', saveFetchPrefs);
 grid.appendChild(label);
 });
}

function saveFetchPrefs() {
 const sources = Array.from(
 document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
 ).map(cb => cb.value);
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const prefs = {
 query: document.getElementById('fetch-query').value,
 max: document.getElementById('fetch-max').value,
 email: document.getElementById('fetch-email').value,
 sources,
 mode,
 topics: [...selectedTopics],
 model: document.getElementById('embedding-model').value,
 modelManual,
 onlyMissing: document.getElementById('only-missing').checked,
 };
 try { localStorage.setItem(FETCH_PREFS_KEY, JSON.stringify(prefs)); } catch (e) { /* ignore */ }
}

function restoreFetchPrefs() {
 let prefs;
 try { prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null'); } catch (e) { prefs = null; }
 if (!prefs) return;
 if (prefs.query) document.getElementById('fetch-query').value = prefs.query;
 if (prefs.max) document.getElementById('fetch-max').value = prefs.max;
 if (prefs.email) document.getElementById('fetch-email').value = prefs.email;
 if (prefs.model) document.getElementById('embedding-model').value = prefs.model;
 modelManual = !!prefs.modelManual;
 if (prefs.mode) {
 const radio = document.querySelector(`input[name="fetch-mode"][value="${prefs.mode}"]`);
 if (radio) radio.checked = true;
 }
    // Derive only-missing from fetch mode (append → on, replace → off).
    // Do this after mode restore so it stays consistent.
 syncOnlyMissingFromFetchMode();
 if (Array.isArray(prefs.topics)) {
 prefs.topics.forEach(tid => {
 selectedTopics.add(tid);
 const card = document.querySelector(`.topic-card[data-topic-id="${tid}"]`);
 if (card) card.classList.add('selected');
 });
 updateRecommendedSources();
 }
 if (Array.isArray(prefs.sources) && prefs.sources.length) {
 Object.keys(ALL_SOURCES).forEach(id => {
 const cb = document.getElementById(`source-${id}`);
 if (cb) cb.checked = prefs.sources.includes(id);
 });
 }
 updateModelHint();
}

/** Last known article count (for Simple-mode prepare section + mode toggles). */
let _lastTotalArticles = 0;
/** True while fetch→prepare auto-chain is running (keeps prepare card visible). */
let _autoChainActive = false;

/**
 * Simple mode: prepare is optional and only appears once the library has papers.
 * Advanced: always visible (step 4). forceShow / auto-chain keep it open mid-job.
 */
/** Show the "Next: Clean up" shortcut once papers are actually ready.
 *
 * Only in Simple mode: Advanced users have the numbered steps and the nav.
 * Hidden again whenever a new fetch starts, so it never advertises a next step
 * for work that is still running.
 */
function setNextStepVisible(visible) {
 const el = document.getElementById('fetch-next-step');
 if (!el) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 el.hidden = !(visible && simple);
 el.classList.toggle('u-hidden', !(visible && simple));
}

function updatePrepareSectionVisibility(totalArticles, opts) {
 const sec = document.getElementById('prepare-section');
 if (!sec) return;
 if (typeof totalArticles === 'number' && !Number.isNaN(totalArticles)) {
  _lastTotalArticles = totalArticles;
 }
 // Deliberately NOT force-shown while the auto-chain runs. Prepare progress is
 // mirrored onto the fetch bar during a chain (see doCreateEmbeddings), so the
 // card has nothing to display yet -- revealing it mid-embed just pops a
 // "Re-prepare" control into view for work that is still in progress.
 const forceShow = !!(opts && opts.forceShow);
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 if (!simple) {
  sec.hidden = false;
  return;
 }
 sec.hidden = _autoChainActive || (!forceShow && !(_lastTotalArticles > 0));
}

async function loadPageData() {
 try {
 const stats = await apiCall('/api/statistics');
 const model = stats.embedding_model || ' - ';
 const total = stats.total_articles || 0;
 const missing = stats.missing_embeddings ?? Math.max(0, total - (stats.articles_with_embeddings || 0));
 document.getElementById('embedding-info').textContent =
 `${stats.articles_with_embeddings} of ${total} papers are ready for search` +
 (stats.articles_with_embeddings ? ` (model: ${model})` : '') +
 (missing ? ` · ${missing} still need preparing` : '') + '.';
 // Topic recommendation drives the dropdown (unless the user overrode it).
 // Do NOT force the corpus's stored model into the select — that made
 // pubmedbert "stick" after a biomedical prep even when topics say specter.
 window._corpusEmbeddingModel = stats.embedding_model || null;
 applyModelRecommendation();
 updateGettingStartedCard(total);
 updatePrepareSectionVisibility(total);
 } catch (e) {
 document.getElementById('embedding-info').textContent = 'Unable to load article info.';
 updateGettingStartedCard(0);
 updatePrepareSectionVisibility(0);
 }
}

function updateGettingStartedCard(totalArticles) {
 const card = document.getElementById('getting-started-card');
 if (!card) return;
 // Hide once the user has any papers, or if they dismissed it.
 if (totalArticles > 0 || (typeof isGettingStartedDismissed === 'function' && isGettingStartedDismissed())) {
 card.hidden = true;
 return;
 }
 card.hidden = false;
 updateGettingStartedChecklist();
}

function updateGettingStartedChecklist() {
 const card = document.getElementById('getting-started-card');
 if (!card || card.hidden) return;
 const hasTopics = selectedTopics.size > 0;
 const query = (document.getElementById('fetch-query') || {}).value || '';
 const hasQuery = query.trim().length >= 3;
 const steps = {
 topics: hasTopics,
 query: hasQuery,
 fetch: false, // completed only after a successful fetch (collection non-empty)
 };
 card.querySelectorAll('.getting-started-list li').forEach(li => {
 const key = li.getAttribute('data-step');
 const done = !!steps[key];
 li.classList.toggle('is-done', done);
 const mark = li.querySelector('.gs-check');
 if (mark) mark.textContent = done ? '●' : '○';
 });
}

async function loadSampleCorpus(clearFirst) {
 const btn = document.getElementById('load-sample-btn');
 if (btn) setLoading(btn, true);
 try {
 const data = await apiCall('/api/load-sample-corpus', {
 method: 'POST',
 body: { clear_first: !!clearFirst },
 });
 showNotification(
 `Loaded ${data.inserted || data.loaded || 0} sample papers. Press Prepare Papers when you are ready.`,
 'success'
 );
 await loadPageData();
 refreshCoverage();
 updateNavStats();
 applyModelRecommendation();
 setStatus(
 'embeddings-status',
 'Sample papers loaded. Choose a model if needed, then press Prepare Papers.',
 'info'
 );
 } catch (e) {
 showNotification(`Could not load sample corpus: ${e.message}`, 'error');
 } finally {
 if (btn) setLoading(btn, false);
 }
}

async function cancelFetch() {
 const btn = document.getElementById('fetch-cancel-btn');
 if (btn) btn.disabled = true;
 try {
 await apiCall('/api/jobs/fetch/cancel', { method: 'POST', body: {} });
 showNotification('Cancel requested — finishing the current source…', 'info');
 } catch (e) {
 showNotification(`Could not cancel: ${e.message}`, 'error');
 if (btn) btn.disabled = false;
 }
}

async function refreshCoverage() {
 const bars = document.getElementById('coverage-bars');
 const sug = document.getElementById('coverage-suggestions');
 try {
 const data = await apiCall('/api/coverage', {
 method: 'POST',
 body: { topics: [...selectedTopics] },
 });
 const sources = data.sources || {};
 const keys = Object.keys(sources);
 bars.innerHTML = '';
 if (!keys.length) {
 bars.innerHTML = '<p class="info-text">No articles yet - run a fetch to fill the map.</p>';
 } else {
 const maxCount = Math.max(...Object.values(sources), 1);
 keys.sort((a, b) => sources[b] - sources[a]).forEach(src => {
 const count = sources[src];
 const pct = (count / maxCount) * 100;
 const div = document.createElement('div');
 div.className = 'source-bar';
 div.innerHTML = `
 <span class="source-name">${escapeHtml(getSourceName(src))}</span>
 <div class="source-bar-fill">
 <div class="source-track">
 <div class="source-bar-inner" style="width: ${pct}%"></div>
 </div>
 </div>
 <span class="source-count">${count}</span>
 `;
 bars.appendChild(div);
 });
 }
 const suggestions = data.suggestions || [];
 if (suggestions.length) {
 const items = suggestions.map((s) => {
 const name = escapeHtml(s.name || getSourceName(s.source));
 const tip = escapeHtml(s.tip || s.reason || '');
 return `<li class="coverage-suggest-item"><strong>${name}</strong>`
 + (tip ? `<span class="source-tip">${tip}</span>` : '')
 + `</li>`;
 }).join('');
 sug.innerHTML = '<strong>Suggested sources you are missing:</strong>'
 + `<ul class="coverage-suggest-list">${items}</ul>`
 + '<p class="help-text" style="margin-top:0.4rem;">Check them under Choose Sources on the next fetch.</p>';
 } else if (keys.length) {
 sug.textContent = selectedTopics.size
 ? 'Coverage looks good for your selected topics - recommended sources each have at least one paper.'
 : 'Select topics above for more specific coverage suggestions.';
 } else {
 sug.textContent = '';
 }
 } catch (e) {
 bars.innerHTML = '<p class="info-text">Could not load coverage.</p>';
 sug.textContent = '';
 }
}

// === Progress polling (jobs return 202; UI waits on /api/progress) ===
// Must see active=true at least once before accepting a finished result — otherwise
// a poll that lands before the job flips active (or sees a stale idle slot) resolves
// with {} and the auto-chain never starts prepare.
function waitForJob(task, fillId, labelId, wrapId, formatLabel, timeoutMs = 600000) {
 return new Promise((resolve, reject) => {
 const fill = document.getElementById(fillId);
 const label = document.getElementById(labelId);
 const wrap = document.getElementById(wrapId);
 if (wrap) wrap.style.display = 'block';
 if (fill) fill.style.width = '0%';
 const started = Date.now();
 let sawActive = false;
 let settled = false;

 const finish = (err, result) => {
  if (settled) return;
  settled = true;
  clearInterval(interval);
  if (fill) fill.style.width = err ? '0%' : '100%';
  if (wrap) {
   setTimeout(() => {
    wrap.style.display = 'none';
    if (fill) fill.style.width = '0%';
   }, 800);
  }
  if (err) reject(err);
  else resolve(result || {});
 };

 const tick = async () => {
  try {
   if (Date.now() - started > timeoutMs) {
    finish(new Error('Timed out waiting for the job to finish'));
    return;
   }
   const data = await apiCall('/api/progress');
   const p = data[task];
   if (!p) return;
   if (p.active) {
    sawActive = true;
    const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
    if (fill) fill.style.width = pct + '%';
    if (label) {
     label.textContent = p.message
      ? p.message
      : (typeof formatLabel === 'function' ? formatLabel(p.done, p.total, pct, p) : '');
    }
    return;
   }
   // Idle: only finish after we observed this job running, or after a short
   // grace if the job completed between 202 and the first poll.
   if (p.error) {
    finish(new Error(p.error));
    return;
   }
   if (sawActive) {
    finish(null, p.result || {});
    return;
   }
   // Not yet active and never was — keep waiting (job may still be starting).
   if (Date.now() - started > 8000 && p.result) {
    // Job finished so fast we never saw active=true; accept result.
    finish(null, p.result);
   }
  } catch (e) {
   finish(e);
  }
 };

 const interval = setInterval(tick, 400);
 tick(); // poll immediately, do not wait for first interval
 });
}

function applyFetchResult(data, sources) {
 syncOnlyMissingFromFetchMode();
 saveFetchPrefs();
 updateNavStats();
 loadPageData();
 refreshCoverage();

 const okLines = Object.entries(data.by_source || {})
 .filter(([src]) => !(data.errors || {})[src])
 .map(([src, count]) => `✓ ${getSourceName(src)}: ${count}`);
 const kinds = data.error_kinds || {};
 const errLines = Object.entries(data.errors || {})
 .map(([src, msg]) => {
 const kind = kinds[src] ? ` [${kinds[src]}]` : '';
 return `✗ ${getSourceName(src)}${kind}: ${msg}`;
 });
 // Surface no-results sources gently
 Object.entries(kinds).forEach(([src, kind]) => {
 if (kind === 'no_results' && !(data.errors || {})[src]) {
 errLines.push(`· ${getSourceName(src)}: no results`);
 }
 });
 // Classroom notes for tricky sources (preprints / DBLP abstracts).
 const tipLines = [];
 const used = new Set(sources || []);
 const counts = data.by_source || {};
 if ((used.has('biorxiv') || used.has('medrxiv')) &&
 ((counts.biorxiv || 0) + (counts.medrxiv || 0) > 0 || used.has('biorxiv') || used.has('medrxiv'))) {
 tipLines.push(
 'Note: bioRxiv / medRxiv are preprints — not peer-reviewed, and only recent posts in a rolling date window.'
 );
 }
 if (used.has('dblp')) {
 tipLines.push(
 'Note: DBLP often has title and venue only; papers without a real abstract are skipped, so counts can look low.'
 );
 }
 if (used.has('arxiv') && (counts.arxiv || 0) > 0) {
 tipLines.push('Note: arXiv items are preprints and may not be peer-reviewed yet.');
 }

 const report = document.getElementById('fetch-source-report');
 report.style.display = 'block';
 const tipHtml = tipLines.length
 ? `<div class="fetch-source-tips">${tipLines.map(escapeHtml).join('<br>')}</div>`
 : '';
 report.innerHTML = [...okLines, ...errLines].map(escapeHtml).join('<br>') + tipHtml;

 const errorCount = Object.keys(data.errors || {}).length;
 const breakdown = Object.entries(data.by_source || {})
 .map(([src, count]) => `${getSourceName(src)}: ${count}`)
 .join(' · ');

 if (data.quota_stopped || data.status === 'quota_stopped') {
 const used = (data.quota && data.quota.used_mb != null) ? data.quota.used_mb : '?';
 const lim = (data.quota && data.quota.limit_mb != null) ? data.quota.limit_mb : '?';
 setStatus(
  'fetch-status',
  `Storage limit reached after ${data.total_fetched || 0} articles (${used} / ${lim} MB) - ${breakdown}. Delete a library or papers, then try again.`,
  'warning'
 );
 showNotification(
  `Storage limit reached (${data.total_fetched || 0} papers kept). Free space, then fetch again.`,
  'warning'
 );
 } else if (data.cancelled || data.status === 'cancelled') {
 setStatus('fetch-status', `Fetch cancelled after ${data.total_fetched || 0} articles - ${breakdown}`, 'warning');
 showNotification(`Fetch cancelled (${data.total_fetched || 0} papers kept).`, 'warning');
 } else if (errorCount === 0) {
 setStatus('fetch-status', `Fetched ${data.total_fetched} articles - ${breakdown}`, 'success');
 showNotification(`Fetched ${data.total_fetched} articles!`, 'success');
 } else if (errorCount < sources.length) {
 setStatus('fetch-status', `Fetched ${data.total_fetched} articles with some source errors (see list).`, 'warning');
 showNotification(`Fetched ${data.total_fetched} articles with some errors.`, 'warning');
 } else {
 setStatus('fetch-status', 'All fetches failed.', 'error');
 showNotification('Fetch failed for all selected sources.', 'error');
 }
}

async function doFetch() {
 const sources = Array.from(
 document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
 ).map(cb => cb.value);
 const query = document.getElementById('fetch-query').value.trim();
 const maxResults = parseInt(document.getElementById('fetch-max').value, 10);
 const email = document.getElementById('fetch-email').value.trim();
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const clearFirst = mode === 'replace';

 setNextStepVisible(false);
 if (!query) { showNotification('Please enter a search query.', 'error'); return; }
 if (sources.length === 0) { showNotification('Please select at least one source.', 'error'); return; }

 saveFetchPrefs();

 const btn = document.getElementById('fetch-btn');
 const cancelBtn = document.getElementById('fetch-cancel-btn');
 setLoading(btn, true);
 if (cancelBtn) {
 cancelBtn.hidden = false;
 cancelBtn.disabled = false;
 }
 document.getElementById('fetch-source-report').style.display = 'none';
 setStatus(
 'fetch-status',
 clearFirst
 ? `Starting fresh: clearing collection, then fetching from ${sources.length} source(s)…`
 : `Adding to collection from ${sources.length} source(s)…`,
 'info'
 );

 try {
 const started = await apiCall('/api/fetch-articles-multi', {
 method: 'POST',
 body: {
 sources,
 query,
 max_results: maxResults,
 email: email || null,
 clear_first: clearFirst,
 },
 });
 // 202 → {status: started}; poll for result. (wait=true legacy returns full body.)
 let data = started;
 if (started && started.status === 'started') {
 data = await waitForJob(
 'fetch', 'fetch-progress-fill', 'fetch-progress-label', 'fetch-progress-wrap',
 (done, total, _pct, p) => {
 const arts = (p && p.articles_so_far) || 0;
 return `${done} of ${total} source(s) · ${arts} paper(s) so far`;
 }
 );
 }
 applyFetchResult(data, sources);
 // Auto-chain prepare after every successful fetch (Simple and Advanced).
 // Never start prepare on zero papers / cancel / quota stop. Never auto-cluster.
 const totalFetched = Number(data.total_fetched) || 0
  || Object.values(data.by_source || {}).reduce((s, n) => s + (Number(n) || 0), 0);
 const fetchedOk = totalFetched > 0
  && !data.cancelled && !data.quota_stopped
  && data.status !== 'quota_stopped'
  && data.status !== 'cancelled';
 if (fetchedOk) {
 applyModelRecommendation();
 _autoChainActive = true;
 _lastTotalArticles = Math.max(_lastTotalArticles, totalFetched);
 // Keeps the card hidden until the chain finishes (see above).
 updatePrepareSectionVisibility(_lastTotalArticles);
 setNextStepVisible(false);
 setStatus(
 'fetch-status',
 `Fetched ${totalFetched} paper(s). Getting them ready for search…`,
 'info'
 );
 setStatus('embeddings-status', 'Getting your papers ready…', 'info');
 try {
 await doCreateEmbeddings({ fromAutoChain: true });
 } catch (chainErr) {
 // doCreateEmbeddings already surfaces errors; do not rethrow into fetch.
 console.warn('Auto-prepare after fetch failed:', chainErr);
 setStatus(
 'fetch-status',
 `Fetched ${totalFetched} paper(s), but prepare did not finish. Use Re-prepare if needed.`,
 'warning'
 );
 }
 }
 } catch (e) {
 const msg = e.message || '';
 if (msg.toLowerCase().includes('already running')) {
 setStatus('fetch-status', 'A fetch is already running.', 'warning');
 showNotification('A fetch is already running.', 'warning');
 } else if (msg.toLowerCase().includes('storage limit') || /507/.test(String(e.status || ''))) {
 setStatus('fetch-status', msg, 'warning');
 showNotification(msg, 'warning');
 } else {
 setStatus('fetch-status', `Fetch failed: ${msg}`, 'error');
 showNotification(`Fetch failed: ${msg}`, 'error');
 }
 } finally {
 _autoChainActive = false;
 updatePrepareSectionVisibility(_lastTotalArticles);
 setLoading(btn, false);
 if (cancelBtn) {
 cancelBtn.hidden = true;
 cancelBtn.disabled = false;
 }
 }
}

async function doCreateEmbeddings(opts) {
 // Button click passes a DOM Event; only treat real option bags as auto-chain.
 const fromAutoChain = !!(opts && opts.fromAutoChain === true);
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const modelEl = document.getElementById('embedding-model');
 const model = (modelEl && modelEl.value) || 'general';
 const onlyMissing = document.getElementById('only-missing')?.checked || false;
 const btn = document.getElementById('embeddings-btn');
 saveFetchPrefs();
 setLoading(btn, true);
 // Auto-chain: show progress on the fetch bar so Simple mode (prepare card
 // may still be opening) always has a visible progress track.
 const progressFill = fromAutoChain ? 'fetch-progress-fill' : 'embed-progress-fill';
 const progressLabel = fromAutoChain ? 'fetch-progress-label' : 'embed-progress-label';
 const progressWrap = fromAutoChain ? 'fetch-progress-wrap' : 'embed-progress-wrap';
 setStatus(
 fromAutoChain ? 'fetch-status' : 'embeddings-status',
 (simple || fromAutoChain)
  ? 'Getting your papers ready… this may take a few minutes on large collections.'
  : 'Preparing papers for search (embeddings)… this may take a few minutes on large collections.',
 'info'
 );
 setStatus(
 'embeddings-status',
 (simple || fromAutoChain)
  ? 'Getting your papers ready…'
  : 'Preparing papers for search (embeddings)…',
 'info'
 );

 try {
 const started = await apiCall('/api/create-embeddings', {
 method: 'POST',
 body: { model, only_missing: onlyMissing },
 });
 let data = started;
 if (started && started.status === 'started') {
 data = await waitForJob(
 'embed', progressFill, progressLabel, progressWrap,
 (done, total, pct) => {
 if (simple || fromAutoChain) {
 return total > 0
  ? `Getting papers ready… ${done} / ${total} (${pct}%)`
  : 'Getting your papers ready…';
 }
 return total > 0 ? `${done} / ${total} articles (${pct}%)` : 'Loading model…';
 }
 );
 }
 // If the 202 body already had a final payload (wait=true legacy), use it.
 if (data && data.status === 'started' && !data.articles_processed) {
  throw new Error('Prepare job did not return a result. Try Re-prepare Papers.');
 }
 const secs = data.seconds != null ? `${data.seconds}s` : '?';
 const device = data.device || 'cpu';
 const created = data.embeddings_created ?? data.articles_processed;
 const skipped = data.skipped_existing || 0;
 if (simple || fromAutoChain) {
 setStatus(
 'embeddings-status',
 `Ready: ${created} paper(s) prepared`
  + (skipped ? `, ${skipped} already ready` : '')
  + `. Total ready for search: ${data.articles_processed}.`,
 'success'
 );
 setStatus(
 'fetch-status',
 `Fetched and prepared ${data.articles_processed != null ? data.articles_processed : created} paper(s) for search.`,
 'success'
 );
 showNotification('Your papers are ready — next: Clean up, then Search.', 'success');
 setNextStepVisible(true);
 } else {
 setStatus(
 'embeddings-status',
 `Done: ${created} prepared, ${skipped} skipped (already prepared). ` +
 `Model ${data.model || model} on ${device} in ${secs}. ` +
 `Total ready for search: ${data.articles_processed}.`,
 'success'
 );
 showNotification('Papers prepared for search!', 'success');
 }
 await loadPageData();
 return data;
 } catch (e) {
 const msg = e.message || '';
 if (msg.toLowerCase().includes('storage limit')) {
  setStatus('embeddings-status', msg, 'warning');
  showNotification(msg, 'warning');
 } else if (msg.toLowerCase().includes('already running')) {
 setStatus('embeddings-status', 'Preparing is already running.', 'warning');
 showNotification('A prepare job is already running.', 'warning');
 } else {
 setStatus('embeddings-status', `Error: ${msg}`, 'error');
 showNotification(
  (simple || fromAutoChain) ? `Could not prepare papers: ${msg}` : `Embeddings failed: ${msg}`,
  'error'
 );
 }
 throw e;
 } finally {
 setLoading(btn, false);
 }
}
