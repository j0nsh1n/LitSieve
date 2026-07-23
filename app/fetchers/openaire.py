"""
OpenAIRE Explore publications fetcher.

Free REST API: https://api.openaire.eu/search/publications
No key for basic classroom use. Aggregates European open-access deposits.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.fetchers.base import BaseFetcher, FetchError, HttpClient


def _node_text(node: Any) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, dict):
        if "$" in node:
            return str(node["$"]).strip()
        if "text" in node:
            return str(node["text"]).strip()
        return ""
    if isinstance(node, list):
        for item in node:
            t = _node_text(item)
            if t:
                return t
        return ""
    return str(node).strip()


def _node_list_text(node: Any) -> List[str]:
    if node is None:
        return []
    if isinstance(node, list):
        out = []
        for item in node:
            t = _node_text(item)
            if t:
                out.append(t)
        return out
    t = _node_text(node)
    return [t] if t else []


class OpenAIREFetcher(BaseFetcher):
    SOURCE_NAME = "openaire"
    BASE_URL = "https://api.openaire.eu/search/publications"

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.45,
            timeout=45,
            user_agent=f"LiteratureResearchAide/4.0 ({email or 'research@example.com'})",
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles: List[Dict] = []
        page = 1
        # OpenAIRE pages can be heavy; keep page size modest.
        page_size = min(25, max_results)

        while len(articles) < max_results:
            size = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        "keywords": query,
                        "size": size,
                        "page": page,
                        "format": "json",
                    },
                )
                data = r.json()
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"OpenAIRE request failed: {e}", kind="network") from e

            results = (
                ((data.get("response") or {}).get("results") or {}).get("result")
            )
            if not results:
                break
            if isinstance(results, dict):
                results = [results]
            for res in results:
                art = self._parse(res)
                if art:
                    articles.append(art)
            if len(results) < size:
                break
            page += 1
            # Hard stop to avoid runaway pagination on huge totals
            if page > 40:
                break

        if not articles:
            raise FetchError("No OpenAIRE publications matched your query.", kind="no_results")
        return articles[:max_results]

    def _parse(self, res: Dict) -> Optional[Dict]:
        try:
            meta = (
                ((res.get("metadata") or {}).get("oaf:entity") or {}).get("oaf:result")
                or {}
            )
            if not meta:
                return None
            title = _node_text(meta.get("title"))
            abstract = _node_text(meta.get("description"))
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
            if not title or not abstract:
                return None

            authors = []
            for a in _node_list_text(meta.get("creator")):
                if a:
                    authors.append(a)
            # creator list may need special handling
            raw_creators = meta.get("creator")
            if isinstance(raw_creators, list):
                authors = []
                for c in raw_creators:
                    name = _node_text(c)
                    if name:
                        authors.append(name)
            elif isinstance(raw_creators, dict):
                name = _node_text(raw_creators)
                authors = [name] if name else []

            date = _node_text(meta.get("dateofacceptance") or meta.get("relevantdate"))
            year = date[:4] if date else ""
            journal = _node_text(meta.get("journal")) or "OpenAIRE"

            # Prefer DOI as id
            pid = meta.get("pid")
            aid = ""
            if isinstance(pid, list):
                for p in pid:
                    if isinstance(p, dict) and str(p.get("@classid", "")).lower() == "doi":
                        aid = _node_text(p)
                        break
                if not aid and pid:
                    aid = _node_text(pid[0])
            else:
                aid = _node_text(pid)
            if not aid:
                aid = _node_text(
                    ((res.get("header") or {}).get("dri:objIdentifier"))
                )
            if not aid:
                return None

            return {
                "article_id": aid,
                "source": "openaire",
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
