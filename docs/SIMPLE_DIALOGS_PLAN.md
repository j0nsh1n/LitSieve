# Plan — Simple-mode dialogs + dense source report (Phase 8)

Build doc, written to be executed by someone who has not seen the design
conversation.

## Goal

Three changes that condense the Data Management page in **Simple mode**:

1. **Fetch mode** (replace vs add) moves out of the page into a dialog — and
   only appears when the choice actually means something.
2. **Re-prepare** asks its one real question in a dialog instead of exposing
   Advanced controls.
3. **The per-source fetch report** shows a few rows with an expander instead of
   15+ lines.

## Non-goals

- **Advanced mode does not change.** Same radios, same Advanced options, same
  report. Everything here is behind `data-mode="simple"` or an explicit Simple
  branch.
- No new endpoints. `clear_first` and `only_missing` already exist on the fetch
  and prepare requests.
- No change to what gets fetched, prepared, or excluded.

---

## Prerequisite — fix the modal shell first

`openSiteModal` (`static/js/common.js:370`, with `siteConfirm` / `sitePrompt` /
`siteAlert` wrappers at ~510–518) already exists and is used by the Account
page. It has `role="dialog"`, `aria-modal="true"`, Escape-to-close, and initial
focus.

It is **missing three things**, and this phase puts dialogs into the main flow
on phones, where all three bite:

1. **Focus trap.** Tab currently escapes the dialog into the page behind it.
2. **Focus restore.** On close, focus must return to the control that opened
   the dialog, or keyboard users are dumped at the top of the document.
3. **Body scroll lock.** Without it the background scrolls under the dialog —
   the classic mobile "I lost my place" bug. Restore the previous scroll
   position on close; do not just set `overflow: hidden` and forget it.

Do this as **step 1**, before any of the three features. It is shared
infrastructure and the Account page benefits immediately.

Also verify on a phone-sized viewport that a dialog containing a text input is
not hidden behind the soft keyboard. If it is, prefer a bottom-sheet layout at
`≤640px` over a vertically centred box.

---

## Feature 1 — Fetch mode dialog (Simple only)

### The insight that shapes this

"Replace collection" and "Add to collection" are **identical when the library
is empty**. Asking a first-time student to choose between them before they have
any papers is a decision with no meaning, and it is the first thing they see.

So do not simply move the radios into a dialog. Instead:

| Collection state | Simple-mode behaviour |
|---|---|
| **Empty** (0 papers) | No dialog. Fetch proceeds as `clear_first: true`. |
| **Has papers** | Dialog asks, then fetch proceeds with their choice. |

That removes a meaningless choice from the first run and surfaces a real one at
the exact moment it matters.

### The dialog

Opens on **Fetch** click, before the request:

> **You already have 231 papers**
> Start fresh, or add these results to what you have?
>
> [Start fresh] [Add to them] [Cancel]

- "Start fresh" → `clear_first: true`
- "Add to them" → `clear_first: false`
- Cancel → no request at all
- The count must be the **real** current total (`/api/statistics`
  `total_articles`), not a guess.

### Wiring details

- The radios (`input[name="fetch-mode"]`) stay in the DOM and keep working in
  Advanced. In Simple they are hidden by CSS, and the dialog result sets them
  before submit so every downstream reader keeps working unchanged — including
  `saveFetchPrefs()` and the `only-missing` hint, which reads the chosen mode
  ("Checked automatically after Add to collection; off for Replace",
  `templates/data_management.html:172`).
- `doFetch()` currently reads the mode at
  `static/js/data_management.js:459`. Resolve the dialog **before** that read.
- Guests and the sample-corpus path are unaffected.

---

## Feature 2 — Re-prepare dialog (Simple only)

### Correcting the premise

`POST /api/create-embeddings` still takes `{model, only_missing}` only — the
research question is **not** sent to prepare. Students still need to verify the
question before re-prepare, because the same text drives **Narrow it down** next
and should not be assumed identical to the last fetch.

### Implemented dialog (one popup)

Manual **Re-prepare Papers** (Simple only; not the post-fetch auto-chain) opens
a single site dialog that always includes a required research-question field
(`openSiteChoice` + `withInput: true`):

> **Re-prepare papers for search**
> Check that this research question is still what you want…
>
> **Your research question** `[editable, pre-filled]`
>
> When papers are already prepared: [Only new papers] [Redo all 231] [Cancel]
> When nothing is prepared yet: [Continue] [Cancel]

- Verified text is written into `#fetch-query`, `#simple-screen-query`, and
  fetch prefs (`applyVerifiedResearchQuestion`).
- "Only new papers" / Continue with nothing prepared → `only_missing: true`
- "Redo all N" → `only_missing: false`
- Cancel → no prepare request
- Auto-chain after fetch does **not** open this dialog

### Screening after re-prepare

After a successful **manual** re-prepare, re-include any `low_relevance`
exclusions via existing `POST /api/screening` so the screening card returns to
*pending* from **corpus state** (not a JS flag). The Narrow it down card also
shows its own confirm box when pending.

---

## Feature 3 — Dense per-source report

Real output today is 15 rows plus 3 note lines (see
`static/js/data_management.js` ~1470–1510). It renders **after** a fetch into
`#fetch-source-report`.

### Collapsed by default

```
✓ arXiv 100 · CrossRef 100 · Europe PMC 98 · Zenodo 96 · OpenAIRE 21
  and 5 more sources · 4 returned nothing        [Show all sources]
```

Rules:

- Show the **top 5 successful sources by count**, descending.
- Collapse the remainder into a single summary line: how many more succeeded,
  and how many returned nothing or errored.
- **Failures are summarised, not hidden and not alarming.** A source returning
  nothing is normal. Keep them muted, exactly as the Phase 7 narrative does.
- The classroom notes (preprints / DBLP / arXiv caveats) move **inside** the
  expander. They matter, but not on every fetch.
- Expanded view shows the current full list unchanged.
- Use a `<details>`/`<summary>` element rather than custom JS toggling — it is
  keyboard- and screen-reader-accessible for free, and matches the existing
  `help-details` / `advanced-details` pattern on the page.
- **Advanced mode keeps the full list expanded by default.**

### Do not double up with the live narrative

Phase 7 added `#fetch-live-sources`, which renders per-source rows **during**
the fetch. This report renders **after**. Both must not be on screen at once
showing the same data — when the final report appears, the live rows should be
cleared or replaced. Check this explicitly; it is the most likely visual bug in
this feature.

### Preserve escaping

The current renderer runs every line through `escapeHtml`. Source names and
error strings come from external APIs. Keep escaping on every path you touch —
do not build HTML from raw API strings.

---

## Work, in shippable order

1. **Modal shell**: focus trap, focus restore, body scroll lock, mobile
   keyboard check. No feature changes.
2. **Dense source report** (`<details>`, top-5 + summary, notes inside,
   live-rows conflict resolved).
3. **Fetch mode dialog** (empty → no dialog; non-empty → ask).
4. **Re-prepare dialog** (research question + only-new vs all; always verify
   prompt; Continue-only when nothing is prepared).

Order matters: 1 is a prerequisite for 3 and 4, and 2 is independent, so it
ships first and de-risks the release.

## Acceptance criteria

- [ ] Advanced mode is unchanged: radios visible, Advanced options present,
      full source report.
- [ ] Modal shell traps focus, restores focus to the opener, and locks body
      scroll (restoring position on close).
- [ ] A dialog with a text input is usable at 380px with a soft keyboard open.
- [ ] Simple + **empty** collection: Fetch starts immediately, no dialog,
      `clear_first: true`.
- [ ] Simple + **non-empty**: dialog shows the real paper count; each button
      sends the correct `clear_first`; Cancel sends no request.
- [ ] The `only-missing` hint still reflects the chosen mode.
- [ ] Simple re-prepare always shows **Your research question** in the same
      popup (required, pre-filled); Cancel sends no prepare request.
- [ ] Simple re-prepare with nothing prepared: Continue / Cancel only (no
      only-new vs all choice); Continue sets `only_missing: true`.
- [ ] Simple re-prepare with papers prepared: Only new / Redo all / Cancel and
      the matching `only_missing`.
- [ ] After manual re-prepare, screening returns to pending **derived from
      corpus state** (low_relevance cleared via include), and survives a reload.
- [ ] Source report collapsed by default in Simple: ≤5 success rows + one
      summary line; notes inside the expander; full list on expand.
- [ ] Live per-source rows and the final report are never both showing the same
      data.
- [ ] All rendered source/error text is still escaped.
- [ ] `ruff check .` clean, full pytest green, pyright ≤ 61/6.

## Tests to add

- Modal shell: Tab from the last focusable element returns into the dialog;
  close restores focus to the opener; body scroll is locked while open and
  restored after.
- Fetch dialog is **skipped** when `total_articles == 0`, and `clear_first` is
  `true` in that path.
- Fetch dialog appears when `total_articles > 0`, and each choice maps to the
  correct `clear_first`; Cancel issues no fetch request.
- Re-prepare dialog includes `withInput` research-question field in the same
  popup; nothing-prepared path uses Continue without only-new/all.
- Re-prepare choices map to the correct `only_missing`.
- Source report renders ≤5 success rows collapsed and the full set expanded;
  notes appear only in the expanded view.
- Advanced mode still renders radios, Advanced options, and the full report.
- Existing guards in `tests/test_simple_mode.py` and `tests/test_guest_mode.py`
  still pass **unchanged**.

## Things that will bite

- **A dialog before every fetch is friction.** The empty-collection skip is the
  whole point of feature 1 — do not "simplify" it into always asking.
- **Hidden radios still submit.** They stay in the DOM for Advanced; the dialog
  must set them so downstream readers (`saveFetchPrefs`, the only-missing hint)
  keep working.
- **The live rows / final report overlap** is the likeliest visual regression.
- **`only_missing` is not the research question.** If a dialog seems to need a
  question field, stop — that belongs on the screening card.
- **Escaping**: source names and API error strings are untrusted text.
