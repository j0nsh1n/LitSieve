"""
OpenAlex Fetcher
Fetches scholarly works from OpenAlex API
"""

import logging
import os
from typing import Dict, List, Optional

from app.fetchers.base import BaseFetcher, HttpClient, json_of, reraise_fetch_error

logger = logging.getLogger(__name__)


class OpenAlexFetcher(BaseFetcher):
    """Fetches scholarly works from OpenAlex"""

    SOURCE_NAME = "openalex"
    BASE_URL = "https://api.openalex.org"

    def __init__(self, email: Optional[str] = None, **kwargs):
        """Email is optional but gets you into the polite pool"""
        self.email = email

        self.http = HttpClient(delay=0.2)


    def _add_identity(self, params: Dict) -> None:
        """Send the API key (when the host has one) and the student's email (when given)."""
        api_key = os.getenv("OPENALEX_API_KEY", "").strip()
        if api_key:
            params["api_key"] = api_key
        if self.email:
            params["mailto"] = self.email

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search OpenAlex, return work IDs"""
        logger.info("Searching OpenAlex for: '%s'", query)
        ids = []
        page = 1
        per_page = min(max_results, 200)

        while len(ids) < max_results:
            params = {
                "search": query,
                "filter": "has_abstract:true,type:article",
                "per_page": per_page,
                "page": page,
            }
            self._add_identity(params)

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                data = json_of(resp)

                results = data.get("results", [])
                if not results:
                    break

                for work in results:
                    openalex_id = work.get("id", "").replace("https://openalex.org/", "")
                    if openalex_id:
                        ids.append(openalex_id)

                if len(results) < per_page:
                    break
                page += 1

            except Exception as e:
                reraise_fetch_error(e)
                logger.exception("Error searching OpenAlex: %s", e)
                break

        logger.info("Found %s works", len(ids[:max_results]))
        return ids[:max_results]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Optimized: OpenAlex search returns full records"""
        logger.info("Searching OpenAlex for: '%s'", query)
        articles = []
        page = 1
        per_page = min(max_results, 200)

        while len(articles) < max_results:
            params = {
                "search": query,
                "filter": "has_abstract:true,type:article",
                "per_page": per_page,
                "page": page,
            }
            self._add_identity(params)

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                results = json_of(resp).get("results", [])

                if not results:
                    break

                for work in results:
                    parsed = self._parse_work(work)
                    if parsed:
                        articles.append(parsed)

                if len(results) < per_page:
                    break
                page += 1

            except Exception as e:
                reraise_fetch_error(e, articles)
                logger.exception("Error fetching from OpenAlex: %s", e)
                break

        logger.info("Successfully fetched %s works", len(articles[:max_results]))
        return articles[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 50) -> List[Dict]:
        """Fetch work details by OpenAlex IDs"""
        articles = []

        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            id_filter = "|".join(batch)

            params = {
                "filter": f"openalex_id:{id_filter}",
                "per_page": batch_size,
            }
            self._add_identity(params)

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                for work in json_of(resp).get("results", []):
                    parsed = self._parse_work(work)
                    if parsed:
                        articles.append(parsed)
            except Exception as e:
                reraise_fetch_error(e, articles)
                logger.exception("Error fetching batch: %s", e)

        logger.info("Successfully fetched %s works", len(articles))
        return articles

    def _parse_work(self, work: Dict) -> Optional[Dict]:
        """Parse an OpenAlex work record"""
        openalex_id = work.get("id", "").replace("https://openalex.org/", "")
        title = work.get("title", "No title")

        if not title:
            return None

        # Reconstruct abstract from inverted index
        abstract_inv = work.get("abstract_inverted_index", {})
        if not abstract_inv:
            return None
        abstract = self._reconstruct_abstract(abstract_inv)
        if not abstract:
            return None

        year = str(work.get("publication_year") or "")

        # Journal
        journal = self._venue(work)

        # Authors
        authors = []
        for authorship in work.get("authorships") or []:
            name = authorship.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)

        return {
            "article_id": openalex_id,
            "source": self.SOURCE_NAME,
            "title": title,
            "abstract": abstract,
            "year": year,
            "authors": authors,
            "journal": journal,
        }

    @staticmethod
    def _venue(work: Dict) -> str:
        """Prefer a journal or conference over repositories and e-book platforms.

        The primary location is often a repository such as PubMed while the
        journal sits further down `locations`. When every location is a
        repository, the name the record was deposited under is usually the
        journal (live W2340941041: "PubMed" vs "Heart disease and stroke ...").
        """
        locations = [work.get("primary_location") or {}, *(work.get("locations") or [])]
        for location in locations:
            source = (location or {}).get("source") or {}
            name = (source.get("display_name") or "").strip()
            if name and source.get("type") not in ("repository", "ebook-platform"):
                return name
        for location in locations:
            source = (location or {}).get("source") or {}
            if source.get("type") == "ebook-platform":
                continue
            raw = ((location or {}).get("raw_source_name") or "").strip()
            if raw:
                return raw
        return ""

    @staticmethod
    def _reconstruct_abstract(inverted_index: Dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index format"""
        if not inverted_index:
            return ""
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(word for _, word in word_positions)
