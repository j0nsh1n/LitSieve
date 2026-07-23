"""
Single source of truth for public academic sources.

- Student tips: what each database is good for / what it misses
- Topic → recommended sources (coverage map + Data Management grid)
- HS unit packs
- Duplicate-resolution priority

Fetcher wiring stays in pipeline.FETCHERS; URL builders stay in citations.py /
common.js getArticleUrl. When adding a source: update this file, FETCHERS,
citations.SOURCE_URL, and common.js getArticleUrl together.

Further sources: only free public APIs with usable abstracts for students.
Do not add campus/paywalled DBs. Propose candidates to the maintainer first.
"""

from __future__ import annotations

from typing import Any, Dict, List

# id → display + classroom tip fields.
# priority: higher wins near-duplicate ties after abstract length.
SOURCE_CATALOG: Dict[str, Dict[str, Any]] = {
    "pubmed": {
        "name": "PubMed",
        "desc": "Biomedical & life sciences",
        "good_for": "Health, medicine, and life-science papers with abstracts.",
        "misses": "Little humanities/CS; some clinical trials better on ClinicalTrials.gov.",
        "tip": "Strong for health/biology abstracts. Not a full hospital library.",
        "badges": [],
        "priority": 100,
        "needs_key": False,
    },
    "europepmc": {
        "name": "Europe PMC",
        "desc": "European biomedical literature",
        "good_for": "Biomedical papers, often overlapping PubMed with EU open-access links.",
        "misses": "Not strong outside life sciences; may duplicate PubMed hits.",
        "tip": "Biomedical like PubMed; good second health source. Expect some overlap.",
        "badges": [],
        "priority": 90,
        "needs_key": False,
    },
    "clinicaltrials": {
        "name": "ClinicalTrials.gov",
        "desc": "Clinical trial registrations",
        "good_for": "Registered trials (status, design). Useful for “is there a trial?” questions.",
        "misses": "Not peer-reviewed journal articles; results text is uneven.",
        "tip": "Trial registries, not finished papers. Great for health methods context.",
        "badges": [],
        "priority": 85,
        "needs_key": False,
    },
    "crossref": {
        "name": "CrossRef",
        "desc": "Broad academic metadata registry",
        "good_for": "Wide subject coverage via DOIs; solid metadata for many journals.",
        "misses": "Abstracts sometimes missing (those records are skipped here).",
        "tip": "Huge DOI registry. Skips items with no abstract.",
        "badges": [],
        "priority": 80,
        "needs_key": False,
    },
    "openalex": {
        "name": "OpenAlex",
        "desc": "Broad multi-discipline academic",
        "good_for": "Almost any school subject; free and broad open scholarly graph.",
        "misses": "Quality varies; not a substitute for your school library databases.",
        "tip": "Best all-round free starter for mixed classroom topics.",
        "badges": [],
        "priority": 75,
        "needs_key": False,
    },
    "semanticscholar": {
        "name": "Semantic Scholar",
        "desc": "AI-curated cross-discipline research",
        "good_for": "Cross-field papers with decent abstracts; good CS/science mix.",
        "misses": "Rate limits under load; not every journal is covered equally.",
        "tip": "Strong free cross-discipline search. Pair with OpenAlex for breadth.",
        "badges": [],
        "priority": 70,
        "needs_key": False,
    },
    "plos": {
        "name": "PLOS",
        "desc": "Fully open-access science journals",
        "good_for": "Peer-reviewed OA science (biology, medicine, environment).",
        "misses": "Only PLOS journals — not a whole-field index.",
        "tip": "Open-access science journals students can usually read in full.",
        "badges": [],
        "priority": 68,
        "needs_key": False,
    },
    "doaj": {
        "name": "DOAJ",
        "desc": "Peer-reviewed open access journals",
        "good_for": "Open-access journals across many subjects.",
        "misses": "Only OA journals listed in DOAJ; smaller than OpenAlex.",
        "tip": "Peer-reviewed open access. Good “readable without paywall” filter.",
        "badges": [],
        "priority": 65,
        "needs_key": False,
    },
    "arxiv": {
        "name": "arXiv",
        "desc": "Physics, math, CS, econ preprints",
        "good_for": "Preprints in physics, math, CS, quant finance/econ.",
        "misses": "Not always peer-reviewed; little humanities/education.",
        "tip": "Preprints (not always peer-reviewed yet). Strong STEM early research.",
        "badges": ["preprint"],
        "priority": 60,
        "needs_key": False,
    },
    "dblp": {
        "name": "DBLP",
        "desc": "Computer science papers & conferences",
        "good_for": "CS titles, authors, venues (conferences and journals).",
        "misses": "Many hits have no real abstract — those are skipped, so counts look low.",
        "tip": "CS bibliography (title/venue). Many records lack abstracts and are skipped.",
        "badges": ["title-only"],
        "priority": 58,
        "needs_key": False,
    },
    "eric": {
        "name": "ERIC",
        "desc": "Education, psychology, social sciences",
        "good_for": "Education research, teaching practice, school policy.",
        "misses": "Not a medical or hard-science index.",
        "tip": "Best free education database for classroom and pedagogy topics.",
        "badges": [],
        "priority": 55,
        "needs_key": False,
    },
    "openaire": {
        "name": "OpenAIRE",
        "desc": "European open research aggregator",
        "good_for": "EU open research graph; multi-discipline OA records.",
        "misses": "Metadata quality varies; some stubs lack abstracts.",
        "tip": "European open research aggregator. Good extra breadth for EU work.",
        "badges": [],
        "priority": 52,
        "needs_key": False,
    },
    "core": {
        "name": "CORE",
        "desc": "Open-access full text, all disciplines",
        "good_for": "Open-access full text across subjects (when key is set).",
        "misses": "Needs a free CORE API key; without it this source skips.",
        "tip": "OA full text (free API key required). Skips if CORE_API_KEY is unset.",
        "badges": [],
        "priority": 50,
        "needs_key": True,
        "key_env": "CORE_API_KEY",
    },
    "hal": {
        "name": "HAL",
        "desc": "French national open archive (multi-discipline)",
        "good_for": "French open archive; multi-discipline, often OA.",
        "misses": "French-heavy; English abstracts not always present.",
        "tip": "French open archive. Useful extra OA; language mix varies.",
        "badges": [],
        "priority": 48,
        "needs_key": False,
    },
    "zenodo": {
        "name": "Zenodo",
        "desc": "Open science: all fields + datasets",
        "good_for": "Open deposits: papers, posters, datasets, software.",
        "misses": "Not all peer-reviewed; mixes papers with data packages.",
        "tip": "Open science deposits (papers + data). Check item type when screening.",
        "badges": [],
        "priority": 45,
        "needs_key": False,
    },
    "nasa_ads": {
        "name": "NASA ADS",
        "desc": "Astronomy, astrophysics & geosciences",
        "good_for": "Astronomy, astrophysics, planetary and some geoscience.",
        "misses": "Needs free NASA_ADS_TOKEN; little outside space/earth science.",
        "tip": "Space & geoscience (free token required). Skips if NASA_ADS_TOKEN is unset.",
        "badges": [],
        "priority": 40,
        "needs_key": True,
        "key_env": "NASA_ADS_TOKEN",
    },
    "biorxiv": {
        "name": "bioRxiv",
        "desc": "Biology preprints",
        "good_for": "Very recent biology preprints.",
        "misses": "Not peer-reviewed; only a recent rolling date window is searched.",
        "tip": "Biology preprints — not peer-reviewed; recent posts only.",
        "badges": ["preprint", "not-peer-reviewed"],
        "priority": 35,
        "needs_key": False,
    },
    "medrxiv": {
        "name": "medRxiv",
        "desc": "Health preprints",
        "good_for": "Very recent clinical/health preprints.",
        "misses": "Not peer-reviewed; recent window only; not medical advice.",
        "tip": "Health preprints — not peer-reviewed; recent posts only. Not advice.",
        "badges": ["preprint", "not-peer-reviewed"],
        "priority": 34,
        "needs_key": False,
    },
}

# Topic id → sources recommended for fetch grid + coverage checks.
# Order is preference for “missing source” suggestions (first = higher priority).
TOPIC_SOURCE_HINTS: Dict[str, List[str]] = {
    "health": [
        "pubmed", "europepmc", "clinicaltrials", "medrxiv", "plos",
        "openalex", "semanticscholar", "doaj", "zenodo", "core",
    ],
    "biology": [
        "pubmed", "europepmc", "biorxiv", "plos", "openalex", "arxiv",
        "semanticscholar", "crossref", "zenodo", "doaj", "core",
    ],
    "chemistry": [
        "openalex", "arxiv", "semanticscholar", "crossref", "zenodo",
        "doaj", "core", "openaire",
    ],
    "physics": [
        "arxiv", "openalex", "semanticscholar", "crossref", "zenodo",
        "nasa_ads", "core", "openaire",
    ],
    "math": [
        "arxiv", "openalex", "semanticscholar", "crossref", "zenodo",
        "core", "openaire",
    ],
    "cs": [
        "dblp", "arxiv", "openalex", "semanticscholar", "crossref",
        "zenodo", "doaj", "core", "openaire",
    ],
    "earth": [
        "openalex", "semanticscholar", "zenodo", "crossref", "doaj",
        "nasa_ads", "core", "openaire", "hal",
    ],
    "history": [
        "openalex", "semanticscholar", "eric", "crossref", "doaj",
        "core", "hal", "openaire",
    ],
    "economics": [
        "arxiv", "openalex", "semanticscholar", "eric", "crossref",
        "doaj", "core", "openaire",
    ],
    "psychology": [
        "pubmed", "openalex", "semanticscholar", "eric", "crossref",
        "doaj", "core", "openaire",
    ],
    "polisci": [
        "openalex", "semanticscholar", "eric", "crossref", "doaj",
        "core", "hal", "openaire",
    ],
    "literature": [
        "openalex", "semanticscholar", "eric", "crossref", "doaj",
        "core", "hal", "openaire",
    ],
    "education": [
        "eric", "openalex", "semanticscholar", "crossref", "doaj",
        "core", "hal", "openaire",
    ],
}

TOPIC_META: Dict[str, Dict[str, str]] = {
    "health": {"name": "Health & Medicine", "icon": "🏥"},
    "biology": {"name": "Biology", "icon": "🧬"},
    "chemistry": {"name": "Chemistry", "icon": "⚗️"},
    "physics": {"name": "Physics", "icon": "⚛️"},
    "math": {"name": "Mathematics", "icon": "📐"},
    "cs": {"name": "Computer Science", "icon": "💻"},
    "earth": {"name": "Earth & Environment", "icon": "🌍"},
    "history": {"name": "History", "icon": "📜"},
    "economics": {"name": "Economics", "icon": "📊"},
    "psychology": {"name": "Psychology", "icon": "🧠"},
    "polisci": {"name": "Political Science", "icon": "🏛️"},
    "literature": {"name": "Literature & Language", "icon": "📖"},
    "education": {"name": "Education", "icon": "🎓"},
}

TOPIC_PACKS: List[Dict[str, Any]] = [
    {
        "id": "pack_climate",
        "name": "Climate unit",
        "icon": "🌡️",
        "blurb": "Earth & environment sources for climate projects",
        "topics": ["earth"],
        "sources": [
            "openalex", "semanticscholar", "nasa_ads", "zenodo",
            "crossref", "doaj", "core", "openaire",
        ],
        "query_hint": "climate change impacts on ecosystems",
    },
    {
        "id": "pack_health_ed",
        "name": "Health education",
        "icon": "❤️",
        "blurb": "Health + classroom education databases",
        "topics": ["health", "education"],
        "sources": [
            "pubmed", "europepmc", "eric", "openalex",
            "semanticscholar", "plos", "doaj", "core",
        ],
        "query_hint": "school-based health education programs",
    },
    {
        "id": "pack_history",
        "name": "History unit",
        "icon": "📜",
        "blurb": "History and social-science open sources",
        "topics": ["history"],
        "sources": [
            "openalex", "semanticscholar", "eric", "crossref",
            "doaj", "hal", "core", "openaire",
        ],
        "query_hint": "civil rights movement oral history",
    },
    {
        "id": "pack_cs_intro",
        "name": "CS intro",
        "icon": "💻",
        "blurb": "CS bibliography + arXiv (many DBLP hits lack abstracts)",
        "topics": ["cs"],
        "sources": [
            "dblp", "arxiv", "openalex", "semanticscholar",
            "crossref", "doaj", "core",
        ],
        "query_hint": "introductory computer science education",
    },
]

# Derived: higher priority first for stable maps.
SOURCE_PRIORITY: Dict[str, int] = {
    sid: int(meta.get("priority") or 0) for sid, meta in SOURCE_CATALOG.items()
}


def source_display_name(source_id: str) -> str:
    meta = SOURCE_CATALOG.get(source_id or "")
    if meta:
        return str(meta.get("name") or source_id)
    if source_id == "sample":
        return "Sample demo"
    return source_id or ""


def student_tip(source_id: str) -> str:
    meta = SOURCE_CATALOG.get(source_id or "") or {}
    tip = (meta.get("tip") or "").strip()
    if tip:
        return tip
    good = (meta.get("good_for") or "").strip()
    misses = (meta.get("misses") or "").strip()
    parts = [p for p in (good, f"Misses: {misses}" if misses else "") if p]
    return " ".join(parts)


def list_sources_for_api() -> List[Dict[str, Any]]:
    """Stable list for Data Management / Search UI."""
    # Sort by display name for grids; priority available for dupes elsewhere.
    items = []
    for sid, meta in SOURCE_CATALOG.items():
        items.append({
            "id": sid,
            "name": meta.get("name") or sid,
            "desc": meta.get("desc") or "",
            "tip": student_tip(sid),
            "good_for": meta.get("good_for") or "",
            "misses": meta.get("misses") or "",
            "badges": list(meta.get("badges") or []),
            "priority": int(meta.get("priority") or 0),
            "needs_key": bool(meta.get("needs_key")),
            "key_env": meta.get("key_env") or None,
        })
    items.sort(key=lambda x: (x["name"] or "").lower())
    return items


def list_topics_for_api() -> List[Dict[str, Any]]:
    topics = []
    for tid, sources in TOPIC_SOURCE_HINTS.items():
        meta = TOPIC_META.get(tid) or {}
        topics.append({
            "id": tid,
            "name": meta.get("name") or tid,
            "icon": meta.get("icon") or "",
            "sources": list(sources),
        })
    # Keep a classroom-friendly order (matches historical UI).
    order = list(TOPIC_META.keys())
    topics.sort(key=lambda t: order.index(t["id"]) if t["id"] in order else 99)
    return topics


def public_catalog() -> Dict[str, Any]:
    """Payload for GET /api/sources."""
    return {
        "sources": list_sources_for_api(),
        "topics": list_topics_for_api(),
        "packs": [
            {
                "id": p["id"],
                "name": p["name"],
                "icon": p["icon"],
                "blurb": p.get("blurb") or "",
                "topics": list(p.get("topics") or []),
                "sources": list(p.get("sources") or []),
                "queryHint": p.get("query_hint") or "",
            }
            for p in TOPIC_PACKS
        ],
        "count": len(SOURCE_CATALOG),
        "note": (
            "All sources are free public APIs. Prefer abstracts students can read. "
            "Campus/paywalled databases are out of scope. Propose new sources to the maintainer."
        ),
    }


def coverage_reason(source_id: str) -> str:
    """Short reason line for missing-source coverage suggestions."""
    tip = student_tip(source_id)
    if tip:
        return tip
    return "Usually useful for your selected topic(s), but you have no articles from it yet."
