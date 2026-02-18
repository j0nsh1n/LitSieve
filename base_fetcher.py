"""
Base Fetcher Module
Abstract base class for all article fetchers
"""

from abc import ABC, abstractmethod
from typing import List, Dict


class BaseFetcher(ABC):
    """Abstract base for article fetchers from different sources"""

    SOURCE_NAME: str = ""

    @abstractmethod
    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search for articles and return list of source-specific IDs"""
        pass

    @abstractmethod
    def fetch_details(self, ids: List[str], batch_size: int = 200) -> List[Dict]:
        """
        Fetch article details for given IDs

        Returns:
            List of article dicts with keys:
            article_id, source, title, abstract, year, authors, journal
        """
        pass

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Complete workflow: search then fetch details"""
        ids = self.search(query, max_results)
        if not ids:
            return []
        return self.fetch_details(ids)
