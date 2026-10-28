# Search and source-selection audit, 2026-10-27

This audit follows the field test in `docs/FIELD_TEST_2026-10-27.md`. It
covers investigation and a plan only; no code changed. Each claim is marked:

- **Confirmed**: read in the code at commit `e96ca8b`, or reproduced live today.
- **Plausible**: consistent with the code and the probes, but not reproduced.
- **Open**: needs data we do not have.

Probe scripts and raw output are in
`~/HealthDatabaseAccess-scratch/audit-2026-10-27/probes/` (not committed).

## 0. What question did LitSieve actually get?

The student's question was "What role did the U.S. government play in
changing society during the Great Depression?" The evaluation that followed
was about African Americans and the New Deal.

**Open.** LitSieve does not keep a durable record of the Collect query.
`job_records` stores task, outcome and error kinds only (`app/storage/user_db.py:305`);
the query lives in in-memory progress (`app/core.py:636`). The 15 results and
the RIS file are not available, and the RIS link has expired.

Evidence that the narrower scope was typed somewhere, as Collect keywords or
as the Search question (**plausible**):

- Running LitSieve's own history-pack fetchers on the broad question returned
  economics, education policy and unrelated "What role did X play" papers. It
  returned nothing like Murphy, Hamilton, Lieberman or Sitkoff
  (`probes/fetch_q1.json`).
- "New Deal African Americans" returns exactly that kind of scholarship from
  OpenAlex and Crossref (`probes/probes.json`).

Until the library is available, the benchmark must treat the broad question
as the stated one. The earlier field-test notes described the narrow version
as the question; that has been corrected there.

## A. Diagnosis

### A1. Providers

`FETCHERS` in `app/services/pipeline.py:58` lists 16 sources. The History
pack (`app/content/source_catalog.py:219`, `:341`) selects OpenAlex, Semantic
Scholar, ERIC, Crossref, DOAJ, HAL and OpenAIRE. DOAJ is **already
integrated** (`app/fetchers/doaj.py`). CORE has a URL builder
(`app/services/citations.py:56`) but no fetcher.

### A2. From question to provider queries

**Confirmed:** the Collect text goes **verbatim** to every provider
(`fetch_articles_parallel` → `fetcher.search_and_fetch(query, max_results)`,
`pipeline.py:218-233`). Only arXiv and PLOS split it into boolean terms
(`app/fetchers/terms.py`). Nothing removes question wording, preserves
concepts, or adds date, place or population constraints. There is no
fetch-time date filter.

Live results with the broad question, 25 per source:

| Source | Result | Cause |
|---|---|---|
| DOAJ | **HTTP 400**, "Query contains disallowed Lucene features" | The trailing `?` is a disabled wildcard. "great depression?" → 400; without `?` → 200. **Confirmed.** |
| HAL | 0 records | Solr treats the sentence as one query. Plausible. |
| Semantic Scholar | 0 records, no error shown | Open: a later raw call got 429 without a key. |
| OpenAIRE | 2 off-topic records, one with journal "OpenAIRE" | Keywords match on the whole sentence. |
| Crossref | Matches "What role did … play" phrasing (El Salvador gangs, Brexit, bronze-age Argaric society) | The question scaffolding dominates `query` relevance. **Confirmed.** |
| OpenAlex | Mostly economics and finance papers about the Depression | The broad question carries no "society" or policy concepts. |

Geography ("U.S."), period ("Great Depression") and population survive only
as words in the string. A year filter on Search (`_candidate_pool`,
`pipeline.py:621`) filters **publication** year, not the period studied.
Setting 1929–1941 would drop modern scholarship about the Depression.

### A3. Merging and duplicates

**Confirmed** (`ArticleDatabase.insert_articles`, `app/storage/database.py:642`):

- Duplicates are keyed by normalized title or a DOI-shaped `article_id`. The
  first source to finish wins; the later copy is **skipped, not merged**, so
  its DOI, type and access data are lost. The winner depends on thread
  completion order (`as_completed`, `pipeline.py:249`).
- DOI dedupe only works where the id itself is a DOI (Crossref, OpenAIRE, HAL,
  PLOS, bioRxiv). OpenAlex, Semantic Scholar, DOAJ and ERIC never store the
  DOI, though OpenAlex sends one for most records (13 of the 15 in the probe).
- No version relationships exist (preprint, accepted manuscript, published
  version).

### A4. Normalization

**Confirmed.** Every fetcher reduces a record to seven fields: `article_id,
source, title, abstract, year, authors, journal`. The `articles` table has
only those (`database.py:78`). Lost along the way:

- Work type: OpenAlex `type`, Crossref `type` (not even selected,
  `crossref.py:41`), ERIC `publicationtype`, PubMed `PublicationType`, Europe
  PMC `pubType`.
- DOI (except where it is the id), ISBN, editors, publisher, and the
  containing book versus journal distinction.
- OpenAlex `open_access`, `best_oa_location` and `locations`; DOAJ full-text
  links; license.
- The raw provider record, so nothing can be re-derived later.

Specific defects:

- Source names used as journals: `openaire.py:148` (`or "OpenAIRE"`),
  `hal.py:96` (`or "HAL"`), `plos.py:97` (`or "PLOS"`). Seen live: the
  OpenAIRE record above.
- Repository names as journals: OpenAlex `_venue` (`openalex.py:198`) falls
  back to `raw_source_name` when every location is a repository. Seen live:
  "Educational Policy Studies Dissertations" (a GSU repository collection) as
  a journal.
- HTML entities are left in: Crossref `container-title` is not passed through
  `clean_text` (`crossref.py:93`). Seen live: "City &amp;amp; Community".
- **Every fetcher drops records without an abstract.** OpenAlex also filters
  `type:article` (`openalex.py:46`, `:87`), and Crossref uses
  `has-abstract:true` (`crossref.py:40`). For the broad question, Crossref
  has 40,749 chapters and 597 books, but only 3,372 chapters and 134 books
  with abstracts. OpenAlex's 2,594 books and 1,861 chapters are filtered out
  entirely. For history, this removes most monographs and chapters before
  ranking. The books and chapters that do arrive come through Crossref,
  Semantic Scholar and OpenAIRE, unlabeled.

### A5. Publication types and export

**Confirmed** (`app/services/citations.py`):

- RIS writes `TY  - JOUR` for every record (`:143`), and BibTeX always writes
  `@article` (`:222`). APA uses journal-article layout (`:270`). The
  misclassification therefore starts at the **internal default and export
  mapping**. Providers do send types (Crossref labeled "What the New Deal
  Did" `book-chapter` and "African Americans in the Great Depression and New
  Deal" `reference-entry`); normalization discards them.
- APA prints the raw `journal` field, not `_real_journal`, so "Unknown
  journal" and placeholder names still appear there (`:280`). RIS and BibTeX
  filter placeholders (`:118`); none of the three filter source or repository
  names.
- RIS and BibTeX `UR` point to the discovery page that supplied the record
  (`SOURCE_URL`, `:44`): `openalex.org/W…`, `explore.openaire.eu`,
  `doaj.org/article/…`. They do not point to the DOI or publisher.
- Formats: RIS, BibTeX and CSV for a selection (`app/routes/exports.py:53`);
  RIS, BibTeX, APA, TXT and CSV for a library (`:202`).

### A6. Relevance ranking and screening

**Confirmed:**

- `search_similar` (`pipeline.py:700`) takes the top `max(5k, 50)` by
  embedding cosine, then re-ranks with `0.7 × semantic + 0.3 × TF-IDF`
  against the whole question text (`_hybrid_rerank`, `:640`).
- The optional PICO boost adds at most 0.08 for clinical terms
  (`app/services/enrich.py:27`).
- Narrow it down (`propose_low_relevance`, `:783`) uses semantic cosine only.

No step separates concepts or asks whether a paper addresses government
**action** and its social **consequences**. A mortality or migration paper
with the same period and population words scores like a policy study. One
blended `similarity_score` is shown, with no relevance category.

### A7. Accessibility

**Confirmed:** LitSieve never checks access. No outbound fetch exists outside
the provider APIs, LLM hosts and Laya (`grep requests./httpx` in `app/services`
and `app/routes`). OpenAlex returns `open_access.oa_status` per work ("closed"
for 14 of the 15 narrow-query results); LitSieve discards it.

### A8. Summaries and evaluations: evidence basis

**Confirmed:** LitSieve's own outputs are abstract-based and say so.

- Key points are extractive sentences from the abstract
  (`app/services/summarize.py`).
- The Reader explanation is labeled "AI explanation (from this abstract only)"
  (`app/services/reader_mode.py:32`), with "Not reported in the abstract"
  fallbacks.
- Study-type tags are hedged heuristics from title and abstract ("Likely a
  review paper", `app/services/study_type.py:22`).
- LitSieve never reads full text.

The definitive-sounding evaluations, "verified" claims and recommendations of
inaccessible sources in the field test came from the **outside assistant**,
not from LitSieve output.

### A9. Provenance, confidence and failures

- Per-source failures reach the UI as `error_kind` (`FetchError.kind`,
  `app/fetchers/base.py:74`) for the current job.
- Totals reach `job_records`, with no query and no per-record provenance.
- Field-level provenance is only `source` (one per row) and `key_points.origin`.
- No confidence field exists for metadata.

### A10. Caching, jobs and isolation

- Each library is its own SQLite file,
  `user_data/<uid>/libraries/<lib>/articles.db` (`app/storage/libraries.py:4`).
- Job slots are keyed `(uid, library_id, task)`.
- Provider responses are not cached. Embeddings are stored per library; only
  the guest sample has a shared disk cache.
- Any access-check cache must be keyed by DOI or URL, hold public facts only,
  and live outside library files. That keeps libraries isolated while letting
  users share results.

### Attribution summary

| Problem | LitSieve | Outside assistant |
|---|---|---|
| Paywalled or abstract-only recommendations | No access data; links to discovery pages | Recommended them as readable |
| URLs "failed" | Links to OpenAlex, OpenAIRE, DOAJ and S2 pages, not DOIs | Read bot walls as failures: today `doaj.org/article/…` → 403 and Semantic Scholar → 202 challenge in curl; a bogus OpenAIRE id → 200 |
| Mixed work types | Drops types, hides them, labels everything JOUR | — |
| Repository or platform as journal | Fallbacks and `_venue` (confirmed) | — |
| Keyword-matching results | Ranking design (confirmed); verbatim provider queries | Did not separate relevance categories at first |
| No primary sources | Coverage: all sources index scholarship | — |
| Overstated evaluations | Labels its own outputs abstract-only | Overstated depth and verification |

## B. Symptom → cause → fix

| Reported symptom | Confirmed cause or uncertainty | Proposed fix | Expected impact | Effort / risk | Validation |
|---|---|---|---|---|---|
| Paywalled or abstract-only picks | No access data stored; OpenAlex OA fields discarded | Keep OpenAlex `open_access`, `best_oa_location`, `locations`; add an access-status model (§3) | Students see "closed / open copy listed" before choosing | M / low | Fixture tests; manual check of 30 DOIs |
| URLs failed | Links go to discovery pages, some bot-walled; "failed" may have meant blocked | Export DOI as `DO` and `https://doi.org/…` as `UR`; keep the source page as an alternate; record blocked separately from broken | Fewer dead-looking links | S / low | Export tests; probe blocked versus 404 cases |
| Mixed types shown alike | Types discarded in normalization; OpenAlex limited to `type:article` | Store `work_type` and `provider_type`; show a type chip; filter by type | Students can tell books, chapters, reviews and articles apart | M / migration | Per-provider mapping tests from fixtures |
| Everything exported as JOUR | Hard-coded in `citations.py:143`, `:222` | Map by type; unknown → `GEN` / `@misc`, never JOUR by default | Correct imports into Zotero and EndNote | S after the type field exists | Round-trip tests per type and format |
| Repository or platform as journal | Fallbacks in `openaire.py`, `hal.py`, `plos.py`; OpenAlex `_venue` repository fallback | Empty journal instead of a source name; keep the repository in a `host` field; treat known names as placeholders on export, including in APA | No fake journals | S / low | Unit tests; export of existing rows |
| Keyword-matching results | Whole-string similarity; verbatim queries; no concept check | Phase 3: concept-aware query building plus a labeled relevance category on the top N | Fewer off-question papers in the top 10 | L / medium | Benchmark (§G) |
| No primary sources | No primary-source provider | Separate Library of Congress channel, labeled primary (§C) | Primary sources available in a separate list | M / rate limits | Benchmark on 3 history questions |
| Overconfident evaluations | Not LitSieve's output | Keep "from the abstract only" labels; show the evidence basis on every card and export | Prevents future misreading | S | UI and export tests |
| (new) DOAJ fails on any question | `?` passed raw to DOAJ's query-string parser | Strip `?` and other disallowed Lucene syntax for DOAJ; rejected queries become a `bad_query` kind with a plain message | DOAJ works for question-form input | XS / none | Unit test: question → 200-safe query |
| (new) Books and chapters dropped | Abstract required everywhere; OpenAlex `type:article`; Crossref `has-abstract` | Allow books and chapters without an abstract (rank on title, container and subjects); drop the OpenAlex type filter | Monographs reach the shortlist | M / ranking on short text | Benchmark top-10 book recall |
| (new) "&amp;" in journal names | Crossref container not cleaned | `clean_text` on the container | Cosmetic | XS | Unit test |

## C. Provider comparison

Checked 2026-10-27. Some official pages refused automated fetches
(`core.ac.uk/documentation`, the BASE developer page through Anubis); those
facts come from search snippets or third-party copies and are marked as such.

| Candidate | Role | Access and terms (as found) | Fit for LitSieve | Verdict |
|---|---|---|---|---|
| **CORE** | Repository aggregator, full text | Free without registration, subject to rate limits. Search allows about 1 batch or 5 single requests per 10 s (official docs, via search snippet). Registered organizations get faster rates that are "typically not free". Commercial use allowed under its terms, with a 30-day trial (core.ac.uk/services/api). **Our keyless probe got 429 on the first request.** | Large repository full text, but much of it overlaps OpenAIRE and OpenAlex repository locations. Its value is full text and download URLs, not discovery. | Experiment only with a registered key, as an access and full-text **resolver** for shortlisted DOIs, not a fan-out search source. Its `documentType` quality is unverified (our probe was rate limited). |
| **DOAJ** | OA journal articles | Already integrated. API v4; 2 requests/s, bursts of 5 queued; Elasticsearch query string with wildcard, regex, fuzzy and proximity disabled; keys mainly for publishers (doaj.org/api/docs). Metadata license not stated on that page. | Journal articles only. Small history yield: 7 hits for "New Deal African Americans". | Keep. Fix the `?` bug. Use DOAJ inclusion only as "listed in DOAJ", not as a quality signal. |
| **BASE** | Repository discovery (~400M records) | Non-commercial only; access by IP whitelist or key after registration; 1 request/s. Source: a 2023 interface guide (v1.27) via a third-party copy and the rbace docs. The official page blocked our fetch. | Strong repository coverage. An IP whitelist fits poorly with a home server whose outbound IP can change. Whether a free educational app counts as non-commercial is BASE's call. | Defer. Ask BASE in writing before any code. |
| **America: History and Life (EBSCO)** | Subject index for U.S. and Canadian history | Licensed EBSCOhost database. Library guides show concurrency caps (e.g. 6 users). We found **no public API**; any EBSCO API access would run through an institutional customer agreement (unverified). Browsing access does not grant API rights. | The best subject coverage for this question, if available. | Optional institutional integration only (Phase 4), with a partner library's written permission. |
| **Library of Congress (loc.gov JSON)** | Primary sources: newspapers, manuscripts, photos, legislation | Public, no key. Search and item: **20 requests/min, 1-hour block** if exceeded; may answer 429 or CAPTCHA below that under load (loc.gov/apis/…/working-within-limits). Chronicling America limits come from a third-party profile only. | The broad question returned 239k hits, 196k of them newspapers. Keyword matches mixed in a 2011 book and a 2016 video, so it needs date (1929–1941) and format facets, plus question-specific query terms. | Recommended experiment, as a **separate primary-source channel** with low result counts, cached, run per question rather than per fan-out. |
| **Crossref** (existing) | DOI registry, metadata | Polite pool by `mailto`; back off on 429 (rate numbers not stated on the tips page we read). | Already sends `type`, ISBN, publisher and container. Best for reconciling the DOI, type and container of a shortlisted work. | Keep. Select `type,ISBN,publisher,editor,link,license`; use it for reconciliation. |
| **Unpaywall** | Access resolver by DOI | v2 only; `email` parameter required; ≤100,000 calls/day (unpaywall.org/api/v2). Field list (`oa_status`, `best_oa_location`, `version`, `license`, `url_for_pdf`) is from prior knowledge; the data-format page did not render for us. Recheck. | The right tool for "is there a legal open copy of this DOI?". Overlaps OpenAlex OA data, which comes from the same organization. | Use OpenAlex OA fields first, since they arrive free with search. Add Unpaywall only for DOIs from other sources. |
| **OpenAlex** (existing) | Discovery, with OA locations | Key optional; free key $1/day, about $0.10/day without (help.openalex.org). 10 requests/s keyless, 30 with key. Search calls cost more than ID lookups (pricing page; the per-1,000 figures came via secondary sources). | Already the main history source. We discard its type, DOI and OA data. | Keep. **Stop discarding fields** before adding providers. |

A new provider alone will not fix ranking, metadata or evaluation. The
broad-question probe shows bad queries ruin every provider. Equally, better
ranking cannot surface books that the abstract filters remove, or primary
sources no current provider indexes.

### Recommended provider experiment

1. **No new search provider first.** Fix DOAJ, drop the OpenAlex type filter,
   allow books and chapters without abstracts, and keep OpenAlex OA fields.
   This is the cheapest gain in coverage and access.
2. **Library of Congress** as an opt-in "Primary sources" channel for
   history, with dates and formats faceted.
3. **CORE** as a resolver for shortlisted DOIs without an open copy, but only
   after registering and confirming the rate tier. Keyless CORE is unusable
   for a multi-user app (429 on the first call).
4. BASE and AHL wait for written terms.

The CORE + DOAJ starting pair from the brief is not validated as stated. DOAJ
is already present and was broken by the query format, not missing. CORE's
value is access resolution, not discovery.

## D. Access status design (Phase 2)

States, stored per (work, location):

| State | Evidence needed |
|---|---|
| `verified_free_full_text` | The fetched PDF or HTML contains the work: title fuzzy match ≥ 0.9 on the first page or in `citation_title` meta, plus body length or page count over a threshold. HTTP 200 alone is never enough. |
| `open_copy_listed` | A provider (OpenAlex, Unpaywall, DOAJ, CORE) lists an OA location; not yet fetched. |
| `abstract_only` | The page fetched and matches the work, but only the abstract is visible, with no full-text or PDF link. |
| `login_or_payment` | The page matches the work and shows a paywall, login form or price; or the location is publisher-hosted with `oa_status=closed` (provider-reported, labeled as such). |
| `unverified` (reasons `blocked`, `timeout`, `captcha`, `error`) | 403, 429, 202 challenge, CAPTCHA or timeout. **Never** read as paywalled or broken. |
| `broken_or_removed` | 404 or 410 from the origin on two checks at least 24 h apart, or a DOI that doi.org does not resolve. |

Fields per location:

- `url`, `kind` (publisher, repository or aggregator), `host`, `version`
  (submitted, accepted or published), `license`;
- `state`, `method` (provider-listed, Unpaywall, fetched), `checked_at`,
  `http_status`, `error`, `title_match`.

Per work, keep separately:

- `canonical_url` (DOI or publisher);
- `best_reading_url` (the best verified free copy, else the best listed one);
- the list of alternative locations.

Staged and cached:

1. **At fetch** (no extra calls): OpenAlex and DOAJ OA data gives
   `open_copy_listed`, or `login_or_payment` from `closed`.
2. **On the shortlist** (the top 15 shown, or on star): Unpaywall for DOIs
   lacking OA data, rate-limited and in the background.
3. **On demand** ("Check access" or export): fetch the best location with a
   strict byte cap and timeout, then run the match test.

The cache is a host-level `access_cache.db` keyed by DOI or normalized URL,
holding public facts only. Verified results are kept 30 days, unverified 1
day. Library files hold references only, so isolation is preserved.

## E. Metadata and citation exports (Phase 1)

New nullable columns on `articles` and the staging table:

- `work_type`: the canonical vocabulary below;
- `provider_type`: the raw value;
- `doi`, `isbn`, `container_title` (journal or book), `editors` (JSON),
  `publisher`, `host` (repository or platform);
- `published_date`, `deposited_date`;
- `metadata_provenance` (JSON: field → source).

Plus `raw_record` (compressed JSON, capped at 32 KB) so later fixes can
re-derive fields. Migration is `ALTER TABLE ADD COLUMN`, as
`migrate_schema` already does. Existing rows stay NULL; nothing is rewritten.

Canonical types and their export mappings:

| work_type | RIS | BibTeX | APA layout |
|---|---|---|---|
| journal-article | JOUR | @article | Journal |
| book | BOOK | @book | Book |
| edited-book | EDBOOK | @book (editor) | Edited book |
| book-chapter | CHAP | @incollection | Chapter in edited book |
| reference-entry | ENCYC | @incollection | Entry in reference work |
| review (book review) | JOUR, plus a "Review of …" note | @article, plus note | Review |
| conference-paper | CPAPER | @inproceedings | Conference paper |
| dissertation | THES | @phdthesis | Dissertation |
| report | RPRT | @techreport | Report |
| preprint | JOUR with a preprint note, or GEN | @misc | Preprint |
| primary-source items (newspaper, manuscript, image) | NEWS / MANSCPT / ART | @misc | By format |
| unknown | GEN | @misc | Generic |

Merge rule for duplicates: keep the first row as the library's row, but fill
**empty** fields from the duplicate (DOI, type, container, OA data) and record
the provenance. Never overwrite a non-empty field silently.

Legacy rows with NULL `work_type` keep `JOUR` when they have a real journal
and `GEN` otherwise. This is a **proposed decision for the owner**: it keeps
old exports stable but is still a guess.

## F. Relevance and evaluation (Phase 3)

Keep four dimensions separate on each card and in CSV export:

1. **Relevance category** to the stated question:
   - direct analysis of government policy and its social consequences;
   - policy implementation;
   - population experience or response;
   - general background;
   - related subject (migration, mortality);
   - modern commentary with incidental overlap.
2. **Work type and suitability**: from metadata only. Peer review is not
   inferred from "journal article", and DOAJ listing or citation counts are
   not used as quality.
3. **Access state** (§D).
4. **Evidence basis**: `metadata only`, `abstract reviewed` or `full text
   reviewed`.

Mechanism options to compare on the benchmark, all limited to the top 30
after today's ranking:

- (a) concept split of the question (actor, action, outcome, population,
  period, place) with coverage scoring;
- (b) Laya as a typed switch: question plus title and abstract → one of the
  six categories, with low-confidence answers shown as "unclassified" (fits
  the Laya rules: fixed labels, code owns each branch);
- (c) a cross-encoder re-ranker.

Rank within the category, never across it: direct analysis comes before
background. Do not penalize age.

Query building for Collect (pairs with F):

- Show a "keywords sent to sources" preview derived from the question:
  question scaffolding removed, concepts kept, each provider's syntax
  escaped. The student can edit it.
- Never silently narrow the scope: population terms appear only if the
  student typed them.

Two result views: **Best scholarly matches** (any access) and **Best verified
free-to-read**. A substitute is suggested only after looking for an open copy
of the same work, with a line on what differs (type, scope, peer review
status). Primary-source labels depend on the question: a 2019 study *of* 1930s
newspapers is secondary.

## G. Benchmark

The original 15 are **missing**. Do not reconstruct them from the
evaluation text. What is needed: the student's library or RIS, or at minimum
the Collect query, the sources ticked and the Search question.

Harness, proposed: `scripts/eval_search.py` runs against a **frozen corpus
snapshot** (fetch once, store the raw provider JSON) so provider drift cannot
move scores. The reference set is a hand-reviewed JSON file per question:

- bibliographic fields and work type;
- relevance category and rationale;
- access state and date checked;
- inspection depth;
- duplicate or version links;
- appropriate use in the paper.

Labels come from a person, not a model.

Metrics, before and after each phase:

- relevant@5 and @10 (category "direct" or "implementation");
- verified-free count in the top 10;
- false accessible, paywalled or broken labels against manual checks;
- type and export accuracy (RIS `TY` and BibTeX entry type per record);
- duplicate rate;
- wall time;
- provider calls and OpenAlex budget used.

Questions:

- the broad Depression question;
- the narrow African American version, labeled as a separate question;
- one non-U.S. history question;
- one health question (regression guard for PubMed-heavy users);
- one education question.

No numbers exist yet. Every figure in §A comes from one probe run on
2026-10-27 and is illustrative.

## H. Phased plan

1. **Immediate correctness** (small, no product decisions except the legacy
   type rule):
   - DOAJ query escaping;
   - remove source-name journal fallbacks;
   - APA uses `_real_journal`;
   - placeholder list adds source and repository names;
   - clean the Crossref container;
   - add `work_type`, `provider_type` and `doi` columns, mapped for OpenAlex,
     Crossref, ERIC, PubMed, Europe PMC, OpenAIRE, HAL and DOAJ;
   - type-aware RIS, BibTeX and APA;
   - DOI exported as `DO` and the DOI URL as `UR`;
   - merge empty fields on duplicates.
2. **Access and providers**:
   - keep OpenAlex OA data; access-state model and cache;
   - Unpaywall for the shortlist; on-demand verification;
   - drop the OpenAlex type filter;
   - allow books and chapters without abstracts;
   - Library of Congress primary-source channel (opt-in);
   - CORE resolver after key registration.
3. **Ranking and evaluation**:
   - benchmark harness and reference sets first;
   - query preview in Collect;
   - relevance categories (compare a, b, c);
   - evidence-basis labels;
   - two result views;
   - type filter in Search and Narrow it down.
4. **Optional institutional**: AHL through a partner library; BASE if its
   terms allow.

## I. Minimal first implementation (proposal, not approved)

Scope is Phase 1 only. Files:

- `app/fetchers/{doaj,openaire,hal,plos,crossref,openalex,eric,pubmed,europepmc}.py`
- `app/storage/database.py` (migration, insert, merge)
- `app/services/citations.py`
- `app/routes/exports.py` (CSV type column)
- tests

Acceptance criteria:

1. A Collect query ending in `?` or containing `:` `"` `(` `)` returns
   DOAJ results, or a typed `no_results`, never HTTP 400.
2. No new row has `journal` equal to a source or repository platform name.
   Export never prints one, including APA.
3. A Crossref `book-chapter` exports as `TY - CHAP` with `T2` (the book),
   `@incollection` with `booktitle`, and an APA chapter layout. A
   `reference-entry` → `ENCYC`; `book` → `BOOK` / `@book`; unknown → `GEN` /
   `@misc`.
4. OpenAlex records store the DOI. RIS includes `DO` and
   `UR  - https://doi.org/…`. The OpenAlex page is kept as an alternate
   (`L2`, or the BibTeX `note`).
5. When two sources return the same DOI, the stored row gains the missing
   type and DOI from the second, and `metadata_provenance` names it.
6. Existing libraries open unchanged. Old rows export as before (`JOUR` with
   a journal, `GEN` without), pending the owner's decision on that rule.
7. Lint, types and the full test suite pass.

Regression tests:

- One captured fixture per provider type: Crossref chapter, reference entry,
  edited book; OpenAlex book and book review; ERIC report; PubMed review.
- The export matrix: each type × RIS, BibTeX, APA and CSV.
- The DOAJ query sanitizer, using the probe's failing string.
- A legacy-row migration test on a copy of a pre-migration database.
- A merge-on-duplicate test.
- A placeholder-journal test covering "OpenAIRE", "HAL", "PLOS" and a
  repository name.

## Smallest set most likely to improve the next shortlist

1. Fix question-form queries: DOAJ escaping now, the keyword preview soon.
   The broad question broke DOAJ and steered Crossref to the wrong papers.
2. Keep the type, DOI and OpenAlex OA status that providers already send,
   then export by type and show type and "open copy listed / closed" on each
   card.
3. Stop inventing journals from source and repository names.
4. Let books and chapters through without abstracts, and stop OpenAlex
   filtering to `type:article`.

These need no new provider and no paid service. Ranking work (Phase 3) should
wait for the benchmark and the original run's data.

## Sources (checked 2026-10-27)

- CORE API: https://core.ac.uk/services/api ; https://core.ac.uk/documentation/api (via search snippet)
- DOAJ API: https://doaj.org/api/docs
- BASE: https://en.wikipedia.org/wiki/BASE_(search_engine) ; rbace docs https://www.rdocumentation.org/packages/rbace/versions/0.2.0 ; interface guide copy https://www.scribd.com/document/935528536/Base-Interface (third-party)
- America: History and Life: https://www.ebsco.com/sites/default/files/acquiadam-assets/America-History-and-Life-with-Full-Text-Getting-Started-Guide.pdf ; https://libguides.regent.edu/az/america-history-and-life-ebsco-interface
- Library of Congress: https://www.loc.gov/apis/json-and-yaml/working-within-limits/ ; Chronicling America limits (third-party) https://apis.io/rate-limits/chroniclingamerica/chroniclingamerica-rate-limits/
- Crossref: https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/
- Unpaywall: https://unpaywall.org/api/v2
- OpenAlex: https://help.openalex.org/api-reference/authentication ; https://help.openalex.org/access/pricing/
