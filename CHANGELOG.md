# Changelog

All notable user-visible changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project aims to follow Semantic Versioning for app version strings
(`app/main.py` / `GET /health`).

## [Unreleased]

### Fixed
- Other listed copies finds the same work when a stored DOI uses a doi.org
  prefix or different capital letters. Unstarring a paper hides that list
  even if a copy request was already in flight. Starring another paper on
  the same page still shows copies that were loading for the other cards.
  A website URL with and without a trailing slash is one copy. A listed
  URL says "Open copy listed" when any stored source for that URL meets
  the open rule.


### Added
- On a starred Search card with no open copy listed, "Other listed copies (N)"
  names other known places for the same work (same DOI or a merged record),
  each with a link. A copy that meets the stored open rule also says "Open
  copy listed". The list uses stored data only, at most five URLs. Crossref
  text-mining links appear only with a recognised Creative Commons licence.
- Search cards show an access label from stored OA fields: "Open copy listed"
  (a link) or "No open copy listed (<source>)". A Free to read filter keeps
  papers with an open copy listed. Nothing is checked over the network.
  Crossref text-mining links count only when that link has a recognised
  Creative Commons licence URL.
- `app/services/question_concepts.py` reads a research question into
  keywords and actor, action, outcome, population, period and place
  phrases. Search does not call it yet.
- Search cards show a type chip when the paper has a stored type (Article,
  Review article, Book, Chapter, Thesis, and the rest of the stored types).
  Papers with no type, or an unknown type, have no chip. A Type filter sits
  next to Sources. It narrows the library before ranking. "Type not stored"
  keeps older papers whose type was never saved. With the filter off, ranking
  matches today's results.
- `tools/eval_search.py` captures a frozen search corpus, replays ranking
  offline, scores human labels, and writes label sheets. Provider records
  stay out of git.
- Each library keeps the last 50 Collect inputs and Search questions in its
  own database (`fetch_runs`, `question_log`). The contact email is never
  stored. Clones do not copy these rows. Start over clears them. Admin and
  support views do not read them.
- Admin Overview has a tile for every queue (over quota, sign-in errors and
  disabled join the six that were there) with real totals rather than the
  queue page's cap of 25, refreshed every minute while the tab is open, and
  a "Recent admin activity" card: the newest 50 admin actions across every
  account, each linking to the student (`GET /api/admin/queue-counts`,
  `GET /api/admin/activity`).
- Admin gains a Tickets tab: filter by status (open, waiting on student,
  investigating, resolved, all), read the whole thread, reply, and set the
  status. The tab shows the open count, the Overview tile opens it, and a
  student's tickets on the Accounts tab link straight to their thread.
  "Reply to latest ticket" is gone with it. An unknown status filter is now
  a 400 instead of the whole list.
- The Host tab shows the last backup, the watchdog's verdict, free disk and
  whether the Laya sidecar answers (`GET /api/admin/host`, read-only), the
  built-in study aid's state with Start and Stop buttons, and the last Ship
  deploy. The Site tab lists each copy key's revisions with "Roll back to
  this".

### Changed
- Label sheets include each paper's abstract and a link, shuffle the rows so
  rank is not first, and write a readable HTML page per question.
- A later fetch of the same work fills empty metadata (including year and
  authors) on the paper already in the library instead of skipping the new
  copy. Same DOI is the same work across sources; different DOIs stay
  separate even when the titles match. A title match also stays separate
  when the journals disagree, the given names are known and different, or
  the types cannot be the same work (book or edited book vs review, book vs
  chapter, preprint vs article, dataset vs article). A fetch that only
  finds papers you already have says so ("already in your library" or
  "updated existing papers"), instead of "returned nothing". Notes, stars
  and embeddings stay on the original record.
- RIS, BibTeX, APA, CSV and TXT exports follow each record's type (journal
  article, book, chapter, report, thesis, preprint, and the rest). Older
  papers with no stored type still export as a journal article when they
  have a real journal, and as a generic record otherwise. Zotero imports
  RIS `GEN` as a journal article, so students who need a generic type
  should prefer BibTeX `@misc`.
- CSV (search results and library) adds Type, DOI, Container, Publisher
  and Open copy URL at the end of the existing columns. TXT lists Type
  and DOI when those fields are present.
- ERIC, PubMed, Europe PMC, bioRxiv, medRxiv, Semantic Scholar, HAL,
  OpenAIRE, Zenodo, arXiv, PLOS, ClinicalTrials.gov and NASA ADS fill type,
  DOI, container, host, OA and biblio on new fetches, matching OpenAlex,
  Crossref and DOAJ. Older rows stay empty. Search, ranking, exports and
  the on-screen list are unchanged.
- OpenAlex, Crossref and DOAJ fill type, DOI, container, host, OA and biblio
  on new fetches, and store provenance, locations and a trimmed provider
  record in `article_extra` (zlib-compressed, stored only at 4096 bytes or
  less). Older rows stay empty. Search, ranking, exports and the on-screen
  list are unchanged.
- Library databases gain nine nullable work-metadata fields and a DOI index,
  plus an `article_extra` table for provenance and compressed provider records
  capped at 4096 bytes. Existing libraries migrate on open, replace fetches
  copy the new fields atomically, and clones exclude provider records.
  Search, cluster, and set-aside API responses
  omit unset metadata keys, so legacy payloads keep their previous shape;
  exports and on-screen behavior are unchanged.
- Text fields, selects and buttons have a visible edge in every look: a
  `--control-edge` token (text mixed 58% into the surface) measures 3.3:1
  or more against the surface and page, where the old `--rule` hairline
  was 1.2 to 2.3:1 (WCAG 1.4.11). Dividers keep `--rule`.
- Night light's accent chip is a shade lighter (12%), so its accent text
  reads at 4.6:1 instead of 4.47:1.
- `spec.md` calls the relevance step "Narrow it down", as the app does.
- Admin Overview's failed-job count and source errors cover the last 24
  hours from saved job records (`job_records` in `users.db`), so a restart
  no longer resets them; active and stalled stay live. The line reads
  "N failed of M in the last 24 h".
- The storage sweep also deletes sign-in events and job records older than
  90 days and one-time tokens a week past expiry (audit 20.5).
- With the sample papers' vectors and key points saved, a guest's prepare
  loads no model at all, even in a fresh server process (0 s instead of
  about 10 s); the saved file now holds key points too.
- Each library runs its own jobs: a fetch or prepare in one library no
  longer blocks another, and an account runs at most two jobs at once. The
  409 says which limit was hit. Search, the wait screen and Cancel act on
  the page's library (`GET /api/progress?library_id=`), and Admin's job
  card names the library and sends it with Cancel and Clear stale.
- A guest start no longer embeds the sample papers each time: the first
  prepare saves their vectors under `USER_DATA_DIR/.cache/`, and later
  guests and "Load sample papers" copy them in (about 10 s down to under
  half a second on the host).
- Admin is four tabs: Overview (tiles that open the queue they count),
  Accounts (search and queues beside the open account), Site (banner and
  student-facing copy) and Host. The address bar follows the tab, queue and
  account, so a link lands on the right thing and Back works.
- Every admin action asks the same way: a reason always, the student's
  username when it changes access or deletes data, and the word `publish`
  to publish or take down the banner. Each reports with the same toast and
  status line. The buttons and their rules come from one list in
  `app/routes/admin.py`, and a test keeps the page equal to it.
- Account notes, sign-in events and the timeline show 25 at a time with
  "Show 25 more" (`GET /api/admin/users/{id}/history`).
- The dead "Reset MFA" button and its route are gone; this host has no MFA.
- Error messages are the app's own sentences. When an AI request or a Ship
  action fails, the message no longer carries the provider's or system's raw
  error text; the server log keeps it.

### Fixed
- Closed Search cards name every source that reported on the paper in
  "No open copy listed (<sources>)". An open label needs a real HTTP(S)
  link with a hostname. A Crossref link counts when that entry has a
  Creative Commons licence URL such as /licenses/by/4.0/.
- Question concept helper keeps effect and impact as content unless they
  are the frame noun, as in "what impact did" or "the effect of". It
  reads a population after "in". Lowercase "us" is not a place. Search
  still does not call it.
- Benchmark replay snapshots now copy each paper's stored type, DOI and
  container title from the frozen corpus, so type_accuracy scores those
  fields.
- APA prints `https://doi.org/<doi>` for every paper with a DOI, not only
  Crossref. RIS `UR` prefers that DOI link; `L2` is only a listed open
  copy, never a Crossref `via=crossref` link; the discovery page goes in
  `N1` when it differs from `UR`.
- ERIC reports, books and other non-journal types store the issuing
  organization as the publisher instead of a container title, so exports
  no longer treat that name as a journal.
- Fetchers leave missing journals empty instead of using OpenAIRE, HAL,
  PLOS, Zenodo publishers, arXiv categories, preprint server names, or
  ERIC's "Online Submission". OpenAlex skips e-book platforms and repository
  names while keeping real journals recovered through `raw_source_name`.
- RIS, BibTeX and APA omit known source and platform placeholders from
  the journal, including those in older stored papers. PLOS ONE and PLOS
  Biology remain journals. ClinicalTrials.gov keeps its stored label,
  but exports omit that label as a journal; RIS still uses `TY  - JOUR`.
- Crossref decodes HTML entities in titles and container names, so
  "City &amp; Community" becomes "City & Community". Abstract handling
  is unchanged.
- Search's year-range hint explains that the filter uses publication
  year and keeps undated papers after dated ones.
- Collect topics with punctuation work with DOAJ, HAL and PLOS. DOAJ
  removes disabled Lucene syntax and encodes the topic as one URL path
  segment, so a slash such as "HIV/AIDS" cannot split the path. HAL escapes
  Solr punctuation; PLOS escapes each term after its boolean tokenizer.
  DOAJ and HAL refuse blank or punctuation-only topics before a request,
  and unreadable queries show "This source couldn't read the search words.
  Try simpler keywords." in the source reports.
- Admin console (audit 16.1 to 16.9). Saving a banner draft no longer takes
  the live banner down: the draft is its own row, the Site tab shows what is
  on the site and the draft separately, and only Publish and Take down
  (both behind the word `publish`) change what students see. A `status`
  field in the save body is ignored, and Roll back brings the earlier
  wording back as the draft.
- An admin can no longer disable, or set the email of, any admin account
  (their own included), or revoke their own sessions; the page says why
  before a dialog opens (`refusals` in `GET /api/admin/users/{id}`).
- A support view now lasts only as long as the admin session that started
  it: logging out, a revoked or disabled admin session, or losing admin
  rights ends it, so the student's identity never outlives the admin's.
- Host tab: a socket-activated Laya worker that idled out reads "asleep,
  starting now" instead of "not answering"; watchdog times show as UTC
  times rather than epoch seconds.
- Recent admin activity leaves out students' own ticket actions, says
  "their own account" instead of ending on a preposition, words student
  view ends and support packet exports, and no longer prints banner row ids.
- Unlock, Re-enable and Retry prepare are enabled only when the account's
  state allows them; Retry fetch reuses the student's own contact email
  instead of a placeholder.

- Account safety (audit 17.1 to 17.12). Wrong passwords only lock an
  account when eight land within 15 minutes, an expired lock starts the
  count again, and a lock no longer signs out sessions that are already in.
  Wrong passwords on Account, Ship unlock and student view count toward the
  same lock, and change-password and delete-account are rate limited.
- Rate limits key on a live session (the account exists and the token
  version matches), not on any signed token; guest tokens last as long as
  the 30-minute demo.
- `/login` and `/register` refuse posts the browser marks as cross-site. A
  guest's "Create a free account" opens the form, and registering replaces
  the demo. A name listed in `ADMIN_USERNAMES` cannot be registered:
  register first, then list it.
- An unknown username costs a full password check, reset codes appear on
  screen only with `RESET_CODES_IN_RESPONSE`, and Ship unlock has no
  fallback secret.
- The last fetch's topic, sources and contact email are stored per account
  in the browser and cleared on Logout.
- Support-view refusals and redirects carry the security headers.
- Ship: a Validate counts only for the exact files it checked; any later
  change, including an Ask Grok edit, needs a new Validate before commit
  or deploy.

- Sources (audit 18.1 to 18.17). bioRxiv and medRxiv search Europe PMC's
  preprint index for that server, so a plain topic finds matching
  preprints; before, they scanned 30 posts from the oldest end of a 60-day
  window and almost always reported no results. Their papers link through
  doi.org.
- Europe PMC stores each paper's journal (it read a field core results do
  not have, so every paper said "Unknown journal"), strips HTML from
  abstracts, and links preprints and PMC records to the right page.
  DOAJ, Zenodo, OpenAIRE and PLOS abstracts and titles are plain text too.
- arXiv and PLOS match every word of a topic instead of any one of them
  ("heart disease" found Alzheimer's papers), and arXiv keeps the
  three-second spacing its API asks for, with one request per page.
- A source that answers with a web page instead of data (DBLP's bot check)
  reports a sentence instead of "Expecting value". PubMed, Semantic Scholar,
  DOAJ, Zenodo, Europe PMC and NASA ADS report failures as failures rather
  than "no results", and NASA ADS says when the server has no token.
- PubMed goes through the shared HTTP client, so its requests time out,
  retry, honour the fetch budget and cancel; older records dated only by a
  range ("1990 Dec 3-17") get their year. The process-wide 30-second socket
  timeout it set at import is gone.
- A source that finishes just after the fetch budget keeps its papers, any
  error keeps the pages already fetched, and a `Retry-After` longer than
  the time left fails at once instead of waiting out the budget.
- DOAJ, Zenodo and OpenAIRE page without re-fetching earlier records.
  OpenAIRE links a PMID to PubMed and its own ids to OpenAIRE Explore
  instead of a broken doi.org link.
- ClinicalTrials.gov no longer stores the sponsor as the journal. OpenAlex
  shows the journal instead of a repository name such as "PubMed". PubMed,
  Europe PMC, OpenAlex and ClinicalTrials.gov keep every author, not the
  first five. A paper with no year is stored with an empty year rather
  than "Unknown".
- Optional host keys `S2_API_KEY`, `OPENALEX_API_KEY` and `NCBI_API_KEY`
  give Semantic Scholar, OpenAlex and PubMed their own limits
  (`docs/SELFHOST.md`). A blank contact email sends no address at all
  instead of a shared placeholder.

- Search ranking (audit 19.1). The number on each result is now the score
  the list is sorted by: 0.7 × meaning plus 0.3 × exact-word overlap, both
  on their own fixed 0-1 scale. Before, word overlap was stretched across
  the shortlist, so the paper with the most overlap got the full word
  weight however small it was ("Public comment periods and environmental
  justice" ranked 4th for an exercise and depression question), and the
  cards could read 0.321, 0.354, 0.167 down the list. The PICO boost adds
  to that same score.
- The Kept / Removed / Screened out rail updates after Not relevant and its
  Undo, Group by theme's Set aside and Undo, and Start over, without a
  reload (19.2).
- Duplicate copies removed after prepare now show inside Narrow it down as
  their own line ("16 duplicate copies already set aside") with Undo, and
  "papers ready to rank" leaves set-aside papers out, so it matches the
  "about 21 of 85" counts (19.3).
- A year range no longer hides papers with no usable year: they appear
  after the results under "No year listed" (19.16).

- Search page flow (audit 19.4 to 19.14):
  - The "All your tools now live on Search" notice shows only in a browser
    that stored the old Advanced layout, not in every new browser.
  - Narrow it down asks for its three level counts once per question
    (six requests before), and Back clears "Showing N paper(s) that would
    be set aside".
  - Laya's topic areas follow the topic: an unsure answer clears its
    earlier pick instead of keeping it as "picked from your topic"; short
    topics such as "Lasers" are asked about; after a hand-picked area a new
    topic offers Laya's areas ("Use these") and drops Laya's own earlier
    ones; Find asks again when Laya's pick was for an earlier topic.
  - A library with papers shows the "already has N papers" banner and the
    "Start fresh deletes N papers" warning again.
  - Closing a wait screen brings the More dock back (Group by theme hid it
    until a reload), and the wait screen's Cancel works after a cancel.
  - The 90% "Almost got it" hold ends on its own whenever Narrow it down is
    not waiting for Apply or Skip (already screened, skipped, nothing
    ready, a failed request) instead of parking the page.
  - Narrow it down and Re-prepare use only the research question typed for
    them; the fetch topic no longer stands in for it, and Re-prepare no
    longer overwrites the fetch topic.
  - One failed progress poll no longer ends the wait while the job runs.
  - Errors read as sentences ("That note is too long. Keep it to 8000
    characters or fewer.", "Too many requests in a short time…") instead
    of "[object Object]" or "Request failed".
  - "Show original abstract" opens the abstract before scrolling to it.

- Smaller Search fixes (audit 19.15): the source chips and Save your work
  load again after the first fetch, so the Sources dialog is no longer
  empty; a look that fails to save shows the old look again; Re-prepare's
  status no longer stays on "Preparing papers…"; topic area cards work
  from the keyboard (Enter or Space, with a focus outline); values inside
  HTML attributes are escaped with `escapeAttr`; one Reader panel's Escape
  listener at a time; public copy says Narrow it down, not "Quick screen".
- Looks: closed results show a star and a note mark beside the title; Save
  note says "Saving…" and then "Saved" only once the note is stored; More
  like this scrolls its "Starting from this paper" banner into view; a
  Skip made before the library list loads is kept after a reload; Catalog
  dark's accent rises from 4.21 to 4.57:1 on its tinted chips and hover;
  danger buttons in every dark look use dark text on the light red (2.35
  to 7.5:1).

- Storage and quota (audit 20.1 to 20.5):
  - Start over, a replace fetch and clearing a library now compact the
    library file, so the freed space counts against the quota again; a
    student at the cap who starts over can fetch again. The storage-limit
    message says what frees space (delete a library or Start over) instead
    of "screen out papers", which frees nothing. Start over runs off the
    request thread.
  - Each account's stored usage, behind the admin over-quota queue and
    tile, refreshes when a job ends, after Start over, and in a sweep every
    15 minutes (`LITSIEVE_STORAGE_SWEEP_SECONDS`), not only when an admin
    opens the account.
  - A share clone copies an allow-list of tables, so the owner's Reader
    explanations, a half-finished fetch's staging and a crashed swap's
    tables no longer reach the student; a failed replace swap drops its
    temporary tables.
  - `tools/backup.py --restore` writes each file to a temp copy, removes
    stale `-wal`/`-shm`/`-journal` sidecars, swaps it in and checks
    integrity before and after; a corrupt archive changes nothing.
    `tools/encrypt_databases.py` follows `USERS_DB`, strips the key like
    the app, and verifies the converted copy before replacing anything.
  - Every batch writer in the library database rolls back on error instead
    of leaving half a batch open on the shared connection; a guest whose
    files cannot be removed keeps its row so the next purge retries;
    `MAX_USER_STORAGE_MB=0.5` means half a megabyte, not unlimited.

- Jobs (audit 21.1 to 21.8, and 16.9's counts):
  - Cancelling a prepare stops it at the next batch (only fetch read the
    cancel flag before); nothing from the cancelled run is saved.
  - Start over, Load sample, Detect duplicates, Narrow it down's counts and
    cluster screening act on the library the page shows, not whichever
    library another tab made active; a library the account does not own is
    a 400.
  - A synchronous prepare claims the job slot like a background one
    instead of overriding a running prepare and then clearing it.
  - Detect duplicates takes a threshold from 0.8 to 1.0 and runs off the
    request thread; a fetch request's databases are deduplicated and an
    unknown one is a 400 with a sentence.
  - Search enrichment (study types via Laya) runs off the request thread,
    so a sleeping sidecar no longer stalls everyone's requests, and a failed
    Laya call wakes it.
  - Admin Retry prepare uses the library's stored model; Retry fetch runs
    on the library the failed fetch used.
  - A second job in another library gets "One fetch runs at a time per
    account, in any of your libraries", and a page ignores another
    library's running job instead of showing its wait screen.
  - Admin: the Tickets badge counts every open ticket, not the 25 listed;
    the job and source-error counts say they cover the time since the last
    restart.

- AI study aids (audit 22.1 to 22.6):
  - Account shows the student's own AI mode and status: the status was
    computed as the host's, and saving from that state replaced the
    student's provider.
  - Choosing an installed local model no longer writes `OLLAMA_MODEL` into
    the server's environment, which made one account's model everyone's.
  - A student's own API base URL must be https and a public address; a
    loopback, private or link-local server is refused on save and again
    before each request (`AI_ALLOW_PRIVATE_BASE_URL=true` allows a LAN
    model server). The timeout is held between 5 and 300 seconds.
  - The settings payload no longer carries the server's file path.
  - The Anthropic provider is offered only when its package is installed
    (a saved key showed the buttons and every click returned 503);
    `anthropic` and `httpx` are now in `requirements.txt`.
  - `HIDE_AI_BUTTONS` also turns Refine, Ask and Explain off (403), so a
    host key is never spent while the buttons are hidden.
- Exports (audit 22.7 to 22.10): CSV cells that start with `=`, `+`, `-`,
  `@`, a tab or a carriage return are prefixed with `'`, so a hostile title
  opens inert in a spreadsheet. The "these results" CSV fills Similarity
  with the score shown on each card and Cluster from the library's themes
  (both were blank). RIS and BibTeX write the DOI for every DOI-shaped id
  (PLOS, OpenAIRE, bioRxiv, medRxiv, not only CrossRef), leave out a
  placeholder journal such as "Unknown journal", strip HTML from the RIS
  abstract, and keep BibTeX URLs unescaped. The whole-library export is
  rate limited (10 a minute) and built off the request thread.
- Host (audit 23.4, 23.5): the version string lives only in
  `app/version.py`; FastAPI, `/health`, the admin summary, support packets
  and the footers read it. `.env.example` lists every setting the code
  reads, and a test keeps it that way.

### Removed
- DBLP is no longer offered as a source: it answers every request from the
  host with a bot check, and its records have no abstracts. Papers already
  stored from DBLP keep their link and name, and a saved fetch that lists
  DBLP simply skips it.

## [6.0.0] - 2026-10-12

### Added
- Account opens as a panel over any page, from the account link in the top
  bar or from More → Adjust look on Search. Dock it right, left, or bottom;
  the choice saves to your account and stays when you change looks. Phones
  get a bottom sheet, and each look or setting you pick repaints the page as
  you go.
- Optional Laya switches. With the local Laya sidecar running and
  `LITSIEVE_LAYA_URL` set, study-type tags the wording patterns were unsure of
  are settled by Laya when it is at least 85% sure (the tooltip says so), and
  the collect step picks the areas from the typed topic. Search ranking is
  unchanged. With Laya off, slow or unsure, everything behaves as before.
  The sidecar gives its memory (about 2 GB) back after 5 idle minutes:
  systemd starts it again on the next request, and opening Search wakes it
  ahead of the first question (`deploy/litsieve-laya.socket`).
- Two more looks join Workshop, Broadsheet, Lab, Night, and Catalog:
  Observatory, deep blue with a green signal and a year, title, and source
  register; and Reading room, quiet blue on white with a book serif and a
  wide reading column.
- Every look now lays the results out its own way: Workshop keeps its cards,
  Broadsheet sets a lead paper beside editorial columns, Lab rules results
  into a source and year table, Night is a quiet ruled list, Catalog lays out
  index cards with source tabs, Observatory keeps a register, and Reading
  room sets a wide reading column.
- Fine-tune any look on Account: results layout, text size, reading width,
  title face, abstract face, accent, spacing, corners, and edges. Changed
  settings save to your account; picking a look again starts it fresh.
- More on Search gains Adjust look: a side panel where the results change as
  you pick a look or a setting, and the changes save to your account.
- The Columns and Index cards layouts open a paper in a side reading panel
  beside the results while its place in the grid keeps a Reading
  placeholder. Click the placeholder, Close, or press Escape to put the
  paper back.
- Group by theme runs as a background job with progress, then
  opens an accessible theme browser with abstracts. Preview selected papers
  before setting them aside, with an Undo limited to those papers.
- Re-prepare keeps the research question, defaults to missing
  papers, and offers the allowed analysis models in a disclosure. Manual
  and automatic preparation share the wait screen and remembered model choice.
- What we fetched shows source/year counts and refreshable
  coverage. Duplicate checking offers Strict, Normal, and Loose previews,
  applies selected copies, and can undo exactly those copies.
- The fetch popup includes database choices and a remembered
  contact email when PubMed or Europe PMC is selected. Cancel leaves choices unchanged.
- Save your work offers visible results, all papers, kept papers,
  set-aside papers, or starred papers. Downloads stay bound to the page's library.
- Search by switches between a question, PICO fields, and a
  paper already in the collection. Saved manual seed searches and More like
  this searches restore their own behavior.
- Simple Search gains reason chips in Set aside and the Not
  relevant Undo strip, source and sort chips, starred-paper ranking, and
  exact-word/PICO ranking options. Paper identifiers and study type appear
  inside the abstract disclosure. Existing Slice 2/3 work is integrated locally.
- Set aside papers: a popup on Search (More, or the funnel's "See set-aside
  papers") that lists every paper left out of your searches, grouped by why
  (marked not relevant, set aside by Narrow it down, duplicate copies, and so
  on), with Restore per paper or per group and one click to set them aside
  again. Before this, duplicate copies and Not relevant papers could only be
  brought back from the Advanced Clusters page.
- `MAX_TOTAL_ACCOUNTS` in `.env`: a cap on real accounts for this host. Once
  reached, the register page says the host is not taking new accounts,
  existing accounts still sign in, and the demo still works. Unset or 0
  means no cap.
- Five looks on the same Simple Search shell: Workshop, Broadsheet, Lab, Night,
  and Catalog. After you create an account, Search opens a Look popup. Change
  it later in Account. The choice is stored on the account and follows login.

### Changed
- Get papers asks for the topic first. The areas that choose the databases
  sit under it: when Laya picks them they show as one line ("Searching
  Psychology databases · picked from your topic") with Change to open every
  area; a hand choice always wins. The Next button is gone. Pressing Find
  before an area is picked asks Laya first, then opens the areas.
- The Search bar stays pinned while results scroll. A strip matching the
  page behind it fills from the top of the window to just under the bar,
  with a soft blurred edge, so results soften and disappear beneath it.
- On phones the pinned Search bar is one query row and one row of modes, so
  results keep most of the screen.
- Refine, Explain, and Ask appear only when the student can get an answer:
  their own saved API key, the host's key, or a configured built-in model.
  Before, the buttons showed and then failed. The Account study-aid card
  stays visible so a key can be added, with a note when AI is off.
- Login, register, and reset forms show their own messages under a field
  ("Enter your username", "Use at least 8 characters", "The two passwords do
  not match") instead of the browser's bubble. The first empty field gets
  focus and the message clears as you type.
- Checkboxes and radio buttons are drawn in the current look instead of the
  operating system's: a box that meets 3:1 contrast, the look's accent when
  chosen, and a round-capped tick like the topic icons. High-contrast modes
  keep the system's own. Number fields lose the OS spinner arrows,
  placeholder text uses the look's soft ink, browser autofill no longer
  paints fields yellow or blue, phones no longer flash grey on tap, and the
  Explain this study glossary uses the site's "+" instead of the browser's
  triangle.
- Hover help now opens immediately in a tooltip drawn with the current look,
  instead of the browser's delayed grey or yellow preview. It works with a
  mouse or keyboard, moves below controls at the top edge, stays inside the
  window, closes with Escape, and does not appear on a phone tap. You can move
  the pointer onto a tooltip to read it without it closing, and it hides while
  its control is scrolled out of view.
- Scrollbars and dropdown lists match the look you picked. The scrollbar is
  a slim rounded thumb in the look's accent with no arrow buttons, instead
  of the browser's grey bar (Firefox keeps its own shape in the accent
  colour). In Chrome, Edge,
  and Safari 27, an open dropdown draws its list in the look's surface,
  corners, and type, marks the chosen option with a check, and keeps the
  keyboard behaviour it always had. Other browsers keep their own list.
- On desktop Simple search, Save your work now sticks just below the Search
  bar instead of sliding under it.
- The Collect help page explains the per-database paper count asked before a
  Simple fetch, and the Account help page explains that your look is saved
  on your account.
- Pressing Find articles on your topic in Simple opens one dialog first:
  how many papers from each database, as preset chips (25, 50, 100, 200)
  or a number you write yourself (10 to 2000), and, when the collection
  already has papers, whether to start fresh or add to them. The choice
  is remembered for next time.
- Phones: the Search bar is the field with a round magnifier button on one
  row and stays under the top bar while the list scrolls; the title is
  smaller with the count beside it; the tools strip fits one row; closed
  result rows show one line of meta with a thumb-sized Open; the open row's
  actions split the width in thirds; the Getting started card folds to
  "New here? Load sample papers"; the menu opens as a panel over a dimmed
  page with full-height Account and Logout rows; the Account section nav
  fades at its edge to show it scrolls; checkboxes are thumb-sized; dialog
  fields stack.
- A button that carries an icon or two mode labels keeps them through a
  loading cycle instead of collapsing to plain text.
- **Save your work stayed at the bottom of the page instead of following
  you.** On phones the export bar is pinned to the bottom of the screen and
  on wide screens the panel stays beside the results while you scroll.
  Toasts, the screening triage overlay, and its detail pane were anchored
  the same wrong way and are fixed by the same change.

### Fixed
- Night and Observatory used Workshop's dark palette when the system was set
  to dark; they now paint their own dark colours.
- Buttons show the keyboard focus ring again; a button's own pressed edge no
  longer covers it.
- Site dialogs open at their heading instead of scrolled down to their
  buttons.
- Logging out resets the look on that computer, so the next person starts
  from the default look, not the last student's.
- A new search or More like this starts at the top of the results, even when
  you asked for it from far down the old list.
- Version 6.0.0 uses one Search workspace. Collection, screening,
  themes, ranking, and export remain on Search; old page URLs permanently
  redirect there. Removed the mode toggle and preference writes, preserved
  historical helpdesk context, and added a one-time layout notice.
- Raised dependency security floors for PyJWT, urllib3, AnyIO,
  and fsspec; verified an upgraded environment with no known audit findings.
- Refine, Ask, and Explain treat paper text as evidence rather
  than instructions. Explain regenerates cached answers under the new prompt.
- Startup warns when the retired global AI settings file exists
  without host AI configuration, without reading the file or its secrets.
- Cleared the app's type-checking errors and made Pyright blocking
  in CI. A regression check now catches disagreement between the look lists.
- A timed-out source with one retained article says "1 paper".
- Fetch sources share a configurable 90-second budget across
  pages, requests, and retry waits. Completed pages survive a timeout, and
  progress identifies queued, running, completed, and timed-out sources.
- Detached deploy completion is covered by database-reopen tests
  for successful deploys and automatic rollbacks, with a host verification checklist.
- Operator rollback runs in a detached unit when available,
  carries the operator identity, and polls for completion across the site restart.
- Checkboxes and radio buttons are sized to their label's text instead of a
  fixed 20px, so they no longer dwarf small print like Show passwords
  (14px beside 12px text); touch screens keep a 20px box for thumbs. The
  Change password and Delete My Account buttons no longer touch the
  checkbox above them.
- Selected text is readable in dark mode. It was white on a light accent,
  below 2:1 in Night dark; it is now the normal text colour on a soft
  accent tint, 7:1 or better in every look.
- A press in the top edge of a button, topic card, or result action now
  registers. They dip 2px while pressed, so the release landed above them
  and the click was lost.
- Account Look showed the heading with no colour choices. The picker now
  lists the five looks in the page itself, so a running server that has
  not reloaded Python still draws the cards.
- Look is no longer a section on the register form. After Create Account,
  Search opens a dialog with the five choices. Login does not reopen it.

## [5.5.0] - 2026-09-17

### Fixed
- Light success green meets 4.5:1 contrast on the page wash.
- The phone top bar shows the full LitSieve wordmark.
- Frosted surfaces stay solid when the browser cannot blur.
- The top-bar article count stays empty until the real number loads.
- The demo banner is a single compact strip on small phones.
- A source that failed during fetch is marked as failed, not as empty.
- Detached operator deploys start in the live checkout with its `.env`, so
  the audit row writes to the live accounts database.

### Changed
- New look, Workshop: warm sand paper with a clay accent in light, warm
  wood tones in dark, and every card, button, chip, and the query tile
  sitting on a solid edge that presses down when you click. No blur
  anywhere; a faint paper grain sits over the page. Both themes keep every
  ink above 4.5:1.
- Simple search results open in place. Rows show score, venue, title, and
  byline; the top result opens by default and any row opens on click or
  with its Open button (Enter or Space), closing the one before. Star,
  Note, and Not relevant sit in one row under the open card.
- Simple collect is one guided column: three questions instead of numbered
  steps, topic areas as chips with line icons, a Next button that reveals
  the topic box and focuses it, and Max results and fetch mode kept out of
  the way. Advanced keeps its numbered steps and every control.
- Motion: results settle in with a spring, chips bounce when picked,
  starring a paper pops once, the wait screen's sieve shakes harder over a
  striped bar and each status line rises in, and the open row slides open.
  Reduced motion turns all of it off.

## [5.4.0] - 2026-09-13

### Changed
- Refreshed the look with an airy glass style: frosted cards on a light
  wash, a softer blue accent, pill buttons and nav chips with frost fill
  and hairline edges (no ink outlines), Source Serif 4 on headings, and
  denser search results. Layout and workflow are unchanged.
- On phones and tablets the top bar is one row (brand + menu). Steps,
  library, mode, and account sit in a drawer so they do not eat the page.
- Modal backdrops are transparent (no `color-mix` wash). That wash was
  the slate veil on “What would be set aside”. Ask for help is a quiet
  `--surface` pill with `--text-soft` ink.
- Saving AI settings writes `{USER_DATA_DIR}/{account id}/ai_settings.json`
  for the signed-in account. Host `.env` keys stay deploy defaults.
  Built-in Ollama start/stop is still process-wide.
- Simple Search screening counts are two bar rows: collected as the full
  set, then kept versus removed of that total, with duplicate and
  screened-out counts under the second bar. The bars refresh when you
  set papers aside.
- Simple Show me what would go opens a split-pane review: papers that
  would be set aside on the left, the selected abstract on the right.
  You can keep or mark individual papers, including ones that would have
  stayed. Nothing is excluded until you confirm.
- Simple Search result cards have **More like this**: re-rank the same
  collected library from that paper. The starting paper stays in the
  list. Nothing new is fetched.
- Simple Search is a tighter ranked list: collapsed collection note,
  sticky query plus Search, Narrow it down with Re-prepare and Start
  over under More, abstracts behind Show abstract, AI under Study aid,
  and Star / Note / Not relevant in a right-hand rail.
- Account uses a section nav (Profile, Libraries, Study aid, Recovery
  email, Password, Danger zone) beside a narrower column. Long
  explanations sit under How this works. Delete keeps the export-first
  warning.

### Fixed
- **A deleted account's password-reset link could unlock the next account
  with the same username.** Reset tokens were keyed by username, and
  deleting an account left unused tokens behind. A later account reusing
  that username could have its password reset by whoever still held the
  old link. Tokens now bind to the account id, are removed on delete, and
  only work for the account they were issued to.
- **Search could keep embeddings from a library that had just changed.**
  Loading the vector cache tagged a snapshot with the generation after
  SQLite returned, so a bump during that read looked like a cache hit.
- **A rate-limited or down literature source could look like an empty
  successful search.** Older fetchers swallowed typed HTTP failures and
  returned no papers. OpenAlex, PubMed, arXiv, Europe PMC, CrossRef,
  ClinicalTrials.gov, and NASA ADS now surface those failures.
- **Operator file reads could redact source and still report success.**
  Secret redaction ran on stdout before JSON parse, so `token = …` in a
  file became `[redacted]` and a broken payload could still be `ok` when
  the process exited 0.
- **Any signed-in student could point the host OpenAI key at a URL they
  chose.** AI keys are now stored per account under `USER_DATA_DIR`, the
  Account page no longer rewrites process env, and a student's base URL
  is used only with that student's own key. Built-in Ollama start/stop
  is admin-only.
- **Reader Mode treated two different 95% confidence intervals as the
  same number**, and dropped whether a p-value was `<` or `=`. Cached
  explanations re-check under verifier v3.
- **An operator alias such as `auditmodel=org/real-model` tried to
  download `auditmodel`.** Embedding load now uses the configured repo
  path.
- **Density clustering crashed on a library with one paper.** Tiny
  corpora now form one group instead of a server error.
- A running fetch or prepare is no longer dropped from tracking when other
  accounts fill the in-memory progress cache, so a second copy of the same job
  cannot start while the first is still working.
- Refreshing a paper's title or abstract now drops that paper's search vector
  and extractive bullets so ranking matches the text on the card. Notes, stars,
  and student-saved AI bullets stay.
- Cancelling a multi-source fetch no longer waits out the full HTTP retry
  ladder (previously up to ~2.6 minutes per unreachable source). Retries
  and backoff abort as soon as the job is cancelled; an in-flight socket
  wait of up to ~30 seconds may still finish before the cancel lands.
- Backups follow `USERS_DB` and `USER_DATA_DIR` instead of assuming
  `users.db` and `user_data/` live under the checkout. Archives still use
  those names as stable prefixes, so restore can land on a custom layout.
- Notes on Search can no longer grow after an account is over its storage
  cap, and notes longer than 8,000 characters are rejected. Clearing or
  shortening a note still works so a student can free disk.
- A Search tab that was left open no longer saves notes, stars, or
  screening into a different library after another tab switches. Fetch
  and prepare from that tab stay on the library the page loaded.
- Docker builds now use an explicit runtime-file allowlist and a
  default-deny build context so local environment files, credentials,
  and databases cannot enter new image layers.

## [5.3.1] - 2026-08-31

### Fixed
- **Reader Mode verification could not fail on three of its checks.** Found by an
  independent audit of 5.3.0 (`docs/READER_MODE_AUDIT.md`):
  - Cached explanations kept showing verdicts from an older, noisier verifier.
    The version stamp that exists to invalidate them was never bumped, so a
    warning a student saw could outlive the rule that produced it. Explanations
    regenerate the next time they are opened.
  - The negation check read the explanation's "What this study does not show"
    section, which is always phrased negatively, so it counted as preserved
    negation for free while the abstract's actual negative finding went missing.
  - The hedging check treated "about", "roughly" and "on average" as caution.
    Those describe how exact a number is, not how confident a claim is, so an
    explanation could assert a flat causal claim and still pass.
  - The number check took whichever figures came first, which are usually
    statistical diagnostics, so a study's headline result could be dropped
    without a warning. Figures stated in an abstract's conclusion are now required.

### Changed
- Dropped the entity-retention check. It skipped on 10 of 12 test abstracts and
  could only trigger in a case the storage keys already prevent, so it took a row
  in the verification report without ever saying anything useful.

## [5.3.0] - 2026-08-29

### Added
- **Explain this study** (Reader Mode): on a paper in Search or Clean up, students
  can ask for a structured plain-language reading of that abstract (high school
  or general reader). Automatic checks flag dropped numbers, lost hedging, and
  similar issues as warnings — they never claim the explanation is “verified”.
  Generated text stays visually distinct from the abstract. Hidden with
  `HIDE_AI_BUTTONS`.

## [5.2.0] - 2026-08-28

### Added
- **Sieve wait screen:** the Simple-mode fetch/prepare screen now shows an
  animated sieve - grains pour in, the pan rocks, a few fall through - with
  status lines in a panning voice ("Scooping up your first batch", "Washing out
  the repeats"). Screen scaled up for legibility.
- **Sieve brand mark:** SVG favicon and a nav wordmark mark drawn from the same
  pan. The previous favicon predated two redesigns.
- **Empty states** on Search, Clean up and Clusters now show an empty pan
  instead of text alone.

### Changed
- **Source Serif 4 for headings**, replacing Public Sans. Body and UI stay on
  Source Sans 3 - same superfamily, so the two harmonise. Self-hosted WOFF2,
  net payload change +4.6 KB.
- **Advanced mode matches Simple:** progress bars share the Simple bar's height
  and tokens; progress copy rewritten in the same voice, with counts kept as a
  secondary detail line rather than dropped.
- Copy swept across Clean up and Clusters: "screened out" is now "set aside",
  matching what Simple mode already said.

### Fixed
- Empty-state guidance told students to press "Prepare papers for search"; no
  such control exists. It now names "Re-prepare Papers" (also fixed in the
  sample-corpus toast).
- Progress bar gradient hardcoded #fff, which broke in dark mode.
- Removed a shimmer animation that ran forever against a flat colour after the
  gradient was dropped - it animated background-position with no gradient to move.

### Removed
- Public Sans (both WOFF2s and its licence), unused once headings moved to a serif.

## [5.1.0] - 2026-08-22

### Added
- **Admin student-stuck tools:** stuck fetch/prepare job queue; clear a
  dead job slot or retry prepare on that account’s current library;
  set/replace email and send verification (never auto-verifies); time-boxed
  per-account quota bump; delete one named library. Reason + timeline on
  every action.
- **Read-only student view** from a selected account (password re-auth,
  15-minute cookie, persistent banner, mutating routes blocked).
- **Service snapshot** on Admin (version, uptime, SMTP/AI/quota, job
  counts, bounded source-error counts). Retry last fetch.
- **Soft-disable / re-enable** with student-facing explanation and optional
  expiry.
- **Ask for help** tickets (safe diagnostics only) with admin status and
  replies (timeline + email if SMTP is on).
- **Incident banner** (draft / publish / expire / disable / rollback) and a
  versioned editor for support links, help text, topic-preset labels, and
  known-issue notices (plain text / JSON, no HTML).
- **Ship** (`/ops`, operator only): edit files in a staging worktree, review
  the diff, validate, commit (`remote-edit:`), deploy with health-check
  rollback, and redeploy a previous SHA. Named actions only; no shell
  interpolation. Re-auth required before save/deploy. Workbench UI; optional
  Grok Build CLI against staging (no shell tools). Unlock duration is
  configurable (5 min–8 hours) with a manual Lock. The timer pauses while
  Ask Grok is running so the console does not lock mid-run. `/ops` is a
  VS Code-like workbench (activity bar, file tabs, panel, status bar).
  Python files in the editor use Dark+/Light+ token colors.

### Changed
- **Teal Soft** visual pass: accent `#0f766e` (dark `#5eead4`) on cool paper
  `#f7f8f8` / `#ffffff`. Self-hosted Public Sans for titles; Source Sans 3
  for body/UI (wider at small sizes). Page canvas is a flat fill (no grain
  or radial wash). Primary buttons are teal-filled. Radii are 8 / 12 /
  18px. Search similarity is a ring (same
  `--score-pct` as before). Star controls use an SVG icon, not a glyph.
  Amber caution is `#96640c` (AA on white). Theme toggle uses sun/moon
  icons and a circular wipe (color fade where View Transitions are
  unavailable; off when reduced-motion is set). Hero, Simple/Advanced,
  and the eight guides stay in place.

### Fixed
- Simple Search field stays visible on phones after Narrow it down
  (no longer hidden while screening state is unknown; stacked query +
  Search on small screens).
- Feature Guide renders one theme toggle (duplicate control dropped).
- Simple Search score ring stays centered (grid overlay, not flex).
- Score number sits inside the ring hole (larger concentric meter, small
  tabular figures; 0.000–1.000 no longer clip the arc).

## [5.0.3] - 2026-08-17

### Added
- **Admin** at `/admin` (`ADMIN_USERNAMES`). Host snapshot, search one
  account, unlock,
  revoke sessions, email a password reset or one-time sign-in link, add a
  note, and download a per-student support packet. Actions are logged.
  The console never lists the full roster or sets a password.

### Changed
- Failed sign-ins lock an account after 8 tries (15 minutes). Admin
  unlock clears that.
- **Simple fetch** asks for a **topic** (not the full research question).
  The question is entered in Narrow it down, then used to search the
  collection.
- **Narrow it down** opens as a required step before Search your
  collection. Apply or skip to continue; closing the dialog does not
  skip it.
- **Simple fetch** shows a wait screen (fetch, then prepare) instead of
  the collect form. Narrow it down opens after that finishes.
- Simple collect: **Narrow your lens** (required general areas), no quick
  packs, and **Find articles on your topic** instead of Fetch Articles.

### Fixed
- Narrow it down no longer sits on a gray empty overlay. It is a page
  step (same background as the rest of Simple) until you apply or skip.
- After Narrow it down, Search keeps **Set aside N papers** + **Undo**
  in the same strip row and type as Re-prepare / Start over.
- **Guest / demo Search:** sample papers are source `sample`, which is not
  a Search checkbox. Ranking no longer requires a source chip when none
  are available. `/guest` starts preparing the sample in the background
  and Search waits on that job instead of showing an empty collect form.
- Account data paths reject `..` / slashes; admin routes only accept a
  UUID account id (CodeQL path-injection / exception leak on `/admin`).

## [5.0.1] - 2026-08-14

### Added
- Public homepage and `/learn` guides use the Phase 10 broadsheet masthead,
  boxed path/guide cards, and a dark/light toggle (no `common.js` on public
  pages).
- Simple Search asks **how many papers** (1–50) and an optional **year range**
  in a dialog before ranking. Advanced still uses the rail.

### Fixed
- **Start over** now keeps starred and noted papers and removes the rest
  immediately (`POST /api/start-over`). If those papers are already
  prepared, you stay on Search (prepare / Narrow it down are not undone).
  An empty leftover collection still opens collect so you can fetch.
- **Library switcher after idle:** rehydrates the nav library select on tab
  focus / visibility change so long idle no longer drops the active library.
- **Fetch progress stall hint:** when a source makes no progress for ~45s,
  the progress label explains that large sources can pause without hanging.

- Replace-fetch that hits the storage cap keeps the current library
  instead of swapping in a partial new collection.
- Sync and background fetches share one per-account job slot so two
  Start-over fetches cannot mix staging rows.
- Start over keeps embeddings only when title and abstract are unchanged
  (changed text is re-prepared).
- **Start over** clears the last search query/results, Show chips, and
  Narrow it down set-asides. Stars, notes, and saved AI key points stay
  on papers that come back.
- Simple result cards show **key points** and **Refine with AI** again.
- Homepage masthead: brand left, theme toggle right; LitSieve title centered
  without reusing Search’s `.pagehead`.
- **Search broadsheet layout:** Simple Search now matches the approved mockup
  composition — kicker + title + count on one line, notice as a single
  italic band, full-width one-line query + Search, results with the Save
  rail on the right. Result cards use score / journal · year / tags, then
  title and text-link actions. Segmented Get papers → Search is back in
  the Simple masthead.
- **Simple Get papers step** goes to `/search?collect=1` (collect state), not
  `/data-management`.
- **Advanced query toggle** sits with the top search bar; PICO/seed open
  under it. Rail keeps ranking options and starred search.
- Simple rail **Collected / Duplicates / Screened out / Kept** no longer
  double-count duplicates.
- Simple nav is one page again (no 1 / 2 stepper). The query bar is a
  single-line field joined to Search (no textarea spinner).
- Library (and other) `<select>` option lists use dark ink on paper so
  dark-mode cream text is not washed out until hover.
- Simple mobile nav: brand + tools on the first row, library on its own
  full-width row (no more 5rem “Parkinso” chip).
- LitSieve wordmark in the app nav links to `/` (the public homepage).
- Simple nav shows an unnumbered **Search** tab (no 1/2 stepper).
- Light/dark toggle interpolates only background-color, color, and
  border-color at 160ms (no lag from transitioning background images).

## [5.0.0] - 2026-08-13

### Changed
- **Broadsheet radii (Phase 10):** `--radius-sm` / `--radius-md` are 2px / 3px
  (was 4 / 8). Modal bottom sheets use `--radius-md` instead of an undefined
  `--radius-lg` fallback.
- **Dark theme (Phase 10):** warm newsprint charcoal (`#1c1a15` / `#242118`)
  in both the system-dark and `[data-theme=dark]` blocks.
- **Masthead nav (Phase 10):** double ink rule; desktop steps are a segmented
  control with inverted active; article count and library wrap are serif
  italic badges. Mobile menu is unchanged.
- **Search notice band (Phase 10):** “Please note” label, 4px accent spine,
  wash background, serif italic body. Query + Search are one joined boxed
  control. Result count is letterspaced caps.
- **Search result cards (Phase 10):** bordered cards with a teal spine, serif
  score numeral + 3px bar (`--score-pct` unchanged), uppercase meta, tag
  chips, and a hairline actions row.
- **Search rail (Phase 10):** boxed Simple Save panel at desktop (bottom bar
  at ≤900px unchanged). Advanced query cards boxed the same way. Simple rail
  shows Fetched / Duplicates / Screened out / Kept from the existing
  screening-report payload.

### Added
- **Guest demo** (`/guest`): temporary sample-corpus account (no multi-source
  fetch), 30-minute expiry/purge, landing/login CTA. Signed-in sessions are
  never swapped for a guest account.
- **Simple mode on two pages** (Phase 6): Get papers → Search. Inline
  screening card (Low/Medium/High with real counts, apply/undo/skip), silent
  duplicate resolve after auto-prepare, sticky Search export/report panel
  (desktop) and bottom bar (small screens). Clean up and Clusters stay in
  Advanced only.
- Skipped Simple screening remembered per library across reloads (localStorage).
- Account page uses **in-app site modals** for confirm / prompt / alert flows
  (no browser `confirm` / `prompt` / `alert`).
- Daily backups of `users.db` and `user_data/` (`tools/backup.py` +
  `litsieve-backup.timer`). Databases are copied through the SQLite online
  backup API and integrity-checked before and after archiving; archives land
  outside the repo, are pruned to `BACKUP_KEEP`, and are written `0600` because
  they contain user data and `SECRET_KEY`.
- JavaScript syntax checking in the test suite. There is no npm or build step,
  so a broken browser script previously shipped with every Python test green.
- **Search Show chips:** after a search, one-click filters on the current list
  (All, Starred, Has a note, Since last-five-years, plus a chip per source in
  the results). No new search. Export uses the filtered list.
- **Narrow it down** in Simple is a popup: Low / Medium / High, preview, set
  aside, and skip stay; the page only keeps a short button plus undo / Go to
  Search after you decide.
- **Simple Search is home** once papers are prepared: Get papers redirects to
  Search. A one-line strip on Search has Narrow it down, Re-prepare, and Start
  over (Start over opens Get papers with `?collect=1`). Empty libraries still
  open Get papers.
- **Simple is one page:** `/search` is collect (empty) or rank/export (papers).
  `/data-management` in Simple always redirects to Search (`?collect=1` opens
  start-over). Nav has no step 1/2. Topics, fetch form, and coverage hide after
  papers exist; source counts open from the papers chip.

### Changed
- **Start fresh copy (Simple):** the existing replace/add dialog now says notes,
  stars, and saved AI key points stay on papers that come back; papers that do
  not return (and their notes) are deleted. Same buttons, no extra click.
- **Advanced replace-fetch:** a live line next to the Replace radio names the
  paper / note / star / AI key-point counts when the collection is not empty.
  No new modal. Append and empty libraries hide the line.
- **Sample corpus load** now builds the demo list before clearing, so a missing
  sample set cannot wipe the library.
- **Replace-fetch is no longer wipe-first.** New papers land in a staging
  table and replace the library only if at least one paper arrived. Notes,
  stars, and saved AI key points stay on papers that come back; papers that
  do not return (and their notes) are deleted. A failed or cancelled fetch
  leaves the previous collection in place.
- **Simple fetch lock:** after this library has papers, Simple hides the Fetch
  Articles form so a second search is not the main action. A secondary
  **Start over or add papers** control reuses the existing replace/add dialog,
  then the form returns for that one fetch. Re-prepare, the source report,
  screening, and Advanced are unchanged. Guests still cannot fetch.
- **UI revamp Phase 8 (Reading Room A + Workbench B shell):** body-scale
  `.info-text` / larger `.help-text`; Search sticky query rail + results;
  numeric 0–1 score meters; summonable **Help** on Search, Data Management,
  Clean up, Clusters, and Account; Workbench shell splits **workflow steps**
  from **tools** (library / mode / theme / account) in `base.html`; dark
  graphite grounds; denser 380px chrome.
- **UI refresh (Phase 7):** design-system type / spacing / radius scales;
  editorial serif headings and abstracts with hairline card sections; live
  per-source fetch progress; list skeletons; optimistic star / note / Not
  relevant; denser 380px mobile layout; motion vocabulary with reduced-motion
  covering shimmer.
- Simple nav is **one Search page** (no step control). Clean up remains on
  `/statistics` for Advanced.
- Simple post-prepare shortcut is **Go to Search** (replaces the Phase 5
  “Next: Clean up your papers” bar once screening is applied or skipped).

### Fixed
- Simple Search bottom bar no longer covers the last result: padding tracks
  the measured bar height (`--simple-panel-h`) with a 40vh fallback; title and
  lead hide when the panel is a fixed bar.
- Guest **End demo** is a 44px secondary button on its own row (not an inline
  link next to Register) and asks before ending the session.
- Library switcher stays on the nav at ≤380px (article count hides instead).
- Site toasts stack above dialogs (`z-index` 1300 vs modal 1200).
- Mobile nav (≤640px) again exposes **Account**: the profile link was
  `display: none`, so phones could only log out. Shows a compact “Account”
  control that still opens `/account`.
- Fetch on Data Management no longer 405s: a `queueAnimationFrame` typo aborted
  page setup before the form submit handler bound, so Enter/click posted the
  HTML form to the GET-only page. Fixed to `requestAnimationFrame`; form no
  longer uses `method="post"` as a fallback.
- The Re-prepare card no longer appears while the automatic prepare is still
  running after a fetch. Progress is shown on the fetch bar during the chain.
- Source and year bar charts scale to each series max under CSP (`style-src
  'self'`) via `--bar-pct` CSS variables instead of ignored inline widths.
- Share/library panels render their spacing and the **Revoked** badge colour
  again. Five script-injected `style="…"` attributes in `account.js`, `join.js`,
  and `data_management.js` were silently dropped under CSP (`style-src 'self'`
  blocks `style-src-attr`), so join previews and the coverage hint lost their
  margins and the Revoked badge never turned red — it also referenced a
  `--danger` variable the themes do not define. Replaced with real classes
  (`.library-manage-badge.is-revoked` using `--err`, `.join-preview-lead`,
  `.u-m-0`, and the existing `.u-mt-sm`). Runtime `element.style` writes are
  unaffected by CSP and were left alone.
- All templates request the same `?v=` build of `theme-init.js` and
  `style.css`. Only `base.html` had been bumped, so returning visitors on the
  public pages (login, register, landing) kept a cached older script.
- Enter in the fetch query field starts fetch via a real form submit handler.

## [4.5.0] - 2026-08-05

### Added
- **Simple / Advanced UI mode** (client preference in `localStorage.uiMode`,
  applied pre-paint via `theme-init.js` as `data-mode`). New accounts seed
  Simple; existing accounts stay Advanced until they toggle.
- **Clean up** page (was Duplicates): duplicates, **Quick screen** (rank against
  a research question and screen out least-related papers with undo), and the
  screening report in one place.
- Per-result **Not relevant** on Search (`off_topic` exclusion).
- Auto **prepare-for-search** after a successful multi-source fetch (both modes).
- AI Refine “Save these as key points” stores `origin=ai` so rewrites survive
  re-search and append-fetch until a replace-fetch clears the library.
- Landing and `/learn/*` guides updated for the new workflow.
- Health watchdog (`tools/watchdog.py` + timer) for local app + Cloudflare
  tunnel connectivity alerts.
- Dev isolation defaults in `run_dev.sh` (`USERS_DB`, `USER_DATA_DIR`, `LOG_FILE`)
  so local work cannot touch live accounts.

### Changed
- Reading mode retired; Simple/Advanced occupies that nav control.
- Nav in Simple mode: Data Management → Clean up → Search (Clusters remains
  available by URL / Advanced).
- Mobile nav layout rebuilt so brand, steps menu, and controls fit on small
  screens.

### Fixed
- Fetch→prepare auto-chain reliability (`waitForJob` no longer resolves on a
  pre-start idle slot).
- Deploy note: new API routes (e.g. Quick screen) require a uvicorn restart.

## [4.4.0] - 2026-08-03

### Added
- CI dependency audit via `pip-audit` (**blocking**), covering known-CVE
  reporting after Dependabot's weekly auto-PRs were disabled. CI now also keeps
  `setuptools` current, since undeclared runner packages are audited too.
- Self-host deploy notes for Cloudflare Tunnel and optional Caddy
  (`docs/SELFHOST.md`, `docs/DEPLOY.md`).

### Changed
- Product name **Literature Research Aide** → **LitPilot** (UI, emails, docs,
  FastAPI title).
- Embedding models are now shared process-wide instead of loaded once per
  cached pipeline. Concurrent users no longer each pay for a copy of the
  weights: measured on CPU, 10 simultaneous PubMedBERT users dropped from
  ~4.6 GB to ~1.6 GB. Matters most for small self-hosted boxes. Registry is
  bounded by `MAX_LOADED_MODELS` (default 3).
- Startup warnings for missing `SECRET_KEY` (DEBUG) and missing FAISS now print
  plain `WARNING:` text instead of an emoji prefix.

### Security
- `cryptography` floor raised to `>=50.0.0` for CVE-2026-69247 (caught by the
  new pip-audit gate on its first real run).
- Embedding model names in `POST /api/create-embeddings` are now validated
  against the model catalog (HTTP 422 otherwise). Previously an unknown name
  was passed through as a HuggingFace path, so any signed-in user could make
  the server download arbitrary models. Operators can still allow extras via
  `EXTRA_EMBEDDING_MODELS`.
- IPv6 rate limiting keys on the /64 prefix instead of the full address. A
  client is normally handed an entire /64, so per-address keying let anyone
  bypass the login limiter by rotating addresses. IPv4 is unchanged.

### Removed
- Unused `pandas` dependency (declared in `requirements.txt`, imported nowhere).
  Slightly smaller installs; no behaviour change.

### Fixed
- Site no longer stalls for everyone while someone signs in or registers.
  Password hashing (~157 ms) ran on the single event loop, so a burst of
  signups froze all other requests — reported by a user as the site "hanging".
  Measured: 6 concurrent signups took 942 ms and a bystander's page load went
  from 1.6 ms to 933 ms; now 172 ms and 1.3 ms. Hash cost is unchanged.
- `/favicon.ico` and `/robots.txt` are served instead of returning 404.

## [4.3.2] - 2026-08-01

### Added
- Governance files: `agents.md`, `spec.md`, `roadmap.md`, tracked `context.md`,
  and this `CHANGELOG.md`.
- Live `.github/` from former templates: CodeQL workflow, pyright in CI
  (report-only until backlog cleared), markdownlint (non-blocking).
- Optional verified recovery email (username separate from email; SMTP-gated)
  — PR #38; human-confirmed with MailerSend SMTP.
- `tools/send_test_email.py` SMTP smoke CLI (PR #49).
- Host deploy checklist: `docs/DEPLOY.md` (SECRET_KEY, DEBUG, SMTP, quota,
  SQLCipher, smoke commands); README links to it.

### Changed
- Dependabot weekly auto-PRs disabled (removed `.github/dependabot.yml`).
- Expanded screening tests; purged unused pipeline/clustering/embedding/HTTP
  helpers; share create bounds single-sourced from `app.storage.shares`.

### Fixed
- Article PICO / similarity labels no longer lift or scale on hover — PR #36.

## [4.3.1] - 2026-07-26

### Fixed
- Search abstract layout (full width) and whole-word query highlighting.
- Starred papers included in “more like my starred” results.

## [4.3.0] - 2026-07-26

### Added
- Per-account storage quota (`MAX_USER_STORAGE_MB`, default 500; `0` = off).
- AES-256-GCM encryption for AI API keys at rest (`enc:v2:`).
- Docker CI smoke job (`/health` and landing).

### Changed
- Python 3.14 for CI, Docker, and Render.
- Passwords via bcrypt directly (passlib removed).
- FastAPI lifespan for UMAP warm-up (replaces deprecated `on_event`).

### Fixed
- Quota mid-fetch status is `quota_stopped` (not user cancel).
- `clear_first` fetch/sample allowed when over quota to recover space.
