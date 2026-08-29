# Plan — Reader Mode / Explain this study

**Status:** Planning only, 2026-08-29. Nothing implemented. No branch, no code.

Build note for a paper-specific plain-language explainer with a deterministic
self-check. Verified against `main` — every path, symbol and table below was
read from the repo, not assumed. Items marked **needs inspection** were not
confirmed and must be before that step is built.

## Goal

A student opens one paper they already have, clicks **Explain this study**,
picks a reading level, and gets a structured plain-language explanation of that
abstract — with the numbers, hedging and negative findings intact, and an
honest label saying how much was checked automatically.

Not a medical-advice tool. Not a "paste any text" box. An educational reading
aid for one abstract at a time.

## Non-goals

- No full-text or PDF extraction. Abstracts already in LitSieve only.
- No diagnosis, treatment, triage or personalised advice.
- No freeform paste-any-text interface.
- No claim that output is medically validated or "verified".
- No local NLI/entailment model (isolated future enhancement at most).
- No model training or fine-tuning; no multi-language support.
- No multi-document synthesis, no human-review workflow.
- No whole-library "explain everything" endpoint — `tests/test_ai_policy.py`
  exists to forbid exactly this class of route.

## Constraints (read before writing code)

- Reuse `app/services/llm.py`. Do not add a second LLM client.
- CSP is `script-src 'self'` / `style-src 'self'`. No inline `style=`, no CDN.
  Runtime values go through CSS custom properties set with `setProperty`.
- No npm, no build step. Vanilla JS, Jinja templates.
- Simple/Advanced parity is a release requirement.
- Never edit `agents.md`. `spec.md` only with explicit human approval.
- `tests/test_static_js.py` enforces `?v=` cache-busts on every script tag.

---

## 1. Current repository findings

### Papers are addressed by a composite key

`(article_id, source)` everywhere — not a single id. This shapes every schema
and endpoint below.

`app/storage/database.py:46`:

```sql
CREATE TABLE IF NOT EXISTS articles (
    article_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'pubmed',
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    year TEXT, authors TEXT, journal TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (article_id, source)
)
```

Retrieval: `Database.get_article_by_id(article_id, source)` —
`app/storage/database.py:673`.

### Ownership is filesystem-scoped, not row-scoped

There is no `user_id` column on `articles`. Each library is its own SQLite
file: `libraries.library_db_path(user_id, library_id)`
(`app/storage/libraries.py:69`), reached via `core.get_pipeline(uid)`
(`app/core.py:148`), which resolves the user's active library.
`_safe_fs_id()` (`app/storage/libraries.py:44`) sanitises ids before any path use.

**Consequence:** a Reader Mode row keyed only on `(article_id, source)` inside
the library DB inherits correct isolation for free. Adding a `user_id` column
would be inconsistent with `notes` and `key_points`.

### There is no paper-detail page

Papers render as expandable cards built client-side. The shared builder is
`renderKeyPointsHtml(bullets, options)` — `static/js/common.js:337` — called
from exactly two places:

- `static/js/search.js:972`
- `static/js/clusters.js:281`

It already emits the AI action row with the composite key and a deployer flag:

```javascript
const showAi = typeof uiFlag === 'function' ? uiFlag('show_ai_buttons', true) : true;
const actions = (aid && src && showAi)
    ? `<div class="ai-actions" data-article-id="${aid}" data-source="${src}">
        <button ... class="ai-refine-btn">Refine with AI</button>
        <button ... class="ai-ask-btn">Ask about this paper</button>
        <span class="ai-status-line help-text" hidden></span>
       </div>
       <div class="ai-panel" hidden></div>`
```

**This is the highest-leverage finding.** `renderKeyPointsHtml` does not branch
on UI mode, so one insertion there gives Simple/Advanced parity structurally
rather than by duplication.

`renderPicoBlock(pico)` (`static/js/search.js:877`) is the closest precedent for
a structured, labelled, visually distinct block on a card.

### Existing AI route pattern

`app/routes/ai.py` (315 lines, five routes). `api_ai_refine_article` (`:158`)
is the template:

```python
user = current_user(request)
if not user: return JSONResponse(401, {"detail": "Not authenticated"})
if csrf_failed(request): return JSONResponse(403, {"detail": "CSRF validation failed"})
uid = user["user_id"]; p = get_pipeline(uid)
try:
    if not is_configured(): return JSONResponse(503, {"detail": _ai_unconfigured_detail()})
    article = p.db.get_article_by_id(req.article_id, req.source)
    if not article: return JSONResponse(404, {"detail": "Article not found"})
    def _work(): return run_with_ephemeral_builtin(lambda: refine_article(...))
    result = await run_in_thread(_work)
except LLMUnavailable as e:  return JSONResponse(503, {"detail": _friendly_ai_unavailable(str(e))})
except LLMError as e:        return JSONResponse(400, {"detail": str(e)})
except Exception as e:       return server_error()
finally: release_pipeline(uid)
```

Conventions to copy: deferred imports of `app.services.llm` inside handlers;
`run_in_thread` for blocking work; `run_with_ephemeral_builtin` for the
start → call → stop Ollama lifecycle; a human-readable `label` on the response
naming provenance (`:207`).

### LLM abstraction and structured output — already solved

`app/services/llm.py:911`:

```python
def _structured_call(system: str, prompt: str, schema_model: Type[BaseModel]):
```

Dispatches to `_structured_ollama` / `_structured_openai` / `_structured_anthropic`
(`:952`, `:984`, `:1043`); parses via `_parse_schema` / `_extract_json_object`
(`:1075`, `:1083`). Error taxonomy: `LLMUnavailable` (`:57`) = no provider or
provider down; `LLMError` (`:61`) = call failed or output unusable.
`provider()` (`:394`), `is_configured()` (`:422`).

Existing output models `RefinedArticle` (`:65`) and `ArticleAnswer` (`:78`)
show the Pydantic-with-`Field(description=...)` style the prompt depends on.

`_REFINE_SYSTEM` (`:791`) and `_ASK_SYSTEM` (`:811`) already encode the safety
posture: abstract-only grounding, no invented numbers, no evidence grades, no
medical advice, "JSON matching the requested schema only (no markdown fences)".

`refine_article` enforces `if len(abstract) < 40: raise LLMError(...)` (`:838`)
— an existing minimum-length precedent to reuse verbatim.

### Study-type detection — reusable as-is

`app/services/study_type.py:192` — `classify_study_type(title, abstract)`
returns `study_type`, `study_type_label`, `study_type_label_formal`,
`study_type_meaning`, `confidence` (0-1), `confidence_band`
(`none`/`low`/`medium`/`high`, via `_confidence_band` at `:182`),
`matched_phrase`, `warning`, `disclaimer`. Pure heuristics, no dependency cost.

### Entity extraction precedent — rules, not ML

`PICOExtractor.extract_pico(text)` — `app/services/embeddings.py:318`. Keyword
lists plus sentence splitting, attached by `enrich.attach_pico`
(`app/services/enrich.py:17`). This is the house style for entity work and the
Reader Mode entity check should follow it rather than introduce spaCy.

`app/services/summarize.py` provides `split_sentences` (`:78`) and
`parse_structured_abstract` (`:86`) over `STRUCTURED_HEADERS` (`:27`) with
`ROLE_ORDER = ("aim","method","findings","conclusion","background")` (`:56`).
Useful for salience filtering now and sentence-span mapping later.

### Permissions, quota, rate limits

- Auth: `core.current_user` (`:545`) — JWT plus live `token_version` check.
- CSRF: `core.csrf_failed` (`:726`) — double-submit cookie, required on all
  state-changing `/api` routes.
- Read-only support view: `app/support_gate.py:32` blocks mutating routes.
  **Needs inspection:** confirm the method/path predicate at
  `app/support_gate.py:27` so a new POST is genuinely covered.
- Quota: `app/storage/quota.py` is **storage bytes only** — `limit_bytes`,
  `usage_bytes`, `is_over_quota`, `QuotaExceeded`. Only `app/routes/corpus.py`
  consults it. **There is no LLM call-count quota anywhere in the codebase.**
  AI cost control today is purely `@limiter.limit("8/minute")`
  (`app/routes/ai.py:157`).
- UI flags: `app/content/ui_flags.py:19` — `show_ai_buttons` (from
  `HIDE_AI_BUTTONS`), `show_study_type_tags`.

### Schema init and migrations

**No migration framework, no `PRAGMA user_version`.** The pattern is idempotent
`CREATE TABLE IF NOT EXISTS` in the init block plus defensive `ALTER TABLE` in
`Database.migrate_schema()` (`app/storage/database.py:138`), e.g. `:165`:

```python
cursor.execute("ALTER TABLE key_points ADD COLUMN origin TEXT NOT NULL DEFAULT 'extractive'")
```

Replace-fetch machinery: `STAGING_TABLE` (`:288`) and `_swap_keep_notes` /
`_swap_keep_ai_kp` / `_swap_keep_screening` / `_swap_keep_emb` (`:344`-`:372`)
preserve student-owned artifacts across a library swap.

### Test conventions

Flat `tests/`, pytest only. Relevant precedents:

- `tests/test_llm_service.py` — providers mocked via `monkeypatch`,
  `_clear_providers()` helper, no network.
- `tests/test_ai_policy.py` — policy tests via `conftest.route_paths(app)`,
  asserting forbidden routes absent **and** required routes present
  ("guards against a vacuous pass").
- `tests/test_disclaimers.py` — canonical phrases checked across templates.
- `tests/test_static_js.py`, `tests/test_ui_tokens.py` — asset contract tests.

`tests/conftest.py` is thin: `_reset_rate_limits` (autouse) and `route_paths`.
**Needs inspection:** there is no shared authenticated-client fixture. Find how
`tests/test_search_http.py` and `tests/test_integration_accounts.py` build a
logged-in `TestClient` with CSRF and reuse it.

### Dependencies

`requirements.txt` has numpy, scikit-learn, sentence-transformers, faiss-cpu,
umap-learn, fastapi, jinja2, PyJWT, cryptography, sqlcipher3-binary, bcrypt,
slowapi, python-dotenv, pytest. **No readability library, no spaCy, no NLTK.**

---

## 2. Integration decision

**New focused route module: `app/routes/reader.py`.**

Not `app/routes/ai.py`. That file already mixes provider settings, Ollama
process control and per-article generation at 315 lines. Reader Mode adds
generation, verification, caching and persistence; folding it in produces the
one-big-route-file problem. A sibling module matches the existing
one-concern-per-module layout (`exports.py`, `shares.py`, `start_over.py`).

**Endpoints:**

- `POST /api/reader/explain` — generate or return cached
- `GET  /api/reader/explanation` — cache-only lookup, never generates

Generation on POST means CSRF and the read-only support gate both apply.

**Service boundaries — three new modules, each single-purpose:**

| Module | Responsibility |
|---|---|
| `app/services/reader_facts.py` | Deterministic extraction from the source abstract: numbers, units, durations, negation cues, uncertainty cues, entity candidates. No LLM. |
| `app/services/reader_verify.py` | Compares generated content against extracted facts; emits the report. No LLM, no I/O. |
| `app/services/reader_mode.py` | Orchestration and prompt versioning. |

`reader_facts` and `reader_verify` are pure functions over strings. That is what
makes the checker testable with no provider in the loop, which the whole test
plan depends on.

**LLM access:** add `generate_reader_explanation()` to `app/services/llm.py`
beside `refine_article` / `ask_article`, so all provider contact stays in
`llm.py` and `reader_mode.py` never touches provider internals.

**Storage:** new table `reader_explanations` in `app/storage/database.py`,
created in the same init block as `notes` / `key_points`. Not a new module, not
a new database — a per-article derived artifact in the library DB, exactly like
`key_points`.

**Schemas:** request/response in `app/schemas.py` beside `AIArticleRequest`;
LLM output model in `llm.py` beside `RefinedArticle`; verification models in
`reader_verify.py`.

**Frontend:** one button inside the existing `.ai-actions` block in
`renderKeyPointsHtml`; handler in a new `static/js/reader.js`; styles appended
to `static/css/style.css`; script tags added to `templates/search.html` and
`templates/clusters.html` with `?v=` cache-busts.

---

## 3. Data contracts

### Request — `app/schemas.py`

```python
class ReaderExplainRequest(BaseModel):
    article_id: str = Field(min_length=1, max_length=256)
    source: str = Field(min_length=1, max_length=64)
    audience: Literal["high_school", "general_reader"] = "general_reader"
    force_regenerate: bool = False
```

### LLM output — `app/services/llm.py`

```python
class GlossaryEntry(BaseModel):
    term: str = Field(max_length=80)
    definition: str = Field(max_length=400)

class ReaderExplanation(BaseModel):
    plain_summary: str = Field(max_length=1500)
    question_asked: str = Field(max_length=800)
    who_was_studied: str = Field(max_length=800)
    what_was_found: str = Field(max_length=1500)
    what_it_does_not_show: str = Field(max_length=1000)
    stated_limitations: str = Field(max_length=1000)
    glossary: List[GlossaryEntry] = Field(default_factory=list, max_length=12)
    not_reported_fields: List[str] = Field(default_factory=list)
```

Every prose field is **required**. The model writes
`"Not reported in the abstract."` rather than omitting a key, which is what
keeps "What this study does not show" always renderable.

### Verification — `app/services/reader_verify.py`

```python
CheckId  = Literal["numeric_detail", "study_design", "negation",
                   "uncertainty_language", "entity_retention", "readability"]
Severity = Literal["info", "warning"]        # no "error": nothing blocks display
Outcome  = Literal["pass", "warn", "skipped"]

class VerificationCheck(BaseModel):
    check_id: CheckId
    outcome: Outcome
    severity: Severity = "info"
    message: str = Field(max_length=300)     # user-facing, plain language
    details: Dict[str, Any] = Field(default_factory=dict)   # never rendered raw

class ReadabilityReport(BaseModel):
    flesch_kincaid_grade: Optional[float] = None
    dale_chall_score: Optional[float] = None
    target_band: str
    within_target_band: Optional[bool] = None
    caveat: str = "Readability scores estimate sentence and word complexity only."

class VerificationReport(BaseModel):
    status: Literal["verified_no_automatic_issues", "needs_review",
                    "verification_incomplete"]
    checks: List[VerificationCheck]
    readability: ReadabilityReport
    checked_at: datetime
    verifier_version: str
```

Status derivation: any `warn` → `needs_review`; any `skipped` on a
non-optional check → `verification_incomplete`; otherwise
`verified_no_automatic_issues`. Precedence: `needs_review` >
`verification_incomplete` > pass.

### Persisted record

```python
class ReaderExplanationRecord(BaseModel):
    article_id: str
    source: str
    audience: Literal["high_school", "general_reader"]
    abstract_hash: str          # sha256 hex of normalised abstract
    prompt_version: str         # "reader_v1"
    verifier_version: str       # "v1"
    content: ReaderExplanation
    verification: VerificationReport
    provider: Optional[str]
    model: Optional[str]
    created_at: datetime
```

### API response

```python
class ReaderExplainResponse(BaseModel):
    article_id: str
    source: str
    audience: str
    cached: bool
    content: ReaderExplanation
    verification: VerificationReport
    label: str = "AI explanation (from this abstract only — not medical advice)"
    disclaimer: str
    provider: Optional[str] = None
    prompt_version: str
```

`label` mirrors `app/routes/ai.py:207`. Errors reuse the repo shape exactly:
`{"detail": "..."}` with 401 / 403 / 404 / 400 / 503 / 500. No new envelope.

### Example payload (abridged)

```json
{
  "article_id": "34567890", "source": "pubmed",
  "audience": "high_school", "cached": false,
  "content": {
    "plain_summary": "Researchers looked at whether starting school later helped teenagers sleep more...",
    "question_asked": "Does moving school start times later increase how long teenagers sleep?",
    "who_was_studied": "Students at secondary schools, followed across two school years.",
    "what_was_found": "Students slept about 43 minutes longer on average per night.",
    "what_it_does_not_show": "The abstract alone cannot establish whether these findings apply to everyone.",
    "stated_limitations": "Not reported in the abstract.",
    "glossary": [{"term": "cohort", "definition": "A group of people followed over time."}],
    "not_reported_fields": ["stated_limitations"]
  },
  "verification": {
    "status": "needs_review",
    "checks": [
      {"check_id": "numeric_detail", "outcome": "warn", "severity": "warning",
       "message": "The abstract mentions 2 numbers that do not appear in the explanation.",
       "details": {"missing": ["two academic years", "p < 0.01"]}},
      {"check_id": "uncertainty_language", "outcome": "pass", "severity": "info",
       "message": "Cautious wording from the abstract was kept."}
    ],
    "readability": {"flesch_kincaid_grade": 9.1, "target_band": "grades 8-10",
                    "within_target_band": true,
                    "caveat": "Readability scores estimate sentence and word complexity only."},
    "verifier_version": "v1"
  },
  "prompt_version": "reader_v1"
}
```

---

## 4. Database and caching

### Table

Added to the init block in `app/storage/database.py` beside `key_points`
(`:125`), following its exact shape:

```sql
CREATE TABLE IF NOT EXISTS reader_explanations (
    article_id       TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'pubmed',
    audience         TEXT NOT NULL,
    abstract_hash    TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    verifier_version TEXT NOT NULL DEFAULT 'v1',
    content_json     TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    provider         TEXT,
    model            TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (article_id, source, audience),
    FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
        ON DELETE CASCADE
)
```

**Ownership** inherited from the library DB file — no `user_id` column,
consistent with `notes` and `key_points`.

**Deletion** is free on three axes: `ON DELETE CASCADE` when an article goes;
`libraries.delete_library` (`app/storage/libraries.py:300`) removes the whole
file; account deletion removes `user_dir`.

**Indexes:** the composite primary key covers the only access path. No
secondary index — unjustified on a table read by single-row lookup.

**Storage economy:** stores `abstract_hash`, never the abstract. The source text
already lives in `articles.abstract` and is joined at read time. A row is
bounded at roughly 4-8 KB.

**Quota:** rows grow the library `.db`, which `quota.library_file_bytes`
(`:159`) already measures. No new quota code; it accrues automatically.

### Cache key

Not a stored string — the primary key plus two stored discriminators:

```
lookup:  (article_id, source, audience)
valid iff  row.abstract_hash    == sha256(normalise(articles.abstract))
      and  row.prompt_version   == CURRENT_PROMPT_VERSION
      and  row.verifier_version == CURRENT_VERIFIER_VERSION
```

Mismatch is a miss → regenerate and `INSERT OR REPLACE`. Free invalidation on
abstract change, prompt revision and verifier revision, with no cleanup job.

`normalise()` = strip, collapse internal whitespace, NFKC, casefold.
**Deliberately not** stripping punctuation — a hash that ignores punctuation
would miss a meaningful abstract change.

### Replace-fetch — decision needed

`_swap_keep_notes` / `_swap_keep_ai_kp` / `_swap_keep_screening` /
`_swap_keep_emb` (`app/storage/database.py:344`-`:372`) preserve student-owned
artifacts across a replace-fetch. Reader explanations are derived and
regenerable, unlike a hand-written note.

**Recommended default: do not preserve.** The hash check would often invalidate
them anyway. If preserved later, add `_swap_keep_reader` on the same pattern.

---

## 5. Generation and verification pipeline

### Lifecycle and failure states

| # | Step | Failure → response |
|---|---|---|
| 1 | Auth + CSRF | 401 `Not authenticated`; 403 `CSRF validation failed`; 403 read-only support view |
| 2 | `get_article_by_id` | 404 `Article not found` |
| 3 | Abstract validation | `< 40` chars → 400, reusing `llm.refine_article:838` phrasing. Empty → 400, distinct message |
| 4 | Normalise + hash | — |
| 5 | Cache lookup | Hit → return `cached: true`, no provider call |
| 6 | `is_configured()` | 503 `_ai_unconfigured_detail()` |
| 7 | Extract source facts | Pure; cannot fail. Empty results degrade individual checks to `skipped` |
| 8 | Structured generation | `LLMUnavailable` → 503 `_friendly_ai_unavailable`; `LLMError` → 400 |
| 9 | Schema validation | Inside `_parse_schema`; failure surfaces as `LLMError` → 400 |
| 10 | Verification | Never fails the request. Internal exception → `verification_incomplete`, all checks `skipped` |
| 11 | Persist | Write failure logged; **response still returned**. A cache write must never lose work the user waited for |
| 12 | Respond / render | — |

Steps 7-8 run inside `run_in_thread(...)` wrapped in
`run_with_ephemeral_builtin(...)`, matching `api_ai_refine_article:189`.

### Numeric extraction and comparison

Single regex pass over normalised text producing typed tokens:

```
percent     (\d+(?:\.\d+)?)\s*%
p_value     [Pp]\s*[=<>≤≥]\s*0?\.\d+
ci          \d+\s*%\s*CI[^)]*|\[\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*\]
duration    \d+(?:\.\d+)?\s*(second|minute|hour|day|week|month|year)s?
sample_size (?:n\s*=\s*|N\s*=\s*)(\d[\d,]*)
dose        \d+(?:\.\d+)?\s*(mg|g|kg|ml|mcg|µg|IU|mmHg)\b
year        \b(19|20)\d{2}\b
bare_number \b\d+(?:\.\d+)?\b        (lowest priority; only if unclaimed)
```

Comparison is **value-normalised, not string-equal**: strip commas, coerce to
float, compare numerically within a unit class. `43-minute` matches
`43 minutes`. Percentages match only percentages.

**Salience filter — the critical design point.** "Every source number must
appear" would fire on nearly every explanation, because plain-language
rewriting legitimately drops some figures. Only these are required:
`sample_size`, `p_value`, `ci`, `dose`, and the **top 3** `percent`/`duration`
tokens by order of appearance in the findings/conclusion sections (via
`summarize.parse_structured_abstract`). Bare numbers and years are reported but
never warned on.

### Negation and uncertainty

Cue lists as module constants, following `PICOExtractor`'s keyword-constant
style:

```python
NEGATION_CUES    = ("not", "did not", "no difference", "no significant",
                    "without", "failed to", "unable to", "did not differ")
UNCERTAINTY_CUES = ("may", "might", "could", "suggests", "appears",
                    "associated with", "potential", "limited", "unclear",
                    "further research", "further study", "preliminary")
CAUSAL_UPGRADES  = ("causes", "proves", "demonstrates that", "shows that",
                    "confirms", "guarantees", "leads to", "will")
```

Two distinct rules:

1. **Loss** — cue count in the source's conclusion sentences > 0 **and** cue
   count in `what_was_found` + `plain_summary` == 0 → `warn`.
2. **Upgrade** (stronger signal) — source conclusion has an uncertainty cue
   **and** the generated section contains a `CAUSAL_UPGRADES` term → `warn`,
   naming the term.

Matching is word-boundary regex on casefolded text. Substring matching would
fire "may" inside "mayor".

### Study-design preservation

Call `study_type.classify_study_type(title, abstract)`. If `confidence_band` is
`high` or `medium` and `study_type != "unclear"`, check whether
`study_type_label` or `study_type_label_formal` (or a synonym) appears in the
generated content. Absent → `warn`.

**Band `low` or `none` → `skipped`**, never a warning. Warning on a
low-confidence heuristic trains users to ignore warnings.

### Entity retention

Reuse `PICOExtractor.extract_pico(abstract)`. From each non-empty PICO list
take the first sentence; extract capitalised multi-word spans and any token
matching the intervention/population keyword lists; cap at 8 candidates. Check
case-insensitive presence in generated content. Missing more than half →
`warn`. No new dependency.

### Readability

**Implement Flesch-Kincaid inline (~25 lines) in `reader_verify.py`. Do not add
a dependency.** FK needs sentence count, word count and syllable count;
`summarize.split_sentences` already provides the first. A vowel-group syllable
heuristic with the standard adjustments (silent trailing `e`, `le` endings,
minimum 1) is what every small library does anyway.

**Dale-Chall is deferred** — it requires shipping and maintaining a 3,000-word
familiar list, real weight for a signal FK already covers in v1. Kept
`Optional` in the schema.

Presented as a band, never a promise: *"Reads at about a 9th-grade level
(target: grades 8-10)."* with `caveat` always rendered.

### Warnings vs failures

**Every check is a conservative warning. There are no hard failures.** Nothing
in the verifier withholds content; it only annotates. A hard failure would
imply the verifier can establish correctness, which is exactly the overclaim to
avoid. The only conditions that withhold output are structural: absent
abstract, too-short abstract, provider unavailable, malformed JSON.

---

## 6. Prompt contract

Versioned constant `READER_PROMPT_VERSION = "reader_v1"` in
`app/services/reader_mode.py`, persisted per row. Two system prompts in
`app/services/llm.py` beside `_REFINE_SYSTEM` (`:791`), sharing a common core.

### Shared core

```
You are a careful reading aid inside a student literature-research app.

CONTEXT / ROLE:
- The student selected ONE paper from their personal library and asked for a
  plain-language explanation.
- You are given that paper's title and abstract only (not the full PDF or any
  paywalled text). Treat the supplied text as your entire knowledge of the paper.
- You are also given structured facts the app extracted deterministically from
  that same abstract. Treat them as trusted; do not contradict them.

RULES:
- Use ONLY the supplied title, abstract, and extracted facts. Never invent
  results, numbers, populations, methods, or claims.
- PRESERVE every quantity, named intervention, and study design that appears in
  the abstract. Do not round, drop, or generalise numbers.
- PRESERVE the strength of the original claims exactly. If the abstract says
  "associated with", "may", "might", "suggests", "limited evidence",
  "no significant difference", or "further research is needed", your explanation
  must carry the same caution. Never upgrade a correlation into a cause.
  PROHIBITED EXAMPLE — abstract: "Later start times were associated with longer
  sleep duration." Wrong: "Later start times cause teenagers to sleep longer."
  Right: "Students with later start times tended to sleep longer, though the
  study cannot show that the later start is what caused it."
- Distinguish two different things:
    stated_limitations    = limits the ABSTRACT ITSELF states. If the abstract
                            states none, write exactly:
                            "Not reported in the abstract."
    what_it_does_not_show = a general boundary of what any single abstract can
                            establish. This is YOUR interpretation, not the
                            paper's claim. Never attribute it to the authors.
                            If you have nothing specific, write exactly:
                            "The abstract alone cannot establish whether these
                            findings apply to everyone."
- If information for a section is absent, write "Not reported in the abstract."
  and add that field name to not_reported_fields. Never leave a field empty.
- Do NOT give medical, legal, or professional advice. Do not suggest what anyone
  should do about their health.
- Do NOT invent an evidence grade (A-D), quality score, or confidence level.
- Respond with JSON matching the requested schema only (no markdown fences).
```

### Audience deltas

**`high_school`** — *"Write for roughly grades 8-10. Short sentences, one idea
per sentence, everyday vocabulary. Every unavoidable scientific or medical term
must appear in the glossary with a one-sentence plain definition. Do not
simplify by deleting a number or a caution."*

**`general_reader`** — *"Write for an informed non-specialist adult. Plain but
not childish; keep meaningful scientific context. Glossary only for genuinely
specialist terms."*

The trailing clause on `high_school` matters: simplification pressure is exactly
what causes numeric and hedge loss, so the prompt must pre-empt it.

### Variables the application supplies

| Variable | Source |
|---|---|
| `title` | `article["title"]` |
| `abstract` | `article["abstract"]`, normalised |
| `source`, `article_id` | request — for the `Library record:` line, per `refine_article:855` |
| `audience` | request; selects the system prompt |
| `extracted_numbers` | `reader_facts` — typed tokens with surface forms |
| `study_type_label` + `confidence_band` | `classify_study_type`; **omitted entirely when band is low/none** |
| `uncertainty_cues_found` | `reader_facts` — verbatim cue phrases present |
| `structured_sections` | `summarize.parse_structured_abstract` when structured |

Nothing else. No user identity, no library name, no note text, no query history.

---

## 7. UI/UX plan

### Placement

One button inside the existing `.ai-actions` block, `static/js/common.js:353`:

```html
<button type="button" class="btn btn-secondary btn-sm reader-mode-btn"
        title="Plain-language explanation of this abstract">Explain this study</button>
```

Because `renderKeyPointsHtml` is shared by `search.js:972` and
`clusters.js:281` and neither branches on mode, **parity is structural.** It
also inherits the `show_ai_buttons` deployer flag automatically.

### Interaction

Click → audience selector appears inline in the existing `.ai-panel` (not a
modal; matches Refine's inline pattern). Two radios, `general_reader`
preselected, plus an Explain button. On submit: loading state, then result.

### States

- **Loading** — reuse `setLoading(btn, true)` plus `.ai-status-line`, identical
  to Refine/Ask. No new spinner.
- **Cached** — render immediately with a quiet *"Saved explanation ·
  Regenerate"* marker. `GET /api/reader/explanation` on card expand allows this
  with no generation.
- **Error** — 503 renders existing `_friendly_ai_unavailable` text; 400 renders
  *"This abstract is too short to explain (a few sentences are needed)."*
- **No/short abstract** — the button is not rendered at all, which beats an
  error after a click.

### Keeping generated text distinguishable from source

The highest-stakes visual requirement. Three reinforcing signals:

1. A **left accent rule** on `.reader-mode-panel`, following `.notification`
   (`style.css:3049`) which already uses `border-left-color` to signal type.
   Generated content reads as a quoted region, not page content.
2. A persistent header: **"AI explanation — generated from this abstract"**,
   same convention as `"Key points (AI rewrite — from the abstract only)"`.
3. The original abstract stays on the card, above the panel, unmodified. The
   panel never replaces it. A "Show original abstract" anchor scrolls to it.

Section headings use `--font-serif`, body uses `--font-sans`. Glossary is a
`<dl>` in a tinted sub-block with its own heading.

### Verification display

| Status | Chip colour | Wording |
|---|---|---|
| `verified_no_automatic_issues` | `--ok` | "Automatic checks found no obvious issues" |
| `needs_review` | `--warn` | "Some details may need checking" |
| `verification_incomplete` | `--text-soft` | "Automatic checks could not run fully" |

Never "verified", "accurate" or "correct" standing alone. Warnings render as a
short plain-language list from `VerificationCheck.message`; `details` is never
rendered raw. Always-present footer: *"This is an educational reading aid, not
medical, legal, or professional advice. Always check the original paper."* —
reusing the canonical phrase from `templates/macros/disclaimers.html:23`.

### Accessibility

- Real `<button>`; audience selector is `<fieldset>` + `<legend>` + radios with
  labels, as `simple-screen-levels` does in `simple_screening_card.html:46`.
- Panel gets `role="region"` and `aria-labelledby` on its header.
- Status line is `role="status" aria-live="polite"`, matching
  `#search-preparing-status` (`search.html:90`).
- Focus moves to the panel header on completion; `Escape` returns focus to the
  trigger.
- The status chip carries text, not colour alone.
- Touch targets inherit the existing `@media (pointer: coarse)` rule.

### Mobile

Full card width, sections stack, glossary single-column, no horizontal scroll.
At ≤380px section headings drop one step on the `--fs-*` scale. Long
explanations get a collapsed-by-default glossary.

---

## 8. Test plan

### `tests/test_reader_verify.py` — pure, no provider

- `test_numeric_missing_sample_size_warns`
- `test_numeric_unit_variant_matches` — `43-minute` vs `43 minutes`
- `test_percentage_and_p_value_preserved`
- `test_bare_numbers_do_not_warn`
- `test_ci_and_dose_preserved`
- `test_negation_loss_warns`
- `test_uncertainty_upgrade_warns` — "associated with" → "causes"
- `test_uncertainty_preserved_passes`
- `test_word_boundary_no_false_positive` — "mayor" must not match "may"
- `test_study_type_omission_warns_only_when_confident`
- `test_entity_retention_uses_pico`
- `test_readability_fk_grade_reasonable`
- `test_status_precedence`
- `test_verifier_never_returns_error_severity`

### `tests/test_reader_service.py` — provider monkeypatched

- `test_malformed_json_maps_to_llm_error`
- `test_provider_timeout_maps_to_unavailable`
- `test_schema_violation_rejected`
- `test_prompt_omits_low_confidence_study_type`
- `test_prompt_contains_no_user_identity` — data minimisation, mechanically checked

### `tests/test_reader_http.py`

- `test_reader_routes_require_auth`
- `test_reader_requires_csrf`
- `test_reader_404_for_unknown_article`
- `test_reader_400_for_short_abstract`
- `test_reader_503_when_unconfigured`
- `test_user_cannot_read_another_users_explanation`
- `test_explanation_not_shared_across_libraries`
- `test_support_view_cannot_generate`
- `test_rate_limit_applies`

### `tests/test_reader_cache.py`

- `test_second_request_is_cached`
- `test_audience_change_is_a_miss`
- `test_abstract_change_invalidates`
- `test_prompt_version_bump_invalidates`
- `test_verifier_version_bump_invalidates`
- `test_get_endpoint_never_generates`
- `test_cache_write_failure_still_returns_content`

### `tests/test_reader_schema.py`

- `test_reader_table_created_on_init`
- `test_table_added_to_existing_db`
- `test_article_delete_cascades`
- `test_library_delete_removes_explanations`

### Extend existing files

- `tests/test_ai_policy.py` — add the two reader routes to required-present;
  add `/api/reader/explain-library`, `/api/reader/bulk-explain` to forbidden.
- `tests/test_disclaimers.py` — assert the reader disclaimer phrase, and that
  `"clinically verified"` / `"medically accurate"` / `"guaranteed"` appear
  nowhere in reader templates or JS.
- `tests/test_static_js.py` — `reader.js?v=` present in both templates.
- `tests/test_ui_flags.py` — `HIDE_AI_BUTTONS=true` hides the button.

### Non-vacuous regression strategy

Three mechanisms, because "the test passes" must be distinguishable from "the
test cannot fail":

1. **Positive-and-negative pairing.** Every checker test asserting `warn` has a
   sibling asserting `pass` on near-identical input. Deleting the rule flips the
   `warn` case; hard-coding it flips the `pass` case. Neither survives.
2. **Route-presence assertions**, copying `test_ai_policy.py` — the
   forbidden-route test also asserts required routes exist, so deleting the
   feature fails the suite rather than trivially passing it.
3. **UI hook contract test.** `tests/test_reader_ui.py` asserts
   `static/js/common.js` contains `reader-mode-btn` inside the `.ai-actions`
   template literal, and that both templates load `reader.js`. Removing the
   button from the shared renderer — the exact regression that would silently
   break parity in one mode — fails here.

Deliberate mutation check during review: delete the negation rule and confirm
`test_negation_loss_warns` fails; remove the button and confirm
`test_reader_ui.py` fails.

---

## 9. Delivery plan

**PR 1 — Reconnaissance and contract tests**
`tests/test_ai_policy.py`, `tests/test_reader_ui.py` (new, xfail).
Acceptance: suite green with xfails recorded. Rollback: revert; nothing shipped.

**PR 2 — Schema and persistence**
`app/storage/database.py`, `tests/test_reader_schema.py`. Table plus
`get_reader_explanation` / `upsert_reader_explanation`.
Acceptance: table created on fresh and existing DBs; cascade verified.
Rollback: table is additive and unread.

**PR 3 — Deterministic verifier**
`app/services/reader_facts.py`, `app/services/reader_verify.py`,
`tests/test_reader_verify.py`. No route, no LLM, no wiring.
Acceptance: full checker matrix green. Rollback: delete two unimported modules.

**PR 4 — Generation service and prompt versioning**
`app/services/llm.py` (models, `generate_reader_explanation`, two system
prompts), `app/services/reader_mode.py`, `tests/test_reader_service.py`.
Acceptance: mocked-provider tests green; no route yet. Rollback: additive.

**PR 5 — API integration**
`app/routes/reader.py`, `app/main.py`, `app/schemas.py`,
`tests/test_reader_http.py`, `tests/test_reader_cache.py`.
Acceptance: authorization, isolation, cache and error mapping green.
Rollback: unregister the router — one line, data intact.

**PR 6 — UI in both modes**
`static/js/common.js`, `static/js/reader.js`, `static/css/style.css`,
`templates/search.html`, `templates/clusters.html`, `tests/test_reader_ui.py`,
`tests/test_disclaimers.py`.
Acceptance: button in both modes, a11y verified, flag hides it, cache-busts
bumped. Rollback: remove the button; API remains harmlessly unused.

**PR 7 — Evaluation fixtures and documentation**
`tests/fixtures/reader/*.json`, `docs/`, `CHANGELOG.md`, `README.md`,
`context.md`. A dozen real abstracts with hand-labelled expected warnings.
Acceptance: corpus runs in CI. Rollback: test-only.

---

## 10. Risks and decisions

### Must be decided before implementation

1. **Is there an LLM call budget?** There is no call-count quota in the
   codebase — only `slowapi` rate limits. Reader Mode is heavier than Refine.
   On a paid provider with ~17 accounts this is a real cost surface.
   **Recommend:** ship with `@limiter.limit("6/minute")`, defer a per-user daily
   cap to v2 — but decide it consciously rather than by omission.
2. **Does Reader Mode survive a replace-fetch?** Recommend no (regenerable).
3. **`generate_reader_explanation()` in `llm.py` vs promoting
   `_structured_call`?** Recommend the former — keeps provider contact in one
   module.
4. **Who signs off on the fallback sentence?** *"The abstract alone cannot
   establish whether these findings apply to everyone."* is app-authored text
   attributed to no one, rendered on many explanations. It needs an owner.

### Can be deferred

- Dale-Chall alongside Flesch-Kincaid
- Source-span attribution — `split_sentences` and `parse_structured_abstract`
  make sentence-index mapping cheap later; storing `{section: [sentence_idx]}`
  in `content_json` is additive and needs no migration
- Additional audiences
- Preserving explanations across replace-fetch
- Export integration (`app/routes/exports.py`)
- Any NLI/entailment model — isolated future enhancement only

### Risks

**Warning fatigue is the primary product risk.** A checker that fires on most
explanations trains users to ignore it, which is worse than no checker. The
salience filter is the mitigation; the PR 7 corpus is how we measure it. Target
under ~30% of explanations showing a warning on typical abstracts.

**False reassurance is the primary safety risk.**
`verified_no_automatic_issues` will be read by some users as "correct".
Mitigated by wording, the always-present disclaimer, and never rendering a bare
"verified".

**Non-English and unstructured abstracts** degrade every regex check. They must
produce `verification_incomplete`, not silent passes. **Needs inspection:** what
fraction of a typical library is non-English — the fetchers cover arXiv, HAL,
OpenAIRE and DOAJ, which carry substantial non-English content.

**Provider variance** — local Ollama-class models follow strict JSON schemas
less reliably than cloud models; `_parse_schema` failures surface as 400s. Run
the evaluation corpus against both a built-in and a cloud provider before
release.

**Scope creep to watch:** full-text extraction; "explain my whole library"; a
chat follow-up on the explanation; exporting explanations into RIS; per-sentence
highlighting. Each is individually reasonable; all are out of scope for v1.

---

## Version 1 decision summary

**Architecture.** New `app/routes/reader.py` with two thin endpoints
(`POST /api/reader/explain`, `GET /api/reader/explanation`) delegating to three
single-purpose services — `reader_facts.py` (extraction), `reader_verify.py`
(checks), `reader_mode.py` (orchestration). All provider contact stays in
`app/services/llm.py` via a new `generate_reader_explanation()` beside
`refine_article`, reusing `_structured_call` and the existing
`LLMUnavailable`/`LLMError` → 503/400 mapping.

**Storage.** One table, `reader_explanations`, in the per-library SQLite DB
beside `key_points`, keyed `(article_id, source, audience)`, storing
`abstract_hash` but never the abstract. Created by idempotent
`CREATE TABLE IF NOT EXISTS` — no migration framework, matching the repo.
Isolation, quota accounting and deletion inherited from the library-file model.

**Caching.** Primary-key lookup validated against `abstract_hash` +
`prompt_version` + `verifier_version`; any mismatch regenerates. No cleanup job.

**Verification.** Six deterministic checks — numeric detail (salience-filtered),
study design (only at medium/high confidence), negation, uncertainty/causal
upgrade, PICO-based entity retention, inline Flesch-Kincaid. **All warnings, no
hard failures.** Status vocabulary exactly `verified_no_automatic_issues` /
`needs_review` / `verification_incomplete`. No new runtime dependency.

**UI.** One button inside the existing `.ai-actions` block in
`renderKeyPointsHtml` (`static/js/common.js:337`), giving Simple/Advanced parity
structurally rather than by duplication, and inheriting `HIDE_AI_BUTTONS`.
Results render in an accent-ruled panel visually distinct from source content,
with the original abstract always still present.

**Scope.** Abstracts already in LitSieve, two audiences, seven fixed sections,
JSON-schema-validated output. No full text, no span attribution, no NLI model,
English-first with graceful `verification_incomplete` degradation.

**Sequence.** Seven PRs — verifier before generation before API before UI — so
the highest-risk logic is reviewable in isolation with no provider in the loop.
