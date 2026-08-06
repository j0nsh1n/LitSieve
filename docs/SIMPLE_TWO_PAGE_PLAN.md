# Plan — Simple mode on two pages (Phase 6)

Build doc, written to be executed by someone who has not seen the design
conversation. Follows Phase 5 (`docs/SIMPLE_MODE_PLAN.md`), which shipped in
v4.5.0.

## Goal

Reduce **Simple mode** to two pages:

```
1. Get papers   /data-management   fetch → auto-prepare → screening card
2. Search       /search            results + sticky export / report panel
```

Clean up (`/statistics`) and Clusters (`/clusters`) leave the Simple nav. Both
routes keep working and both stay in Advanced.

## Non-goals

- **Advanced mode does not change at all.** Same pages, same controls, same
  nav, same numbering. Every change here is behind `html[data-mode="simple"]`
  or an explicit Simple-mode branch in JS.
- No new ranking, clustering, or dedup algorithms.
- No server-side enforcement — Simple/Advanced stays a client preference.
- No new capability. Anything Simple can do, Advanced can already do.

---

## Constraints (read before writing code)

Carried from Phase 5 because they are still the things most easily broken.

1. **One uvicorn worker.** Heavy work goes through `core.start_user_job`, never
   inline in a request. Password hashing on the event loop once froze the site
   for every concurrent user.
2. **No auto-clustering.** Deliberate decision, not an oversight: the screening
   card ranks papers against the research question, which needs embeddings and
   not clusters. Clustering is the heaviest operation in the app and nothing in
   this flow consumes it. Clusters stay an Advanced-only page.
3. **Jobs are in-memory** (`core._all_progress`) and die on restart. No UI state
   may depend on a job surviving a reload.
4. **CSRF on every non-GET.** `common.js#apiCall` already attaches the header.
5. **Public templates** (landing, login, register, feature_guide,
   reset_password, verify_email) do not extend `base.html` and must not load
   `common.js`.
6. **`theme-init.js` stays a blocking, non-module `<script src>`** in `<head>`
   (CSP is `script-src 'self'`; deferring causes a flash of the wrong mode).
7. **Bump `?v=` on every asset you change**, in *all* templates that reference
   it. `tests/test_static_js.py` enforces cross-template consistency.
8. Never edit `agents.md`. `spec.md` only with explicit human approval.
9. **Never `git push` or open a PR without being asked.** Commit locally.
10. Dev with `./run_dev.sh 7861` (isolated data). Never point a dev server at
    the live `users.db` — it has real accounts.
11. Before every commit: `ruff check .` clean and
    `SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q` green. Pyright
    baseline 61 errors / 6 warnings — do not add to it.
12. Deploy is `systemctl --user restart litsieve-uvicorn.service`. New API
    routes require it.

---

## Existing pieces to reuse (do not rebuild)

| Need | Already exists |
|------|----------------|
| Rank least-relevant | `POST /api/screening/quick-preview` — `{query, fraction}`, `fraction` 0.05–0.50, read-only |
| Apply exclusions | `POST /api/screening` — `{items, action, reason}` |
| Undo | same endpoint, `action="include"` |
| Find duplicates | `POST /api/detect-duplicates` — `{threshold}` |
| Auto-resolve duplicates | `POST /api/resolve-duplicates` — `{threshold}` (0.98 default, preferred-source rule) |
| Export search results | `POST /api/export/selection` |
| Screening report | `GET /api/screening-report?format=` |
| Reason code | `low_relevance` (already in `EXCLUSION_REASONS` + `SYSTEM_REASONS`) |

No new backend endpoints should be needed. If one seems necessary, say so
before adding it.

---

## Page 1 — Get papers (`/data-management`, Simple mode)

Order: topics → query + Fetch → (auto-prepare) → **screening card** → Go to Search.

### Auto-prepare

Already implemented in v4.5.0 and works. Do not change it. Progress shows on
the fetch bar; the re-prepare card stays hidden while `_pipelineBusy`.

### Duplicates: silent

Once prepare finishes, run `POST /api/resolve-duplicates` with the default
threshold as part of the same flow. The student never chooses anything.

- Report the outcome as one line, not a UI: *"Removed 12 duplicate copies."*
- If it fails, log it and continue — duplicates are a tidiness win, not a
  blocker. Never let a dedup failure strand the flow.
- Exclusions are recorded with the existing `duplicate` reason, so the
  screening report already accounts for them.

### Screening card (replaces the "Next: Clean up" button)

Renders **inline as the next card**, not as a surprise modal. A fetch takes
minutes; an unprompted modal after a long async job gets dismissed reflexively,
and dismissing means skipping screening entirely.

Content:

> **Narrow it down**
> Your question: `[editable field, pre-filled]`
> How much should we set aside?
> ( ) Low — sets aside about **25 of 200**
> (•) Medium — sets aside about **50 of 200**
> ( ) High — sets aside about **100 of 200**
> [Show me what would go] [Set them aside] [Skip this]

- Levels map to `fraction`: **low 0.10, medium 0.25, high 0.50**.
- **Each level must show the real count**, from `quick-preview`. "High" quietly
  removing half of someone's papers is how you lose their trust; the numbers
  make the trade visible. Fetch counts once and reuse — do not call the
  endpoint on every radio click.
- "Show me what would go" expands the actual titles. Preview and apply stay
  separate calls; nothing is excluded without an explicit apply.
- After applying: *"Set aside 50 papers. [Undo]"* — undo calls `/api/screening`
  with `action="include"`.
- **Skip is a first-class option.** A student who wants everything must be able
  to move on.

**Must survive a reload.** Jobs are in-memory, so derive "screening still
pending" from the corpus (papers prepared, none excluded with `low_relevance`),
not from a JS flag. The research question comes from
`localStorage.lra_fetch_prefs_v1`; keep it editable.

### Go to Search

Once screening is applied or skipped, show the primary action:
**"Go to Search →"** linking to `/search`. Hide it again if a new fetch starts.

---

## Page 2 — Search (`/search`, Simple mode)

Search itself is unchanged. Add a **results side panel** that stays with the
student as they scroll:

- **Export these results** → `POST /api/export/selection`
- **Download screening report** → `GET /api/screening-report`

Appears only once a search has returned results. The report is the academic
artifact students hand in — it must be obvious, not buried.

---

## Small screens (design this in, do not retrofit)

Real users are overwhelmingly on phones. Existing breakpoints in
`static/css/style.css`: `900px`, `640px`, `380px`, plus `(hover: none)`.

- **A scroll-following side panel does not work below ~900px.** Under that,
  collapse it to a **bottom action bar** (or a single button that opens a small
  sheet). It must not cover the last result card — add bottom padding to the
  results list equal to the bar height.
- The screening card's radio options must stack vertically under 640px, with
  tap targets ≥44px (`(hover: none)` already exists for touch tweaks).
- The title preview list must be scrollable with a max height, not an
  unbounded list that pushes the buttons off-screen.
- Test at **380px** — that is the narrowest breakpoint the CSS already
  acknowledges.

---

## Work, in shippable order

Each step is its own commit, tests green, useful on its own.

1. **Silent duplicates** after auto-prepare, with the one-line outcome. Small,
   independent, no UI surface.
2. **Screening card** inline on `/data-management` (levels, counts, preview,
   apply, undo, skip) + "Go to Search". Replaces the Phase 5 "Next: Clean up"
   button.
3. **Search side panel** (export + report), desktop layout.
4. **Small-screen treatment** for both the card and the panel.
5. **Nav**: remove Clean up from the Simple nav; Simple becomes
   `Get papers → Search` (2 steps, contiguous numbering). `/statistics` and
   `/clusters` keep working by URL and stay in Advanced.

---

## Acceptance criteria

- [ ] Advanced mode is byte-for-byte unchanged in behaviour: same pages, same
      nav, same numbering, same controls.
- [ ] A Simple student can go topics → fetch → screen → search → export without
      leaving two pages, and without seeing "embedding", "cluster", "HDBSCAN",
      "threshold", or a model name.
- [ ] Nothing clusters automatically anywhere.
- [ ] Duplicate removal happens without a decision and is reported in one line.
- [ ] Each screening level shows a real count before it is applied.
- [ ] Nothing is excluded without an explicit apply; undo restores.
- [ ] Skipping screening leaves a usable library.
- [ ] Reloading mid-flow does not lose or duplicate the screening step.
- [ ] At 380px: no horizontal scroll, no control covered by the bottom bar, all
      tap targets reachable.
- [ ] `ruff check .` clean, full pytest green, pyright ≤ 61/6.

## Tests to add

- Screening levels map to the documented fractions, and every fraction is
  within the endpoint's 0.05–0.50 bounds.
- Preview does not exclude anything (assert corpus unchanged after a preview).
- Apply then undo returns the corpus to its previous count.
- Skip leaves zero `low_relevance` exclusions and a usable library.
- Duplicate auto-resolve runs after prepare and its failure does not block the
  flow (simulate a failing call).
- The screening card's pending/complete state is derived from the corpus, not a
  JS flag — assert it survives a simulated reload.
- Advanced mode still renders Clean up and Clusters in the nav, and its step
  numbering is unchanged.
- Simple nav numbering is contiguous (1, 2) with no gap.
- JS parses (`tests/test_static_js.py` already covers this).
- Asset `?v=` tokens are consistent across templates (already enforced).

## Things that will bite

- **The modal instinct.** Resist it. Inline, or modal-only-if-focused with an
  inline fallback.
- **Counting on every radio click** will hammer `quick-preview`. Fetch once.
- **Hidden controls still submit.** Anything the Simple card hides must still
  send a valid value — this bit us in Phase 5 with the source list.
- **The screening report gets thinner** if students skip screening. That is
  acceptable; do not compensate by auto-applying exclusions without consent.
- **`/statistics` still exists.** Do not delete the page or its JS just because
  the Simple nav no longer points at it — Advanced uses it.
