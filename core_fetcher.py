"""
CORE Fetcher
CORE (core.ac.uk) — the largest aggregator of open-access research papers,
indexing full text + metadata from repositories and journals worldwide.
Requires a free API key: https://core.ac.uk/services/api  (set CORE_API_KEY).
"""

import os
import time
import requests
from typing import List, Dict, Optional
from base_fetcher import BaseFetcher


class COREFetcher(BaseFetcher):
    SOURCE_NAME = "core"
    BASE_URL = "https://api.core.ac.uk/v3"
    MAX_429_RETRIES = 5

    def __init__(self, email: str = None):
        self.token = os.getenv("CORE_API_KEY", "").strip()
        self.session = requests.Session()
        headers = {
            "User-Agent": f'LiteratureSearchTool/1.0 ({email or "research@example.com"})',
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers.update(headers)

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        """CORE's search returns full work records, so fetch in one pass."""
        if not self.token:
            print("CORE: CORE_API_KEY env var not set; skipping source")
            return []

        articles = []
        offset = 0
        page_size = min(100, max_results)  # CORE caps page size at 100
        retries_429 = 0

        while len(articles) < max_results:
            n = min(page_size, max_results - len(articles))
            try:
                r = self.session.get(
                    f"{self.BASE_URL}/search/works",
                    params={"q": query, "limit": n, "offset": offset},
                    timeout=30,
                )
                if r.status_code == 429:
                    retries_429 += 1
                    if retries_429 > self.MAX_429_RETRIES:
                        print(f"CORE: giving up after {self.MAX_429_RETRIES} consecutive 429s")
                        break
                    retry_after = r.headers.get("Retry-After", "")
                    time.sleep(int(retry_after) if retry_after.isdigit() else 3 * retries_429)
                    continue
                retries_429 = 0
                r.raise_for_status()

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
                time.sleep(0.5)
            except Exception as e:
                print(f"CORE fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_work(self, work: Dict) -> Optional[Dict]:
        try:
            article_id = str(work.get("id") or "").strip()
            title = (work.get("title") or "").strip()
            abstract = (work.get("abstract") or "").strip()
            # Skip records without an abstract — the embeddings need text.
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

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        # Unused: search_and_fetch already returns full records in one pass.
        return []
