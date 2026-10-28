"""
PLOS (Public Library of Science) open-access journal fetcher.

Free Solr API: https://api.plos.org/search
API key optional for higher rate limits (not required for classroom use).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.fetchers.querytext import solr_escape_term
from app.fetchers.terms import OPERATORS, boolean_terms
from app.services.work_types import (
    attach_work_fields,
    build_biblio,
    build_location,
    canonical_work_type,
    join_provider_types,
    normalize_doi,
)


class PLOSFetcher(BaseFetcher):
    SOURCE_NAME = "plos"
    BASE_URL = "https://api.plos.org/search"

    def __init__(self, email: Optional[str] = None):
        self.http = HttpClient(
            delay=0.35,
            user_agent=user_agent(email),
        )

    @staticmethod
    def solr_query(query: str) -> str:
        """Every word in the title or the abstract; bare `title:a b` scoped only `a`."""
        terms = " ".join(
            term if term in OPERATORS else solr_escape_term(term)
            for term in boolean_terms(query)
        )
        return f"title:({terms}) OR abstract:({terms})" if terms else "*:*"

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        start = 0
        page_size = min(100, max_results)
        solr_q = self.solr_query(query)

        while len(articles) < max_results:
            rows = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "q": solr_q,
                        "fl": "id,title,abstract,author,publication_date,journal",
                        "rows": rows,
                        "start": start,
                        "wt": "json",
                    },
                )
                docs = (json_of(r).get("response") or {}).get("docs") or []
            except FetchError as e:
                reraise_fetch_error(e, articles)
            except Exception as e:
                raise FetchError(f"PLOS request failed: {e}", kind="network", articles=articles) from e

            if not docs:
                break
            for doc in docs:
                art = self._parse(doc)
                if art:
                    articles.append(art)
            if len(docs) < rows:
                break
            start += len(docs)

        if not articles:
            raise FetchError("No PLOS articles matched your query.", kind="no_results")
        return articles[:max_results]

    def _parse(self, doc: Dict) -> Optional[Dict]:
        try:
            title = doc.get("title")
            if isinstance(title, list):
                title = title[0] if title else ""
            title = clean_text(title)
            abstract = doc.get("abstract")
            if isinstance(abstract, list):
                abstract = " ".join(str(a) for a in abstract if a)
            abstract = clean_text(abstract)
            if not title or not abstract:
                return None
            authors = doc.get("author") or []
            if isinstance(authors, str):
                authors = [authors]
            authors = [str(a).strip() for a in authors if str(a).strip()]
            pub = doc.get("publication_date") or ""
            year = str(pub)[:4] if pub else ""
            journal = doc.get("journal") or ""
            if isinstance(journal, list):
                journal = journal[0] if journal else ""
            aid = (doc.get("id") or "").strip()
            if not aid:
                return None
            doi = normalize_doi(aid)
            oa_url = f"https://doi.org/{doi}" if doi else None
            loc = build_location(url=oa_url, kind="fulltext", via="plos")
            article = {
                "article_id": aid,
                "source": "plos",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": str(journal),
            }
            return attach_work_fields(
                article,
                "plos",
                doc,
                work_type=canonical_work_type("plos", "journal-article"),
                provider_type=join_provider_types("plos", "journal-article"),
                doi=doi,
                container_title=str(journal) or None,
                oa_status="gold",
                best_oa_url=oa_url,
                biblio=build_biblio(published_date=str(pub)[:10] if pub else None),
                locations=[loc] if loc else None,
            )
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
