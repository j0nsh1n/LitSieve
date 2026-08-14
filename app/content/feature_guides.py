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
            "On Search (Simple collect) or Data Management (Advanced), choose "
            "academic topics (e.g. Education, Health). Recommended databases "
            "light up based on those topics.",
            "In Simple mode the source grid is hidden but still auto-checks "
            "recommended databases; Advanced lets you tick sources by hand.",
            "Type a normal research query (the kind you would type into a library site).",
            "Set max results per source and choose Replace (start fresh) or Add "
            "(keep what you already have).",
            "Fetch runs sources in parallel in the background; when papers arrive, "
            "prepare-for-search (embeddings) starts automatically so you do not "
            "need a second click.",
            "You get a ✓/✗ report per database when the fetch finishes. Papers "
            "without an abstract are skipped - later steps need text to work with.",
            "In Advanced, the coverage map shows papers per source and which "
            "recommended sources are still empty.",
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
        "where_in_app": "Search collect (Simple) · Data Management → topics, "
        "sources (Advanced), fetch (prepare runs after fetch).",
        "app_path": "/data-management",
        "app_label": "Open Data Management",
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
            "science → specter, otherwise general). Advanced can override under "
            "preparation options.",
            "Add-to-collection prefers only new papers; Replace re-prepares the "
            "whole set so dimensions stay consistent.",
            "If you switch models in Advanced, everything is re-embedded so all "
            "vectors stay compatible with each other.",
            "Embedding runs in the background with a progress bar - safe to leave "
            "the page open while a large batch finishes.",
            "When available, work runs on your GPU (including ROCm on supported "
            "Linux setups); otherwise it uses the CPU.",
            "Optional Re-prepare on Data Management is only needed if prepare "
            "failed or you changed the model by hand.",
        ],
        "tips": [
            "Wait for prepare to finish before Search or Clean up (nav shows ready "
            "counts).",
            "Stick to one model for a project so results stay consistent.",
            "Large collections take longer the first time; “only new papers” on "
            "Add makes later fetches cheap.",
        ],
        "where_in_app": "Automatic after fetch on Search (Simple) or Data "
        "Management (Advanced); optional Re-prepare.",
        "app_path": "/data-management",
        "app_label": "Open Data Management",
    },
    "clustering-triage": {
        "slug": "clustering-triage",
        "title": "Clustering & triage",
        "icon": "🧩",
        "tagline": "Group papers by theme (Advanced), or Quick screen on Clean up.",
        "summary": (
            "You can screen papers two ways. Simple mode uses Narrow it down on "
            "Search (the same idea as Quick screen: rank against your research "
            "question and drop least-related papers, with undo). Advanced keeps "
            "the Clusters page: group papers by theme with embeddings, then exclude "
            "off-topic piles. Clean up still has Quick screen. Search only ranks "
            "what you kept. Cluster labels are best when they read like real topics; "
            "if they look weak, prefer Quick screen."
        ),
        "how_it_works": [
            "Simple path: after prepare, use Narrow it down on Search. Enter your "
            "research question, pick how many least-related papers to set aside, "
            "and confirm (or preview first). Undo once if needed.",
            "Advanced path: open Clusters after embeddings exist (prepare runs after "
            "fetch on Data Management).",
            "Density mode (recommended) finds natural topic groups and puts odd "
            "papers in an “outliers” bucket. K-Means and Hierarchical need a count "
            "(or Auto).",
            "Open a cluster to read its topic overview and paper list. Exclude "
            "cluster screens out every paper in that group from Search.",
            "Each paper also has Exclude / Restore; nothing is permanently deleted.",
            "Search also has per-paper Not relevant (off-topic) for catch-all "
            "exclusions.",
            "Exclusion reasons (low relevance, cluster, duplicate, off topic, …) "
            "show on the Clean up screening report for hand-ins.",
        ],
        "tips": [
            "Students in Simple: Narrow it down on Search, then rank; use Not "
            "relevant on stragglers. Advanced: Quick screen on Clean up or Clusters.",
            "Teachers: ask for the Clean up screening report plus a short note on "
            "what was excluded and why.",
            "Clusters stays in Advanced nav; Simple hides it but /clusters still "
            "works if bookmarked.",
            "Re-clustering refreshes groups but keeps your exclusion list.",
        ],
        "where_in_app": "Search → Narrow it down (Simple) · Clean up → Quick "
        "screen · Clusters (Advanced group triage) · Search → Not relevant.",
        "app_path": "/statistics",
        "app_label": "Open Clean up",
    },
    "duplicate-resolution": {
        "slug": "duplicate-resolution",
        "title": "Clean up (duplicates & report)",
        "icon": "🔄",
        "tagline": "Duplicates, Quick screen, and the hand-in report.",
        "summary": (
            "The Clean up page (nav label: Clean up, Advanced) is where you finish "
            "the collection before Search: remove near-duplicate copies across "
            "databases, optionally Quick-screen least-related papers, and download a "
            "screening report (collected / excluded / included counts) for hand-ins. "
            "Simple shows collected / dups / screened-out / kept on the Search rail."
        ),
        "how_it_works": [
            "Open Clean up after papers are prepared (auto after fetch).",
            "Remove duplicates: set match strictness (Advanced; Simple hides the "
            "slider and uses the default). Detect Duplicates, then Auto-Resolve or "
            "Keep this per group.",
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
            "Run Clean up after a multi-source fetch and before writing - cuts "
            "double-counting in bibliographies.",
            "If Auto-Resolve feels aggressive, raise the threshold (Advanced) or "
            "resolve groups manually.",
            "Teachers: ask students to attach the screening report text with a "
            "short reflection on what they excluded.",
        ],
        "where_in_app": "Clean up page (duplicates + Quick screen + screening "
        "report). Simple: Search rail counts plus Narrow it down.",
        "app_path": "/statistics",
        "app_label": "Open Clean up",
    },
    "similarity-search": {
        "slug": "similarity-search",
        "title": "Similarity search",
        "icon": "🎯",
        "tagline": "Rank by meaning, words, years - or like your stars.",
        "summary": (
            "Describe your study in plain language or PICO fields. The app embeds "
            "your description, ranks closest papers by meaning, and (by default) "
            "slightly boosts papers that also share your exact words. Advanced can "
            "filter by source, start from a seed paper, or use more ranking options. "
            "This searches only your fetched library, not the whole web."
        ),
        "how_it_works": [
            "Simple: Text or PICO, then Search. Use More like my starred after "
            "bookmarking papers. Seed paper and advanced ranking options stay in "
            "Advanced mode.",
            "Optional (Advanced): source filter, Prefer PICO matches, Prefer exact "
            "words (hybrid), seed paper mode.",
            "Hybrid ranking blends embedding similarity with TF-IDF word overlap "
            "so rare terms in your query still surface.",
            "Results show key points, a collapsible abstract, and PICO snippets "
            "when detected. Use Not relevant to screen out one paper as off-topic.",
            "Star papers and add private notes for your study log. Saved AI key "
            "points (Refine → Save) stay on that paper until you replace the "
            "library.",
            "Export the ranked list as RIS for Zotero. Advanced can also export a "
            "whole-library scope (all / included / screened out / starred).",
            "Process counts for hand-ins live on Clean up as the screening report "
            "— not on Search.",
        ],
        "tips": [
            "Search only ranks papers already in your collection (from public "
            "databases you fetched). It is not Google Scholar and not a full library "
            "search. Use it to prioritise candidates, then verify in original sources.",
            "Each result may show a study Type tag (plain-language guess from title "
            "and abstract - often wrong when confidence is low). It is not an evidence "
            "grade.",
            "Screen with Clean up (Quick screen / duplicates) first so the ranking "
            "pool is clean.",
            "Advanced: Seed mode is great when a teacher gives one starter paper.",
            "Star a handful of must-read papers, then use More like my starred to "
            "expand the set without rewriting the query.",
            "Need a real bibliography? Export RIS of the search results from Search, then "
            "Zotero → File → Import… (not drag-and-drop) → Create Bibliography. "
            "Need process counts? Clean up → Screening report (.txt).",
        ],
        "where_in_app": "Search page (Simple or Advanced).",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "private-workspace": {
        "slug": "private-workspace",
        "title": "Private workspace",
        "icon": "🔒",
        "tagline": "Your papers, notes, and Simple/Advanced layout - only your account.",
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
            "a bcrypt hash, never plain text. New accounts open in Simple mode "
            "(fewer controls); existing accounts keep Advanced until you toggle.",
            "Optionally add an email on Account for password recovery. It only "
            "counts once you click the link we send, and it is used for "
            "recovery alone.",
            "Log in to reach Search (Simple home: collect + rank). Advanced shows "
            "Data Management, Clusters, Clean up, and Search in the nav "
            "(Simple can still open those pages by URL).",
            "Use the Library switcher in the nav (or Account) to create and "
            "switch collections. Fetch, prepare, and search only touch "
            "the active library.",
            "Simple / Advanced is a browser preference (like light/dark theme) "
            "on this device — it does not delete data.",
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
            "Theme (light/dark) and Simple/Advanced stay in your browser "
            "on this device.",
        ],
        "tips": [
            "Shared computers: log out when finished; do not reuse simple passwords.",
            "Keep one library per project or topic so papers do not mix.",
            "For process counts, use Clean up → Screening report. Search keeps ranking "
            "and library RIS export. Notes/stars stay private process evidence, not grades.",
            "Export a library as RIS (Search) and/or a screening report (Clean up) "
            "before deleting it if you need an archive.",
            "If you change your password on a shared machine, other open tabs "
            "for that account will need to log in again.",
        ],
        "where_in_app": "Register / Log in · Simple/Advanced toggle · Library switcher · Account.",
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
            "Use this app to collect candidates (fetch + auto-prepare), screen on "
            "Clean up (duplicates and/or Quick screen), rank on Search, and export "
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
        "where_in_app": "Landing /learn/citation-quality · use while screening on Clean up "
        "or Clusters (Advanced).",
        "app_path": "/statistics",
        "app_label": "Open Clean up",
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
