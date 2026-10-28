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


def canonical_work_type(provider: str, raw_type: Any) -> str:
    """Map a provider's type string onto the stored vocabulary, or unknown."""
    if raw_type is None:
        return "unknown"
    raw = str(raw_type).strip().lower()
    if not raw:
        return "unknown"
    table = TYPE_MAP.get((provider or "").strip().lower(), {})
    return table.get(raw, "unknown")


def provider_type_label(provider: str, raw_type: Any) -> Optional[str]:
    """Keep the raw type tagged with its source, e.g. openalex:book-chapter."""
    if raw_type is None:
        return None
    raw = str(raw_type).strip()
    if not raw:
        return None
    name = (provider or "").strip().lower()
    return f"{name}:{raw}" if name else raw


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
    trimmer = {
        "openalex": trim_openalex,
        "crossref": trim_crossref,
        "doaj": trim_doaj,
    }.get((provider or "").strip().lower(), dict)
    return {
        "provenance": dict(provenance or {}),
        "locations": [dict(item) for item in (locations or []) if item.get("url")],
        "provider_record": trimmer(dict(record)),
    }


def provenance_for(provider: str, fields: Mapping[str, Any]) -> Dict[str, str]:
    name = (provider or "").strip().lower()
    return {key: name for key, value in fields.items() if value is not None and value != ""}


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
