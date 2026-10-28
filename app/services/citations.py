"""
Citation export helpers (RIS and BibTeX).

URL builders must stay in sync with getArticleUrl() in static/js/common.js.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

from app.fetchers.base import clean_text


def _openaire_url(aid: Any) -> str:
    """OpenAIRE ids are a DOI, a bare PMID, or an OpenAIRE object id.

    Keep in sync with the 'openaire' case of getArticleUrl() in static/js/common.js.
    """
    text = str(aid)
    if text.startswith("10."):
        return f"https://doi.org/{text}"
    if text.startswith("http"):
        return text
    if text.isascii() and text.isdigit():
        return f"https://pubmed.ncbi.nlm.nih.gov/{text}/"
    return f"https://explore.openaire.eu/search/result?id={quote(text, safe='')}"


def _europepmc_url(aid: Any) -> str:
    """Europe PMC ids carry their collection: PPR preprints, PMC full texts, bare MED ids.

    Keep in sync with the 'europepmc' case of getArticleUrl() in static/js/common.js.
    """
    text = str(aid)
    for prefix in ("PPR", "PMC"):
        if text.startswith(prefix):
            return f"https://europepmc.org/article/{prefix}/{text}"
    return f"https://europepmc.org/article/MED/{text}"


# Keep in sync with getArticleUrl() in static/js/common.js
SOURCE_URL: Dict[str, Callable[[str], str]] = {
    "pubmed": lambda aid: f"https://pubmed.ncbi.nlm.nih.gov/{aid}/",
    "europepmc": _europepmc_url,
    "clinicaltrials": lambda aid: f"https://clinicaltrials.gov/study/{aid}",
    "openalex": lambda aid: f"https://openalex.org/{aid}",
    "arxiv": lambda aid: f"https://arxiv.org/abs/{aid}",
    "semanticscholar": lambda aid: f"https://www.semanticscholar.org/paper/{aid}",
    "eric": lambda aid: f"https://eric.ed.gov/?id={aid}",
    "zenodo": lambda aid: f"https://zenodo.org/record/{aid}",
    "crossref": lambda aid: f"https://doi.org/{aid}",
    "doaj": lambda aid: f"https://doaj.org/article/{aid}",
    "nasa_ads": lambda aid: f"https://ui.adsabs.harvard.edu/abs/{aid}",
    "core": lambda aid: f"https://core.ac.uk/works/{aid}",
    "biorxiv": lambda aid: f"https://doi.org/{aid}",
    "medrxiv": lambda aid: f"https://doi.org/{aid}",
    "dblp": lambda aid: f"https://dblp.org/rec/{aid}",
    "openaire": _openaire_url,
    "plos": lambda aid: f"https://doi.org/{aid}",
    "hal": lambda aid: (
        f"https://doi.org/{aid}"
        if str(aid).startswith("10.")
        else f"https://hal.science/{aid}"
    ),
}

# Single-pass translate; include backslash so it is not left raw for LaTeX.
_BIBTEX_ESCAPE = str.maketrans({
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "&": r"\&",
    "#": r"\#",
    "$": r"\$",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
})

_KEY_SAFE = re.compile(r"[^A-Za-z0-9_]")


def article_url(article: dict) -> Optional[str]:
    source = (article.get("source") or "").strip()
    aid = article.get("article_id")
    if not source or aid is None or aid == "":
        return None
    builder = SOURCE_URL.get(source)
    if not builder:
        return None
    return builder(str(aid))


def _authors_list(article: dict) -> List[str]:
    authors = article.get("authors") or []
    if isinstance(authors, str):
        return [a.strip() for a in authors.split(";") if a.strip()]
    return [str(a).strip() for a in authors if str(a).strip()]


def _collapse_ws(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _four_digit_year(year: Any) -> Optional[str]:
    if year is None:
        return None
    m = re.search(r"\b(\d{4})\b", str(year))
    return m.group(1) if m else None


_DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")
_PLACEHOLDER_JOURNALS = {
    "unknown journal", "unknown", "n/a", "na", "none", "null", "-", "--", "?",
    "openaire", "hal", "plos", "zenodo", "doaj", "eric", "semantic scholar",
    "openalex", "crossref", "clinicaltrials.gov", "online submission",
}

# Export tags checked against Zotero translators/RIS.js (lastUpdated 2026-01-05).
# Import map: JOUR journalArticle; BOOK/EDBOOK book; CHAP bookSection;
# ENCYC encyclopediaArticle; CPAPER conferencePaper; THES thesis; RPRT report;
# DATA dataset (Zotero >= 6.0.24); MANSCPT/INPR/UNPD manuscript.
# GEN imports as journalArticle — students who need a generic type should use
# BibTeX @misc. No RIS tag imports as preprint, so preprints use MANSCPT.
#
# work_type          RIS       BibTeX          Zotero import
# journal-article    JOUR      @article        journalArticle
# review-article     JOUR      @article        journalArticle
# book-review        JOUR      @article        journalArticle (+ N1)
# book               BOOK      @book           book
# edited-book        EDBOOK    @book           book
# book-chapter       CHAP      @incollection   bookSection
# reference-entry    ENCYC     @incollection   encyclopediaArticle
# conference-paper   CPAPER    @inproceedings  conferencePaper
# dissertation       THES      @phdthesis/@misc thesis
# report             RPRT      @techreport     report
# preprint           MANSCPT   @misc           manuscript
# registry-record    GEN       @misc           journalArticle (+ N1)
# dataset            DATA      @misc           dataset
# other / unknown    GEN       @misc           journalArticle
_JOURNAL_TYPES = frozenset({"journal-article", "review-article", "book-review"})
_CONTAINER_T2_TYPES = frozenset({
    "book-chapter", "reference-entry", "conference-paper",
})
_TYPE_EXPORT: Dict[str, Tuple[str, str, str]] = {
    "journal-article": ("JOUR", "article", "journal"),
    "review-article": ("JOUR", "article", "journal"),
    "book-review": ("JOUR", "article", "journal"),
    "book": ("BOOK", "book", "book"),
    "edited-book": ("EDBOOK", "book", "edited_book"),
    "book-chapter": ("CHAP", "incollection", "chapter"),
    "reference-entry": ("ENCYC", "incollection", "entry"),
    "conference-paper": ("CPAPER", "inproceedings", "conference"),
    "dissertation": ("THES", "phdthesis", "dissertation"),
    "report": ("RPRT", "techreport", "report"),
    "preprint": ("MANSCPT", "misc", "preprint"),
    "registry-record": ("GEN", "misc", "generic"),
    "dataset": ("DATA", "misc", "generic"),
    "other": ("GEN", "misc", "generic"),
    "unknown": ("GEN", "misc", "generic"),
}
_DOCTORAL_HINTS = ("phd", "doctoral", "doctorate", "dphil")


@dataclass(frozen=True)
class CitationModel:
    """Shared bibliographic fields for every export formatter."""

    work_type: str
    ris_ty: str
    bibtex_type: str
    apa_kind: str
    title: str
    authors: List[str]
    editors: List[str]
    year: Optional[str]
    container: str
    publisher: str
    volume: str
    issue: str
    pages: str
    isbn: str
    doi: Optional[str]
    canonical_url: Optional[str]
    open_copy_url: Optional[str]
    discovery_url: Optional[str]
    notes: Tuple[str, ...]


def article_doi(article: dict) -> Optional[str]:
    """DOI from the doi column, else a DOI-shaped article_id."""
    stored = str(article.get("doi") or "").strip()
    if stored:
        text = stored
        lowered = text.lower()
        if lowered.startswith("https://doi.org/"):
            text = text[len("https://doi.org/"):].strip()
        elif lowered.startswith("http://doi.org/"):
            text = text[len("http://doi.org/"):].strip()
        text = text.strip().rstrip(".")
        if _DOI_SHAPE.match(text):
            return text
        if _DOI_SHAPE.match(text.lower()):
            return text.lower()
    aid = str(article.get("article_id") or "").strip()
    if aid.lower().startswith("https://doi.org/"):
        aid = aid[len("https://doi.org/"):]
    return aid if _DOI_SHAPE.match(aid) else None


def _is_placeholder_journal(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered.rstrip(".") in _PLACEHOLDER_JOURNALS
        or lowered.startswith("arxiv:")
        or lowered.endswith((" preprint", " ebooks"))
    )


def _real_journal(article: dict) -> str:
    """Journal or container name, or "" when it is empty or a placeholder."""
    for key in ("journal", "container_title"):
        name = _collapse_ws(article.get(key) or "")
        if name and not _is_placeholder_journal(name):
            return name
    return ""


def _stored_work_type(article: dict) -> Optional[str]:
    if "work_type" not in article or article.get("work_type") is None:
        return None
    text = str(article.get("work_type") or "").strip()
    return text or None


def _biblio(article: dict) -> Dict[str, Any]:
    raw = article.get("biblio")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return {}


def _string_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: Sequence[Any] = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        items = value
    else:
        items = [value]
    out: List[str] = []
    for item in items:
        text = _collapse_ws(item)
        if text:
            out.append(text)
    return out


def _doctoral_degree(article: dict) -> bool:
    blob = " ".join(
        str(article.get(key) or "") for key in ("provider_type", "work_type")
    ).lower()
    return any(hint in blob for hint in _DOCTORAL_HINTS)


def _open_copy_url(article: dict) -> Optional[str]:
    url = str(article.get("best_oa_url") or "").strip()
    if not url or "via=crossref" in url.lower():
        return None
    return url


def _same_url(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return not left and not right
    return left.rstrip("/").lower() == right.rstrip("/").lower()


def citation_model(article: dict) -> CitationModel:
    """One bibliographic record that every formatter reads."""
    venue = _real_journal(article)
    stored = _stored_work_type(article)
    if stored is None:
        work_type = "journal-article" if venue else "unknown"
    elif stored == "unknown":
        work_type = "unknown"
    else:
        work_type = stored if stored in _TYPE_EXPORT else "unknown"

    ris_ty, bibtex_type, apa_kind = _TYPE_EXPORT[work_type]
    notes: List[str] = []
    if work_type == "book-review":
        notes.append("Book review")
    elif work_type == "preprint":
        notes.append("Preprint")
    elif work_type == "registry-record":
        notes.append("Trial registry record")
    elif work_type == "dissertation" and not _doctoral_degree(article):
        bibtex_type = "misc"
        notes.append("Dissertation")

    biblio = _biblio(article)
    editors = _string_values(biblio.get("editors"))
    isbn_values = _string_values(biblio.get("isbn"))
    doi = article_doi(article)
    canonical = f"https://doi.org/{doi}" if doi else None
    discovery = article_url(article)
    container = venue if work_type in _JOURNAL_TYPES | _CONTAINER_T2_TYPES else ""

    return CitationModel(
        work_type=work_type,
        ris_ty=ris_ty,
        bibtex_type=bibtex_type,
        apa_kind=apa_kind,
        title=_collapse_ws(article.get("title") or ""),
        authors=_authors_list(article),
        editors=editors,
        year=_four_digit_year(article.get("year")),
        container=container,
        publisher=_collapse_ws(biblio.get("publisher") or ""),
        volume=_collapse_ws(biblio.get("volume") or ""),
        issue=_collapse_ws(biblio.get("issue") or ""),
        pages=_collapse_ws(biblio.get("pages") or ""),
        isbn="; ".join(isbn_values),
        doi=doi,
        canonical_url=canonical,
        open_copy_url=_open_copy_url(article),
        discovery_url=discovery,
        notes=tuple(notes),
    )


def _record_url(model: CitationModel) -> Optional[str]:
    return model.canonical_url or model.discovery_url


def _ris_line(tag: str, value: str) -> str:
    return f"{tag}  - {value}"


def _page_span(pages: str) -> Tuple[str, str]:
    text = pages.replace("–", "-").replace("—", "-")
    if "-" in text:
        start, end = text.split("-", 1)
        return start.strip(), end.strip()
    return text.strip(), ""


def article_to_ris(article: dict) -> str:
    """Serialize one article as a RIS record for its work type."""
    model = citation_model(article)
    lines = [_ris_line("TY", model.ris_ty)]
    if model.title:
        lines.append(_ris_line("TI", model.title))
    for name in model.authors:
        lines.append(_ris_line("AU", name))
    for name in model.editors:
        lines.append(_ris_line("ED", name))
    if model.year:
        lines.append(_ris_line("PY", model.year))
    if model.container:
        tag = "T2" if model.work_type in _CONTAINER_T2_TYPES else "JO"
        lines.append(_ris_line(tag, model.container))
    if model.volume:
        lines.append(_ris_line("VL", model.volume))
    if model.issue:
        lines.append(_ris_line("IS", model.issue))
    if model.pages:
        start, end = _page_span(model.pages)
        if start:
            lines.append(_ris_line("SP", start))
        if end:
            lines.append(_ris_line("EP", end))
    if model.publisher:
        lines.append(_ris_line("PB", model.publisher))
    if model.isbn:
        for isbn in model.isbn.split("; "):
            lines.append(_ris_line("SN", isbn))
    abstract = clean_text(article.get("abstract"))
    if abstract:
        lines.append(_ris_line("AB", abstract))
    if model.doi:
        lines.append(_ris_line("DO", model.doi))
    url = _record_url(model)
    if url:
        lines.append(_ris_line("UR", url))
    if model.open_copy_url:
        lines.append(_ris_line("L2", model.open_copy_url))
    source = (article.get("source") or "").strip()
    aid = str(article.get("article_id") or "")
    for note in model.notes:
        lines.append(_ris_line("N1", note))
    if model.discovery_url and not _same_url(model.discovery_url, url):
        lines.append(_ris_line("N1", f"Found via {source}: {model.discovery_url}"))
    if source or aid:
        lines.append(_ris_line("ID", f"{source}:{aid}"))
    lines.append("ER  - ")
    lines.append("")
    return "\n".join(lines)


def _bibtex_escape(value: str) -> str:
    return value.translate(_BIBTEX_ESCAPE)


def _bibtex_key(source: str, article_id: str) -> str:
    raw = f"{source}_{article_id}"
    return _KEY_SAFE.sub("_", raw)


def _bibtex_url(url: Optional[str]) -> Optional[str]:
    # A URL is written raw: escaping _ % # ~ would break the link. A brace or a
    # line break would break the entry, so such a URL is left out.
    if url and not re.search(r"[{}\r\n]", url):
        return url
    return None


def article_to_bibtex(article: dict) -> str:
    """Serialize one article as a BibTeX entry for its work type."""
    model = citation_model(article)
    source = (article.get("source") or "").strip()
    aid = str(article.get("article_id") or "")
    key = _bibtex_key(source, aid)
    fields: List[str] = []

    if model.title:
        fields.append(f"  title = {{{{{_bibtex_escape(model.title)}}}}}")
    if model.authors:
        author_str = " and ".join(_bibtex_escape(a) for a in model.authors)
        fields.append(f"  author = {{{author_str}}}")
    if model.editors:
        editor_str = " and ".join(_bibtex_escape(a) for a in model.editors)
        fields.append(f"  editor = {{{editor_str}}}")
    if model.year:
        fields.append(f"  year = {{{model.year}}}")
    if model.work_type in _JOURNAL_TYPES and model.container:
        fields.append(f"  journal = {{{_bibtex_escape(model.container)}}}")
    if model.work_type in _CONTAINER_T2_TYPES and model.container:
        fields.append(f"  booktitle = {{{_bibtex_escape(model.container)}}}")
    if model.publisher:
        fields.append(f"  publisher = {{{_bibtex_escape(model.publisher)}}}")
    if model.volume:
        fields.append(f"  volume = {{{_bibtex_escape(model.volume)}}}")
    if model.issue:
        fields.append(f"  number = {{{_bibtex_escape(model.issue)}}}")
    if model.pages:
        fields.append(f"  pages = {{{_bibtex_escape(model.pages)}}}")
    if model.isbn:
        fields.append(f"  isbn = {{{_bibtex_escape(model.isbn)}}}")
    if model.doi:
        fields.append(f"  doi = {{{_bibtex_escape(model.doi)}}}")
    url = _bibtex_url(model.canonical_url) or _bibtex_url(model.discovery_url)
    if url:
        fields.append(f"  url = {{{url}}}")

    note_parts = list(model.notes)
    record_url = _record_url(model)
    if model.discovery_url and not _same_url(model.discovery_url, record_url):
        note_parts.append(f"Found via {source}: {model.discovery_url}")
    elif source and not note_parts:
        note_parts.append(f"Source: {source}")
    if note_parts:
        note = "; ".join(note_parts)
        fields.append(f"  note = {{{_bibtex_escape(note)}}}")

    body = ",\n".join(fields)
    if body:
        body = body + "\n"
    return f"@{model.bibtex_type}{{{key},\n{body}}}\n"


def collection_to_ris(articles: List[dict]) -> str:
    return "\n".join(article_to_ris(a) for a in articles)


def collection_to_bibtex(articles: List[dict]) -> str:
    parts = [article_to_bibtex(a).rstrip("\n") for a in articles]
    return "\n\n".join(parts) + ("\n" if parts else "")


def _apa_authors(authors: List[str]) -> str:
    """Format author list roughly as APA 7th (best-effort for free-text names)."""
    if not authors:
        return ""
    formatted = []
    for name in authors:
        name = name.strip()
        if not name:
            continue
        # "Last F" or "Last, F." or "First Last"
        if "," in name:
            formatted.append(name if name.endswith(".") else name + ".")
            continue
        parts = name.split()
        if len(parts) == 1:
            formatted.append(parts[0])
        else:
            # Assume last token is family name when "First Middle Last"
            # or first token is family when "Last F" (initial without period).
            if len(parts[-1]) <= 2 and parts[-1].isalpha():
                family = parts[0]
                initials = " ".join(p[0].upper() + "." for p in parts[1:] if p)
                formatted.append(f"{family}, {initials}".strip())
            else:
                family = parts[-1]
                initials = " ".join(p[0].upper() + "." for p in parts[:-1] if p)
                formatted.append(f"{family}, {initials}".strip())
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]}, & {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"


def _apa_pages(pages: str) -> str:
    return pages.replace("-", "–")


def _apa_link(model: CitationModel) -> str:
    if model.doi:
        return f" https://doi.org/{model.doi}"
    url = _record_url(model)
    return f" {url}" if url else ""


def _apa_head(authors: str, year: str) -> str:
    return f"{authors} ({year}). " if authors else f"({year}). "


def article_to_apa(article: dict) -> str:
    """One reference in approximate APA 7th style for the record's type.

    Free-text author strings from academic APIs are imperfect; this is good
    enough for classroom drafts. Prefer Zotero/RIS for polished bibliographies.
    """
    model = citation_model(article)
    authors = _apa_authors(model.authors)
    year = model.year or "n.d."
    title = model.title or "Untitled"
    head = _apa_head(authors, year)
    link = _apa_link(model)
    kind = model.apa_kind

    if kind == "journal":
        body = f"{title}."
        if model.container:
            body += f" *{model.container}*"
            issue_bit = f"({model.issue})" if model.issue else ""
            extras: List[str] = []
            if model.volume:
                extras.append(f"{model.volume}{issue_bit}")
            elif model.issue:
                extras.append(model.issue)
            if model.pages:
                extras.append(_apa_pages(model.pages))
            if extras:
                body += ", " + ", ".join(extras)
            body += "."
        return head + body + link

    if kind == "book":
        body = f"*{title}*."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind == "edited_book":
        editors = _apa_authors(model.editors)
        if editors:
            suffix = "Ed." if len(model.editors) == 1 else "Eds."
            head = f"{editors} ({suffix}). ({year}). "
        body = f"*{title}*."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind in ("chapter", "entry"):
        body = f"{title}."
        in_parts: List[str] = []
        if model.editors:
            ed = _apa_authors(model.editors)
            suffix = "Ed." if len(model.editors) == 1 else "Eds."
            in_parts.append(f"{ed} ({suffix})")
        if model.container:
            book = f"*{model.container}*"
            if model.pages:
                book += f" (pp. {_apa_pages(model.pages)})"
            in_parts.append(book)
        if in_parts:
            body += " In " + ", ".join(in_parts) + "."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind == "conference":
        body = f"{title}."
        if model.container:
            body += f" In *{model.container}*."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind == "dissertation":
        body = f"*{title}* [Dissertation]."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind == "report":
        body = f"*{title}*."
        if model.publisher:
            body += f" {model.publisher}."
        return head + body + link

    if kind == "preprint":
        return head + f"{title} [Preprint]." + link

    body = f"{title}."
    if model.container:
        body += f" *{model.container}*."
    return head + body + link


def collection_to_apa(articles: List[dict]) -> str:
    lines = [article_to_apa(a) for a in articles]
    return "\n\n".join(lines) + ("\n" if lines else "")
