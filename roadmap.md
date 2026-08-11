# roadmap.md — LitSieve

Note: "Complete when" conditions are verified locally (tests pass, feature
works) and via PR review. One phase may span several small PRs.

## Phase 1 — Governance files adoption
- Tasks:
  - Commit tracked `agents.md`, `spec.md`, `roadmap.md`, `context.md`, `CHANGELOG.md`
  - Stop gitignoring `context.md`; structure it as state-only (no policy rules)
  - Align agent workflow to agents.md (no push/PR without explicit ask)
- Complete when: all five files tracked on the working branch; CI green;
  agents can resume from context.md handoff without reading gitignored secrets
- Status: [x] 2026-07-30 (local commits may still need push when human asks)

## Phase 2 — Optional recovery email
- Tasks:
  - Username separate from email; optional verified recovery address
  - SMTP-gated; Account UI and password-reset paths
  - Tests in `tests/test_email_recovery.py`
  - SMTP smoke tool (`tools/send_test_email.py`); MailerSend verified locally
- Complete when: feature on main, human-confirmed send/recovery works, secrets
  only in gitignored `.env` / secret dumps, `.env.example` documents SMTP
- Status: [x] 2026-07-30 (PR #38 merged; SMTP confirmed working by human)

## Phase 3 — Stabilize v4.3.x host
- Tasks:
  - Keep multi-library + student starting-point positioning
  - Storage quota, AI key AES-GCM, optional SQLCipher as deploy options
  - Deploy checklist: SECRET_KEY, optional SMTP, quota, tokens; `/health` 200
  - No teacher LMS / live-share expansion unless human reopens scope
- Complete when: deploy checklist documented **and** production-ish smoke
  passes: `DEBUG=false` + real `SECRET_KEY`, `GET /health` → 200
  (`status: healthy`). Public cloud is operator-owned — run the same smoke
  against that URL when you deploy (see `docs/DEPLOY.md`).
- Status: [x] 2026-08-03 — `docs/DEPLOY.md` + README link; production smoke
  verified. Live publicly at **https://www.litpilot.org**, self-hosted on the
  operator's desktop behind a Cloudflare Tunnel (TLS at Cloudflare; Uvicorn
  serves plain HTTP on loopback). No PaaS involved.

## Phase 4 — Operate a live instance
Shipping changed the risk profile: there are real accounts with real data on a
home desktop, and the link has been shared publicly.
- Tasks:
  - Cap total accounts (registration is open; per-account quota bounds disk per
    user but nothing bounds the number of users)
  - Back up `users.db` + `user_data/` — `tools/backup.py` +
    `litsieve-backup.timer` (daily; integrity-checked archives)
  - Watch `logs/litsieve.log` after incidents (rotating; ~30 MB ceiling)
  - Health watchdog (`tools/watchdog.py` + timer) for app + tunnel
  - Keep the HF model cache warm so no student pays for a first download
- Complete when: an account cap (or invite gate) is enforced, a restore has been
  tested at least once from a backup, and the operator can answer "what happened
  at 14:05?" from the log file
- Status: [ ] in progress — logging, backups, and watchdog landed 2026-08-04–06;
  **account cap still open**; restore drill still open

## Phase 5 — Simple / Advanced mode
Full build doc: **[docs/SIMPLE_MODE_PLAN.md](docs/SIMPLE_MODE_PLAN.md)**.
A per-user toggle that hides power-user surfaces and automates the steps a
student should not have to think about. No capability is removed from Advanced.
- Tasks:
  - Mode toggle (`data-mode="simple"`, localStorage, applied in
    `theme-init.js` pre-paint) + a CSS-only hiding layer; retire reading mode
    but keep its serif abstract styling as the default
  - Auto-chain fetch → prepare in Simple, via `start_user_job` (never inline)
  - Rename Duplicates → **Clean up**; screening moves there, since the
    screening report already lives on that page
  - **Quick screen**: rank against the student's research question, propose the
    least-related set, apply only on confirm. New `low_relevance` code in
    `EXCLUSION_REASONS` + `SYSTEM_REASONS` so the PRISMA report distinguishes
    machine-suggested from student-judged exclusions
  - **By topic group**: existing cluster triage, auto-run on density, triggered
    lazily as a background job — never on fetch completion
  - Per-paper "Not relevant" on Search result cards as the catch-all
- Complete when: a student can go topics → fetch → clean up → search → export
  RIS in Simple mode without seeing "embedding", "cluster", "HDBSCAN", or a
  model name; the screening report is non-empty and distinguishes
  `low_relevance`; nothing heavy runs inline; `/clusters` still loads by URL
- Status: [x] 2026-08-05 — shipped in **v4.5.0** (PR #52 lineage). Quick screen
  + Clean up rename + auto-prepare + Simple/Advanced toggle. Phase 6 further
  collapses Simple to two pages (below).
- Notes: `spec.md` triage/workflow text updated 2026-08-06 (human-approved) for
  Clean up, Quick screen, Simple screening card, and guest. Cluster label
  quality remains a concern for topic-group triage; Phase 6 deliberately avoids
  auto-clustering.

## Phase 6 — Simple mode on two pages
Full build doc: **[docs/SIMPLE_TWO_PAGE_PLAN.md](docs/SIMPLE_TWO_PAGE_PLAN.md)**.
Simple collapses to `Get papers` → `Search`. **Advanced is unchanged.**
- Tasks:
  - Duplicates resolved **silently** after auto-prepare, reported in one line
    (`/api/resolve-duplicates`, existing preferred-source rule)
  - Inline **screening card** on Data Management — Low / Medium / High mapping
    to `fraction` 0.10 / 0.25 / 0.50, each showing the real paper count before
    it is applied; preview and apply stay separate; undo and skip both
    first-class. Inline, not a surprise modal after a minutes-long fetch
  - **Go to Search** action once screening is applied or skipped
  - Search gains a sticky **export / screening report** panel, collapsing to a
    bottom bar under ~900px
  - Clean up and Clusters leave the Simple nav; both routes keep working and
    stay in Advanced
  - **No auto-clustering anywhere** — the screening card ranks against the
    research question, which needs embeddings, not clusters
- Complete when: a Simple student goes topics → fetch → screen → search →
  export across two pages without seeing "embedding", "cluster", "threshold",
  or a model name; Advanced behaviour is unchanged; nothing is excluded without
  an explicit apply; and the flow works at 380px with no horizontal scroll
- Status: [x] 2026-08-06 — implemented on `main` / `feat/phase6-guest-demo`
  (guest demo + polish on the same line; live fix for fetch form 405)
- Notes: small screens are a first-class requirement, not a retrofit — real
  traffic is overwhelmingly mobile. Existing breakpoints: 900 / 640 / 380px.
  Guest demo (`/guest`, sample-only, 30‑min purge) ships alongside as a low-friction
  try-without-register path; not a separate roadmap phase.

## Phase 7 — UI/UX refresh (design system + editorial)
Full build doc: **[docs/UI_REFRESH_PLAN.md](docs/UI_REFRESH_PLAN.md)**.
Presentation only — no flow, endpoint, or copy changes.
- Tasks:
  - **Token layer**: type / line-height / spacing / radius scales in `:root`,
    alongside the existing colour + motion tokens (which stay). Re-point the
    `.u-mt-*` utilities rather than deleting them
  - **Collapse the hand-tuned values**: 38 distinct font sizes → 8, 29 paddings
    → 6, 6 radii → 3, section by section through the 41 CSS banners
  - **Editorial pass**: serif headings + abstracts, sans for UI chrome, hairline
    rules instead of shadows for cards, accent reserved for actions/focus
  - **Design the waiting** (the UX half): live per-source fetch narrative from
    data the API already returns, skeletons matched to real card geometry,
    optimistic star / not-relevant / note-save, and no async layout shift
  - **Mobile first** at 380 / 640 / 900 — a different layout, not a squeeze
  - **Motion vocabulary**: one enter, one exit, one emphasis, with a single
    `prefers-reduced-motion` block that neutralises all of it
- Complete when: ≤8 font sizes / ≤6 paddings / ≤3 radii remain; both themes hold
  contrast; every interactive element shows the focus ring; 380px has no
  horizontal scroll or overlapped controls; loading regions show skeletons
  rather than blank space; and the Simple/Advanced guards in
  `tests/test_simple_mode.py` still pass unchanged (proving presentation-only)
- Status: [x] 2026-08-10 — implemented on `feat/phase6-guest-demo` (local
  commits; presentation only). Token scales, value collapse, editorial pass,
  fetch narrative + skeletons + optimistic writes, mobile 380 layout, motion
  vocabulary + reduced-motion covering shimmer.
- Notes: the colour/motion layer was preserved (existing tokens not renamed).
  Dark mode is derived via `color-mix` — re-check contrast after future colour
  edits. Public templates do not extend `base.html`. `--measure` stays off
  Search result cards.

## Phase 8 — UI revamp (information architecture)
Concept pitch (four directions, mockups built from the real markup):
**<https://claude.ai/code/artifact/7b79cf7f-fc3f-4c5e-8758-77988e54db6d>**

Premise: Phase 7 already won the token layer — all 177 `font-size` declarations
read from `--fs-*`, no raw `rem` values, and templates carry no inline styles.
So another repaint would spend effort on the one layer that is not broken. What
is left is **information architecture and density**.

- Findings this phase is judged against (measured, not taste):
  1. **Smallness is concentrated in the explanatory layer.** 123 rules use
     `--fs-sm`/`--fs-xs` against 21 at `--fs-base`. Nuance worth keeping
     straight: `.article-abstract` and `body` are *already* `--fs-base` with
     `--lh-relaxed`, so abstracts are fine. The offenders are `.info-text`
     (14px, `--lh-snug`, 77 uses) and `.help-text` (12px, 36 uses) — which is
     exactly where LitSieve puts most of its words.
  2. **The nav carries ten controls** in one strip plus a second row of four
     workflow steps; identity and workflow-position share one bar (`base.html`).
  3. **Search is five stacked `.card` sections** — query and results are never
     on screen together.
  4. **Results hide themselves** — `buildResultCard` renders `<details>` with
     only the first three open, and shows Low/Medium/High instead of the 0–1
     similarity score that ordered the list.
  5. **Help outweighs the controls** — 74 inline `info-text`/`help-details`
     blocks across five templates (22 on Data Management), plus 17 flat source
     checkboxes.
- Chosen direction: **A ("Reading Room") now, B ("Workbench") next**, and take
  C's type sizes immediately. A keeps the linen/teal identity and `base.html`
  untouched, so it can ship behind the same presentation-only guard Phase 7
  used. B is the right end state if LitSieve should feel like an instrument, but
  it rewrites the shell and `search.js` — its own phase, not a bolt-on.
- Tasks (A):
  - **Type — the C borrowings.** These are the four things taken from direction
    C, and the cheapest real win on the list:
    - `.info-text` → `--fs-base` / `--lh-normal` (from 14px / `--lh-snug`).
      77 uses; this is body copy and should read as such
    - `.help-text` → `--fs-sm` (from `--fs-xs`). 36 uses
    - `--fs-xs` (12px) reserved for badges, meta, and true fine print —
      **no reading copy below 14px anywhere**
    - the Search query prompt set large (`--fs-xl`), so the page opens on the
      question rather than on chrome
    - Watch the `@media` override at ~3747 and the `.empty-state-card` /
      `.help-details` / `.advanced-details` specificity chains, so mobile
      resets do not silently undo the sizes
    - *Not* taken from C: the single-column front-door IA and Simple-as-the-
      product. That is a product decision about whether Advanced stays a mode,
      and it should be settled on its own terms, not as a side effect of a
      type change
  - **Search layout**: sticky query rail beside a results column, replacing the
    five-card stack. Query and results visible together
  - **Results**: scannable rows showing the real 0–1 score as a meter, instead
    of `<details>` collapsibles labelled Low/Medium/High
  - **Help**: fold the inline blocks into one summonable panel per page
  - **Dark theme — decided: re-ground A's dark on B's graphite.** Today's dark
    reads blue-slate; B's ground is a neutral-warm graphite, and that is the
    part of B worth having early. Change the *grounds only* and keep A's warm
    paper ink and teal accent, because brand continuity is A's whole point —
    B's ochre signal does not come along:
    - `--bg` `#12151a` → `#16181a`
    - `--surface` `#1a1e26` → `#1e2124`
    - `--rule` `#2e343f` → `#2c2f33` (the most obviously blue of the three)
    - `--text`, `--text-soft`, `--accent` (`#7eb8c4` teal) unchanged
    - Both dark blocks must change: the `prefers-color-scheme` media query
      (~line 82) *and* the explicit `[data-theme="dark"]` toggle (~line 104).
      `--text-body`, `--accent-soft`, `--nav-blur`, `--wash-*`, and
      `--focus-ring` are `color-mix`-derived from these, so re-check contrast
      on both themes after the swap rather than assuming it held
  - Note A and B are **not** light/dark variants of one design — they differ in
    layout, and a theme toggle must never rearrange the page. Each direction
    needs both of its own themes; borrowing B's ground is a palette decision,
    not a merge of the two directions
- Complete when: query and results are co-visible on Search; every result row
  shows its numeric score; no reading surface below 14px; both themes hold
  contrast; 380px has no horizontal scroll or overlapped controls; and the
  Simple/Advanced guards in `tests/test_simple_mode.py` still pass unchanged
  (proving presentation-only)
- Status: [ ] planning — concepts pitched and direction chosen 2026-08-10. Only
  the CSP fix below has landed; no layout or type work started.
- Landed 2026-08-10 (not part of A, found while setting up a local preview):
  **CSP inline-style removal.** `style-src 'self'` blocks `style-src-attr`, so
  the five literal `style="…"` attributes still injected by `account.js`,
  `join.js`, and `data_management.js` were being dropped in production — lost
  margins, and a "Revoked" badge that never rendered red (it also referenced
  `--danger`, which is not a defined token; the theme uses `--err`). Replaced
  with `.is-revoked`, `.join-preview-lead`, `.u-m-0`, and the existing
  `.u-mt-sm`; asset cache-bust bumped to `v=20260810a`. Verified against a
  running server: Data Management, Search, and Account now load with an empty
  console. The `.is-revoked` path is not exercised by the guest demo (guests
  cannot create share codes), so that one line is by inspection only.
- Notes: the current warm-linen + Georgia + teal palette is close to this
  year's generic AI-generated house style. A preserves brand continuity but not
  distinctiveness; D ("Card Catalog" — index cards, typed slips, stamped match
  grades) was the only direction with a real point of view, and is parked rather
  than rejected.
- Notes on Windows (explored 2026-08-10, then reverted — host stays Linux):
  the full stack does install and run on **Python 3.14.6** (torch 2.13.0+cpu,
  faiss-cpu 1.15.0, sentence-transformers 5.7.0, umap-learn 0.5.12 / numba
  0.66, scikit-learn 1.9.0) — no wheel gaps, and the app imports even without
  torch/faiss/umap because those sit behind try/except and function-level
  imports. Two things a future Windows attempt should expect: **17 test
  failures that are portability, not bugs** (14 × `UnicodeDecodeError` from
  `read_text()` with no `encoding="utf-8"` under cp1252; one POSIX `0600`
  assertion in `test_backup.py`; and `test_hashing_does_not_block_the_event_loop`,
  whose `ticks > 10` bar is unreachable because `asyncio.sleep(0.001)` resolves
  at ~15ms on Windows vs ~1ms on Linux — an *idle* loop scores 10). Also
  `sqlcipher3-binary` has no Windows wheel at all, which skips all 5
  at-rest-encryption tests. Run the suite as CI does (`SECRET_KEY` + `DEBUG`
  only): setting `USER_DATA_DIR` breaks `test_delete_account_flow`, which
  asserts a hardcoded relative `user_data`, and setting `CI=true` makes
  `test_db_encryption.py` hard-import sqlcipher3 by design.

## Backlog (unscheduled)
- Make `pyright app` blocking in CI after clearing the current error backlog
- Dependency lockfile (pip-tools / uv) if reproducibility becomes a priority
- Optional later ruff ratchet: E501 / UP / E402
- Scale opts (FAISS defaults, TF-IDF corpus cache) only with new ≥10× evidence
- Not building: clinical evidence grades, paywalled DBs, live teacher shares / LMS
