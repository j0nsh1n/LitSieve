# Plan — Workshop restyle and expand-in-place results (Phase 14)

Chosen on 2026-09-17 from five switchable mock-ups built on a capture of the
real Search page (`design_mockups/ui3`, local only, never committed). Jonathan
picked mock-up E: the Workshop look with rows that open in place, plus a
reworked collect page. This file records the decisions the code follows.

## Goal

One identity that carries the sieve idea: warm sand paper, a clay accent,
solid surfaces on a tool edge, physical motion. Fewer things on screen at
once: a result row shows only what you need to pick it, and the collect page
asks one question at a time.

## Non-goals

- Advanced mode does not change behaviour. It gets the palette and edges,
  keeps numbered steps, full cards, and every control. Removing it is
  Phase 13.
- No new endpoints. No npm. No SVG filters for texture.
- No layout split (list beside a reading pane). Jonathan rejected that
  structure; the open row expands where it sits.

## Decisions

- Palette, light: bg `#f3ede3`, surface `#fbf7f0`, text `#2a2118`, soft
  `#6a5c4d`, rule `#dccfbc`, accent `#a8472a`, edge `#cbbba4`. Dark: bg
  `#1b1712`, surface `#262019`, text `#f2e9dc`, soft `#b8a894`, rule
  `#3d3328`, accent `#e39a73`, edge `#14100c`. Every ink measures above 5:1
  on both grounds; `test_theme_inks_meet_wcag_aa_on_page_grounds` computes
  it rather than pinning it.
- Frost is gone. `--frost` became `--surface`, `--frost-edge` became
  `--rule`, `--glass-shine` became `--sheen`, `--nav-blur` became
  `--nav-bg`; every `backdrop-filter` rule was deleted and a test forbids
  new ones. The modal scrim is `--scrim`.
- The tool edge is `border-bottom: 3px solid var(--edge)` on cards, buttons,
  chips, the query tile, and the wait track. Press states sink 2px onto it.
- Radii are 8/14/18. Grain is two gradient dot lattices on `body::before`.
- Motion tokens `--ease-spring` and `--ease-settle`. Keyframes: `rowSettle`,
  `rowOpen`, `chipTag`, `starPop`, `lineSwap`, `collectArrive`,
  `barStripes`. The universal reduced-motion rule neutralises all of them.
- Simple result rows: compact by default, one open at a time, the top result
  open after a search. The Open button is real (`aria-expanded`,
  `aria-controls`) so Enter and Space work; a click on the row body opens it
  too. The action rail is a row under the open card.
- Simple collect: header, scope note as one quiet line, "Which areas does
  your topic belong to?" with topic chips, a "Next: name your topic" button
  once an area is picked, then "What topic do you want papers about?" with
  the topic box focused. Max results and fetch-mode radios stay hidden in
  Simple. A library that already has papers shows the box at once.
- Topic icons are `icon_svg` on each `TOPIC_META` entry, inner markup of a
  24x24 stroke icon; the emoji stays as the client fallback.

## Work, as shipped (one commit each on `feat/ui3-workshop`)

1. Tokens and surfaces, no blur anywhere.
2. Simple result rows open in place.
3. Collect as one guided column with line-icon chips.
4. Star pop and wait-line swap.
5. Next button after choosing areas (Jonathan's note during review).
6. Bookkeeping: changelog, 5.5.0, cache-bust, context.
7. Pre-fetch dialog: per-database count as preset chips or a written number,
   with the fresh-or-add choice folded in when papers exist (Jonathan's note
   after 5.5.0 approval). `openSiteForm` gained a `choice` field type.

## Verification

Each unit: the related test files, the full suite, and a headless Chromium
run against a throwaway server on port 8801 with a temporary users database
(`design_mockups/ui3/capture/*.mjs`), checking behaviour by reading the DOM,
not only screenshots. Mutation checks on every new test.

## spec.md

- Line 79 health example moved to 5.5.0 with Jonathan's approval on
  2026-09-18.
