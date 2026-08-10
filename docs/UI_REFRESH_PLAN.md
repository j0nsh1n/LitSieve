# Plan — UI/UX refresh: design system + editorial direction (Phase 7)

Build doc, written to be executed by someone who has not seen the design
conversation.

## Goal

Two things at once, in this order:

1. **A real design system.** Add the scale tokens the CSS never had, and
   collapse the hand-tuned values onto them.
2. **An editorial visual direction.** Lean into the "library / open textbook"
   identity the palette already implies, instead of softening it toward
   generic SaaS.

Plus the UX half that no visual change can fix on its own: **design the
waiting.** Fetch and prepare take minutes. That is the dominant experience of
this app and currently the least designed part of it.

## Why (measured, not felt)

`static/css/style.css` is 4564 lines with 41 section banners. The colour and
motion layer is good — derived tokens via `color-mix`, dark mode, focus rings,
reduced-motion support. What is missing is underneath it:

| | Now | Target |
|---|---|---|
| Distinct `font-size` values | **38** | 8 |
| Distinct `padding` values | **29** | 6 |
| Distinct `border-radius` values | 6 | 3 |
| Spacing / type / radius tokens | **0** | full scale |
| Skeleton / spinner rules | **3** | proper loading states |
| `prefers-reduced-motion` blocks | 1 | covers all motion |

The type sizes cluster at 0.78 / 0.80 / 0.82 / 0.85 / 0.86 / 0.88 / 0.90rem —
seven values inside 0.12rem. Nobody can see the difference, but nothing lines
up either, and that is what reads as "almost professional."

## Non-goals

- **No behaviour changes.** No flow, endpoint, or copy changes. If a change
  requires touching JS logic (not classnames), stop and ask.
- **No new dependencies.** No npm, no build step, no CSS framework, no icon
  package, no webfont downloads. Vanilla CSS, `script-src 'self'`.
- **Advanced mode keeps every control.** This is presentation only; nothing
  becomes unreachable in either mode.
- Not a rewrite of `style.css`. Migrate in place, section by section.

---

## Constraints (read before writing code)

1. **No build step.** Hand-authored CSS, served directly. Custom properties are
   fine (already used heavily); CSS nesting and `@layer` are not — keep it to
   what the current file already relies on.
2. **`theme-init.js` stays a blocking, non-module `<script src>` in `<head>`.**
   CSP is `script-src 'self'`; deferring it causes a flash of the wrong
   theme/mode.
3. **Public templates** (landing, login, register, feature_guide,
   reset_password, verify_email) do **not** extend `base.html` and must not load
   `common.js`. Style changes must be verified on those pages separately.
4. **Bump `?v=` on every asset you change, in every template that references
   it.** `tests/test_static_js.py` enforces cross-template consistency and will
   fail otherwise.
5. **Both themes, every change.** Light and dark are both first-class. Verify
   contrast in both; do not hardcode a colour that only works in one.
6. Never edit `agents.md`. `spec.md` only with explicit human approval.
7. **Never `git push` or open a PR without being asked.** Commit locally.
8. Dev with `./run_dev.sh 7861` (isolated data). Never point a dev server at the
   live `users.db` — it has real accounts.
9. Before every commit: `ruff check .` clean, and
   `SECRET_KEY=x DEBUG=true ./venv/bin/python -m pytest -q` green. Pyright
   baseline 61 errors / 6 warnings — do not add to it.
10. Deploy is `systemctl --user restart litsieve-uvicorn.service`.

---

## Part 1 — The token layer

Add to `:root` alongside the existing colour/motion tokens. **Do not remove or
rename any existing token** — `--accent`, `--text-body`, `--elev-1`,
`--dur-fast`, `--ease-soft` and friends are all in use and must keep working.

### Type scale

```css
--fs-xs:   0.75rem;   /* fine print, badges, meta */
--fs-sm:   0.875rem;  /* secondary UI, labels, help text */
--fs-base: 1rem;      /* body */
--fs-md:   1.125rem;  /* lead paragraphs, card titles */
--fs-lg:   1.25rem;   /* section headings (h3) */
--fs-xl:   1.5rem;    /* card headings (h2) */
--fs-2xl:  1.875rem;  /* page headings (h1) */
--fs-3xl:  2.5rem;    /* landing hero only */
```

Migration rule: round each existing value to the **nearest** token. The seven
values between 0.78 and 0.90 collapse to `--fs-sm` or `--fs-base`; judge by role
(is it secondary chrome, or body copy?), not by arithmetic alone.

### Line height and measure

```css
--lh-tight:   1.25;  /* headings */
--lh-snug:    1.4;
--lh-normal:  1.6;   /* UI body */
--lh-relaxed: 1.75;  /* abstracts, long reading */
--measure:    68ch;  /* max line length for reading text */
```

`--measure` applies to abstracts and guide prose. It must **not** be applied to
result cards on Search (that was tried before and read as "half the column" on
wide screens — see the note in the retired reading-mode section).

### Spacing (4px base)

```css
--space-1: 0.25rem;  --space-2: 0.5rem;   --space-3: 0.75rem;
--space-4: 1rem;     --space-5: 1.5rem;   --space-6: 2rem;
--space-7: 3rem;     --space-8: 4rem;
```

### Radii

```css
--radius-sm:   4px;    /* inputs, chips, small controls */
--radius-md:   8px;    /* cards, buttons, panels */
--radius-full: 999px;  /* pills, avatars */
```

Existing 2px / 6px / 12px values map onto these three.

### Existing utilities

`.u-mt-sm` / `.u-mt-md` / `.u-mt-lg` already exist and are used in templates.
Re-point them at the spacing scale rather than deleting them — templates depend
on the class names.

---

## Part 2 — Editorial direction

The palette is already "linen desk / open textbook" (`--bg: #f5f1e9`,
`--accent: #2a5f6e` library teal, Georgia loaded as `--font-serif`). Commit to
it rather than half-using it.

**Typography**
- **Serif (`--font-serif`) for headings and abstracts.** Sans (`--font-sans`)
  for UI chrome: labels, buttons, nav, form controls, badges.
- Headings get `--lh-tight` and slightly negative tracking at `--fs-2xl` and up.
- Abstracts keep serif at `--fs-base` / `--lh-relaxed` (already the case — do
  not regress it).

**Surfaces**
- Prefer **hairline rules** (`--rule`) over shadows for card separation. Keep
  `--elev-1` for genuinely floating things only: toasts, the sticky panel, the
  mobile bottom bar, dropdowns.
- Cards read as sections of a page, not as floating tiles.

**Colour discipline**
- Accent is for **actions, focus, and the active nav step**. Not for decoration,
  not for card backgrounds, not for headings.
- Status colours (`--ok`, `--warn`, `--err`) stay reserved for status.

**Rhythm**
- One vertical rhythm unit between related blocks (`--space-5`), a larger one
  between sections (`--space-7`). No one-off margins.

---

## Part 3 — Design the waiting (the UX half)

This is the highest-impact item in the plan and is independent of visual taste.

### Fetch: a narrative, not a bar

A fetch queries up to 17 sources in parallel and takes minutes. The progress
data already exists — `updateProgress` carries per-source counts and error
kinds, and the fetch response includes `by_source`, `ok_sources`, `errors`, and
`error_kinds`.

Show it live:

```
Searching 8 sources…
  PubMed          142 papers
  Europe PMC       89 papers
  arXiv         searching…
  Semantic Scholar  rate-limited, retrying
```

Rules:
- Never invent progress. Only render counts the API actually reported.
- A per-source failure is normal and must read as normal (muted, not red
  alarm) — the overall job still succeeds.
- The existing cancel affordance stays exactly where it is.

### Skeletons instead of empty space

Search results, cluster lists, and the Clean up tables should render **skeleton
rows** matched to the real card geometry while loading — not a spinner, not a
blank region that then jumps. Reuse the existing `shimmer` keyframe.

### Optimistic feedback

Star, "Not relevant", and note-save should reflect immediately and roll back
visibly on failure. These are single-row writes; a full-list refresh for each is
what makes the UI feel heavy.

### Never move content under the cursor

Reserve space for anything that appears asynchronously (status lines, progress,
the screening card). Layout shift is the single biggest contributor to "feels
janky."

---

## Part 4 — Mobile first

Real traffic is overwhelmingly phones (the access log is almost entirely mobile
IPv6 ranges). Existing breakpoints: `900px`, `640px`, `380px`, plus
`(hover: none)`.

- **Design and verify 380px first**, then let desktop be the enhancement.
- Tap targets ≥ 44px on anything interactive; `(hover: none)` already exists for
  touch-specific tweaks.
- Editorial layouts want whitespace, and whitespace is expensive on a phone —
  the mobile treatment is a *different* layout, not the desktop one squeezed.
- The sticky export/report panel already collapses to a bottom bar under 900px.
  Keep that, and keep the results list's bottom padding equal to the bar height
  so it never covers the last card.

---

## Part 5 — Motion vocabulary

13 keyframes and 56 transitions exist, applied ad hoc, with a single
`prefers-reduced-motion` block. Define three and use only these:

```css
/* enter  */ opacity + 4px rise, --dur-fast, --ease-out
/* exit   */ opacity only,       120ms,      --ease-soft
/* emph.  */ transform/colour,   --dur-med,  --ease-soft
```

- Nothing animates longer than `--dur-med` except deliberate progress
  indicators.
- **One `prefers-reduced-motion: reduce` block must neutralise all of it**,
  including the skeleton shimmer and any new animation. Today's single block
  does not cover the new work.

---

## Part 6 — Accessibility (non-negotiable)

- Contrast ≥ 4.5:1 for body text, ≥ 3:1 for large text — **in both themes**.
  `--text-soft` on `--bg` is currently the tightest pair; re-verify after any
  colour change.
- Keep the existing `--focus-ring`. Every interactive element must show it, and
  it must be visible against both `--bg` and `--surface`.
- Do not remove focus outlines to make something look cleaner.
- Headings stay in order (no `h2` → `h4` jumps) — screen readers use them to
  navigate, and the guide pages depend on it.
- Colour must never be the only signal: status needs an icon or text too.

---

## Work, in shippable order

Each step is its own commit, tests green, and independently useful.

1. **Token layer.** Add scales to `:root`. Re-point `.u-mt-*` utilities. No
   visual change yet — this commit should be a no-op on screen.
2. **Collapse type + spacing + radii** onto the tokens, section by section
   through the 41 banners. Expect small visual shifts; that is the point.
3. **Editorial pass**: serif headings, hairline card separation, colour
   discipline, vertical rhythm.
4. **Waiting states**: fetch narrative, skeletons, optimistic feedback.
5. **Mobile pass** at 380 / 640 / 900.
6. **Motion + reduced-motion sweep.**

Steps 1–2 are mechanical and low risk. Step 3 is where judgement is needed —
if something looks wrong after collapsing to the scale, the fix is usually the
*layout*, not adding a ninth font size back.

## Acceptance criteria

- [ ] `:root` defines type, line-height, spacing, and radius scales.
- [ ] ≤ 8 distinct `font-size` values, ≤ 6 `padding`, ≤ 3 `border-radius` in
      `style.css` (excluding `0`).
- [ ] No behaviour change: same flows, same endpoints, same copy.
- [ ] Both themes verified; contrast holds in both.
- [ ] Every interactive element shows the focus ring.
- [ ] One `prefers-reduced-motion` block neutralises **all** motion, new
      included.
- [ ] 380px: no horizontal scroll, no overlapped controls, tap targets ≥ 44px.
- [ ] Search, Clean up, and cluster lists show skeletons, not blank regions.
- [ ] Fetch shows live per-source progress using only data the API returned.
- [ ] Public templates (which do not extend `base.html`) verified separately.
- [ ] `ruff check .` clean, full pytest green, pyright ≤ 61/6.

## Tests to add

- Token presence: `:root` defines each documented scale variable.
- Scale discipline: parse `style.css` and assert the distinct-value counts above
  (this is the guard that stops the 38 sizes creeping back).
- Every `?v=` for a changed asset is consistent across all templates (extend the
  existing check in `tests/test_static_js.py`).
- `prefers-reduced-motion` block count ≥ 1 **and** it covers the shimmer
  keyframe.
- Public templates still render and still do not reference `common.js`.
- Existing Simple/Advanced guards in `tests/test_simple_mode.py` still pass
  unchanged — that is the proof this was presentation-only.

## Things that will bite

- **Collapsing sizes will reveal bad layout** that the odd values were papering
  over. Fix the layout; do not re-add the size.
- **Dark mode drifts silently.** It is derived via `color-mix`, so a change that
  looks right in light can fail contrast in dark. Check both, every time.
- **The public pages are easy to forget** — they do not extend `base.html`, so
  nothing you do there propagates automatically.
- **Skeletons must match real card geometry.** A skeleton of the wrong height
  causes exactly the layout shift it was meant to prevent.
- **`--measure` on Search result cards was already tried and rejected.** Do not
  reintroduce it there.
