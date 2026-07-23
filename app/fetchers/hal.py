"""
HAL (Hyper Articles en Ligne) — French national open archive.

Free Solr API: https://api.archives-ouvertes.fr/search/
No key required. Multidisciplinary open-access / institutional deposit.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.fetchers.base import BaseFetcher, FetchError, HttpClient


class HALFetcher(BaseFetcher):
    SOURCE_NAME = "hal"
    BASE_URL = "https://api.archives-ouvertes.fr/search/"

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

        while len(articles) < max_results:
            rows = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "q": q,
                        "wt": "json",
                        "rows": rows,
                        "start": start,
                        "fl": (
                            "halId_s,title_s,abstract_s,authFullName_s,"
                            "producedDateY_i,journalTitle_s,doiId_s"
                        ),
                    },
                )
                docs = (r.json().get("response") or {}).get("docs") or []
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"HAL request failed: {e}", kind="network") from e

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
            raise FetchError("No HAL records matched your query.", kind="no_results")
        return articles[:max_results]

    @staticmethod
    def _first(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, list):
            return str(val[0]).strip() if val else ""
        return str(val).strip()

    def _parse(self, doc: Dict) -> Optional[Dict]:
        try:
            title = self._first(doc.get("title_s"))
            abstract = self._first(doc.get("abstract_s"))
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
            if not title or not abstract:
                return None
            authors = doc.get("authFullName_s") or []
            if isinstance(authors, str):
                authors = [authors]
            authors = [str(a).strip() for a in authors if str(a).strip()]
            year = doc.get("producedDateY_i")
            year = str(year) if year else ""
            journal = self._first(doc.get("journalTitle_s")) or "HAL"
            aid = self._first(doc.get("doiId_s")) or self._first(doc.get("halId_s"))
            if not aid:
                return None
            return {
                "article_id": aid,
                "source": "hal",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": journal,
            }
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
