"""
Public “learn more” pages for each landing-page feature card.
Content is written for teachers and students in plain language.
"""

from __future__ import annotations

from typing import Dict, List, Optional, TypedDict


class FeatureGuide(TypedDict):
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
            "On Data Management, choose academic topics (e.g. Education, Health). "
            "Recommended databases light up based on those topics.",
            "Type a normal research query (the kind you would type into a library site).",
            "Set max results per source and choose Replace (start fresh) or Add "
            "(keep what you already have).",
            "Fetch runs sources in parallel in the background so you can leave the "
            "tab open; you get a ✓/✗ report per database when it finishes.",
            "Papers without an abstract are skipped - later steps (search, clusters) "
            "need text to work with.",
            "The coverage map shows how many papers you have per source and which "
            "recommended sources are still empty.",
        ],
        "tips": [
            "Teachers: assign a topic pack (e.g. “use ERIC + OpenAlex”) so every "
            "student’s corpus is comparable.",
            "Students: start broad, then re-fetch with Add to deepen a sub-topic "
            "without wiping your first batch.",
            "Some sources need free API keys (CORE, NASA ADS). Without a key they "
            "simply skip - the others still run.",
            "If a fetch is already running, wait for it to finish before starting "
            "another (the app will say so).",
        ],
        "where_in_app": "Data Management → steps 1-3 (Topics, Sources, Fetch).",
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
            "After you fetch papers, open Create Embeddings on Data Management.",
            "Pick a model: general (fast, mixed topics), pubmedbert / biosentbert "
            "(medical), or specter (scientific papers).",
            "By default only new papers are embedded - already-processed ones are "
            "skipped so re-runs stay fast. (Replace mode turns that off so a full "
            "re-embed is easy to request.)",
            "If you switch models, everything is re-embedded so all vectors stay "
            "compatible with each other.",
            "Embedding runs in the background with a progress bar - safe to leave "
            "the page open while a large batch finishes.",
            "When available, work runs on your GPU (including ROCm on supported "
            "Linux setups); otherwise it uses the CPU.",
            "You see how many papers still need vectors, which model was used, "
            "device, and how long the run took.",
        ],
        "tips": [
            "Always embed after a fetch before using Search, Clusters, or Duplicates.",
            "Stick to one model for a project so results stay consistent.",
            "Large collections take longer the first time; “only new papers” makes "
            "later fetches cheap.",
        ],
        "where_in_app": "Data Management → step 4 (Create Embeddings).",
        "app_path": "/data-management",
        "app_label": "Open Data Management",
    },
    "clustering-triage": {
        "slug": "clustering-triage",
        "title": "Clustering & triage",
        "icon": "🧩",
        "tagline": "Group papers by theme, then screen out the noise.",
        "summary": (
            "Clustering sorts your collection into topic piles using the embeddings. "
            "Each pile gets a distinctive keyword label and a real paper title as a "
            "headline, plus a short topic overview. This is the only place for topic "
            "triage: exclude whole off-topic groups (or single papers) so Search, "
            "hybrid ranking, and more-like-starred only see what you kept."
        ),
        "how_it_works": [
            "Open Clusters after embeddings exist (create them on Data Management; "
            "that job can finish in the background).",
            "Density mode (recommended) finds natural topic groups and puts odd "
            "papers in an “outliers” bucket. K-Means and Hierarchical need a count "
            "(or Auto).",
            "Open a cluster to read its topic overview (year span + example titles) "
            "and the paper list.",
            "Exclude cluster screens out every paper in that group from Search. "
            "Each paper also has its own Exclude / Restore toggle.",
            "Nothing is permanently deleted - Restore brings papers back anytime.",
            "Labels are built so the same keyword is not repeated across every "
            "cluster (they stay distinctive).",
            "Exclusion reasons show up later on the Duplicates screening report "
            "(cluster vs duplicate vs manual counts for hand-ins).",
        ],
        "tips": [
            "Students: exclude clearly off-topic piles before similarity search so "
            "rankings stay on assignment.",
            "Teachers: ask for a short note on which clusters were excluded and why, "
            "plus the screening report text from Duplicates.",
            "Re-clustering refreshes groups but keeps your exclusion list.",
        ],
        "where_in_app": "Clusters page (only place for topic/paper triage).",
        "app_path": "/clusters",
        "app_label": "Open Clusters",
    },
    "duplicate-resolution": {
        "slug": "duplicate-resolution",
        "title": "Duplicate resolution",
        "icon": "🔄",
        "tagline": "Same paper, many databases - keep the best copy.",
        "summary": (
            "The same study often appears in PubMed, Europe PMC, OpenAlex, and more "
            "under different ids. Near-duplicate detection finds those pairs by "
            "embedding similarity. You can compare them side by side, keep one by "
            "hand, or auto-resolve groups. The same page can also build a "
            "screening report (collected / excluded / included counts) for hand-ins."
        ),
        "how_it_works": [
            "Open the Duplicates page (nav label: Duplicates).",
            "Set a similarity threshold (higher = only near-identical pairs).",
            "Detect Duplicates lists pairs; expand a group to compare fields "
            "(title, abstract, year, etc.).",
            "Auto-Resolve All keeps the most complete abstract; if lengths are "
            "similar it prefers trusted sources (PubMed first, then Europe PMC, "
            "ClinicalTrials, CrossRef, OpenAlex, and so on).",
            "Losers are screened out (hidden from Search), not deleted. You can "
            "restore them from Clusters if needed.",
            "Use per-group “Keep this” when you want to choose the winner yourself.",
            "Screening report shows how many papers you collected, removed as "
            "duplicates, excluded by cluster triage, excluded manually, and kept "
            "in the final set - downloadable as plain text.",
        ],
        "tips": [
            "Run duplicates after a multi-source fetch and before writing - cuts "
            "double-counting in bibliographies.",
            "If Auto-Resolve feels aggressive, raise the threshold or resolve "
            "groups manually.",
            "Teachers: ask students to attach the screening report text with a "
            "short reflection on what they excluded.",
        ],
        "where_in_app": "Duplicates page (statistics + detection + screening report).",
        "app_path": "/statistics",
        "app_label": "Open Duplicates",
    },
    "similarity-search": {
        "slug": "similarity-search",
        "title": "Similarity search",
        "icon": "🎯",
        "tagline": "Rank by meaning, words, years - or like your stars.",
        "summary": (
            "Describe your study in plain language or PICO fields. The app embeds "
            "your description, ranks closest papers by meaning, and (by default) "
            "slightly boosts papers that also share your exact words. You can "
            "filter by year, start from a seed paper, or find more papers like "
            "everything you have starred. This searches only your fetched library, "
            "not the whole web."
        ),
        "how_it_works": [
            "Choose Text, PICO (Population / Intervention / Comparison / Outcome), "
            "or Seed paper. Or click More like my starred after bookmarking papers.",
            "Optional filters: sources, from/to year (unknown years hide when a "
            "range is set), Prefer PICO matches, Prefer exact words (hybrid ranking).",
            "Hybrid ranking blends embedding similarity with TF-IDF word overlap "
            "so rare terms in your query still surface.",
            "Results show a similarity score (0-1), highlighted query words in "
            "abstracts, and PICO snippets when detected.",
            "Star papers and add private notes for your study log.",
            "Export this ranked list (CSV/TXT) or export the whole library as "
            "CSV, RIS (Zotero/EndNote), or BibTeX - by scope (all / included / "
            "excluded / starred).",
            "For APA/MLA/Chicago hand-formatting, use the ZoteroBib link on "
            "titles or DOIs so style rules stay under your control.",
        ],
        "tips": [
            "Screen off-topic clusters first so the ranking pool is clean.",
            "Seed mode is great when a teacher gives one starter paper: find more "
            "like it from what you already fetched.",
            "Star a handful of must-read papers, then use More like my starred to "
            "expand the set without rewriting the query.",
            "Need a bibliography file? Export RIS or BibTeX from Search, not just "
            "the ranked CSV.",
        ],
        "where_in_app": "Search page.",
        "app_path": "/search",
        "app_label": "Open Search",
    },
    "private-workspace": {
        "slug": "private-workspace",
        "title": "Private workspace",
        "icon": "🔒",
        "tagline": "Your papers, embeddings, notes - only your account.",
        "summary": (
            "Every account is private on the server. Within an account you can "
            "keep several named libraries (for example one per class unit). "
            "Fetched articles, embeddings, clusters, screening choices, stars, "
            "and notes stay inside the active library and never mix with other "
            "users. Sessions use signed tokens; changing your password signs out "
            "other devices while keeping this one signed in. Long fetches and "
            "embedding runs continue in the background so closing a laptop "
            "mid-job is less painful."
        ),
        "how_it_works": [
            "Register with a username or school email-style login and a password "
            "(stored as a bcrypt hash, not plain text).",
            "Log in to reach Data Management, Clusters, Search, and Duplicates.",
            "Use the Library switcher in the nav (or Account) to create and "
            "switch collections. Fetch, prepare, cluster, and search only touch "
            "the active library.",
            "All API actions require your session; state-changing actions also "
            "check a CSRF token. Each signed-in user has their own rate limit "
            "bucket (classrooms behind one network do not share one budget).",
            "Stars and notes attach to papers inside the active library only.",
            "Account page: manage libraries, change password (revokes other "
            "sessions), or delete your account with password confirmation.",
            "Teachers can Share a library to create a short class code. Students "
            "Join with the code and receive their own copy (papers + screening + "
            "optional embeddings) — not live write access to the teacher.",
            "Fetch and embedding jobs return immediately and finish in the "
            "background on the library that was active when they started; "
            "the progress bar follows until they complete.",
            "Theme (light/dark) and reading mode preferences stay in your browser "
            "on this device.",
        ],
        "tips": [
            "School lab computers: log out when finished; do not reuse simple "
            "passwords.",
            "Teachers: keep one library per unit or class so papers do not mix; "
            "share a finished unit library via class code so everyone starts equal.",
            "Export a library (CSV/RIS/BibTeX) before deleting it if you need a "
            "hand-in archive.",
            "If you change your password on a shared machine, other open tabs "
            "for that account will need to log in again.",
        ],
        "where_in_app": "Register / Log in · Library switcher · Account · /join.",
        "app_path": "/account",
        "app_label": "Open Account",
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
