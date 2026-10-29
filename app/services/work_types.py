"""Canonical work types, DOI/biblio helpers, and trimmed provider records."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

WORK_TYPES = (
    "journal-article",
    "review-article",
    "book-review",
    "book",
    "edited-book",
    "book-chapter",
    "reference-entry",
    "conference-paper",
    "dissertation",
    "report",
    "preprint",
    "dataset",
    "registry-record",
    "other",
)

# Sentinel for NULL / empty / unknown rows in the Search type filter.
WORK_TYPE_NOT_STORED = "not-stored"

WORK_TYPE_CHIP_LABELS = {
    "journal-article": "Article",
    "review-article": "Review article",
    "book-review": "Book review",
    "book": "Book",
    "edited-book": "Book",
    "book-chapter": "Chapter",
    "reference-entry": "Reference entry",
    "dissertation": "Thesis",
    "report": "Report",
    "preprint": "Preprint",
    "conference-paper": "Conference paper",
    "registry-record": "Trial registration",
    "dataset": "Dataset",
}

WORK_TYPE_FILTER_LABELS = {
    **WORK_TYPE_CHIP_LABELS,
    "other": "Other",
    WORK_TYPE_NOT_STORED: "Type not stored",
}

ALLOWED_WORK_TYPE_FILTERS = frozenset(WORK_TYPES) | {WORK_TYPE_NOT_STORED}

# Narrow it down: books/chapters with no abstract stay in; reviews and trial
# registrations can be set aside only if the student ticks that box.
NARROW_KEEP_NO_ABSTRACT_TYPES = frozenset({"book", "edited-book", "book-chapter"})
NARROW_OPTIONAL_ASIDE_TYPES = frozenset({"book-review", "registry-record"})

# provider -> raw type -> canonical. Unknown or absent raw values map to unknown.
TYPE_MAP: Dict[str, Dict[str, str]] = {
    "openalex": {
        "article": "journal-article",
        "review": "review-article",
        "book-review": "book-review",
        "book": "book",
        "edited-book": "edited-book",
        "book-chapter": "book-chapter",
        "reference-entry": "reference-entry",
        "conference-paper": "conference-paper",
        "proceedings-article": "conference-paper",
        "conference": "conference-paper",
        "dissertation": "dissertation",
        "thesis": "dissertation",
        "report": "report",
        "preprint": "preprint",
        "dataset": "dataset",
        "other": "other",
    },
    "crossref": {
        "journal-article": "journal-article",
        "book-review": "book-review",
        "book": "book",
        "monograph": "book",
        "reference-book": "book",
        "edited-book": "edited-book",
        "book-chapter": "book-chapter",
        "book-part": "book-chapter",
        "book-section": "book-chapter",
        "reference-entry": "reference-entry",
        "proceedings-article": "conference-paper",
        "dissertation": "dissertation",
        "report": "report",
        "posted-content": "preprint",
        "dataset": "dataset",
        "other": "other",
    },
    "doaj": {
        "journal-article": "journal-article",
        "article": "journal-article",
    },
    "eric": {
        "journal articles": "journal-article",
        "reports - research": "report",
        "reports - evaluative": "report",
        "reports - descriptive": "report",
        "reports - general": "report",
        "books": "book",
        "collected works - general": "book",
        "speeches/meeting papers": "conference-paper",
        "dissertations/theses": "dissertation",
        "dissertations/theses - doctoral dissertations": "dissertation",
        "dissertations/theses - masters theses": "dissertation",
        "information analyses": "review-article",
        "numerical/quantitative data": "dataset",
        "tests/questionnaires": "other",
        "guides - classroom": "other",
        "opinion papers": "other",
    },
    "pubmed": {
        "journal article": "journal-article",
        "review": "review-article",
        "systematic review": "review-article",
        "meta-analysis": "review-article",
        "book": "book",
        "book chapter": "book-chapter",
        "case reports": "other",
        "editorial": "other",
        "letter": "other",
        "comment": "other",
        "dataset": "dataset",
        "preprint": "preprint",
        "clinical trial": "journal-article",
        "randomized controlled trial": "journal-article",
        "congress": "conference-paper",
        "published erratum": "other",
        "news": "other",
    },
    "europepmc": {
        "journal article": "journal-article",
        "research-article": "journal-article",
        "review": "review-article",
        "review-article": "review-article",
        "systematic-review": "review-article",
        "meta-analysis": "review-article",
        "book review": "book-review",
        "book-review": "book-review",
        "preprint": "preprint",
        "letter": "other",
        "editorial": "other",
        "case-report": "other",
        "dataset": "dataset",
        "book": "book",
        "chapter": "book-chapter",
        "conference-paper": "conference-paper",
        "other": "other",
    },
    "semanticscholar": {
        "journalarticle": "journal-article",
        "review": "review-article",
        "conference": "conference-paper",
        "casereport": "other",
        "clinicaltrial": "journal-article",
        "dataset": "dataset",
        "editorial": "other",
        "lettersandcomments": "other",
        "metaanalysis": "review-article",
        "news": "other",
        "study": "journal-article",
        "book": "book",
        "booksection": "book-chapter",
    },
    "hal": {
        "art": "journal-article",
        "comm": "conference-paper",
        "couv": "book-chapter",
        "ouv": "book",
        "these": "dissertation",
        "report": "report",
        "hdr": "dissertation",
        "proceedings": "conference-paper",
        "mem": "dissertation",
        "lecture": "other",
        "undefined": "other",
        "other": "other",
        "poster": "other",
        "patent": "other",
        "issue": "other",
        "blog": "other",
        "notice": "other",
        "img": "other",
        "video": "other",
        "software": "other",
    },
    "openaire": {
        "part of book or chapter of book": "book-chapter",
        "article": "journal-article",
        "journal article": "journal-article",
        "contribution to journal": "journal-article",
        "other literature type": "other",
        "thesis": "dissertation",
        "doctoral thesis": "dissertation",
        "bachelor thesis": "dissertation",
        "master thesis": "dissertation",
        "preprint": "preprint",
        "book": "book",
        "report": "report",
        "conference object": "conference-paper",
        "conference proceedings article": "conference-paper",
        "dataset": "dataset",
        "publication": "other",
    },
    "zenodo": {
        "article": "journal-article",
        "preprint": "preprint",
        "report": "report",
        "book": "book",
        "section": "book-chapter",
        "conferencepaper": "conference-paper",
        "thesis": "dissertation",
        "workingpaper": "report",
        "deliverable": "report",
        "patent": "other",
        "other": "other",
        "dataset": "dataset",
        "publication": "other",
    },
    "arxiv": {
        "preprint": "preprint",
    },
    "plos": {
        "journal-article": "journal-article",
        "article": "journal-article",
        "research article": "journal-article",
        "review": "review-article",
    },
    "clinicaltrials": {
        "registry-record": "registry-record",
    },
    "nasa_ads": {
        "article": "journal-article",
        "eprint": "preprint",
        "inproceedings": "conference-paper",
        "inbook": "book-chapter",
        "book": "book",
        "phdthesis": "dissertation",
        "mastersthesis": "dissertation",
        "techreport": "report",
        "review": "review-article",
        "catalog": "other",
        "circular": "other",
        "proposal": "other",
        "software": "other",
        "dataset": "dataset",
        "misc": "other",
        "proceedings": "conference-paper",
        "abstract": "other",
    },
    "biorxiv": {
        "preprint": "preprint",
    },
    "medrxiv": {
        "preprint": "preprint",
    },
}

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)
# Registrant prefix 10.NNNN plus a non-empty suffix; reject whitespace.
_DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")

_BIBLIO_KEYS = (
    "publisher",
    "volume",
    "issue",
    "pages",
    "isbn",
    "editors",
    "published_date",
    "license",
    "parent_book_id",
)


# First match wins when a record carries several mapped types.
TYPE_PREFERENCE = (
    "review-article",
    "book-review",
    "book-chapter",
    "reference-entry",
    "edited-book",
    "dissertation",
    "conference-paper",
    "dataset",
    "registry-record",
    "journal-article",
    "book",
    "preprint",
    "report",
    "other",
)


def as_list(value: Any) -> List[Any]:
    """One-item list for a scalar or mapping; flatten a sequence."""
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray, dict)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _raw_type_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, Mapping):
        for key in ("@classname", "classname", "name", "$", "text"):
            text = _text(raw.get(key))
            if text:
                return text
        return ""
    return str(raw).strip()


def stored_work_type_is_missing(stored: Any) -> bool:
    """True for NULL, blank, and unknown — no chip, and 'Type not stored'."""
    text = str(stored or "").strip()
    return not text or text == "unknown"


def work_type_chip_label(stored: Any) -> Optional[str]:
    """Plain chip words for a stored type; None when the card should hide it."""
    if stored_work_type_is_missing(stored):
        return None
    return WORK_TYPE_CHIP_LABELS.get(str(stored).strip())


def work_type_count_key(stored: Any) -> str:
    """Group missing types under the filter sentinel for library counts."""
    if stored_work_type_is_missing(stored):
        return WORK_TYPE_NOT_STORED
    return str(stored).strip()


def work_type_matches_filter(stored: Any, wanted: Iterable[str]) -> bool:
    wanted_set = set(wanted)
    if stored_work_type_is_missing(stored):
        return WORK_TYPE_NOT_STORED in wanted_set
    return str(stored).strip() in wanted_set


def parse_work_type_filter(values: Optional[Iterable[str]]) -> Optional[List[str]]:
    """None/empty means no type filter. Unknown names raise ValueError."""
    if not values:
        return None
    out: List[str] = []
    seen = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        if text not in ALLOWED_WORK_TYPE_FILTERS:
            raise ValueError(text)
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out or None


def canonical_work_type(provider: str, raw_type: Any) -> str:
    """Map a provider's type string onto the stored vocabulary, or unknown."""
    raw = _raw_type_text(raw_type).lower()
    if not raw:
        return "unknown"
    table = TYPE_MAP.get((provider or "").strip().lower(), {})
    return table.get(raw, "unknown")


def pick_canonical_work_type(provider: str, raw_types: Any) -> str:
    """Most specific mapped type from a provider's type list."""
    mapped = [canonical_work_type(provider, raw) for raw in as_list(raw_types)]
    known = [item for item in mapped if item != "unknown"]
    if not known:
        return "unknown"
    rank = {name: index for index, name in enumerate(TYPE_PREFERENCE)}
    return min(known, key=lambda item: rank.get(item, len(rank)))


def provider_type_label(provider: str, raw_type: Any) -> Optional[str]:
    """Keep the raw type tagged with its source, e.g. openalex:book-chapter."""
    raw = _raw_type_text(raw_type)
    if not raw:
        return None
    name = (provider or "").strip().lower()
    return f"{name}:{raw}" if name else raw


def join_provider_types(provider: str, raw_types: Any) -> Optional[str]:
    """All raw type labels, original order, tagged once with the provider."""
    labels: List[str] = []
    seen = set()
    for raw in as_list(raw_types):
        text = _raw_type_text(raw)
        if text and text not in seen:
            seen.add(text)
            labels.append(text)
    if not labels:
        return None
    name = (provider or "").strip().lower()
    joined = "; ".join(labels)
    return f"{name}:{joined}" if name else joined


def normalize_doi(value: Any) -> Optional[str]:
    """Bare lower-case 10.x/... DOI, or None if the value is not a DOI."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix):].strip()
            lowered = text.lower()
            break
    text = text.strip().rstrip(".").lower()
    if not _DOI_SHAPE.match(text):
        return None
    return text


def build_biblio(
    *,
    publisher: Any = None,
    volume: Any = None,
    issue: Any = None,
    pages: Any = None,
    isbn: Any = None,
    editors: Any = None,
    published_date: Any = None,
    license: Any = None,
    parent_book_id: Any = None,
) -> Optional[Dict[str, Any]]:
    """Bibliographic JSON object with empty keys omitted; None if nothing remains."""
    values = {
        "publisher": _text(publisher),
        "volume": _text(volume),
        "issue": _text(issue),
        "pages": _text(pages),
        "isbn": _string_list(isbn),
        "editors": _string_list(editors),
        "published_date": _text(published_date),
        "license": _text(license),
        "parent_book_id": _text(parent_book_id),
    }
    out = {key: values[key] for key in _BIBLIO_KEYS if values[key]}
    return out or None


def biblio_json(biblio: Optional[Mapping[str, Any]]) -> Optional[str]:
    if not biblio:
        return None
    return json.dumps(dict(biblio), ensure_ascii=False, separators=(",", ":"))


def build_location(
    *,
    url: Any,
    kind: Any = None,
    host: Any = None,
    version: Any = None,
    license: Any = None,
    via: Any = None,
) -> Optional[Dict[str, str]]:
    href = _text(url)
    if not href:
        return None
    out = {"url": href}
    for key, value in (
        ("kind", kind),
        ("host", host),
        ("version", version),
        ("license", license),
        ("via", via),
    ):
        text = _text(value)
        if text:
            out[key] = text
    return out


def extra_payload(
    provider: str,
    record: Mapping[str, Any],
    *,
    provenance: Optional[Mapping[str, str]] = None,
    locations: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fetcher-side article['_extra'] body for insert_articles."""
    name = (provider or "").strip().lower()
    trimmer = {
        "openalex": trim_openalex,
        "crossref": trim_crossref,
        "doaj": trim_doaj,
        "eric": trim_eric,
        "pubmed": trim_pubmed,
        "europepmc": trim_europepmc,
        "biorxiv": trim_europepmc,
        "medrxiv": trim_europepmc,
        "semanticscholar": trim_semanticscholar,
        "hal": trim_hal,
        "openaire": trim_openaire,
        "zenodo": trim_zenodo,
        "arxiv": trim_arxiv,
        "plos": trim_plos,
        "clinicaltrials": trim_clinicaltrials,
        "nasa_ads": trim_nasa_ads,
    }.get(name, dict)
    body = record if isinstance(record, Mapping) else {}
    return {
        "provenance": dict(provenance or {}),
        "locations": [dict(item) for item in (locations or []) if item.get("url")],
        "provider_record": trimmer(dict(body)),
    }


def provenance_for(provider: str, fields: Mapping[str, Any]) -> Dict[str, str]:
    name = (provider or "").strip().lower()
    return {key: name for key, value in fields.items() if value is not None and value != ""}


def attach_work_fields(
    article: Dict[str, Any],
    provider: str,
    record: Mapping[str, Any],
    *,
    work_type: str,
    provider_type: Optional[str],
    doi: Optional[str],
    container_title: Optional[str] = None,
    host_name: Optional[str] = None,
    oa_status: Optional[str] = None,
    best_oa_url: Optional[str] = None,
    biblio: Optional[Dict[str, Any]] = None,
    locations: Optional[Iterable[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fill P1 metadata columns and `_extra` the same way on every fetcher."""
    article["work_type"] = work_type
    article["provider_type"] = provider_type
    article["doi"] = doi
    article["container_title"] = container_title or None
    article["host_name"] = host_name
    article["oa_status"] = oa_status
    article["best_oa_url"] = best_oa_url
    article["evidence_basis"] = "abstract"
    article["biblio"] = biblio_json(biblio)
    article["_extra"] = extra_payload(
        provider,
        record,
        provenance=provenance_for(provider, {
            "work_type": work_type,
            "provider_type": provider_type,
            "doi": doi,
            "container_title": article["container_title"],
            "host_name": host_name,
            "oa_status": oa_status,
            "best_oa_url": best_oa_url,
            "evidence_basis": "abstract",
            "biblio": article["biblio"],
        }),
        locations=locations,
    )
    return article


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        items = list(value)
    else:
        items = [value]
    out = []
    seen = set()
    for item in items:
        text = _text(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out or None


def _keep(mapping: Mapping[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    return {key: mapping[key] for key in keys if key in mapping}


def trim_loc(loc: Any) -> Optional[Dict[str, Any]]:
    if not loc or not isinstance(loc, Mapping):
        return None
    source = loc.get("source") or {}
    if not isinstance(source, Mapping):
        source = {}
    return {
        "is_oa": loc.get("is_oa"),
        "landing_page_url": loc.get("landing_page_url"),
        "pdf_url": loc.get("pdf_url"),
        "license": loc.get("license"),
        "license_id": loc.get("license_id"),
        "version": loc.get("version"),
        "raw_source_name": loc.get("raw_source_name"),
        "raw_type": loc.get("raw_type"),
        "source": {
            "id": source.get("id"),
            "display_name": source.get("display_name"),
            "type": source.get("type"),
            "host_organization_name": source.get("host_organization_name"),
            "issn_l": source.get("issn_l"),
        },
    }


def trim_openalex(work: Mapping[str, Any]) -> Dict[str, Any]:
    """Drop inverted abstracts and other large unused OpenAlex fields."""
    oa = work.get("open_access") or {}
    if not isinstance(oa, Mapping):
        oa = {}
    authors = []
    for authorship in (work.get("authorships") or [])[:40]:
        if not isinstance(authorship, Mapping):
            continue
        author = authorship.get("author") or {}
        if not isinstance(author, Mapping):
            author = {}
        authors.append({
            "name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "position": authorship.get("author_position"),
        })
    ids = work.get("ids") or {}
    if not isinstance(ids, Mapping):
        ids = {}
    return {
        "id": work.get("id"),
        "doi": work.get("doi"),
        "ids": {key: ids[key] for key in ("openalex", "doi", "pmid", "pmcid") if ids.get(key)},
        "title": work.get("title"),
        "publication_year": work.get("publication_year"),
        "publication_date": work.get("publication_date"),
        "type": work.get("type"),
        "type_crossref": work.get("type_crossref"),
        "language": work.get("language"),
        "biblio": work.get("biblio"),
        "volume": work.get("volume"),
        "open_access": {
            key: oa.get(key)
            for key in ("is_oa", "oa_status", "oa_url", "any_repository_has_fulltext")
        },
        "primary_location": trim_loc(work.get("primary_location")),
        "best_oa_location": trim_loc(work.get("best_oa_location")),
        "locations": [trim_loc(loc) for loc in (work.get("locations") or []) if isinstance(loc, Mapping)],
        "authors": authors,
    }


_CROSSREF_KEEP = (
    "DOI",
    "type",
    "subtype",
    "title",
    "container-title",
    "short-container-title",
    "publisher",
    "ISBN",
    "ISSN",
    "editor",
    "author",
    "issued",
    "published",
    "published-print",
    "published-online",
    "page",
    "volume",
    "issue",
    "link",
    "license",
    "URL",
    "subject",
)


def trim_crossref(item: Mapping[str, Any]) -> Dict[str, Any]:
    out = _keep(item, _CROSSREF_KEEP)
    if "author" in out:
        out["author"] = [
            {
                "given": person.get("given"),
                "family": person.get("family"),
                "sequence": person.get("sequence"),
                "ORCID": person.get("ORCID"),
            }
            for person in (out["author"] or [])
            if isinstance(person, Mapping)
        ][:40]
    if "editor" in out:
        out["editor"] = [
            {
                "given": person.get("given"),
                "family": person.get("family"),
                "sequence": person.get("sequence"),
            }
            for person in (out["editor"] or [])
            if isinstance(person, Mapping)
        ][:20]
    return out


def trim_doaj(result: Mapping[str, Any]) -> Dict[str, Any]:
    bib = result.get("bibjson") or {}
    if not isinstance(bib, Mapping):
        bib = {}
    journal = bib.get("journal") or {}
    if not isinstance(journal, Mapping):
        journal = {}
    return {
        "id": result.get("id"),
        "bibjson": {
            "title": bib.get("title"),
            "year": bib.get("year"),
            "identifier": bib.get("identifier"),
            "link": bib.get("link"),
            "journal": {
                "title": journal.get("title"),
                "publisher": journal.get("publisher"),
            },
            "author": [
                {"name": person.get("name")}
                for person in (bib.get("author") or [])
                if isinstance(person, Mapping)
            ][:40],
        },
    }


def trim_eric(doc: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(doc, (
        "id", "title", "publicationdateyear", "publicationtype", "source",
        "url", "isbn", "issn", "peerreviewed",
    ))


def trim_pubmed(record: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(record, (
        "pmid", "doi", "pmc", "publication_types", "journal", "volume",
        "issue", "pages", "year",
    ))


def trim_europepmc(record: Mapping[str, Any]) -> Dict[str, Any]:
    journal_info = record.get("journalInfo") or {}
    if not isinstance(journal_info, Mapping):
        journal_info = {}
    journal = journal_info.get("journal") or {}
    if not isinstance(journal, Mapping):
        journal = {}
    return {
        "id": record.get("id"),
        "doi": record.get("doi"),
        "pmid": record.get("pmid"),
        "pmcid": record.get("pmcid"),
        "source": record.get("source"),
        "pubTypeList": record.get("pubTypeList"),
        "isOpenAccess": record.get("isOpenAccess"),
        "fullTextUrlList": record.get("fullTextUrlList"),
        "firstPublicationDate": record.get("firstPublicationDate"),
        "pageInfo": record.get("pageInfo"),
        "journalInfo": {
            "volume": journal_info.get("volume"),
            "issue": journal_info.get("issue") or journal_info.get("issueNumber"),
            "journal": {"title": journal.get("title")},
        },
    }


def trim_semanticscholar(paper: Mapping[str, Any]) -> Dict[str, Any]:
    journal = paper.get("journal") or {}
    if not isinstance(journal, Mapping):
        journal = {}
    pdf = paper.get("openAccessPdf") or {}
    if not isinstance(pdf, Mapping):
        pdf = {}
    ids = paper.get("externalIds") or {}
    if not isinstance(ids, Mapping):
        ids = {}
    return {
        "paperId": paper.get("paperId"),
        "externalIds": {key: ids.get(key) for key in ("DOI", "PubMed", "PMC", "ArXiv") if ids.get(key)},
        "publicationTypes": paper.get("publicationTypes"),
        "venue": paper.get("venue"),
        "publicationDate": paper.get("publicationDate"),
        "journal": {
            "name": journal.get("name"),
            "volume": journal.get("volume"),
            "pages": journal.get("pages"),
        },
        "openAccessPdf": {"url": pdf.get("url"), "status": pdf.get("status")},
    }


def trim_hal(doc: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(doc, (
        "halId_s", "doiId_s", "docType_s", "submitType_s", "fileMain_s",
        "journalTitle_s", "producedDateY_i",
    ))


def trim_openaire(result: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(result, (
        "pid", "resulttype", "instancetype", "hostedby", "bestaccessright",
        "journal", "dateofacceptance",
    ))


def trim_zenodo(record: Mapping[str, Any]) -> Dict[str, Any]:
    meta = record.get("metadata") or {}
    if not isinstance(meta, Mapping):
        meta = {}
    files = []
    for item in (record.get("files") or [])[:8]:
        if not isinstance(item, Mapping):
            continue
        links = item.get("links") or {}
        if not isinstance(links, Mapping):
            links = {}
        files.append({"key": item.get("key"), "links": {"self": links.get("self")}})
    journal = meta.get("journal") or {}
    if not isinstance(journal, Mapping):
        journal = {}
    license_info = meta.get("license") or {}
    if not isinstance(license_info, Mapping):
        license_info = {}
    resource = meta.get("resource_type") or {}
    if not isinstance(resource, Mapping):
        resource = {}
    return {
        "id": record.get("id"),
        "metadata": {
            "doi": meta.get("doi"),
            "access_right": meta.get("access_right"),
            "publication_date": meta.get("publication_date"),
            "resource_type": {
                "type": resource.get("type"),
                "subtype": resource.get("subtype"),
                "title": resource.get("title"),
            },
            "journal": {
                "title": journal.get("title"),
                "volume": journal.get("volume"),
                "issue": journal.get("issue"),
                "pages": journal.get("pages"),
            },
            "license": {"id": license_info.get("id")},
        },
        "files": files,
    }


def trim_arxiv(record: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(record, ("id", "doi", "pdf", "published", "primary_category"))


def trim_plos(doc: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(doc, ("id", "journal", "publication_date", "article_type"))


def trim_clinicaltrials(record: Mapping[str, Any]) -> Dict[str, Any]:
    proto = record.get("protocolSection") or {}
    if not isinstance(proto, Mapping):
        proto = {}
    ident = proto.get("identificationModule") or {}
    if not isinstance(ident, Mapping):
        ident = {}
    status = proto.get("statusModule") or {}
    if not isinstance(status, Mapping):
        status = {}
    return {
        "nctId": ident.get("nctId"),
        "briefTitle": ident.get("briefTitle"),
        "startDate": (status.get("startDateStruct") or {}).get("date")
        if isinstance(status.get("startDateStruct"), Mapping) else None,
    }


def trim_nasa_ads(doc: Mapping[str, Any]) -> Dict[str, Any]:
    return _keep(doc, ("bibcode", "doi", "doctype", "pub", "year", "title"))
