"""
CORE Fetcher
CORE (core.ac.uk) — the largest aggregator of open-access research papers,
indexing full text + metadata from repositories and journals worldwide.
Requires a free API key: https://core.ac.uk/services/api  (set CORE_API_KEY).
"""

import os
from typing import Dict, List, Optional

from base_fetcher import BaseFetcher, FetchError, HttpClient


class COREFetcher(BaseFetcher):
    SOURCE_NAME = "core"
    BASE_URL = "https://api.core.ac.uk/v3"

    def __init__(self, email: str = None):
        self.token = os.getenv("CORE_API_KEY", "").strip()
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.http = HttpClient(
            delay=0.5,
            user_agent=f'LiteratureResearchAide/3.7 ({email or "research@example.com"})',
            headers=headers,
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        """CORE's search returns full work records, so fetch in one pass."""
        if not self.token:
            print("CORE: CORE_API_KEY env var not set; skipping source")
            return []

        articles = []
        offset = 0
        page_size = min(100, max_results)

        while len(articles) < max_results:
            n = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    f"{self.BASE_URL}/search/works",
                    params={"q": query, "limit": n, "offset": offset},
                )
                results = r.json().get("results", [])
                if not results:
                    break
                for work in results:
                    parsed = self._parse_work(work)
                    if parsed:
                        articles.append(parsed)
                if len(results) < n:
                    break
                offset += len(results)
            except FetchError as e:
                print(f"CORE fetch error: {e}")
                raise
            except Exception as e:
                print(f"CORE fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_work(self, work: Dict) -> Optional[Dict]:
        try:
            article_id = str(work.get("id") or "").strip()
            title = (work.get("title") or "").strip()
            abstract = (work.get("abstract") or "").strip()
            if not article_id or not title or not abstract:
                return None

            year = str(work.get("yearPublished") or "").strip()
            if not year:
                published = str(work.get("publishedDate") or "")
                year = published[:4] if published[:4].isdigit() else ""

            authors = [
                a["name"].strip()
                for a in (work.get("authors") or [])[:5]
                if isinstance(a, dict) and a.get("name")
            ]

            journal = ""
            journals = work.get("journals") or []
            if journals and isinstance(journals[0], dict):
                journal = (journals[0].get("title") or "").strip()
            if not journal:
                journal = (work.get("publisher") or "").strip()

            return {
                "article_id": article_id,
                "source": self.SOURCE_NAME,
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": journal,
            }
        except Exception as e:
            print(f"CORE parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
