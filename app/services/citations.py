"""
Citation export helpers (RIS and BibTeX).

URL builders must stay in sync with getArticleUrl() in static/js/common.js.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional
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


def article_doi(article: dict) -> Optional[str]:
    """The DOI for an article whose id is DOI-shaped (10.<digits>/...), whatever the source."""
    aid = str(article.get("article_id") or "").strip()
    if aid.lower().startswith("https://doi.org/"):
        aid = aid[len("https://doi.org/"):]
    return aid if _DOI_SHAPE.match(aid) else None


def _real_journal(article: dict) -> str:
    """Journal name, or "" when it is empty or a placeholder such as "Unknown journal"."""
    journal = _collapse_ws(article.get("journal") or "")
    name = journal.lower()
    if (
        name.rstrip(".") in _PLACEHOLDER_JOURNALS
        or name.startswith("arxiv:")
        or name.endswith((" preprint", " ebooks"))
    ):
        return ""
    return journal


def _ris_line(tag: str, value: str) -> str:
    return f"{tag}  - {value}"


def article_to_ris(article: dict) -> str:
    """Serialize one article as a RIS journal record."""
    lines = [_ris_line("TY", "JOUR")]
    title = _collapse_ws(article.get("title") or "")
    if title:
        lines.append(_ris_line("TI", title))
    for name in _authors_list(article):
        lines.append(_ris_line("AU", name))
    year = _four_digit_year(article.get("year"))
    if year:
        lines.append(_ris_line("PY", year))
    journal = _real_journal(article)
    if journal:
        lines.append(_ris_line("JO", journal))
    abstract = clean_text(article.get("abstract"))
    if abstract:
        lines.append(_ris_line("AB", abstract))
    source = (article.get("source") or "").strip()
    aid = str(article.get("article_id") or "")
    doi = article_doi(article)
    if doi:
        lines.append(_ris_line("DO", doi))
    url = article_url(article)
    if url:
        lines.append(_ris_line("UR", url))
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


def article_to_bibtex(article: dict) -> str:
    """Serialize one article as a BibTeX @article entry."""
    source = (article.get("source") or "").strip()
    aid = str(article.get("article_id") or "")
    key = _bibtex_key(source, aid)
    fields: List[str] = []

    title = _collapse_ws(article.get("title") or "")
    if title:
        fields.append(f"  title = {{{{{_bibtex_escape(title)}}}}}")

    authors = _authors_list(article)
    if authors:
        author_str = " and ".join(_bibtex_escape(a) for a in authors)
        fields.append(f"  author = {{{author_str}}}")

    year = _four_digit_year(article.get("year"))
    if year:
        fields.append(f"  year = {{{year}}}")

    journal = _real_journal(article)
    if journal:
        fields.append(f"  journal = {{{_bibtex_escape(journal)}}}")

    doi = article_doi(article)
    if doi:
        fields.append(f"  doi = {{{_bibtex_escape(doi)}}}")

    # A URL is written raw: escaping _ % # ~ would break the link. A brace or a
    # line break would break the entry, so such a URL is left out.
    url = article_url(article)
    if url and not re.search(r"[{}\r\n]", url):
        fields.append(f"  url = {{{url}}}")

    if source:
        fields.append(f"  note = {{{_bibtex_escape(f'Source: {source}')}}}")

    body = ",\n".join(fields)
    if body:
        body = body + "\n"
    return f"@article{{{key},\n{body}}}\n"


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


def article_to_apa(article: dict) -> str:
    """One reference in approximate APA 7th journal-article style.

    Free-text author strings from academic APIs are imperfect; this is good
    enough for classroom drafts. Prefer Zotero/RIS for polished bibliographies.
    """
    authors = _apa_authors(_authors_list(article))
    year = _four_digit_year(article.get("year")) or "n.d."
    title = _collapse_ws(article.get("title") or "Untitled")
    # Sentence case is ideal; we keep the stored title as-is.
    journal = _real_journal(article)
    source = (article.get("source") or "").strip()
    aid = str(article.get("article_id") or "")

    head = f"{authors} ({year}). " if authors else f"({year}). "
    body = f"{title}."
    if journal:
        body += f" *{journal}*."
    # DOI for CrossRef ids
    if source == "crossref" and aid:
        body += f" https://doi.org/{aid}"
    else:
        url = article_url(article)
        if url:
            body += f" {url}"
    return head + body


def collection_to_apa(articles: List[dict]) -> str:
    lines = [article_to_apa(a) for a in articles]
    return "\n\n".join(lines) + ("\n" if lines else "")
