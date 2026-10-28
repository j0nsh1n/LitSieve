# Field test 2026-10-27: government action and African Americans in the Depression

An outside evaluation of one student run. The student's stated question
was "What role did the U.S. government play in changing society during the
Great Depression?" The evaluation narrowed this to African Americans and the
New Deal. Whether that narrower scope was ever typed into LitSieve is not
known (see `docs/SEARCH_AUDIT_2026-10-27.md` §0). The run produced 15
results, exported as RIS. We did not have the RIS file;
its signed link had expired. Each finding below is checked against the code
where that was possible.

## What the evaluator found

Discovery was good. Murphy (New Deal, discrimination, Black advisers),
Hamilton (NAACP and New Deal laws), Lieberman (race and the institutions
running social policy) and Sitkoff's collection make a usable core.

The shortlist was weak. The evaluator would keep 4 core and 2 supporting
sources, use 6 only as background, and drop 3:
- Baugh's review;
- a present-day "Marshall Plan" proposal;
- a broad economic overview.

The export needed cleanup.

## Findings

1. **Every record exports as a journal article.** Confirmed.
   - `app/services/citations.py:143` writes `TY  - JOUR` for every record, and
     BibTeX always writes `@article` (`citations.py:222`). The APA formatter
     is journal-article style.
   - No fetcher keeps a record type, and the `articles` table has no type
     column.
   - Our captured fixtures carry PubMed's `PublicationType` and Europe PMC's
     `pubType`. OpenAlex, Crossref, Semantic Scholar and OpenAIRE are expected
     to send one (unchecked).
   - Abstracts often say it outright: "This book assembles writings", "a
     collection of essays".
2. **One record's journal is "OpenAIRE".** Confirmed.
   - `app/fetchers/openaire.py:148` falls back to the source name when a record
     has no journal. HAL ("HAL", `hal.py:96`) and PLOS ("PLOS", `plos.py:97`)
     do the same.
   - ClinicalTrials.gov writes its registry name (`clinicaltrials.py:164`),
     which is defensible.
   - The placeholder list (`citations.py:118`) does not catch these. This is
     the same class of bug as audit 22.9's "Unknown journal".
3. **Ranking matches the topic, not the relationship the question asks
   about.** Inferred from the design.
   - The score is 0.7 meaning similarity plus 0.3 keyword (TF-IDF) similarity
     to the whole question (`app/services/pipeline.py:660-700`).
   - A broad collection containing every keyword can outrank studies of
     government action.
   - Nothing scores whether a paper addresses the cause-and-effect link that
     was asked about.
   - Narrow it down (`propose_low_relevance`, `pipeline.py:783`) uses the same
     similarity. So it cannot set aside "right population, wrong question"
     papers: mortality trends, newspaper commentary on migration, present-day
     poverty.
4. **Reviews and overviews stay in.** There is no document-type filter.
   This follows from finding 1.
5. **No primary sources.** This is outside today's sources, which only index
   scholarship. No laws, agency reports, correspondence or newspapers.
   - Free candidates (unchecked): the Library of Congress and Chronicling
     America APIs, FRASER, HathiTrust, the National Archives catalog.
   - Whether to add any is a product decision.
6. **Students still have to verify.** The evaluator's advice was to get the
   full texts, check each citation, and pair claims with evidence. The
   export could say so; that is a copy decision.

## Candidate work (proposed, not approved)

- **A. Record type end to end** (medium, schema change).
  - Store a `doc_type` from each source, plus abstract cues.
  - Export RIS `BOOK`, `CHAP`, `JOUR`, `THES` and so on; BibTeX `@book`,
    `@incollection` and `@article`; APA by type.
  - Show a type chip and allow filtering by type.
- **B. Journal fallbacks** (small).
  - Stop using a source's name as a journal.
  - Treat stored "OpenAIRE", "HAL" and "PLOS" as placeholders on export.
- **C. Question-aware ranking** (large). Build an evaluation set first.
  - This run is a ready labelled case: the evaluator's four groups (4 core,
    2 supporting, 6 conditional, 3 drop).
  - Options to compare:
    - re-score the top N against the question with a cross-encoder;
    - split the question into concepts (government action, African
      Americans, the Depression) and reward papers that cover each;
    - a Laya relevance judgment on the top N.
- **D. Set aside reviews or overviews in Narrow it down**, once A exists.
- **E. Add a primary-source collection.** Product decision.

## Needed from the owner

The run's RIS file or library, to reproduce the ranking and score the
options in C against the evaluator's labels.
