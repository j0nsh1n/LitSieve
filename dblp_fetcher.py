"""
DBLP computer-science bibliography fetcher.

Free JSON API: https://dblp.org/search/publ/api
No key required. Records are title/venue-centric — abstracts are usually
absent, so we synthesize a short abstract from title+venue so the rest of
the pipeline (which requires abstract text) can still embed and search.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any

from base_fetcher import BaseFetcher, HttpClient, FetchError


class DBLPFetcher(BaseFetcher):
    SOURCE_NAME = "dblp"
    BASE_URL = "https://dblp.org/search/publ/api"

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.4,
            user_agent=f"LiteratureResearchAide/4.0 ({email or 'research@example.com'})",
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        # API max h is typically 1000; stay moderate for classroom use.
        page_size = min(100, max_results)
        first = 0
        while len(articles) < max_results:
            n = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "q": query,
                        "format": "json",
                        "h": n,
                        "f": first,
                    },
                )
                data = r.json()
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"DBLP request failed: {e}", kind="network") from e

            hits = (data.get("result") or {}).get("hits") or {}
            hit_list = hits.get("hit") or []
            if isinstance(hit_list, dict):
                hit_list = [hit_list]
            if not hit_list:
                break
            for hit in hit_list:
                art = self._parse(hit)
                if art:
                    articles.append(art)
            if len(hit_list) < n:
                break
            first += len(hit_list)
        if not articles:
            raise FetchError("No DBLP publications matched your query.", kind="no_results")
        return articles[:max_results]

    def _parse(self, hit: Dict) -> Optional[Dict]:
        try:
            info = hit.get("info") or {}
            title = (info.get("title") or "").strip().rstrip(".")
            if not title:
                return None
            key = (info.get("key") or hit.get("@id") or "").strip()
            if not key:
                return None
            year = str(info.get("year") or "")[:4]
            venue = (info.get("venue") or info.get("journal") or "").strip()
            # Authors: list of dicts or single dict
            authors: List[str] = []
            auth = (info.get("authors") or {}).get("author")
            if isinstance(auth, list):
                for a in auth:
                    if isinstance(a, dict):
                        name = (a.get("text") or "").strip()
                    else:
                        name = str(a).strip()
                    if name:
                        authors.append(name)
            elif isinstance(auth, dict):
                name = (auth.get("text") or "").strip()
                if name:
                    authors.append(name)
            elif isinstance(auth, str) and auth.strip():
                authors.append(auth.strip())

            # DBLP rarely provides abstracts — synthesize so embeddings can run.
            abstract = (
                f"{title}. "
                f"Computer science publication indexed by DBLP"
                f"{f' in {venue}' if venue else ''}"
                f"{f' ({year})' if year else ''}. "
                "No abstract was provided by DBLP; matching uses title and venue only."
            )
            return {
                "article_id": key,
                "source": "dblp",
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": venue or "DBLP",
            }
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]
