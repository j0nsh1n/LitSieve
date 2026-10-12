"""
Public “learn more” pages for each landing-page feature card.
Content is written for students in plain language (research starting point).
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class ChecklistBlock(TypedDict):
    title: str
    intro: str
    # Named "checks" (not "items") so Jinja does not hit dict.items().
    checks: List[str]


class FeatureGuide(TypedDict, total=False):
    slug: str
    title: str
    icon: str  # HTML entity or emoji
    tagline: str
    summary: str
    how_it_works: List[str]
    tips: List[str]
    where_in_app: str
    app_path: str  # path for CTA when logged in
    app_label: str
    # Optional R7 checklists (citation quality, weak appraisal, etc.)
    checklists: List[ChecklistBlock]


FEATURE_GUIDES: Dict[str, FeatureGuide] = {
    "multi-source-search": {
        "slug": "multi-source-search",
        "title": "Multi-source search",
        "icon": "🔍",
        "tagline": "One query, many databases - in parallel.",
        "summary": (
            "Instead of opening PubMed, Google Scholar, ERIC, and arXiv one by one, "
            "you pick the databases that fit your topic and run a single query. The app "
            "asks every selected source at the same time and saves titles, abstracts, "
            "authors, years, and journals into your private collection."
        ),
        "how_it_works": [
            "On Search, enter a topic for the database query. Save your full "
            "research question for Narrow it down and Search.",
            "Below the topic, the areas (e.g. Education, Health) decide which "
            "databases are recommended. When the host runs the optional Laya model, "
            "it picks the areas from your topic and shows them as one line; press "
            "Change to see every area and pick your own. Without Laya you pick them "
            "yourself.",
            "Review the source choices in the Databases disclosure and select "
            "which databases to search.",
            "Choose the result limit for each database and whether to start fresh "
            "or add results to the active library.",
            "Fetch runs sources in parallel in the background; when papers arrive, "
            "prepare-for-search (embeddings) starts automatically so you do not "
            "need a second click. Search shows one wait screen for fetch and prepare, "
            "then offers Narrow it down.",
            "You get a ✓/✗ report per database when the fetch finishes. Papers "
            "without an abstract are skipped - later steps need text to work with.",
            "The coverage map shows papers per source and which recommended "
            "sources are still empty.",
        ],
        "tips": [
            "Starting point only: publicly accessible research databases you select. "
            "Paywalled or unindexed work will not appear. Not a complete library search. "
            "Finish important work with your school library and teacher’s required sources.",
            "Teachers: assign a topic pack (e.g. “use ERIC + OpenAlex”) so every "
            "student’s corpus is comparable.",
            "Students: start broad, then re-fetch with Add to deepen a sub-topic "
            "without wiping your first batch (saved AI key points on old papers stay).",
            "Some sources need free API keys (NASA ADS). Without a key they "
            "simply skip - the others still run.",
            "If a fetch is already running, wait for it to finish before starting "
            "another (the app will say so).",
        ],
        "where_in_app": "Search → topics, database choices, and fetch.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "semantic-embeddings": {
        "slug": "semantic-embeddings",
        "title": "Semantic embeddings",
        "icon": "🧠",
        "tagline": "Turn every abstract into a “meaning fingerprint.”",
        "summary": (
            "An embedding is a list of numbers that represents what a paper is about - "
            "not just which words it used. Similar ideas land near each other in that "
            "space, even if the wording differs. Search, clustering, and duplicate "
            "detection all depend on these fingerprints."
        ),
        "how_it_works": [
            "After a successful fetch, prepare-for-search starts automatically "
            "(same progress flow as “getting your papers ready”).",
            "The model is chosen from your topics (biomedical → pubmedbert, hard "
            "science → specter, otherwise general). Choose another model in the "
            "Re-prepare controls when needed.",
            "Add-to-collection prefers only new papers; Replace re-prepares the "
            "whole set so dimensions stay consistent.",
            "If you switch models, everything is re-embedded so all "
            "vectors stay compatible with each other.",
            "Embedding runs in the background with a progress bar. Search uses the "
            "same wait screen for fetching and preparing; a large batch can finish "
            "in the background.",
            "When available, work runs on your GPU (including ROCm on supported "
            "Linux setups); otherwise it uses the CPU.",
            "Optional Re-prepare on Search is only needed if prepare "
            "failed or you changed the model by hand.",
        ],
        "tips": [
            "Wait for prepare to finish before searching (nav shows ready "
            "counts).",
            "Stick to one model for a project so results stay consistent.",
            "Large collections take longer the first time; “only new papers” on "
            "Add makes later fetches cheap.",
        ],
        "where_in_app": "Automatic after fetch on Search; optional Re-prepare.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "clustering-triage": {
        "slug": "clustering-triage",
        "title": "Clustering & triage",
        "icon": "🧩",
        "tagline": "Screen papers and group them by theme.",
        "summary": (
            "Search includes several optional screening tools. Narrow it down "
            "ranks papers against your research question and can set aside the "
            "least-related papers with undo. Group by theme uses embeddings to "
            "organize papers; review a group before excluding it. Search ranks the "
            "papers you keep. Cluster labels are best when they read like real "
            "topics; if they look weak, prefer Quick screen."
        ),
        "how_it_works": [
            "After prepare, Narrow it down can help focus the collection. Enter your "
            "research question, choose how many least-related papers to set aside, "
            "and confirm (or preview first). Skip if you want everything. Undo once "
            "from the Search strip if needed.",
            "Group by theme is available after papers have embeddings (prepare runs "
            "automatically after a successful fetch).",
            "Density mode (recommended) finds natural topic groups and puts odd "
            "papers in an “outliers” bucket. K-Means and Hierarchical need a count "
            "(or Auto).",
            "Open a cluster to read its topic overview and paper list. Exclude "
            "cluster screens out every paper in that group from Search.",
            "Each paper also has Exclude / Restore; nothing is permanently deleted.",
            "Search also has per-paper Not relevant (off-topic) for catch-all "
            "exclusions.",
            "Exclusion reasons (low relevance, cluster, duplicate, off topic, …) "
            "appear in the screening report for hand-ins.",
        ],
        "tips": [
            "Use Narrow it down to focus the set, then mark individual stragglers Not "
            "relevant or open Group by theme for broader patterns.",
            "Teachers: ask for the screening report plus a short note on "
            "what was excluded and why.",
            "Re-clustering refreshes groups but keeps your exclusion list.",
        ],
        "where_in_app": "Search → Narrow it down, Quick screen, Group by theme, and Not relevant.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "duplicate-resolution": {
        "slug": "duplicate-resolution",
        "title": "Duplicate checks & report",
        "icon": "🔄",
        "tagline": "Duplicates, Quick screen, and the hand-in report.",
        "summary": (
            "Search includes tools to finish a collection: remove near-duplicate "
            "copies across databases, optionally Quick-screen least-related papers, "
            "and download a screening report (collected / excluded / included "
            "counts) for hand-ins."
        ),
        "how_it_works": [
            "Open the screening and duplicate tools in Search after papers are prepared.",
            "Remove duplicates: choose match strictness, detect duplicates, then "
            "Auto-Resolve or Keep this per group.",
            "Auto-Resolve keeps the most complete abstract; if lengths are similar "
            "it prefers trusted sources (PubMed first, then Europe PMC, and so on).",
            "Losers are screened out (hidden from Search), not deleted.",
            "Quick screen: rank against your research question and screen out the "
            "least related set (primary button), or Preview first; Undo once.",
            "Screening report shows collected, duplicates removed, exclusions by "
            "reason (including low relevance and cluster triage), and included set "
            "— downloadable as plain text.",
        ],
        "tips": [
            "Run duplicate checks after a multi-source fetch and before writing; this "
            "cuts double-counting in bibliographies.",
            "If Auto-Resolve feels aggressive, raise the threshold or resolve groups manually.",
            "Teachers: ask students to attach the screening report text with a "
            "short reflection on what they excluded.",
        ],
        "where_in_app": "Search → duplicate checks, Quick screen, and screening report.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "similarity-search": {
        "slug": "similarity-search",
        "title": "Similarity search",
        "icon": "🎯",
        "tagline": "Rank by meaning, words, years - or like your stars.",
        "summary": (
            "Describe your study in plain language or PICO fields. The app embeds "
            "your description, ranks closest papers by meaning, and (by default) "
            "slightly boosts papers that also share your exact words. You can also "
            "filter by source, start from a seed paper, or adjust ranking options. "
            "This searches only your fetched library, not the whole web."
        ),
        "how_it_works": [
            "Enter your question as text or PICO and Search. Use More like my starred "
            "after bookmarking papers. Seed paper and ranking options are also "
            "available in Search.",
            "Optional controls include source filters, Prefer PICO matches, Prefer exact "
            "words (hybrid ranking), and seed paper mode.",
            "Hybrid ranking blends embedding similarity with TF-IDF word overlap "
            "so rare terms in your query still surface.",
            "Results show key points, a collapsible abstract, and PICO snippets "
            "when detected. Use Not relevant to screen out one paper. Why? on that line "
            "records a reason such as wrong population, "
            "wrong study type, language, or too little information.",
            "Star papers and add private notes for your study log. Saved AI key "
            "points (Refine → Save) stay on that paper until you replace the "
            "library.",
            "Export the ranked list or choose a whole-library scope (all / included / "
            "screened out / starred) as RIS for Zotero.",
            "Process counts for hand-ins are available in the Search screening report.",
        ],
        "tips": [
            "Study-type tags (trial, review, survey...) are guesses from the wording "
            "of the title and abstract. When those patterns are unsure and the host "
            "runs the optional Laya model, Laya picks the tag, but only when it is at "
            "least 85% sure; hover the tag to see which one tagged it.",
            "Search only ranks papers already in your collection (from public "
            "databases you fetched). It is not Google Scholar and not a full library "
            "search. Use it to prioritise candidates, then verify in original sources.",
            "Each result may show a study Type tag (plain-language guess from title "
            "and abstract - often wrong when confidence is low). It is not an evidence "
            "grade.",
            "Narrow it down or run Quick screen before ranking if you want a smaller set.",
            "Seed mode is useful when a teacher gives you a starter paper.",
            "Star a handful of must-read papers, then use More like my starred to "
            "expand the set without rewriting the query.",
            "Need a real bibliography? Export RIS of the search results from Search, then "
            "Zotero → File → Import… (not drag-and-drop) → Create Bibliography. "
            "Need process counts? Search → Screening report (.txt).",
        ],
        "where_in_app": "Search page.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "private-workspace": {
        "slug": "private-workspace",
        "title": "Private workspace",
        "icon": "🔒",
        "tagline": "Your papers and notes stay private to your account.",
        "summary": (
            "Every account is private on the server. Within an account you can "
            "keep several named libraries (for example one per project or topic). "
            "Fetched articles, embeddings, clusters, screening choices, stars, "
            "and notes stay inside the active library and never mix with other "
            "users. Sessions use signed tokens; changing your password signs out "
            "other devices while keeping this one signed in. Long fetches and "
            "prepare jobs continue in the background so closing a laptop "
            "mid-job is less painful."
        ),
        "how_it_works": [
            "Register with a username (not an email) and a password, stored as "
            "a bcrypt hash, never plain text. Every account opens the same Search "
            "workspace.",
            "Optionally add an email on Account for password recovery. It only "
            "counts once you click the link we send, and it is used for "
            "recovery alone.",
            "Log in to reach Search, where you can collect, screen, rank, and export "
            "papers from one workspace.",
            "Use the Library switcher in the nav (or Account) to create and "
            "switch collections. Fetch, prepare, and search only touch "
            "the active library.",
            "Your look and light/dark setting affect appearance; they do not change "
            "your collection or available tools.",
            "All API actions require your session; state-changing actions also "
            "check a CSRF token. Each signed-in user has their own rate limit "
            "bucket.",
            "Stars and notes attach to papers inside the active library only.",
            "Account page: manage libraries, change password (revokes other "
            "sessions), or delete your account with password confirmation.",
            "Optional: someone can create a short library copy code. Joining "
            "adds a new library that is a full clone (papers + screening + "
            "optional embeddings) — not live access to theirs.",
            "Fetch and prepare jobs return immediately and finish in the "
            "background on the library that was active when they started; "
            "the progress bar follows until they complete.",
            "Light/dark appearance stays in your browser on this device.",
            "Your look (Workshop, Broadsheet, Lab, Night, or Catalog) is saved on "
            "your account, so it comes with you when you log in on another device. "
            "New accounts are offered the choice after signing up; change it any "
            "time on the Account page.",
        ],
        "tips": [
            "Shared computers: log out when finished; do not reuse simple passwords.",
            "Keep one library per project or topic so papers do not mix.",
            "For process counts, use the Search screening report. Search keeps ranking "
            "and library RIS export. Notes/stars stay private process evidence, not grades.",
            "Export a library as RIS and/or a screening report from Search "
            "before deleting it if you need an archive.",
            "If you change your password on a shared machine, other open tabs "
            "for that account will need to log in again.",
        ],
        "where_in_app": "Register / Log in · Library switcher · Account.",
        "app_path": "/account",
        "app_label": "Open Account",
    },
    "finish-your-research": {
        "slug": "finish-your-research",
        "title": "Finish your research",
        "icon": "📚",
        "tagline": "This app is a starting point — here is how to finish well.",
        "summary": (
            "LitSieve only queries free public research APIs. "
            "That is great for gathering candidates and practising screening, but it "
            "is not a complete literature search and not a college library. After you "
            "export RIS and a screening report, plan a short path to stronger sources "
            "with people and tools that do have broader access."
        ),
        "how_it_works": [
            "Use this app to collect candidates (fetch + auto-prepare), screen in "
            "Search (duplicates and/or Quick screen), and export "
            "RIS plus a screening report.",
            "Write down what you still need (for example: a peer-reviewed review, "
            "a local newspaper archive, or a book chapter your teacher assigned).",
            "Search your school library catalogue and any databases your school "
            "subscribes to (often available only on campus or via a school login).",
            "Use Google Scholar to find citation trails and PDF links — but verify "
            "the version (preprint vs published) and access rights.",
            "Ask a librarian or teacher when something important is paywalled or "
            "missing. Bring your shortlist and your screening notes.",
            "Check author, year, venue, and abstract again before you cite. Prefer "
            "peer-reviewed sources over preprints when the assignment expects them.",
        ],
        "tips": [
            "Do not pretend this tool covers Web of Science, JSTOR, EBSCO, or other "
            "campus packages — those need institutional access we do not provide.",
            "Teachers: grade process (screening report, notes, source mix) as well as "
            "final citations so students are not punished for honest public-DB limits.",
            "If a paper is central to your claim, get the full text through legal "
            "channels (library, OA link, author site) — never scrape paywalls.",
            "See also: Citation quality guide for peer-reviewed vs preprint vs website.",
        ],
        "where_in_app": "Landing /learn/finish-your-research · after Search export.",
        "app_path": "/search",
        "app_label": "Open Search",
        "checklists": [
            {
                "title": "Hand-off checklist (after this app)",
                "intro": (
                    "Use this when you leave the public-database starting point and "
                    "finish with school tools."
                ),
                "checks": [
                    "I exported RIS and/or a screening report for what I kept.",
                    "I searched the school library catalogue or databases for gaps.",
                    "I used Google Scholar for citation trails and verified access rights.",
                    "I asked a librarian or teacher about paywalled or missing sources.",
                    "I know this app does not replace campus packages (JSTOR, EBSCO, "
                    "Web of Science, SSO proxy full-text).",
                ],
            },
        ],
    },
    "citation-quality": {
        "slug": "citation-quality",
        "title": "Citation quality checklist",
        "icon": "✅",
        "tagline": "Manual signals only — not an evidence grade.",
        "summary": (
            "A short checklist to help students judge whether a candidate is a "
            "peer-reviewed paper, a preprint, or a weaker web source. This is a "
            "thinking aid for class, not clinical A–D grading and not a substitute "
            "for reading the full work."
        ),
        "how_it_works": [
            "Identify the source type: journal article, preprint server (arXiv, "
            "bioRxiv, medRxiv), conference paper, report, or website.",
            "Peer-reviewed journals usually name a journal, volume/issue, and often "
            "a DOI. Preprints say preprint or list a server and may not be final.",
            "Check year, authors, and venue. Unknown year or missing abstract is a "
            "yellow flag for classroom use (this app already skips abstract-less rows).",
            "Use the weak appraisal signals below only as reading questions — never "
            "as automatic grades or clinical evidence levels.",
            "Match the assignment: some units want peer-reviewed only; others allow "
            "preprints with clear labeling. Your teacher’s rubric wins.",
            "Export RIS into Zotero (or similar) and fix author/title details before "
            "the final bibliography. APA text generators outside this app are drafts.",
        ],
        "tips": [
            "Study-type tags in Search are rough guesses from title+abstract — never "
            "use them as clinical evidence levels or auto-excludes.",
            "Preprints can be useful early research but are not peer-reviewed yet.",
            "Websites and news pieces may help context; they are not the same as "
            "journal research for most science/social-science hand-ins.",
            "Out of scope for this product: campus proxy full-text, Web of Science, "
            "JSTOR/EBSCO packages, SSO into university systems.",
        ],
        "where_in_app": "Landing /learn/citation-quality · use alongside Search.",
        "app_path": "/search",
        "app_label": "Open Search",
        "checklists": [
            {
                "title": "Citation quality (manual)",
                "intro": (
                    "Judge each candidate before you cite it. Teacher rubric wins "
                    "over any default here."
                ),
                "checks": [
                    "Peer-reviewed journal or scholarly book chapter? (Usually stronger "
                    "than a blog, news site, or commercial page.)",
                    "Preprint (bioRxiv, medRxiv, arXiv, etc.)? Label it as a preprint; "
                    "find a peer-reviewed version if required.",
                    "Authors and year clear? Prefer named researchers or institutions "
                    "over anonymous posts.",
                    "Can you open the abstract (or full text via school access) and "
                    "confirm the claim matches what you wrote?",
                    "DOI or stable library link when available — better than a "
                    "fragile homepage URL.",
                    "Does the source match the assignment (topic, date range, "
                    "discipline)?",
                    "Website / government / NGO pages: fine for background if you say "
                    "what kind of source it is — do not pretend it is a journal trial.",
                ],
            },
            {
                "title": "Weak appraisal signals (not evidence grades)",
                "intro": (
                    "Optional questions while you read an abstract. Weak signals only "
                    "— not clinical A–D grades, not CASP certification, and not a "
                    "reason to auto-exclude papers in the app."
                ),
                "checks": [
                    "What question did the authors try to answer? (Restate in one line.)",
                    "Who or what was studied (people, animals, cells, documents, models)?",
                    "Is this primarily a review, a trial/experiment, a survey, or "
                    "an opinion piece? (Study-type tags in Search are approximate.)",
                    "Do results sound measured (samples, comparisons) or only claimed?",
                    "Do the authors mention limitations or uncertainty?",
                    "Could funding, conflicts, or venue bias matter for this claim?",
                    "Would you still trust this claim if the abstract were the only "
                    "text you had? If not, get full text via the library first.",
                ],
            },
        ],
    },
}

# Stable order matching the landing page grid.
FEATURE_ORDER: List[str] = [
    "multi-source-search",
    "semantic-embeddings",
    "clustering-triage",
    "duplicate-resolution",
    "similarity-search",
    "private-workspace",
    "finish-your-research",
    "citation-quality",
]


def get_guide(slug: str) -> Optional[FeatureGuide]:
    return FEATURE_GUIDES.get(slug)


def list_guides() -> List[FeatureGuide]:
    return [FEATURE_GUIDES[s] for s in FEATURE_ORDER if s in FEATURE_GUIDES]


def neighbors(slug: str) -> tuple[Optional[FeatureGuide], Optional[FeatureGuide]]:
    """Previous / next guide in landing order."""
    if slug not in FEATURE_ORDER:
        return None, None
    i = FEATURE_ORDER.index(slug)
    prev_g = FEATURE_GUIDES[FEATURE_ORDER[i - 1]] if i > 0 else None
    next_g = FEATURE_GUIDES[FEATURE_ORDER[i + 1]] if i + 1 < len(FEATURE_ORDER) else None
    return prev_g, next_g
