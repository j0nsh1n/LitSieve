# Plan — Simple mode on one page

**Status:** Steps 1–5 implemented 2026-08-13. spec.md Simple nav updated.

Build note for collapsing Simple from Get papers → Search into **one surface**.
Advanced is unchanged. Follows Phase 6 (`docs/SIMPLE_TWO_PAGE_PLAN.md`) and the
dialogs already shipped (fetch lock, re-prepare popup, Narrow it down popup).

## Goal

A Simple student lives on **one URL**. The page shows only the current job.
Everything else is hidden or in a popup they opened.

```
Empty library     topics + question + Fetch + progress
Busy              progress only
Has papers        question + Search + results + Show chips + export
```

Nav in Simple is brand + library + account. No step 1 / 2.

## Non-goals

- Advanced does not change. `/data-management`, `/statistics`, `/clusters`,
  `/search` stay as they are when `data-mode` is not simple.
- No new endpoints. No new JS bundle / npm.
- No surprise modal after a minutes-long fetch (Phase 6 still holds). Narrow
  it down opens only when they tap the button.
- Do not concatenate both existing pages into one long scroll.

## Already shipped (reuse, do not rebuild)

| Piece | Where |
|---|---|
| Fetch lock + Start over dialog | `data_management.js` |
| Re-prepare dialog (question + only-new/all) | `data_management.js` + `openSiteChoice` |
| Narrow it down popup (Low/Med/High, preview, apply, skip, undo) | `simple_screening_card.html` |
| Show chips (starred / note / recent / source) | `search.js` |
| Modal shell (focus trap, Escape, bottom sheet, scroll lock) | `common.js` `openSiteModal` |
| Silent dedup after auto-prepare | `data_management.js` |
| Guest: no multi-source fetch | server 403 + CSS |

## What stays on the page vs popup vs gone

**Always on (once they have papers):** research question, Search, results,
Show chips, export.

**Popup (tap to open):** Narrow it down, Re-prepare, Start over / add papers,
optional “What we fetched” source report.

**Hidden until needed:** topics (only when the library is empty), Fetch form
(only when empty or after Start over), progress (only while a job runs).

**Gone from Simple:** Go to Search hop, step numbers, Coverage, source
checkboxes, Advanced fetch/prepare details.

---

## Work, in shippable order

Each step is its own commit, green tests, useful alone. Do not start Step 3
until spec.md’s Simple-nav lines are human-approved.

### Step 1 — Search is home when the library has papers

If Simple and `total_articles > 0` (or embeddings ready), visiting
`/data-management` redirects to `/search`. Empty libraries stay on Get papers.

- Implement in the page route (`app/routes/pages.py`), client-only is not
  enough: a bookmark to Get papers should land on Search.
- Guest with sample papers already loaded follows the same rule.
- Advanced never redirects.
- Keep `/data-management` working when Simple users need Start over: add
  `?collect=1` (or similar) that skips the redirect.

**Done when:** a Simple account with papers that opens Get papers sees Search;
an empty Simple account still sees Fetch.

### Step 2 — Tools strip on Search (no second page)

On Search in Simple, when the library has papers, show a one-line strip:

`231 papers · Narrow it down · Re-prepare · Start over`

- Narrow it down reuses the existing popup (move the partial include onto
  Search, or load the same markup from a shared partial — it already is a
  partial).
- Re-prepare and Start over reuse the existing dialogs. That means Search
  must load the small dialog helpers (or a shared slice of DM JS), **not**
  all of `data_management.js`.
- Undo / skip outcome from Narrow it down stays on the strip, not a card.

**Done when:** a Simple student can screen, re-prepare, and start over without
leaving `/search`. Get papers is unused except empty / `?collect=1`.

### Step 3 — Empty state lives on Search too

When Simple and the library is empty, `/search` renders the collect UI
(topics + question + Fetch + progress) instead of “Nothing to search yet”.

- Preferred home for Simple: `/search` always. Empty → collect. Full → search.
- `/data-management` in Simple redirects to `/search` (or `/search?collect=1`
  if empty, to the same collect view).
- After a successful fetch+prepare on this page, hide collect, show Search
  (no navigation).
- Progress stays on-page; do not open Narrow it down automatically.

**Done when:** a new Simple account can fetch → prepare → search → export
without changing URL. `spec.md` Simple nav updated (human-approved) from
“Get papers → Search” to “one Search page, two states”.

### Step 4 — Simple nav is not a stepper

Hide the workflow step control in Simple. Brand + library + mode + account
+ logout remain. `/data-management` stays in Advanced and by URL.

**Done when:** Simple nav has no “1 Get papers / 2 Search”; tests that
assert two Simple steps are rewritten, not deleted without replacement.

### Step 5 — Freeze leftover collect chrome

Once Step 3 is in:

- Topics disappear after the library has papers (already planned with the
  fetch lock).
- Source report is a tap on “N papers · K sources”, not a block on the page.
- Getting-started checklist only on the empty collect state.

**Done when:** a library with papers shows Search + the tools strip + results;
no topic grid, no fetch form, no coverage.

---

## Constraints (same as Phase 6)

1. One uvicorn worker; jobs via `start_user_job`.
2. Jobs die on restart; UI state from the corpus, not the job.
3. CSRF on every non-GET.
4. Public templates do not load `common.js`.
5. Bump `?v=` on every asset you change, all templates that reference it.
6. Never edit `agents.md`. `spec.md` only with explicit approval (needed
   before Step 3).
7. No push unless asked. Dev: `./run_dev.sh 7861`.

## Acceptance (whole phase)

- [x] Empty Simple: topics → fetch → auto-prepare on one URL
- [x] Full Simple: search, Show chips, export, Narrow it down / Re-prepare /
      Start over as popups, same URL
- [x] No auto-opened screening dialog after fetch
- [x] Advanced pages, nav, and controls unchanged
- [x] Guest still cannot multi-source fetch
- [ ] 380px: no horizontal scroll; export bar still clears the last result
- [x] `ruff check .` clean, full pytest green

## spec.md (propose, do not edit until approved)

Replace the Simple nav / flow bullets with: Simple is one page (`/search`)
with an empty collect state and a papers-present search state; screening and
re-prepare are popups; Advanced nav unchanged.
