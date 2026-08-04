"""
Europe PMC Fetcher
Fetches articles from Europe PMC REST API
"""

import logging
from typing import Dict, List, Optional

from app.fetchers.base import BaseFetcher, HttpClient

logger = logging.getLogger(__name__)


class EuropePMCFetcher(BaseFetcher):
    """Fetches articles from Europe PMC"""

    SOURCE_NAME = "europepmc"
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, email: str = None, **kwargs):
        self.email = email

        self.http = HttpClient(delay=0.3)


    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search Europe PMC, return list of IDs"""
        logger.info("Searching Europe PMC for: '%s'", query)
        ids = []
        page_size = min(max_results, 1000)
        cursor_mark = "*"

        while len(ids) < max_results:
            params = {
                "query": query,
                "format": "json",
                "pageSize": page_size,
                "cursorMark": cursor_mark,
            }

            try:
                resp = self.http.get(f"{self.BASE_URL}/search", params=params, timeout=30)
                data = resp.json()

                results = data.get("resultList", {}).get("result", [])
                if not results:
                    break

                for result in results:
                    article_id = result.get("id", "")
                    if article_id:
                        ids.append(article_id)

                next_cursor = data.get("nextCursorMark")
                if not next_cursor or next_cursor == cursor_mark:
                    break
                cursor_mark = next_cursor

            except Exception as e:
                logger.exception("Error searching Europe PMC: %s", e)
                break

        logger.info("Found %s articles", len(ids[:max_results]))
        return ids[:max_results]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Optimized: Europe PMC search with resultType=core returns full records"""
        logger.info("Searching Europe PMC for: '%s'", query)
        articles = []
        page_size = min(max_results, 1000)
        cursor_mark = "*"

        while len(articles) < max_results:
            params = {
                "query": query,
                "format": "json",
                "pageSize": page_size,
                "cursorMark": cursor_mark,
                "resultType": "core"
            }

            try:
                resp = self.http.get(f"{self.BASE_URL}/search", params=params, timeout=30)
                data = resp.json()

                results = data.get("resultList", {}).get("result", [])
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

            except Exception as e:
                logger.exception("Error fetching from Europe PMC: %s", e)
                break

        logger.info("Successfully fetched %s articles", len(articles[:max_results]))
        return articles[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        """Fetch details for given IDs"""
        articles = []

        for article_id in ids:
            try:
                resp = self.http.get(
                    f"{self.BASE_URL}/search",
                    params={
                        "query": f"EXT_ID:{article_id}",
                        "format": "json",
                        "resultType": "core"
                    },
                    timeout=30
                )
                results = resp.json().get("resultList", {}).get("result", [])
                if results:
                    parsed = self._parse_article(results[0])
                    if parsed:
                        articles.append(parsed)
            except Exception as e:
                logger.exception("Error fetching %s: %s", article_id, e)

        logger.info("Successfully fetched %s articles", len(articles))
        return articles

    def _parse_article(self, record: Dict) -> Optional[Dict]:
        """Parse a Europe PMC article record"""
        article_id = record.get("id", "")
        title = record.get("title", "No title")
        abstract = record.get("abstractText", "")

        if not abstract:
            return None

        year = str(record.get("pubYear", "Unknown"))
        journal = record.get("journalTitle", "Unknown journal")

        authors = []
        for author in record.get("authorList", {}).get("author", [])[:5]:
            name = author.get("fullName", "")
            if name:
                authors.append(name)

        return {
            "article_id": article_id,
            "source": self.SOURCE_NAME,
            "title": title,
            "abstract": abstract,
            "year": year,
            "authors": authors,
            "journal": journal,
        }
