"""
PLOS (Public Library of Science) open-access journal fetcher.

Free Solr API: https://api.plos.org/search
API key optional for higher rate limits (not required for classroom use).
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional

from base_fetcher import BaseFetcher, HttpClient, FetchError


class PLOSFetcher(BaseFetcher):
    SOURCE_NAME = "plos"
    BASE_URL = "https://api.plos.org/search"

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.35,
            user_agent=f"LiteratureResearchAide/4.0 ({email or 'research@example.com'})",
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        start = 0
        page_size = min(100, max_results)
        q = (query or "").strip() or "*:*"
        # Prefer title/abstract hits for classroom relevance.
        solr_q = f"title:{q} OR abstract:{q}" if q != "*:*" else q

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
                docs = (r.json().get("response") or {}).get("docs") or []
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"PLOS request failed: {e}", kind="network") from e

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
            title = (title or "").strip()
            abstract = doc.get("abstract")
            if isinstance(abstract, list):
                abstract = " ".join(str(a) for a in abstract if a)
            abstract = re.sub(r"<[^>]+>", "", (abstract or "")).strip()
            if not title or not abstract:
                return None
            authors = doc.get("author") or []
            if isinstance(authors, str):
                authors = [authors]
            authors = [str(a).strip() for a in authors if str(a).strip()]
            pub = doc.get("publication_date") or ""
            year = str(pub)[:4] if pub else ""
            journal = doc.get("journal") or "PLOS"
            if isinstance(journal, list):
                journal = journal[0] if journal else "PLOS"
            aid = (doc.get("id") or "").strip()
            if not aid:
                return None
            return {
                "article_id": aid,
                "source": "plos",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": str(journal),
            }
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        return []
