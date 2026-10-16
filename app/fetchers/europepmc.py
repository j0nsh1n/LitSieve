"""
Europe PMC Fetcher
Fetches articles from Europe PMC REST API
"""

import logging
from datetime import date
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

logger = logging.getLogger(__name__)


class EuropePMCFetcher(BaseFetcher):
    """Fetches articles from Europe PMC"""

    SOURCE_NAME = "europepmc"
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, email: Optional[str] = None, **kwargs):
        self.email = email
        self.http = HttpClient(delay=0.3, user_agent=user_agent(email))

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Europe PMC search with resultType=core returns full records."""
        return self._search_core(query, max_results)

    def _search_core(self, query: str, max_results: int) -> List[Dict]:
        logger.info("Searching %s for: '%s'", self.SOURCE_NAME, query)
        articles: List[Dict] = []
        page_size = min(max_results, 1000)
        cursor_mark = "*"

        while len(articles) < max_results:
            params = {
                "query": query,
                "format": "json",
                "pageSize": page_size,
                "cursorMark": cursor_mark,
                "resultType": "core",
            }
            try:
                resp = self.http.get(f"{self.BASE_URL}/search", params=params, timeout=30)
                data = json_of(resp)
            except FetchError as e:
                reraise_fetch_error(e, articles)
                raise
            except Exception as e:
                raise FetchError(
                    f"{self.SOURCE_NAME} request failed: {e}", kind="network", articles=articles
                ) from e

            results = (data.get("resultList") or {}).get("result") or []
            if not results:
                break
            for result in results:
                parsed = self._parse_article(result)
                if parsed:
                    articles.append(parsed)

            next_cursor = data.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor_mark:
                break
            cursor_mark = next_cursor

        logger.info("Fetched %s articles from %s", len(articles[:max_results]), self.SOURCE_NAME)
        return articles[:max_results]

    @staticmethod
    def _year(record: Dict) -> str:
        # Some records carry a future year in every publication field (live
        # 42680123: 2028, where PubMed says 2026); then the indexing date wins.
        years = [
            str(record.get(field) or "").strip()[:4]
            for field in ("pubYear", "firstPublicationDate", "firstIndexDate", "dateOfCreation")
        ]
        years = [y for y in years if y.isdigit()]
        for year in years:
            if int(year) <= date.today().year:
                return year
        return years[0] if years else ""

    @staticmethod
    def _journal(record: Dict) -> str:
        # resultType=core puts the journal under journalInfo; lite uses journalTitle.
        journal = ((record.get("journalInfo") or {}).get("journal") or {}).get("title")
        journal = journal or record.get("journalTitle")
        if journal:
            return clean_text(journal)
        publisher = (record.get("bookOrReportDetails") or {}).get("publisher")
        if publisher and record.get("source") == "PPR":
            return f"{clean_text(publisher)} preprint"
        return ""

    @staticmethod
    def _authors(record: Dict) -> List[str]:
        authors = []
        for author in (record.get("authorList") or {}).get("author") or []:
            name = (author.get("fullName") or author.get("collectiveName") or "").strip()
            if name:
                authors.append(name)
        return authors

    def _parse_article(self, record: Dict) -> Optional[Dict]:
        article_id = record.get("id", "")
        title = clean_text(record.get("title"))
        abstract = clean_text(record.get("abstractText"))
        if not article_id or not title or not abstract:
            return None
        return {
            "article_id": article_id,
            "source": self.SOURCE_NAME,
            "title": title,
            "abstract": abstract,
            "year": self._year(record),
            "authors": self._authors(record),
            "journal": self._journal(record),
        }
