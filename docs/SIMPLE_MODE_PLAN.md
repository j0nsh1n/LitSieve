# Plan — Simple / Advanced mode

Build doc for the Simple-mode work. Written to be executed by someone (or
something) that has not seen the rest of this conversation.

## Goal

A per-user **Simple / Advanced** toggle. Simple mode hides power-user surfaces
and automates the steps a student should not have to think about, without
removing any capability from Advanced mode.

Target user: high-school / early-college students. The product is a *starting
point* for a literature review, not a full library search.

## Non-goals

- No new product features. This is presentation + automation of existing ones.
- No server-side enforcement. Simple/Advanced is a **client preference**, like
  the existing theme and reading-mode toggles. A user flipping to Advanced and
  seeing everything is correct behaviour, not a bug.
- No changes to the ranking, clustering, dedup, or export algorithms.
- No redesign of Advanced mode. It keeps every control it has today.

---

## Constraints (read before writing code)

These are specific to this repo and easy to violate by accident.

1. **One uvicorn worker.** Anything heavy MUST run through the existing
   background-job system (`core.start_user_job`), never inline in a request.
   Password hashing on the event loop once froze the whole site for every
   concurrent user; clustering is far heavier than that.
2. **Jobs are in-memory** (`core._all_progress`) and die on restart. Do not
   design anything that assumes a job survives a deploy.
3. **CSRF** is required on every non-GET request (`core.csrf_failed`).
   `static/js/common.js#apiCall` already attaches the header.
4. **Public templates** (`landing`, `login`, `register`, `feature_guide`,
   `reset_password`, `verify_email`) do **not** extend `base.html`, and must not
   load `common.js`. Anything added to `base.html` will not appear on them.
5. **`theme-init.js` must stay a blocking `<script src>` in `<head>`** — no
   defer/async/module, no inline script (CSP is `script-src 'self'`). Mode must
   be applied there, pre-paint, or users see a flash of the wrong layout.
6. **Governance**: never edit `agents.md`. Do not edit `spec.md` without
   explicit human approval — if this work changes the contract (it changes the
   "Clusters page is the only triage UI" line), *propose* the edit, do not make
   it.
7. **Never `git push` or open a PR without being asked.** Commit locally.
8. **Dev server**: `./run_dev.sh 7861`. It isolates data (`dev_users.db`,
   `dev_data/`, `logs/dev.log`). Never point a dev server at the live
   `users.db` — there are real accounts in it.
9. **Deploy** is `systemctl --user restart litsieve-uvicorn.service`. Run the
   test suite first.
10. Tests: `SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q`. Use
    `./venv`. Keep `ruff check .` clean. Pyright baseline is 61 errors /
    6 warnings — do not add to it.

---

## Design decisions already made

- **Mechanism**: `data-mode="simple"` on `<html>`, persisted in
  `localStorage.uiMode`, applied in `theme-init.js`. Most hiding is CSS.
- **Toggle placement**: replaces the current reading-mode button in the
  `base.html` nav.
- **Reading mode is retired**, but keep its serif abstract styling by folding
  those rules into the default. Do not delete the typography, only the toggle
  and the 28 `html[data-reading="on"]` rules.
- **Default**: Simple for newly registered accounts, Advanced for accounts that
  already exist (there are live users; do not change the UI under them).
  Implement by seeding `localStorage.uiMode` at first login based on account
  age, or simplest acceptable equivalent.
- **Clusters page leaves the nav in Simple mode.** Screening moves to the
  Duplicates page, renamed **Clean up**. The `/clusters` route keeps working so
  existing bookmarks do not 404.
- **Two screening paths**, both writing to existing endpoints and both feeding
  the same PRISMA report:
  - *Quick screen* — app suggests by relevance, student approves (Simple default)
  - *By topic group* — the existing cluster triage, simplified
- Per-paper **"Not relevant"** on Search result cards as a catch-all.

---

## Work, in shippable order

Each step should be its own commit, green tests, and be useful on its own.

### Step 1 — Mode toggle + CSS layer (no behaviour change)

- `static/js/theme-init.js`: read `localStorage.uiMode`, set
  `data-mode="simple"` on `<html>` before paint. Keep the existing try/catch —
  localStorage throws in private mode and must never break the page.
- `templates/base.html`: replace the reading-mode button with a mode toggle.
  Keep it keyboard accessible and `aria-pressed`-correct, matching the existing
  theme button.
- `static/js/common.js`: wire the toggle (mirror the existing
  `reading-toggle` handler around line 811).
- `static/css/style.css`: new section, `html[data-mode="simple"] …` rules only.
  Do not touch existing selectors; add, do not restructure.
- Retire reading mode: delete the toggle + its 28 rules; move the serif
  `.article-abstract` styling into the default.

Hide in Simple (CSS only, this step):

| Page | Hide |
|------|------|
| Data Management | "2. Choose Sources" grid, Coverage map, Advanced fetch options, Advanced preparation options, embedding-model selector |
| Duplicates | "Articles by Source", "Papers by year", match-strictness control |
| Search | "Advanced: ranking options and source filter", seed-paper mode, "Export whole library instead", similarity percentages |
| Nav | Clusters link |

**Critical**: hidden controls are still in the DOM and still submit. Sources are
already auto-checked by `updateRecommendedSources()`
(`static/js/data_management.js:354`) whenever topics are selected, and the
model by `recommendModel()`. Verify the values actually submitted in Simple
mode are valid — never an empty source list.

Renumber the nav steps so Simple reads 1–3 with no gap.

### Step 2 — Auto-chain fetch → prepare

- After a successful fetch in Simple mode, automatically start the embedding
  job instead of waiting for the "Prepare Papers" click.
- Reuse `start_user_job` and the existing progress UI. Do not block the request.
- Present it as one continuous "Getting your papers ready" progress, not two.
- Advanced mode keeps the two explicit buttons.
- If the fetch returns zero papers, do not start an embed job.

### Step 3 — Clean up page (Duplicates + screening)

Rename the Duplicates page to **Clean up** (`templates/statistics.html`,
nav label, page header). Route stays `/statistics`.

Order on the page in Simple mode:
1. Remove duplicates (existing)
2. **Quick screen** (new, below)
3. Download screening report (existing)

**Quick screen**

- Input: the student's research question. It currently exists only in
  `localStorage.lra_fetch_prefs_v1` and is never sent to the server. Show it as
  a pre-filled, editable field.
- Rank all non-excluded papers against that question using the existing search
  machinery (query embedding + cosine, same path as `search_similar`).
- Propose the least-related set. Conservative default (start with the bottom
  25%); offer "remove fewer / remove more".
- **Always preview the actual titles before applying.** Never auto-apply.
- Apply via the existing `POST /api/screening` with `action="exclude"`.
- Add a new reason code `low_relevance` to
  `app/content/screening_reasons.py`, in `EXCLUSION_REASONS` **and**
  `SYSTEM_REASONS` (it is system-suggested, not student-picked, so it must not
  appear in the student reason dropdown). `format_screening_report_txt`
  iterates `EXCLUSION_REASONS`, so it flows into the report automatically.
  This keeps the report honest about *how* a paper was excluded — a teacher can
  see which exclusions a human actually judged.
- Undo: re-include via the same endpoint with `action="include"`.
- If the corpus is large enough that ranking is slow, run it as a background
  job. Do not block the event loop.

**By topic group** (secondary link on the same page)

- Auto-run clustering with method `hdbscan` and auto count. Hide the method
  selector, count control, and reason dropdown in Simple mode.
- **Trigger lazily** — when the student opens this section, as a background
  job. Do **not** auto-cluster on fetch completion.
- Each group: plain-language label, count, 2–3 example titles, one
  **Keep / Not my topic** choice.
- Apply via existing `POST /api/clusters/{cluster_id}/screening`.
- Show a running "Keeping N of M papers" so the effect is visible.
- Undo must be one click.

### Step 4 — Per-paper "Not relevant" on Search

- One button per result card, `POST /api/screening` with a single item and
  reason `off_topic`. No dropdown in Simple mode.
- Remove the card from the current result list; make undo available.
- Advanced mode may keep the full reason picker.

---

## Acceptance criteria

- [ ] Toggling Simple/Advanced changes only presentation and automation; no
      capability is reachable in Simple that is not reachable in Advanced.
- [ ] A student in Simple mode can go topics → fetch → clean up → search →
      export RIS without ever seeing the words "embedding", "cluster",
      "HDBSCAN", or a model name.
- [ ] The screening report is non-empty after a Quick screen, and distinguishes
      `low_relevance` from student-judged reasons.
- [ ] Nothing heavy runs inline: fetch, prepare, and clustering all go through
      `start_user_job`.
- [ ] `/clusters` still loads directly by URL in Simple mode.
- [ ] Existing accounts default to Advanced; new accounts default to Simple.
- [ ] `ruff check .` clean, full pytest green, pyright not above 61/6.

## Tests to add

- Simple mode submits a valid, non-empty source list when the source grid is
  hidden (guards the "hidden control still submits" trap).
- `low_relevance` is in `EXCLUSION_REASONS` and in `SYSTEM_REASONS`, and does
  **not** appear in `USER_SELECTABLE_REASONS`.
- The screening report includes `low_relevance` counts when such exclusions
  exist.
- Quick screen preview and apply are separate calls — no endpoint excludes
  papers without an explicit apply.
- Re-include restores a paper excluded by Quick screen.
- `theme-init.js` sets `data-mode` before paint (assert the file has no
  `defer`/`async`/`type=module` and is referenced in `<head>`).
- A drift guard that the nav step numbers in Simple mode are contiguous.

## Things that will bite

- **Cluster label quality**: group screening is only simple if labels read like
  "diabetes in adolescents" and not "cluster 3". Sample real labels before
  building UI around them; if they are poor, ship Quick screen alone.
- **Semantic similarity is not relevance.** A genuinely relevant paper phrased
  unusually can rank low. This is why Quick screen must preview, must be
  conservative, and must be trivially undoable.
- **Auto-clustering on fetch would be the bcrypt incident again**, but in
  seconds-to-minutes instead of milliseconds. Lazy + background only.
- `spec.md` currently says the Clusters page is the only triage UI. That line
  becomes wrong. Propose the edit; do not make it unilaterally.
