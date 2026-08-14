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
 loadPageData().finally(() => {
  refreshSimpleScreeningCard();
 });
 refreshCoverage();
 });
 // Simple: hide optional prepare card until the library has papers.
 // Re-evaluate when the mode toggle flips (common.js sets data-mode first).
 const modeBtn = document.getElementById('mode-toggle');
 if (modeBtn) {
  modeBtn.addEventListener('click', () => {
   requestAnimationFrame(() => {
    updatePrepareSectionVisibility(_lastTotalArticles);
    refreshSimpleScreeningCard();
   });
  });
 }
 // Start hidden until stats load (avoids a flash of prepare on empty libs).
 updatePrepareSectionVisibility(0);
 // Phase 6: derive screening card visibility from corpus after stats load.
 requestAnimationFrame(() => refreshSimpleScreeningCard());
 // Form submit (button click or Enter in any field) starts fetch.
 const fetchForm = document.getElementById('fetch-form');
 if (fetchForm) {
  fetchForm.addEventListener('submit', (e) => {
   e.preventDefault();
   doFetch();
  });
 } else {
  document.getElementById('fetch-btn').addEventListener('click', doFetch);
 }
 const cancelBtn = document.getElementById('fetch-cancel-btn');
 if (cancelBtn) cancelBtn.addEventListener('click', cancelFetch);
 const unlockBtn = document.getElementById('simple-fetch-unlock-btn');
 if (unlockBtn) {
  unlockBtn.addEventListener('click', unlockSimpleFetch);
 }
 document.getElementById('embeddings-btn').addEventListener('click', doCreateEmbeddings);
 document.getElementById('coverage-refresh').addEventListener('click', refreshCoverage);
 const dismissGs = document.getElementById('dismiss-getting-started');
 if (dismissGs) dismissGs.addEventListener('click', () => {
 if (typeof dismissGettingStarted === 'function') dismissGettingStarted();
 });
 const sampleBtn = document.getElementById('load-sample-btn');
 if (sampleBtn) sampleBtn.addEventListener('click', () => loadSampleCorpus(true));
 const guestSampleBtn = document.getElementById('load-sample-btn-guest');
 if (guestSampleBtn) guestSampleBtn.addEventListener('click', () => loadSampleCorpus(true));
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
 updateReplaceConsequence();
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

/** Last known article count (for prepare section + mode toggles). */
let _lastTotalArticles = 0;
/** Papers with embeddings (ready for search). Optional prepare card gates on this. */
let _lastReadyArticles = 0;
/** Student-authored rows used by the Advanced replace-consequence line. */
let _lastNotesCount = 0;
let _lastStarredCount = 0;
let _lastAiKeyPoints = 0;
/**
 * Simple: student chose Start over / add papers, so the fetch form is live
 * again until this fetch finishes (or the page reloads).
 */
let _simpleFetchUnlocked = false;
/** Unlock dialog already set replace/append — skip asking again on submit. */
let _simpleFetchModePicked = false;
/**
 * True while a fetch is running or the post-fetch auto-prepare is in flight.
 * Both modes keep the optional prepare card fully hidden for this whole
 * window — progress lives on the fetch bar, not on a second "Re-prepare" card.
 */
let _pipelineBusy = false;

/**
 * Prepare is optional in both modes and only appears once papers are ready for
 * search (embeddings exist). Never mid-fetch / mid-auto-chain.
 * forceShow: reveal after a failed auto-prepare so Re-prepare is reachable.
 */
/** Show "Go to Search" once screening is applied or skipped (Simple only).
 *
 * Hidden again whenever a new fetch starts.
 */
function setNextStepVisible(visible) {
 const el = document.getElementById('fetch-next-step');
 if (!el) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const show = !!(visible && simple);
 el.hidden = !show;
 el.classList.toggle('u-hidden', !show);
}

// --- Phase 6 Simple screening card ------------------------------------------
// Levels → quick-preview fraction. Counts fetched once, not on every radio click.
const SIMPLE_SCREEN_LEVELS = {
 low: 0.10,
 medium: 0.25,
 high: 0.50,
};
/** @type {Record<string, {proposed_count:number, total_ranked:number, candidates:array}|null>} */
let _simpleScreenCounts = { low: null, medium: null, high: null };
let _simpleScreenCandidates = [];
let _simpleScreenLastItems = null;
/** Session-only: skip hides the decision UI until reload (pending is corpus-derived). */
let _simpleScreenSkippedSession = false;
// Last Narrow-it-down exclusion set (per library) so Undo survives a soft reload.
// Corpus API is the source of truth after restart; this is a fast path.
const SIMPLE_SCREEN_UNDO_KEY = 'lra_simple_screen_undo_v1';

// Skip is remembered per library, not just per page view.
//
// "Pending vs complete" is derived from the corpus (prepared papers, and
// whether any low_relevance exclusions exist), which is correct and survives a
// reload. Skipping leaves no trace in the corpus by definition, so without
// this the card reappears on refresh and — worse — the "Go to Search" button
// they were just offered disappears with it.
//
// Per library, because skipping one collection says nothing about the next.
const SKIP_KEY = 'lra_screen_skipped_v1';

// Resolved once per page and cached. The nav select is populated
// asynchronously by common.js, so reading it during the first card refresh
// races and comes back empty — which would silently lose a persisted skip.
let _activeLibIdCache = '';

function _activeLibraryId() {
 const sel = document.getElementById('nav-library-select');
 return (sel && sel.value) || _activeLibIdCache || '';
}

/** Authoritative active library id; falls back to the API before the nav loads. */
async function ensureActiveLibraryId() {
 const fromSelect = (document.getElementById('nav-library-select') || {}).value;
 if (fromSelect) {
  _activeLibIdCache = fromSelect;
  return fromSelect;
 }
 if (_activeLibIdCache) return _activeLibIdCache;
 try {
  const data = await apiCall('/api/libraries');
  _activeLibIdCache = (data && data.active_id) || '';
 } catch (e) {
  _activeLibIdCache = '';
 }
 return _activeLibIdCache;
}

function _skipStore() {
 try {
  return JSON.parse(localStorage.getItem(SKIP_KEY) || '{}') || {};
 } catch (e) {
  return {};
 }
}

function isSimpleScreenSkipped() {
 if (_simpleScreenSkippedSession) return true;
 const lib = _activeLibraryId();
 if (!lib) return false;
 return _skipStore()[lib] === true;
}

function setSimpleScreenSkipped(skipped) {
 _simpleScreenSkippedSession = skipped;
 const lib = _activeLibraryId();
 if (!lib) return;
 try {
  const store = _skipStore();
  if (skipped) {
   store[lib] = true;
  } else {
   delete store[lib];
  }
  localStorage.setItem(SKIP_KEY, JSON.stringify(store));
 } catch (e) {
  // Private mode / storage disabled: fall back to session-only behaviour.
 }
}

function _simpleScreenUndoStore() {
 try {
  return JSON.parse(localStorage.getItem(SIMPLE_SCREEN_UNDO_KEY) || '{}') || {};
 } catch (e) {
  return {};
 }
}

/** Persist last set-aside items (localStorage) as a fast path; corpus API is authoritative. */
function saveSimpleScreenUndoItems(items) {
 _simpleScreenLastItems = items && items.length ? items : null;
 const lib = _activeLibraryId();
 if (!lib) return;
 try {
  const store = _simpleScreenUndoStore();
  if (_simpleScreenLastItems) {
   store[lib] = _simpleScreenLastItems;
  } else {
   delete store[lib];
  }
  localStorage.setItem(SIMPLE_SCREEN_UNDO_KEY, JSON.stringify(store));
 } catch (e) {
  // Private mode: in-memory only.
 }
}

function loadSimpleScreenUndoItems() {
 if (_simpleScreenLastItems && _simpleScreenLastItems.length) {
  return _simpleScreenLastItems;
 }
 const lib = _activeLibraryId();
 if (!lib) return null;
 try {
  const stored = _simpleScreenUndoStore()[lib];
  if (Array.isArray(stored) && stored.length) {
   _simpleScreenLastItems = stored;
   return stored;
  }
 } catch (e) { /* ignore */ }
 return null;
}

function clearSimpleScreenUndoItems() {
 saveSimpleScreenUndoItems(null);
}

/** Load low_relevance exclusions from the server so Undo works after a full restart. */
async function fetchLowRelevanceUndoItems() {
 const cached = loadSimpleScreenUndoItems();
 if (cached && cached.length) return cached;
 try {
  const data = await apiCall('/api/screening/excluded?reason=low_relevance');
  const items = (data && data.items) || [];
  if (items.length) {
   saveSimpleScreenUndoItems(items);
   return items;
  }
 } catch (e) {
  console.warn('fetchLowRelevanceUndoItems failed:', e);
 }
 return null;
}

/** Show/hide the confirm-your-question box with the decision UI (pending only). */
function setSimpleScreenConfirmVisible(visible) {
 const el = document.getElementById('simple-screen-confirm');
 if (el) el.hidden = !visible;
}

let _simpleScreenWired = false;

function simpleScreenSelectedLevel() {
 const el = document.querySelector('input[name="simple-screen-level"]:checked');
 return (el && el.value) || 'medium';
}

function simpleScreenFraction(level) {
 return SIMPLE_SCREEN_LEVELS[level] != null ? SIMPLE_SCREEN_LEVELS[level] : 0.25;
}

function simpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 if (el && el.value.trim()) return el.value.trim();
 const fetchQ = document.getElementById('fetch-query');
 return (fetchQ && fetchQ.value.trim()) || '';
}

function prefillSimpleScreenQuery() {
 const el = document.getElementById('simple-screen-query');
 if (!el) return;
 // Always surface a candidate so the confirm box is never empty when we know one,
 // but do not overwrite if the student already edited the field.
 if (el.value.trim()) return;
 try {
  const prefs = JSON.parse(localStorage.getItem('lra_fetch_prefs_v1') || 'null');
  if (prefs && prefs.query) {
   el.value = prefs.query;
   return;
  }
 } catch (e) { /* ignore */ }
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ && fetchQ.value.trim()) el.value = fetchQ.value.trim();
}

function setSimpleScreenGotoVisible(visible) {
 const el = document.getElementById('simple-screen-goto');
 if (el) el.hidden = !visible;
 setNextStepVisible(visible);
}

/**
 * Pending/complete from corpus, not a job flag:
 *  - pending: prepared papers exist and no low_relevance exclusions yet
 *  - complete: low_relevance > 0 (applied at least once)
 */
async function refreshSimpleScreeningCard() {
 const card = document.getElementById('simple-screening-card');
 if (!card) return;
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 if (!simple || _pipelineBusy) {
  card.hidden = true;
  return;
 }
 try {
  const [stats, report] = await Promise.all([
   apiCall('/api/statistics'),
   apiCall('/api/screening-report?format=json'),
   // Resolves (and caches) the active library so a persisted skip is not
   // missed just because the nav select has not populated yet.
   ensureActiveLibraryId(),
  ]);
  const ready = Number(stats.articles_with_embeddings) || 0;
  const lowRel = Number(
   report && report.excluded && report.excluded.low_relevance
  ) || 0;
  const total = Number(stats.total_articles) || 0;

  if (ready <= 0) {
   card.hidden = true;
   setSimpleScreenGotoVisible(false);
   return;
  }

  card.hidden = false;
  prefillSimpleScreenQuery();
  wireSimpleScreeningCard();

  const decision = document.getElementById('simple-screen-levels');
  const actions = document.getElementById('simple-screen-actions');
  const outcome = document.getElementById('simple-screen-outcome');
  const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
  const undoBtn = document.getElementById('simple-screen-undo-btn');
  const preview = document.getElementById('simple-screen-preview');

  if (lowRel > 0) {
   // Complete: already screened this library.
   if (decision) decision.hidden = true;
   if (actions) actions.hidden = true;
   setSimpleScreenConfirmVisible(false);
   if (preview) {
    preview.hidden = true;
    preview.classList.add('u-hidden');
   }
   if (outcome) {
    outcome.hidden = false;
    outcome.classList.remove('u-hidden');
   }
   if (outcomeMsg) {
    outcomeMsg.textContent =
     `Set aside ${lowRel} paper${lowRel === 1 ? '' : 's'} as less related to your question.`;
   }
   // Always offer a small Undo when low_relevance exclusions exist (corpus-backed).
   if (undoBtn) {
    undoBtn.hidden = false;
    undoBtn.textContent = 'Undo';
   }
   // Warm the undo cache in the background; the button stays visible either way.
   fetchLowRelevanceUndoItems();
   setSimpleScreenGotoVisible(true);
   return;
  }

  if (isSimpleScreenSkipped()) {
   if (decision) decision.hidden = true;
   if (actions) actions.hidden = true;
   setSimpleScreenConfirmVisible(false);
   if (outcome) {
    outcome.hidden = false;
    outcome.classList.remove('u-hidden');
   }
   if (outcomeMsg) {
    outcomeMsg.textContent = 'Screening skipped — you can still search everything you fetched.';
   }
   if (undoBtn) undoBtn.hidden = true;
   setSimpleScreenGotoVisible(true);
   return;
  }

  // Pending: confirm question + levels + actions; fetch counts once.
  if (decision) decision.hidden = false;
  if (actions) actions.hidden = false;
  setSimpleScreenConfirmVisible(true);
  if (outcome) {
   outcome.hidden = true;
   outcome.classList.add('u-hidden');
  }
  if (undoBtn) undoBtn.hidden = true;
  setSimpleScreenGotoVisible(false);
  const totalEl = document.getElementById('simple-screen-total');
  if (totalEl) {
   totalEl.hidden = false;
   totalEl.textContent = `${ready} paper${ready === 1 ? '' : 's'} ready to rank`
    + (total > ready ? ` (${total} in collection).` : '.');
  }
  await loadSimpleScreenCounts();
 } catch (e) {
  console.warn('refreshSimpleScreeningCard failed:', e);
  card.hidden = true;
 }
}

async function loadSimpleScreenCounts() {
 const query = simpleScreenQuery();
 const status = document.getElementById('simple-screen-status');
 if (!query) {
  ['low', 'medium', 'high'].forEach((level) => {
   const el = document.getElementById(`simple-screen-count-${level}`);
   if (el) el.textContent = '…';
  });
  if (status) {
   setStatus('simple-screen-status', 'Enter a research question to see how many papers each level would set aside.', 'info');
  }
  return;
 }
 if (status) setStatus('simple-screen-status', 'Counting papers for each level…', 'info');
 // Fetch all three fractions once (parallel). Reuse until query changes.
 const qKey = query;
 if (_simpleScreenCounts._query === qKey
  && _simpleScreenCounts.low && _simpleScreenCounts.medium && _simpleScreenCounts.high) {
  applySimpleScreenCountLabels();
  if (status) setStatus('simple-screen-status', '', 'info');
  return;
 }
 try {
  const entries = await Promise.all(
   Object.keys(SIMPLE_SCREEN_LEVELS).map(async (level) => {
    const fraction = SIMPLE_SCREEN_LEVELS[level];
    const data = await apiCall('/api/screening/quick-preview', {
     method: 'POST',
     body: { query, fraction },
    });
    return [level, data];
   })
  );
  _simpleScreenCounts = { low: null, medium: null, high: null, _query: qKey };
  entries.forEach(([level, data]) => {
   _simpleScreenCounts[level] = data;
  });
  applySimpleScreenCountLabels();
  if (status) setStatus('simple-screen-status', '', 'info');
 } catch (e) {
  if (status) setStatus('simple-screen-status', `Could not rank papers: ${e.message}`, 'error');
  console.warn('loadSimpleScreenCounts failed:', e);
 }
}

function applySimpleScreenCountLabels() {
 const total =
  (_simpleScreenCounts.medium && _simpleScreenCounts.medium.total_ranked)
  || (_simpleScreenCounts.low && _simpleScreenCounts.low.total_ranked)
  || 0;
 ['low', 'medium', 'high'].forEach((level) => {
  const el = document.getElementById(`simple-screen-count-${level}`);
  if (!el) return;
  const data = _simpleScreenCounts[level];
  if (!data) {
   el.textContent = '…';
   return;
  }
  const n = Number(data.proposed_count) || 0;
  const t = Number(data.total_ranked) || total || 0;
  el.textContent = t ? `${n} of ${t}` : String(n);
 });
}

function wireSimpleScreeningCard() {
 if (_simpleScreenWired) return;
 _simpleScreenWired = true;
 const previewBtn = document.getElementById('simple-screen-preview-btn');
 const applyBtn = document.getElementById('simple-screen-apply-btn');
 const skipBtn = document.getElementById('simple-screen-skip-btn');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 const queryEl = document.getElementById('simple-screen-query');
 if (previewBtn) previewBtn.addEventListener('click', doSimpleScreenPreview);
 if (applyBtn) applyBtn.addEventListener('click', doSimpleScreenApply);
 if (skipBtn) skipBtn.addEventListener('click', doSimpleScreenSkip);
 if (undoBtn) undoBtn.addEventListener('click', doSimpleScreenUndo);
 if (queryEl) {
  let t = null;
  queryEl.addEventListener('change', () => {
   _simpleScreenCounts = { low: null, medium: null, high: null };
   loadSimpleScreenCounts();
  });
  queryEl.addEventListener('input', () => {
   clearTimeout(t);
   t = setTimeout(() => {
    _simpleScreenCounts = { low: null, medium: null, high: null };
    loadSimpleScreenCounts();
   }, 600);
  });
 }
 // Radios only switch labels already loaded — no re-fetch.
}

async function doSimpleScreenPreview() {
 const level = simpleScreenSelectedLevel();
 const fraction = simpleScreenFraction(level);
 const query = simpleScreenQuery();
 const btn = document.getElementById('simple-screen-preview-btn');
 const panel = document.getElementById('simple-screen-preview');
 if (!query) {
  showNotification('Enter a research question first.', 'error');
  return;
 }
 setLoading(btn, true);
 setStatus('simple-screen-status', 'Finding the least related papers…', 'info');
 try {
  let data = _simpleScreenCounts[level];
  if (!data || _simpleScreenCounts._query !== query) {
   data = await apiCall('/api/screening/quick-preview', {
    method: 'POST',
    body: { query, fraction },
   });
   _simpleScreenCounts[level] = data;
   _simpleScreenCounts._query = query;
   applySimpleScreenCountLabels();
  }
  const candidates = data.candidates || [];
  _simpleScreenCandidates = candidates;
  if (!panel) return;
  panel.innerHTML = '';
  if (!candidates.length) {
   panel.innerHTML = '<p class="info-text">Nothing to set aside at this level.</p>';
  } else {
   const list = document.createElement('div');
   list.className = 'simple-screen-list';
   candidates.forEach((c) => {
    const row = document.createElement('div');
    row.className = 'quick-screen-row';
    const title = document.createElement('span');
    title.className = 'qs-title';
    title.textContent = c.title || '(no title)';
    const meta = document.createElement('span');
    meta.className = 'qs-meta help-text';
    meta.textContent =
     `${c.year || ''} · ${typeof getSourceName === 'function' ? getSourceName(c.source) : c.source}`;
    row.appendChild(title);
    row.appendChild(meta);
    list.appendChild(row);
   });
   panel.appendChild(list);
  }
  panel.hidden = false;
  panel.classList.remove('u-hidden');
  setStatus(
   'simple-screen-status',
   `Showing ${candidates.length} paper(s) that would be set aside. Nothing is excluded yet.`,
   'info'
  );
 } catch (e) {
  setStatus('simple-screen-status', `Preview failed: ${e.message}`, 'error');
  showNotification(`Preview failed: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

async function doSimpleScreenApply() {
 const level = simpleScreenSelectedLevel();
 const fraction = simpleScreenFraction(level);
 const query = simpleScreenQuery();
 const btn = document.getElementById('simple-screen-apply-btn');
 if (!query) {
  showNotification('Enter a research question first.', 'error');
  return;
 }
 setLoading(btn, true);
 setStatus('simple-screen-status', 'Setting aside the least related papers…', 'info');
 try {
  let data = _simpleScreenCounts[level];
  if (!data || _simpleScreenCounts._query !== query) {
   data = await apiCall('/api/screening/quick-preview', {
    method: 'POST',
    body: { query, fraction },
   });
  }
  const candidates = data.candidates || [];
  if (!candidates.length) {
   setStatus('simple-screen-status', 'Nothing to set aside at this level.', 'info');
   return;
  }
  const items = candidates.map((c) => ({
   article_id: c.article_id,
   source: c.source,
  }));
  const applied = await apiCall('/api/screening', {
   method: 'POST',
   body: { items, action: 'exclude', reason: 'low_relevance' },
  });
  saveSimpleScreenUndoItems(items);
  _simpleScreenCandidates = [];
  const n = applied.count || items.length;
  const decision = document.getElementById('simple-screen-levels');
  const actions = document.getElementById('simple-screen-actions');
  if (decision) decision.hidden = true;
  if (actions) actions.hidden = true;
  setSimpleScreenConfirmVisible(false);
  const outcome = document.getElementById('simple-screen-outcome');
  const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
  const undoBtn = document.getElementById('simple-screen-undo-btn');
  if (outcome) {
   outcome.hidden = false;
   outcome.classList.remove('u-hidden');
  }
  if (outcomeMsg) {
   outcomeMsg.textContent = `Set aside ${n} paper${n === 1 ? '' : 's'}.`;
  }
  // Always offer a small Undo after Narrow it down completes (this tab session).
  if (undoBtn) {
   undoBtn.hidden = false;
   undoBtn.textContent = 'Undo';
  }
  const preview = document.getElementById('simple-screen-preview');
  if (preview) {
   preview.hidden = true;
   preview.classList.add('u-hidden');
  }
  setStatus('simple-screen-status', `Set aside ${n} paper(s). You can undo once.`, 'success');
  showNotification(`Set aside ${n} paper(s).`, 'success');
  setSimpleScreenGotoVisible(true);
  updateNavStats();
 } catch (e) {
  setStatus('simple-screen-status', `Could not set papers aside: ${e.message}`, 'error');
  showNotification(`Could not set papers aside: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

function doSimpleScreenSkip() {
 setSimpleScreenSkipped(true);
 clearSimpleScreenUndoItems();
 const decision = document.getElementById('simple-screen-levels');
 const actions = document.getElementById('simple-screen-actions');
 const preview = document.getElementById('simple-screen-preview');
 if (decision) decision.hidden = true;
 if (actions) actions.hidden = true;
 setSimpleScreenConfirmVisible(false);
 if (preview) {
  preview.hidden = true;
  preview.classList.add('u-hidden');
 }
 const outcome = document.getElementById('simple-screen-outcome');
 const outcomeMsg = document.getElementById('simple-screen-outcome-msg');
 const undoBtn = document.getElementById('simple-screen-undo-btn');
 if (outcome) {
  outcome.hidden = false;
  outcome.classList.remove('u-hidden');
 }
 if (outcomeMsg) {
  outcomeMsg.textContent = 'Screening skipped — you can still search everything you fetched.';
 }
 if (undoBtn) undoBtn.hidden = true;
 setStatus('simple-screen-status', '', 'info');
 setSimpleScreenGotoVisible(true);
}

async function doSimpleScreenUndo() {
 const btn = document.getElementById('simple-screen-undo-btn');
 setLoading(btn, true);
 try {
  // Cache first; otherwise one corpus request (errors surface to catch).
  let items = loadSimpleScreenUndoItems();
  if (!items || !items.length) {
   const data = await apiCall('/api/screening/excluded?reason=low_relevance');
   items = (data && data.items) || [];
   if (items.length) saveSimpleScreenUndoItems(items);
  }
  if (!items.length) {
   showNotification('Nothing to undo.', 'info');
   return;
  }
  await apiCall('/api/screening', {
   method: 'POST',
   body: { items, action: 'include' },
  });
  const n = items.length;
  clearSimpleScreenUndoItems();
  setSimpleScreenSkipped(false);
  _simpleScreenCounts = { low: null, medium: null, high: null };
  setStatus('simple-screen-status', `Restored ${n} paper(s).`, 'success');
  showNotification(`Restored ${n} paper(s).`, 'success');
  await refreshSimpleScreeningCard();
  updateNavStats();
 } catch (e) {
  setStatus('simple-screen-status', `Undo failed: ${e.message}`, 'error');
  showNotification(`Undo failed: ${e.message}`, 'error');
 } finally {
  setLoading(btn, false);
 }
}

function isGuestSession() {
 return !!(document.body && document.body.getAttribute('data-guest') === '1');
}

/**
 * Simple + this library already has papers: hide Fetch Articles unless the
 * student explicitly unlocked via Start over. Advanced and empty libraries
 * stay unchanged. Guests never see the fetch form (CSS + server 403).
 */
function isSimpleFetchLocked() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) return false;
 if (isGuestSession()) return false;
 if (_pipelineBusy) return false;
 if (_simpleFetchUnlocked) return false;
 return _lastTotalArticles > 0;
}

function updateSimpleFetchLock() {
 const lock = isSimpleFetchLocked();
 const form = document.getElementById('fetch-form');
 const lead = document.getElementById('fetch-lead');
 const banner = document.getElementById('simple-fetch-locked');
 const heading = document.querySelector('.dm-step-heading.dm-step-simple');
 if (form) form.hidden = lock;
 if (lead) lead.hidden = lock;
 if (banner) {
  banner.hidden = !lock;
  const msg = document.getElementById('simple-fetch-locked-msg');
  if (lock && msg) {
   const n = Number(_lastTotalArticles) || 0;
   const nLabel = n === 1 ? '1 paper' : `${n} papers`;
   msg.textContent =
    `This collection already has ${nLabel}. Fetching again can replace them or mix in a new search. Use Re-prepare if you only need to get them ready for search again.`;
  }
 }
 if (heading) {
  heading.textContent = lock ? '2. Your papers' : '2. Fetch Articles';
 }
}

async function unlockSimpleFetch() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) return;
 if (isGuestSession()) return;
 const proceed = await resolveSimpleFetchModeBeforeRequest();
 if (!proceed) return;
 _simpleFetchUnlocked = true;
 _simpleFetchModePicked = true;
 updateSimpleFetchLock();
 const q = document.getElementById('fetch-query');
 if (q) {
  q.focus();
  if (typeof q.select === 'function') q.select();
 }
}

/**
 * Advanced only (Simple hides the radio row): live line next to Replace
 * when this library is non-empty. No modal — the radios stay the control.
 */
function updateReplaceConsequence() {
 const el = document.getElementById('fetch-replace-consequence');
 if (!el) return;
 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const show = mode === 'replace' && _lastTotalArticles > 0;
 el.hidden = !show;
 if (!show) return;
 const n = Number(_lastTotalArticles) || 0;
 const nLabel = n === 1 ? '1 paper' : `${n} papers`;
 const notes = Number(_lastNotesCount) || 0;
 const stars = Number(_lastStarredCount) || 0;
 const kps = Number(_lastAiKeyPoints) || 0;
 if (notes || stars || kps) {
  el.textContent =
   `Replace deletes these ${nLabel}, including ${notes} note${notes === 1 ? '' : 's'}, ` +
   `${stars} star${stars === 1 ? '' : 's'}, and ${kps} saved AI key point${kps === 1 ? '' : 's'}.`;
 } else {
  el.textContent =
   `Replace deletes these ${nLabel} and any notes, stars, and saved AI key points.`;
 }
}

function updatePrepareSectionVisibility(totalArticles, opts) {
 const sec = document.getElementById('prepare-section');
 if (!sec) return;
 if (typeof totalArticles === 'number' && !Number.isNaN(totalArticles)) {
  _lastTotalArticles = totalArticles;
 }
 if (opts && typeof opts.readyArticles === 'number' && !Number.isNaN(opts.readyArticles)) {
  _lastReadyArticles = opts.readyArticles;
 }
 const forceShow = !!(opts && opts.forceShow);
 // Busy (fetch or auto-chain): never show the re-prepare card (Simple or Advanced).
 if (_pipelineBusy) {
  sec.hidden = true;
  updateSimpleFetchLock();
  updateReplaceConsequence();
  return;
 }
 if (forceShow) {
  sec.hidden = false;
  updateSimpleFetchLock();
  updateReplaceConsequence();
  return;
 }
 // Optional re-prepare only once something is actually ready for search.
 sec.hidden = !(_lastReadyArticles > 0);
 updateSimpleFetchLock();
 updateReplaceConsequence();
}

async function loadPageData() {
 try {
 const stats = await apiCall('/api/statistics');
 const model = stats.embedding_model || ' - ';
 const total = stats.total_articles || 0;
 const ready = stats.articles_with_embeddings || 0;
 _lastNotesCount = Number(stats.notes) || 0;
 _lastStarredCount = Number(stats.starred) || 0;
 _lastAiKeyPoints = Number(stats.ai_key_points) || 0;
 const missing = stats.missing_embeddings ?? Math.max(0, total - ready);
 document.getElementById('embedding-info').textContent =
 `${ready} of ${total} papers are ready for search` +
 (ready ? ` (model: ${model})` : '') +
 (missing ? ` · ${missing} still need preparing` : '') + '.';
 // Topic recommendation drives the dropdown (unless the user overrode it).
 // Do NOT force the corpus's stored model into the select — that made
 // pubmedbert "stick" after a biomedical prep even when topics say specter.
 window._corpusEmbeddingModel = stats.embedding_model || null;
 applyModelRecommendation();
 updateGettingStartedCard(total);
 // Stats refresh (incl. library reload / sample load): lock fetch again in Simple.
 _simpleFetchUnlocked = false;
 _simpleFetchModePicked = false;
 updatePrepareSectionVisibility(total, { readyArticles: ready });
 } catch (e) {
 document.getElementById('embedding-info').textContent = 'Unable to load article info.';
 updateGettingStartedCard(0);
 _simpleFetchUnlocked = false;
 _simpleFetchModePicked = false;
 updatePrepareSectionVisibility(0, { readyArticles: 0 });
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
 `Loaded ${data.inserted || data.loaded || 0} sample papers. Use Re-prepare Papers when you are ready.`,
 'success'
 );
 await loadPageData();
 // Samples have no embeddings yet; reveal the optional prepare card so Re-prepare is available.
 updatePrepareSectionVisibility(_lastTotalArticles, { forceShow: true });
 refreshCoverage();
 updateNavStats();
 applyModelRecommendation();
 setStatus(
 'embeddings-status',
 'Sample papers loaded. Choose a model if needed, then press Re-prepare Papers.',
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
 // Scale each bar to the largest source count in this map (not a fixed global max).
 const counts = keys.map((src) => Math.max(0, Number(sources[src]) || 0));
 const maxCount = Math.max(...counts, 0);
 keys
  .map((src, i) => ({ src, count: counts[i] }))
  .sort((a, b) => b.count - a.count || a.src.localeCompare(b.src))
  .forEach(({ src, count }) => {
 const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
 const widthPct = count > 0 ? Math.max(pct, 1.5) : 0;
 const label = getSourceName(src);
 const div = document.createElement('div');
 div.className = 'source-bar';
 div.setAttribute('title', `${label}: ${count}` + (maxCount ? ` (max ${maxCount})` : ''));

 const name = document.createElement('span');
 name.className = 'source-name';
 name.textContent = label;

 const fill = document.createElement('div');
 fill.className = 'source-bar-fill';
 const track = document.createElement('div');
 track.className = 'source-track';
 track.setAttribute('role', 'presentation');
 const inner = document.createElement('div');
 inner.className = 'source-bar-inner';
 // CSP blocks inline style attributes from innerHTML; set width via CSS variable (CSSOM).
 inner.style.setProperty('--bar-pct', `${widthPct}%`);
 track.appendChild(inner);
 fill.appendChild(track);

 const countEl = document.createElement('span');
 countEl.className = 'source-count';
 countEl.textContent = String(count);

 div.appendChild(name);
 div.appendChild(fill);
 div.appendChild(countEl);
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
 + '<p class="help-text u-mt-sm">Check them under Choose Sources on the next fetch.</p>';
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
/** Render live per-source fetch rows from progress payload only (no invented counts). */
function renderFetchLiveSources(p) {
 const host = document.getElementById('fetch-live-sources');
 if (!host) return;
 const sources = Array.isArray(p && p.sources) ? p.sources : [];
 const by = (p && p.by_source) || {};
 const status = (p && p.source_status) || {};
 if (!sources.length) {
  host.innerHTML = '';
  return;
 }
 const rows = sources.map((src) => {
  const name = typeof getSourceName === 'function' ? getSourceName(src) : src;
  const done = Object.prototype.hasOwnProperty.call(by, src);
  const count = done ? Number(by[src]) || 0 : null;
  const kind = status[src] || '';
  let detail;
  let rowClass = 'fetch-live-row';
  if (!done) {
   detail = 'searching…';
   rowClass += ' is-pending';
  } else if (kind && kind !== 'ok' && kind !== 'no_results') {
   // Muted — per-source failure is normal while the job overall succeeds.
   detail = String(kind).replace(/_/g, ' ');
   rowClass += ' is-muted';
  } else if (kind === 'no_results' || count === 0) {
   detail = '0 papers';
   rowClass += ' is-muted';
  } else {
   detail = `${count} paper${count === 1 ? '' : 's'}`;
   rowClass += ' is-ok';
  }
  return `<div class="${rowClass}"><span class="fetch-live-name">${escapeHtml(name)}</span>`
   + `<span class="fetch-live-detail">${escapeHtml(detail)}</span></div>`;
 });
 host.innerHTML = rows.join('');
}

function waitForJob(task, fillId, labelId, wrapId, formatLabel, timeoutMs = 600000) {
 return new Promise((resolve, reject) => {
 const fill = document.getElementById(fillId);
 const label = document.getElementById(labelId);
 const wrap = document.getElementById(wrapId);
 const live = document.getElementById('fetch-live-sources');
 if (wrap) wrap.style.display = 'block';
 if (fill) fill.style.width = '0%';
 if (task === 'fetch' && live) live.innerHTML = '';
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
    if (live && task === 'fetch') live.innerHTML = '';
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
    if (task === 'fetch') renderFetchLiveSources(p);
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

/**
 * Build a structured per-source report model from a fetch result.
 * Pure (no DOM) so Simple can collapse to top-5 successes + summary.
 */
function buildFetchSourceReportModel(data, sources) {
 const counts = (data && data.by_source) || {};
 const errors = (data && data.errors) || {};
 const kinds = (data && data.error_kinds) || {};
 const used = new Set(sources || []);
 Object.keys(counts).forEach((s) => used.add(s));
 Object.keys(errors).forEach((s) => used.add(s));
 Object.keys(kinds).forEach((s) => used.add(s));

 const successes = [];
 const muted = []; // no results / soft failures (not alarming)

 used.forEach((src) => {
  const name = typeof getSourceName === 'function' ? getSourceName(src) : src;
  const count = Number(counts[src]) || 0;
  const err = errors[src];
  const kind = kinds[src] || '';
  if (err) {
   const kindBit = kind ? ` [${kind}]` : '';
   muted.push({
    src,
    name,
    line: `✗ ${name}${kindBit}: ${err}`,
    zero: false,
   });
   return;
  }
  if (kind === 'no_results' || count === 0) {
   muted.push({
    src,
    name,
    line: `· ${name}: no results`,
    zero: true,
   });
   return;
  }
  successes.push({
   src,
   name,
   count,
   line: `✓ ${name}: ${count}`,
  });
 });

 successes.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
 muted.sort((a, b) => a.name.localeCompare(b.name));

 // Classroom notes for tricky sources (preprints / DBLP abstracts).
 const tipLines = [];
 if (used.has('biorxiv') || used.has('medrxiv')) {
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

 return { successes, muted, tipLines };
}

/**
 * Render the final source report HTML.
 * Simple: <details> collapsed by default — top 5 successes + summary of the rest.
 * Advanced: full list expanded (open attribute).
 * All dynamic strings go through escapeHtml.
 */
function renderFetchSourceReportHtml(model, opts) {
 const simple = !!(opts && opts.simple);
 const successes = (model && model.successes) || [];
 const muted = (model && model.muted) || [];
 const tipLines = (model && model.tipLines) || [];
 const topN = 5;
 const top = successes.slice(0, topN);
 const restOk = successes.slice(topN);
 const zeroCount = muted.filter((m) => m.zero).length;
 const otherMuted = muted.length - zeroCount;

 const topHtml = top.map((s) => escapeHtml(s.line)).join('<br>');
 let summaryBits = [];
 if (restOk.length) summaryBits.push(`${restOk.length} more`);
 if (zeroCount) {
  summaryBits.push(
   zeroCount === 1 ? '1 returned nothing' : `${zeroCount} returned nothing`
  );
 }
 if (otherMuted > 0) {
  summaryBits.push(
   otherMuted === 1 ? '1 with an error' : `${otherMuted} with errors`
  );
 }
 const summaryLine = summaryBits.length
  ? `<div class="fetch-source-report-summary-line">${escapeHtml('and ' + summaryBits.join(' · '))}</div>`
  : '';

 const fullLines = [
  ...successes.map((s) => s.line),
  ...muted.map((m) => m.line),
 ];
 const fullHtml = fullLines.map((ln) => escapeHtml(ln)).join('<br>');
 const tipHtml = tipLines.length
  ? `<div class="fetch-source-tips">${tipLines.map(escapeHtml).join('<br>')}</div>`
  : '';

 if (!simple) {
  // Advanced: full list always visible (no collapse).
  return `<div class="fetch-source-report-full">${fullHtml}${tipHtml}</div>`;
 }

 // Simple: collapsed default — show top successes + one summary line.
 const collapsedBody = (topHtml || escapeHtml('(no sources returned papers)')) + summaryLine;
 const openAttr = ''; // collapsed by default
 return `<details class="fetch-source-report-details help-details"${openAttr}>
  <summary>${collapsedBody}<span class="help-text"> · Show all sources</span></summary>
  <div class="fetch-source-report-full">${fullHtml}${tipHtml}</div>
 </details>`;
}

function applyFetchResult(data, sources) {
 syncOnlyMissingFromFetchMode();
 saveFetchPrefs();
 updateNavStats();
 loadPageData();
 refreshCoverage();

 // Clear live per-source rows so they never sit next to the final report.
 const live = document.getElementById('fetch-live-sources');
 if (live) live.innerHTML = '';
 const progressWrap = document.getElementById('fetch-progress-wrap');
 if (progressWrap) progressWrap.style.display = 'none';

 const model = buildFetchSourceReportModel(data, sources);
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const report = document.getElementById('fetch-source-report');
 if (report) {
  report.style.display = 'block';
  report.classList.remove('u-hidden');
  report.innerHTML = renderFetchSourceReportHtml(model, { simple });
 }

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

/**
 * Simple mode only: decide replace vs append before fetch.
 * Empty library → no dialog, force replace (clear_first true).
 * Non-empty → dialog with real count from /api/statistics.
 * Returns false if the user cancelled (no request should be sent).
 * Sets the fetch-mode radios so saveFetchPrefs / only-missing hint stay correct.
 */
/**
 * Best-known research question for Simple re-prepare / Narrow it down.
 * Prefers the screening field, then fetch query, then saved prefs.
 */
function getResearchQuestionCandidate() {
 const screen = document.getElementById('simple-screen-query');
 if (screen && screen.value.trim()) return screen.value.trim();
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ && fetchQ.value.trim()) return fetchQ.value.trim();
 try {
  const prefs = JSON.parse(localStorage.getItem(FETCH_PREFS_KEY) || 'null');
  if (prefs && prefs.query && String(prefs.query).trim()) {
   return String(prefs.query).trim();
  }
 } catch (e) { /* ignore */ }
 return '';
}

/** Write a verified question into fetch + screening fields and persist prefs. */
function applyVerifiedResearchQuestion(query) {
 const q = String(query || '').trim();
 if (!q) return;
 const fetchQ = document.getElementById('fetch-query');
 if (fetchQ) fetchQ.value = q;
 const screen = document.getElementById('simple-screen-query');
 if (screen) screen.value = q;
 // Counts were for the old question — force a re-rank after re-prepare.
 _simpleScreenCounts = { low: null, medium: null, high: null };
 try {
  saveFetchPrefs();
 } catch (e) { /* ignore */ }
}

/**
 * Simple re-prepare dialog: research question lives *in the same popup* as
 * only-new / redo-all (not a separate step). Sets #only-missing + verified
 * query. Returns false if cancelled.
 */
async function resolveSimplePrepareModeBeforeRequest() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) {
  return true;
 }
 let ready = 0;
 let total = Number(_lastTotalArticles) || 0;
 try {
  const stats = await apiCall('/api/statistics');
  ready = Number(stats.articles_with_embeddings) || 0;
  total = Number(stats.total_articles) || total;
  _lastTotalArticles = total;
 } catch (err) {
  console.warn('Could not load prepare counts for dialog:', err);
 }
 const box = document.getElementById('only-missing');
 const current = getResearchQuestionCandidate();

 // Always open a re-prepare dialog with the research question field visible.
 // When nothing is prepared yet, only Continue / Cancel (no scope choice).
 if (typeof openSiteChoice !== 'function') {
  if (ready <= 0 && box) box.checked = true;
  return true;
 }

 const allLabel = total > 0 ? `Redo all ${total}` : 'Redo all papers';
 const choices = ready <= 0
  ? [
   { label: 'Continue', value: 'missing', primary: true },
   { label: 'Cancel', value: null, cancel: true },
  ]
  : [
   { label: 'Only new papers', value: 'missing', primary: true },
   { label: allLabel, value: 'all' },
   { label: 'Cancel', value: null, cancel: true },
  ];

 const result = await openSiteChoice({
  title: 'Re-prepare papers for search',
  message: ready <= 0
   ? 'Check that this research question is still what you want. Edit if needed — Narrow it down will use it next.'
   : 'Check that this research question is still what you want, then choose how much to re-prepare. Only new papers need this most of the time.',
  withInput: true,
  inputLabel: 'Your research question',
  defaultValue: current,
  placeholder: 'e.g., climate change effects on ecosystems',
  requireNonEmpty: true,
  emptyMessage: 'Please confirm your research question before re-preparing.',
  selectAll: !current,
  choices,
 });
 if (result == null) return false;

 // withInput → { value, input }; bare string if modal helper is older.
 let scope = result;
 let question = current;
 if (result && typeof result === 'object' && 'value' in result) {
  scope = result.value;
  question = result.input;
 }
 if (scope == null) return false;

 applyVerifiedResearchQuestion(String(question || '').trim());
 if (box) box.checked = scope !== 'all';
 return true;
}

async function resolveSimpleFetchModeBeforeRequest() {
 if (typeof isSimpleMode !== 'function' || !isSimpleMode()) {
  return true;
 }
 let total = Number(_lastTotalArticles) || 0;
 try {
  const stats = await apiCall('/api/statistics');
  if (stats && stats.total_articles != null) {
   total = Number(stats.total_articles) || 0;
   _lastTotalArticles = total;
  }
 } catch (err) {
  console.warn('Could not load paper count for fetch dialog:', err);
 }
 const setMode = (value) => {
  const radio = document.querySelector(`input[name="fetch-mode"][value="${value}"]`);
  if (radio) radio.checked = true;
  syncOnlyMissingFromFetchMode();
 };
 // Empty collection: choice is meaningless — start fresh, no dialog.
 if (total <= 0) {
  setMode('replace');
  return true;
 }
 if (typeof openSiteChoice !== 'function') {
  // Fallback: keep radios (hidden in Simple CSS) if modal helper missing.
  return true;
 }
 const nLabel = total === 1 ? '1 paper' : `${total} papers`;
 const choice = await openSiteChoice({
  title: 'You already have papers',
  message:
   `You already have ${nLabel}. Start fresh deletes those papers and any notes, ` +
   `stars, and saved AI key points — this cannot be undone. Or add these results ` +
   `to what you have?`,
  choices: [
   { label: 'Start fresh', value: 'replace', primary: true },
   { label: 'Add to them', value: 'append' },
   { label: 'Cancel', value: null, cancel: true },
  ],
 });
 if (choice == null) return false;
 setMode(choice === 'append' ? 'append' : 'replace');
 return true;
}

async function doFetch() {
 if (isSimpleFetchLocked()) {
  showNotification('This collection already has papers. Use Start over if you want to fetch again.', 'info');
  return;
 }
 const sources = Array.from(
 document.querySelectorAll('#source-option-grid input[type="checkbox"]:checked')
 ).map(cb => cb.value);
 const query = document.getElementById('fetch-query').value.trim();
 const maxResults = parseInt(document.getElementById('fetch-max').value, 10);
 const email = document.getElementById('fetch-email').value.trim();

 setNextStepVisible(false);
 if (!query) { showNotification('Please enter a search query.', 'error'); return; }
 if (sources.length === 0) { showNotification('Please select at least one source.', 'error'); return; }

 // Simple: dialog (or skip when empty) must run BEFORE reading fetch-mode.
 // Unlock already ran that dialog — do not ask twice.
 let proceed = true;
 if (_simpleFetchModePicked) {
  _simpleFetchModePicked = false;
 } else {
  proceed = await resolveSimpleFetchModeBeforeRequest();
 }
 if (!proceed) return;

 const mode = (document.querySelector('input[name="fetch-mode"]:checked') || {}).value || 'replace';
 const clearFirst = mode === 'replace';

 saveFetchPrefs();

 const btn = document.getElementById('fetch-btn');
 const cancelBtn = document.getElementById('fetch-cancel-btn');
 // Hide Simple re-prepare for the whole fetch (+ auto-chain) window.
 _pipelineBusy = true;
 setSimpleScreenSkipped(false);
 clearSimpleScreenUndoItems();
 _simpleScreenCounts = { low: null, medium: null, high: null };
 updatePrepareSectionVisibility(_lastTotalArticles);
 setNextStepVisible(false);
 refreshSimpleScreeningCard(); // hides while busy
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

 let autoChainFailed = false;
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
 _lastTotalArticles = Math.max(_lastTotalArticles, totalFetched);
 // Still busy: keep prepare hidden; progress stays on the fetch bar.
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
 autoChainFailed = true;
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
 _pipelineBusy = false;
 _simpleFetchUnlocked = false;
 _simpleFetchModePicked = false;
 // After a failed auto-prepare with papers in hand, force the re-prepare card open
 // so the student has a control (ready count may still be 0).
 if (autoChainFailed && _lastTotalArticles > 0) {
  updatePrepareSectionVisibility(_lastTotalArticles, { forceShow: true });
 } else {
  updatePrepareSectionVisibility(_lastTotalArticles);
 }
 // Simple screening card becomes available once papers are prepared.
 refreshSimpleScreeningCard();
 setLoading(btn, false);
 if (cancelBtn) {
 cancelBtn.hidden = true;
 cancelBtn.disabled = false;
 }
 }
}

/**
 * Phase 6 Simple: after auto-prepare, resolve near-duplicates without a UI.
 * Preferred-source rule lives on the server (threshold 0.98 default).
 * Failures are logged only — never block the fetch → screen → search flow.
 * @returns {Promise<string|null>} one-line outcome, or null if nothing/error
 */
async function silentResolveDuplicatesAfterPrepare() {
 try {
  const data = await apiCall('/api/resolve-duplicates', {
   method: 'POST',
   body: { threshold: 0.98 },
  });
  const n = Number(data && data.excluded) || 0;
  if (n <= 0) return null;
  return n === 1
   ? 'Removed 1 duplicate copy.'
   : `Removed ${n} duplicate copies.`;
 } catch (err) {
  console.warn('Silent duplicate resolve failed (continuing):', err);
  return null;
 }
}

async function doCreateEmbeddings(opts) {
 // Button click passes a DOM Event; only treat real option bags as auto-chain.
 const fromAutoChain = !!(opts && opts.fromAutoChain === true);
 const simple = typeof isSimpleMode === 'function' && isSimpleMode();
 const modelEl = document.getElementById('embedding-model');
 const model = (modelEl && modelEl.value) || 'general';
 // Simple manual re-prepare: dialog before reading only_missing.
 // Auto-chain after fetch keeps the radio-driven only-missing state (no dialog).
 if (simple && !fromAutoChain) {
  const ok = await resolveSimplePrepareModeBeforeRequest();
  if (!ok) return;
 }
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
 const preparedCount = data.articles_processed != null ? data.articles_processed : created;
 if (simple || fromAutoChain) {
 setStatus(
 'embeddings-status',
 `Ready: ${created} paper(s) prepared`
  + (skipped ? `, ${skipped} already ready` : '')
  + `. Total ready for search: ${data.articles_processed}.`,
 'success'
 );
 let fetchLine =
  `Fetched and prepared ${preparedCount} paper(s) for search.`;
 // Phase 6: Simple auto-flow removes duplicates silently after prepare.
 // Advanced is unchanged — students still use Clean up for dedup.
 if (fromAutoChain && simple) {
  const dedupLine = await silentResolveDuplicatesAfterPrepare();
  if (dedupLine) fetchLine = `${fetchLine} ${dedupLine}`;
 }
 setStatus('fetch-status', fetchLine, 'success');
 showNotification(
  simple
   ? 'Your papers are ready — narrow them down, then Search.'
   : 'Your papers are ready — next: Clean up, then Search.',
  'success'
 );
 // Simple: screening card (not Go to Search yet). Advanced: no next-step bar.
 if (!simple) {
  setNextStepVisible(false);
 }
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
 // Manual Simple re-prepare: clear low_relevance exclusions so screening
 // returns to *pending* via corpus state (not a JS flag) and survives reload.
 // Uses existing POST /api/screening include — no new endpoint.
 if (simple && !fromAutoChain) {
  try {
   const excl = await apiCall('/api/screening/excluded?reason=low_relevance');
   const items = (excl && excl.items) || [];
   if (items.length) {
    await apiCall('/api/screening', {
     method: 'POST',
     body: { items, action: 'include', reason: 'low_relevance' },
    });
   }
   setSimpleScreenSkipped(false);
   clearSimpleScreenUndoItems();
  } catch (screenErr) {
   console.warn('Could not reset screening after re-prepare:', screenErr);
  }
 }
 await loadPageData();
 // Manual re-prepare (and auto-chain) must refresh Narrow it down so the
 // confirm-your-question box appears without a full page reload.
 await refreshSimpleScreeningCard();
 if (simple) {
  const card = document.getElementById('simple-screening-card');
  if (card && !card.hidden) {
   try {
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
   } catch (e) { /* ignore */ }
  }
 }
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
