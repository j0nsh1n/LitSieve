"""
bioRxiv / medRxiv preprint fetchers.

Official API (api.biorxiv.org) is date-window based, not full-text search.
We scan recent deposits (default ~60 days), filter by query tokens in
title+abstract, and stop when we have enough matches or hit a page cap.

No API key required. Good for "newest biology/medicine preprints" for students.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import List, Dict, Optional

from base_fetcher import BaseFetcher, HttpClient, FetchError


def _tokens(query: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9]{3,}", query or "") if t]


def _matches(query: str, title: str, abstract: str) -> bool:
    toks = _tokens(query)
    if not toks:
        return True
    blob = f"{title} {abstract}".lower()
    # Require all tokens for short queries; majority for long ones.
    if len(toks) <= 3:
        return all(t in blob for t in toks)
    hits = sum(1 for t in toks if t in blob)
    return hits >= max(2, (len(toks) + 1) // 2)


class _RxivFetcher(BaseFetcher):
    """Shared logic for bioRxiv and medRxiv."""

    SOURCE_NAME = "biorxiv"
    SERVER = "biorxiv"  # or medrxiv
    BASE = "https://api.biorxiv.org/details"
    LOOKBACK_DAYS = 60
    PAGE_SIZE = 100
    MAX_PAGES = 12  # scan at most ~1200 recent records per request

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.35,
            user_agent=f"LiteratureResearchAide/4.0 ({email or 'research@example.com'})",
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        end = date.today()
        start = end - timedelta(days=self.LOOKBACK_DAYS)
        interval = f"{start.isoformat()}/{end.isoformat()}"
        articles: List[Dict] = []
        cursor = 0
        pages = 0
        while len(articles) < max_results and pages < self.MAX_PAGES:
            url = f"{self.BASE}/{self.SERVER}/{interval}/{cursor}/json"
            try:
                r = self.http.get(url)
                data = r.json()
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"{self.SOURCE_NAME} request failed: {e}", kind="network") from e

            msgs = data.get("messages") or []
            if msgs and str(msgs[0].get("status", "")).lower() not in ("ok",):
                # Empty window or bad request
                break
            collection = data.get("collection") or []
            if not collection:
                break
            for rec in collection:
                art = self._parse(rec)
                if not art:
                    continue
                if not _matches(query, art["title"], art["abstract"]):
                    continue
                articles.append(art)
                if len(articles) >= max_results:
                    break
            pages += 1
            cursor += len(collection)
            # Stop if fewer than a full page (end of window)
            if len(collection) < self.PAGE_SIZE:
                break
        if not articles:
            raise FetchError(
                f"No recent {self.SOURCE_NAME} preprints matched your query "
                f"(scanned ~{self.LOOKBACK_DAYS} days of posts).",
                kind="no_results",
            )
        return articles[:max_results]

    def _parse(self, rec: Dict) -> Optional[Dict]:
        try:
            title = (rec.get("title") or "").strip()
            abstract = (rec.get("abstract") or "").strip()
            if not title or not abstract:
                return None
            abstract = re.sub(r"<[^>]+>", "", abstract).strip()
            if not abstract:
                return None
            authors_raw = rec.get("authors") or ""
            authors = [a.strip() for a in authors_raw.split(";") if a.strip()]
            doi = (rec.get("doi") or "").strip()
            if not doi:
                return None
            year = (rec.get("date") or "")[:4]
            return {
                "article_id": doi,
                "source": self.SOURCE_NAME,
                "title": title,
                "abstract": abstract,
                "year": year,
                "authors": authors,
                "journal": f"{self.SERVER} preprint",
            }
        except Exception:
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]


class BioRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "biorxiv"
    SERVER = "biorxiv"


class MedRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "medrxiv"
    SERVER = "medrxiv"
