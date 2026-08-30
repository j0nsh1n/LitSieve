/** Reader Mode: Explain this study panel (Search + Clean up). */

(function () {
    const STATUS_COPY = {
        no_automatic_issues: 'Automatic checks found no obvious issues',
        needs_review: 'Some details may need checking',
        verification_incomplete: 'Automatic checks could not run fully',
    };
    const SECTION_LABELS = [
        ['plain_summary', 'In short'],
        ['question_asked', 'What they asked'],
        ['who_was_studied', 'Who was studied'],
        ['what_was_found', 'What they found'],
        ['what_it_does_not_show', 'What this does not show'],
        ['stated_limitations', 'Limits the paper states'],
    ];

    function safeId(aid, src) {
        return `reader-${String(aid || '')}-${String(src || '')}`.replace(/[^A-Za-z0-9_-]/g, '');
    }

    function statusClass(status) {
        if (status === 'needs_review') return 'is-warn';
        if (status === 'verification_incomplete') return 'is-incomplete';
        return 'is-ok';
    }

    function renderGlossary(entries) {
        const list = (entries || []).filter((e) => e && e.term && e.definition);
        if (!list.length) return '';
        const rows = list.map((e) => (
            `<div class="reader-glossary-row">`
            + `<dt>${escapeHtml(String(e.term))}</dt>`
            + `<dd>${escapeHtml(String(e.definition))}</dd>`
            + `</div>`
        )).join('');
        return `<details class="reader-glossary">`
            + `<summary>Words used in this explanation</summary>`
            + `<dl>${rows}</dl>`
            + `</details>`;
    }

    function renderWarnings(verification) {
        const checks = (verification && verification.checks) || [];
        const warns = checks.filter((c) => c && c.outcome === 'warn' && c.message);
        if (!warns.length) return '';
        const items = warns.map((c) => `<li>${escapeHtml(String(c.message))}</li>`).join('');
        return `<ul class="reader-warnings">${items}</ul>`;
    }

    function renderExplanation(data, aid, src) {
        const content = data.content || {};
        const verification = data.verification || {};
        const status = verification.status || 'verification_incomplete';
        const chipText = STATUS_COPY[status] || STATUS_COPY.verification_incomplete;
        const hid = `${safeId(aid, src)}-h`;
        const sections = SECTION_LABELS.map(([key, label]) => {
            const text = content[key] ? String(content[key]) : '';
            if (!text) return '';
            return `<section class="reader-section">`
                + `<h4 class="reader-section-heading">${escapeHtml(label)}</h4>`
                + `<p class="reader-section-body">${escapeHtml(text)}</p>`
                + `</section>`;
        }).join('');
        const cachedBit = data.cached
            ? `<p class="reader-cached help-text">Saved explanation · `
              + `<button type="button" class="btn-link reader-regen-btn">Regenerate</button></p>`
            : '';
        const readability = verification.readability || {};
        const grade = readability.flesch_kincaid_grade;
        const gradeBit = (typeof grade === 'number')
            ? `<p class="help-text reader-readability">Reads at about a ${escapeHtml(String(Math.round(grade)))}th-grade level `
              + `(target: ${escapeHtml(String(readability.target_band || 'grades 8-10'))}). `
              + `${escapeHtml(String(readability.caveat || ''))}</p>`
            : '';
        return `<div class="reader-mode-panel" role="region" aria-labelledby="${hid}">`
            + `<h3 class="reader-mode-heading" id="${hid}" tabindex="-1">AI explanation — generated from this abstract</h3>`
            + `<p class="ai-label help-text">${escapeHtml(data.label || 'AI explanation (from this abstract only)')}</p>`
            + cachedBit
            + `<p class="reader-status-chip ${statusClass(status)}">${escapeHtml(chipText)}</p>`
            + renderWarnings(verification)
            + sections
            + renderGlossary(content.glossary)
            + gradeBit
            + `<p class="reader-disclaimer">${escapeHtml(data.disclaimer || '')}</p>`
            + `<p><a href="#reader-original" class="reader-show-original">Show original abstract</a></p>`
            + `</div>`;
    }

    function audienceFormHtml() {
        return `<form class="reader-audience-form">`
            + `<fieldset class="reader-audience">`
            + `<legend>Reading level</legend>`
            + `<label class="radio-label"><input type="radio" name="reader-audience" value="general_reader" checked> General reader</label>`
            + `<label class="radio-label"><input type="radio" name="reader-audience" value="high_school"> High school</label>`
            + `</fieldset>`
            + `<button type="submit" class="btn btn-secondary btn-sm reader-submit-btn">Explain</button>`
            + `</form>`;
    }

    function bindReaderModeActions(opts) {
        const wrap = opts && opts.wrap;
        const panel = opts && opts.panel;
        const article = opts && opts.article;
        const setStatus = opts && opts.setStatus;
        const showPanel = opts && opts.showPanel;
        const softAiError = opts && opts.softAiError;
        if (!wrap || !panel || !article) return;
        const btn = wrap.querySelector('.reader-mode-btn');
        if (!btn) return;
        const aid = article.article_id;
        const source = article.source;
        let lastAudience = 'general_reader';
        let escapeHandler = null;

        const clearEscape = () => {
            if (escapeHandler) {
                document.removeEventListener('keydown', escapeHandler);
                escapeHandler = null;
            }
        };

        const armEscape = () => {
            clearEscape();
            escapeHandler = (ev) => {
                if (ev.key !== 'Escape') return;
                ev.preventDefault();
                panel.hidden = true;
                clearEscape();
                btn.focus();
            };
            document.addEventListener('keydown', escapeHandler);
        };

        const scrollToAbstract = (ev) => {
            if (ev) ev.preventDefault();
            const root = wrap.closest('.result-card, .cluster-article, .article-card') || wrap.parentElement;
            const abs = root && root.querySelector('.article-abstract');
            if (abs && typeof abs.scrollIntoView === 'function') {
                abs.scrollIntoView({ block: 'nearest' });
            }
        };

        const paint = (data) => {
            showPanel(renderExplanation(data, aid, source));
            const heading = panel.querySelector('.reader-mode-heading');
            if (heading && typeof heading.focus === 'function') heading.focus();
            const orig = panel.querySelector('.reader-show-original');
            if (orig) orig.addEventListener('click', scrollToAbstract);
            const regen = panel.querySelector('.reader-regen-btn');
            if (regen) {
                regen.addEventListener('click', (ev) => {
                    ev.preventDefault();
                    runExplain(lastAudience, true);
                });
            }
            armEscape();
        };

        const runExplain = async (audience, force) => {
            lastAudience = audience;
            setStatus('Starting study aid and explaining this paper…', true);
            btn.disabled = true;
            try {
                const data = await apiCall('/api/reader/explain', {
                    method: 'POST',
                    body: {
                        article_id: aid,
                        source: source,
                        audience: audience,
                        force_regenerate: !!force,
                    },
                });
                setStatus('', false);
                paint(data);
            } catch (err) {
                setStatus('', false);
                const msg = err && err.message ? String(err.message) : 'AI explain failed';
                if (/too short|empty/i.test(msg)) {
                    showNotification(msg, 'warning');
                } else if (typeof softAiError === 'function') {
                    softAiError(msg, 'explain');
                } else {
                    showNotification(msg, 'error');
                }
            } finally {
                btn.disabled = false;
            }
        };

        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            showPanel(audienceFormHtml());
            armEscape();
            const form = panel.querySelector('.reader-audience-form');
            const firstRadio = panel.querySelector('input[name="reader-audience"]');
            if (firstRadio && typeof firstRadio.focus === 'function') firstRadio.focus();
            if (!form) return;
            form.addEventListener('submit', (ev) => {
                ev.preventDefault();
                const picked = form.querySelector('input[name="reader-audience"]:checked');
                runExplain((picked && picked.value) || 'general_reader', false);
            });
        });
    }

    window.bindReaderModeActions = bindReaderModeActions;
})();
