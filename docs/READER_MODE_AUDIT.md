# Audit — Reader Mode (5.3)

**Scope:** `app/services/reader_verify.py`, `app/services/reader_facts.py`, `app/services/reader_mode.py`, `app/storage/database.py`, `tests/fixtures/reader/`, `tests/test_reader_corpus.py`.
**Branch/commit audited:** `feat/5.3-reader-mode` at `a85ca3b` (PR #62, merged as `c9e29da` on 2026-08-30).
**Method:** full read of the merged tree; the verifier was run against all 12 corpus fixtures and four crafted adversarial cases. Scratch harnesses were throwaway (`/tmp`); no repo files were modified for the audit.
**Review standard:** agents.md Writing Style — evidence, file paths, and failing cases.

## Verdicts

| Area | Verdict |
|---|---|
| 1 — Verifier logic | Fix before wider use. Three of six checks can pass on genuinely lossy explanations (numeric headline drop, negation masked by model copy, hedge loss satisfied by "about"). One check is near-inert. The upgrade rule and the corpus's degraded twins do work. |
| 2 — Corpus honesty | Sound, with one caveat. Labels for the 3 re-derived fixtures are correct; the rewrites were enrichment, not tuning; degraded fixtures provably isolate one defect each. Caveat: the faithful fixtures are near-ideal explanations exceeding what the prompt contract guarantees from a real model. |
| 3 — Schema and cache | One real bug. Schema, isolation, and cache-write failure handling are correct; `CURRENT_VERIFIER_VERSION` was not bumped across two substantial verifier rewrites, so pre-rewrite cached verdicts are served as current. |

## AREA 1 — Verifier logic

### Findings

| # | Severity | Location | Finding |
|---|---|---|---|
| 1.1 | major | `app/services/reader_verify.py:156-162` — `t for t in conclusion_tokens if t["kind"] in ("percent", "duration")][:SALIENT_MAX]` | The headline effect size can be dropped and `numeric_detail` still passes. Salience takes the first 3 percent/duration tokens in document order, not the important ones. Confirmed by construction: abstract names "54% … primary outcome" in its conclusion; the explanation reports 41/33/28% and drops 54% entirely → `numeric: pass, missing=[]`. A headline expressed as a bare number ("fell by 2.3 points") is never required at all — `bare_number` is in no required set (`reader_verify.py:65`). The first-1 cap on p-values (line 70) has the same defect: it requires the first p in the conclusion — the diagnostic, not the headline — and passes when the headline p is dropped (adversarial case B: `checked: 2`, the abstract's `p = 0.4` gone, pass). |
| 1.2 | major | `app/services/reader_verify.py:40` (`PROSE_FIELDS` includes `what_it_does_not_show`) and `:285` (`count_cues(ctx["prose"], "negation")`) | Negation loss is masked by the model's own boundary sentence. The scan pool for "did the explanation mention a negative?" includes `what_it_does_not_show`, which the model authors and which naturally contains "does not". Confirmed by construction: abstract concludes "anxiety showed no significant difference (p = 0.4)"; explanation drops that finding; `what_it_does_not_show: "This study does not show that the programme helps with anxiety."` → `generated_cues: ['does not']` → pass. The rule only fires when the app fallback sentence is used (it contains no negation cue — `reader_mode.py:29-31`), which is exactly the `sst_rct_negation_lost` fixture. The rule fires on app-fallback explanations and is satisfiable away on model-authored ones. |
| 1.3 | major | `app/services/reader_facts.py:44-52` (`HEDGE_MARKERS` includes `"about"`, `"roughly"`, `"on average"`, `"estimate"`, `"estimated"`) feeding `has_hedging` (`reader_facts.py:278-290`), used at `reader_verify.py:316` | Hedge-loss is satisfied by ordinary number phrasing. "about 43 minutes" is a precision qualifier, not preserved epistemic caution, but it satisfies `has_hedging`. Confirmed by construction: abstract concludes "Sleep may improve with later school starts"; explanation asserts "Later starts helped: students slept about 43 minutes longer" → `uncertainty_language: pass, reasons: []`. "Helped" is also not in `CAUSAL_UPGRADES` (`reader_facts.py:33-37`), so both rules miss an explanation that converts a hedge into a flat claim. The comment at `reader_facts.py:280-283` documents the generosity as deliberate, but the consequence — the loss rule is unfirable whenever any number is quoted with "about" — contradicts the check's stated purpose. The upgrade rule does have teeth (alabama fixture fires, `term: causes`, `reasons: ['lost','upgrade']`). |
| 1.4 | minor | `app/services/reader_verify.py:206-208` — `r"pooled (?:analysis|studies|results)"`, `r"combin\w+[^.]{0,40}stud(?:y|ies)"`, `r"earlier studies"` | Synthesis design can be "named" without naming it. Confirmed by construction: a systematic-review/meta-analysis abstract whose explanation says only "Building on earlier studies…" → `study_design: pass` (label "Likely a review paper"). No wrong type can be accepted (synonym sets are keyed by the detected type, `reader_verify.py:253`), but a synthesis explanation that never says review/meta-analysis/pooled/combined is accepted. The corpus's own `dsst_meta_numbers_dropped` passes study_design through this same loose net ("combined several earlier studies"). Lenient direction, and the type itself is a heuristic — hence minor. |
| 1.5 | major (recommendation) | `app/services/reader_verify.py:353` (`if len(candidates) < 3`), `:366` (`if len(missing) < len(candidates)`) | `entity_retention` should be dropped, not shipped near-inert. Measured on the corpus: skipped on 10/12 fixtures. It fires only when at least 3 candidates exist and every one is missing — a wrong-paper scenario already prevented structurally: rows are keyed `(article_id, source, audience)` in the article's own library DB and validated against `abstract_hash` (`reader_mode.py:126-131`). Recommendation: remove the check from `CHECK_ORDER` and the report, or keep it as a details-only diagnostic with no outcome. |
| 1.6 | info | `app/services/reader_verify.py:448-453`; corpus runs | `verification_incomplete` is not dead UI — but only `study_design`'s skip reaches it. Both crafted cases A and C produced `verification_incomplete` (no confident study type). In the corpus it never occurs (all 12 classified confidently). Notes: (a) the status will be common on unclassifiable abstracts, so the chip "Automatic checks could not run fully" often really means "we could not tell what kind of study this is"; (b) `numeric_detail` can pass vacuously — on `caffeine_sleep_null_faithful` nothing is required (`checked: 0`: Bayesian HDIs excluded by the 90/95/99 rule at `reader_verify.py:161`, no `n =` token, no conclusion percents/durations). `details.checked` already records this; the UI does not surface it. |

### Verified as working

- `uncertainty_language` upgrade rule: alabama fixture warns, names "causes", `reasons: ['lost','upgrade']`.
- `negation` fires correctly when the boundary is the app fallback: `sst_rct_negation_lost`, `src_cues: ['did not','did not differ','non-significant']`, `gen_cues: []` — the dropped findings are real (sleep onset "did not differ"; the delayed group's "non-significant" increase).
- The 90/95/99% confidence-convention exclusion (`reader_verify.py:161`) correctly leaves the migraine fixture's `I2 = 60%` required and present.

## AREA 2 — Corpus honesty

### Independent re-derivation (3 fixtures)

| Fixture | Independent read | Label | Agree? |
|---|---|---|---|
| `caffeine_sleep_null_faithful` | Null result; explanation carries it ("did not find a clear effect", "did not detect one"; hedges via "estimated"). Caveat: `numeric_detail` passes vacuously — `checked: 0`, nothing was required. | all pass, `no_automatic_issues` | Agree (outcome correct; one pass vacuous) |
| `sst_rct_negation_lost` | Abstract has three real negative/secondary findings, all dropped; positives kept. | negation warns only, `needs_review` | Agree — correct for the right reason |
| `dsst_meta_faithful` | Keeps 69 min, SMDs, heterogeneity, "associated with", association-not-proof boundary. | all pass, `no_automatic_issues` | Agree |

### The two rewritten faithful fixtures

Git history cannot show the rewrite — all fixtures landed in a single commit (`767171d`). Judged from final text, both rewrites were **enrichment, not tuning**:

- `gamers_cross_sectional_faithful` names "cross-sectional" three times, keeps all four sample sizes, both headline p-values, and the dropped negative ("No significant difference was found in IQ (P = 0.36) or in visual acuity").
- `screen_migraine_review_faithful` names the design, keeps pooled OR/CI/p/heterogeneity, and the two clinic-based studies' negative finding.

The alternative — loosening the verifier until they passed — was not taken. Legitimate. Caveat: both are near-ideal, hand-polished explanations; the warning-fatigue guard therefore measures the verifier against a ceiling standard, not against typical model output. Expect faithful model output to warn more than 0/12.

### Degraded isolation and dead assertions

- Degraded fixtures are provably single-defect: `tests/test_reader_corpus.py:93` asserts `warns == [seeded_defect]` exactly, and the suite is green. `dsst_meta_numbers_dropped`'s `missing: ['69 min']` confirms the seeded defect is the headline statistic.
- No literally dead assertions. Weakest: `tests/test_reader_corpus.py:122-125` re-asserts the severity vocabulary that `_check_outcome` (`reader_verify.py:113-123`) guarantees by construction — it can only fail if the helper changes.
- Circularity note: the docstring (`tests/test_reader_corpus.py:22-24`) says labels were hand-read, not verifier-generated. The labels were verifier-derived first (per the audit brief), but independent re-derivation agrees for the audited subset, so the claim is defensible for those fixtures.

## AREA 3 — Schema and cache

| # | Severity | Location | Finding |
|---|---|---|---|
| 3.1 | major | `app/services/reader_verify.py:24` — `CURRENT_VERIFIER_VERSION = "v1"`, unchanged through both rewrites (`51646dd` → `767171d`); `app/services/reader_mode.py:126-131` | Cached verdicts from the old verifier are served as current. `_cache_valid` checks `abstract_hash + prompt_version + verifier_version`; the verifier's behavior changed substantially (the pre-rewrite version warned on 8/8 faithful explanations) without a version bump. User-visible consequence: any explanation generated before the rewrite keeps rendering its old status chip and warning list — potentially "Some details may need checking" that the current verifier would not produce — until the abstract changes or the student hits Regenerate. The version constant exists precisely to prevent this (plan §4: "Free invalidation on … verifier revision"). Fix is one line: bump to `"v2"`. |
| 3.2 | clean | `app/storage/database.py:141-160` | DDL as specified: PK `(article_id, source, audience)`, FK `ON DELETE CASCADE` to `articles`, no `user_id` column, `verifier_version` default `'v1'`. Isolation genuinely comes from the per-library DB file (`libraries.library_db_path`), not a query filter — there is no user column to filter on. `upsert_reader_explanation` uses `ON CONFLICT DO UPDATE`, never `INSERT OR REPLACE`. |
| 3.3 | clean | `app/services/reader_mode.py:250-264, 265-274` | Cache-write failure is caught, logged via `logger.exception("reader explanation cache write failed")` (not silent), and the response is still built and returned afterwards. |
| 3.4 | clean | `app/storage/database.py:383-386` | `_swap_keep_*` lists exactly `notes, ai_kp, screening, emb`. No `_swap_keep_reader` exists — replace-fetch drops explanations, per locked decision #2. |

## Most important fix

**Bump `CURRENT_VERIFIER_VERSION` to `"v2"`** (`app/services/reader_verify.py:24`).

One line, contract-correct (the constant's sole purpose is invalidation on verifier change), and without it every cached explanation generated this week carries a verdict from a verifier that measurably warned on 8/8 faithful explanations — the exact failure the corpus was built to end.

Follow-ups, in order: 1.1 (numeric salience by importance, not document order) → 1.2 (negation must not scan `what_it_does_not_show` model text) → 1.3 (tighten `HEDGE_MARKERS` — drop "about"/"roughly"/"on average"/"estimated") → 1.5 (drop `entity_retention`). Each fix should add a degraded fixture to the corpus so it is pinned.

---

## AREA 4 — Mutation matrix and docs/version (2026-08-31)

**Scope:** the 11 named mutation gates, then version/spec/README/CHANGELOG/untracked-path checks.
**Branch/commit audited:** `feat/5.3-reader-mode` at `c1e022d`.
**Method:** break each rule, run the named pytest, restore with `git checkout --`, re-run green. Command:

```
DEBUG=true SECRET_KEY='pytest-only-not-a-secret-32b-min!!' ./venv/bin/python -m pytest <args> -q --tb=line
```

Breaks used: early `pass`/`skipped` return on each `_check_*`; delete the `(?P<percent>…)` alternative; skip the `negation` kind in `extract_cues`; rename the first `.reader-mode-btn` in `common.js`; revert `app/routes/reader.py` `LLMBadInput` handler to `str(e)`; copy faithful `generated` into each of the four degraded fixtures.

**Tree after restore:** `git diff --stat` empty. `git status -sb` showed only `?? opencode.json`.

### Mutation results

| # | Rule | Test | Failed when broken? | Notes |
|---|---|---|---|---|
| 4.1 | `_check_numeric_detail` | `tests/test_reader_verify.py -k numeric` | Yes | `test_numeric_missing_sample_size_warns`: expected `warn`, got `pass`. `1 failed, 1 passed, 21 deselected`. Restored: `2 passed … exit=0`. |
| 4.2 | `_check_negation` | `-k negation` | Yes | `test_negation_loss_warns` at `tests/test_reader_verify.py:123`. Restored: `2 passed`. |
| 4.3 | `_check_uncertainty_language` | `-k uncertainty` | Yes | `test_uncertainty_upgrade_warns` at `:162`. Restored: `2 passed`. |
| 4.4 | `_check_study_design` | `-k study_type` | Yes | `test_study_type_omission_warns_only_when_confident` (warn→pass) and `test_study_type_low_confidence_skipped` (skip→pass). Restored: `2 passed`. |
| 4.5 | `_check_entity_retention` | `-k entity` | Yes | `test_entity_retention_uses_pico` (warn→pass) and `test_entity_retention_few_candidates_skipped` (skip→pass). Restored: `3 passed`. |
| 4.6 | `_check_readability` | `-k readability` | Yes | `test_readability_fk_grade_reasonable` at `:286` expected `pass`, got `skipped`. Restored: `2 passed`. |
| 4.7 | `extract_numbers` percent branch | `tests/test_reader_facts.py` | Yes | Crash, not a percent assertion: `IndexError: no such group` at `app/services/reader_facts.py:135` in `test_extract_numbers_kinds_and_units` and `test_extract_numbers_bare_number_token`. Restored: `12 passed`. See 4.A. |
| 4.8 | `extract_cues` negation branch | `tests/test_reader_facts.py` | Yes | `test_cues_word_boundary_no_substring_hits` at `:84`: `assert 'no significant' in []`. Restored: `12 passed`. |
| 4.9 | `.reader-mode-btn` in `static/js/common.js` | `tests/test_reader_ui.py` | Yes | `test_reader_button_lives_in_shared_ai_actions` at `:14`. Restored: `3 passed`. |
| 4.10 | `BAD_INPUT_MESSAGES` lookup → `str(e)` in `app/routes/reader.py` | `tests/test_reader_service.py -k static` | Yes | `test_bad_input_messages_are_static_and_code_selected` at `:189`: `reader route returns exception text to the client`. Restored: `1 passed, 7 deselected`. |
| 4.11 | Four degraded fixtures, `generated` replaced with the faithful twin | `tests/test_reader_corpus.py` | Yes | All four seeded defects went warn→pass: `dsst_meta_numbers_dropped` (`numeric_detail`), `sst_rct_negation_lost` (`negation`), `gamers_design_omitted` (`study_design`), `alabama_commentary_causal_upgrade` (`uncertainty_language`). `8 failed, 42 passed`. Restored: `50 passed`. |

No named suite stayed green after its rule was deleted. The mutation gate is not vacuous.

### Docs, spec, version

`git grep -n '5.3.0'` on the last-bump list — every listed file is on 5.3.0: `app/main.py` (module docstring + `version=`), `app/routes/admin.py:268`, `app/routes/pages.py:29`, `app/routes/support.py:49`, `templates/base.html:153`, `templates/login.html:17`, `templates/landing.html:116`, `templates/feature_guide.html:125`, `README.md:1`, `context.md:4`, `docs/DEPLOY.md:267`, `spec.md:79`.

Remaining `5.2.0` (`git grep -n '5.2.0'`):

```
CHANGELOG.md:21:## [5.2.0] - 2026-08-28
context.md:115:- **Branch:** `design/5.2.0` (local; do not push until asked)
context.md:116:- **Done:** 5.2.0 design — sieve wait/brand/empty states, Source Serif 4
```

CHANGELOG `[Unreleased]` is empty; Reader Mode notes sit under `## [5.3.0] - 2026-08-29` and are not duplicated.

`git diff --exit-code origin/main -- spec.md` → `diff_exit=0` (this branch and `origin/main` have the same `spec.md`). The introducing hunk (`git show 416fbf2 -- spec.md` / `git diff cebd9e6 416fbf2 -- spec.md`) only: extended the Refine/Ask bullet with two audiences, warning-only checks, `HIDE_AI_BUTTONS`, no bulk-explain (`spec.md:48-53`); added button placement on Search/Clean up via `renderKeyPointsHtml` (`spec.md:76-78`); bumped `/health` to 5.3.0; added one acceptance checkbox (`spec.md:164-165`). No unrelated section rewritten.

README Features bullet at `:32-35` covers Explain this study, abstract-only, two reading levels, warning-not-verified, `HIDE_AI_BUTTONS`, not bulk. It is a list item, not a standalone paragraph.

`git ls-files | grep -E 'opencode|design_mockups|^notes.md$|docs/notes.md'` → empty. `opencode.json` is untracked only.

### Findings from this pass

| # | Severity | Location | Finding |
|---|---|---|---|
| 4.A | minor | `app/services/reader_facts.py:135`; `tests/test_reader_facts.py` | Deleting the percent regex alternative does not fail a “34% is a percent token” assertion. It raises `IndexError: no such group` because `extract_numbers` still calls `m.group("percent")`. The suite goes red, so the mutation gate holds, but it is not testing percent extraction. |
| 4.B | minor | `context.md:115-116` | Session Handoff still names `design/5.2.0` while Current State says **5.3.0**. Product version strings agree; this handoff block does not. |
| 4.C | minor | `README.md:32-35` | Explain this study shipped as one Features bullet, not a short standalone paragraph. Content is present. |

No CRITICAL or MAJOR from the mutation/docs pass. Does not retract Area 1–3 findings (1.1–1.5, 3.1): those are about whether the rules mean what they claim, not whether deleting them turns a test red.
