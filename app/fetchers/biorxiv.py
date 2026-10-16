"""
bioRxiv / medRxiv preprint fetchers.

The servers' own API (api.biorxiv.org) lists posts by date with no search,
30 per request, about 300 posts a day, so scanning it cannot find a topic.
Europe PMC indexes both servers' preprints with full-text search and
abstracts, so these sources search Europe PMC limited to one server.

No API key required.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.fetchers.base import FetchError
from app.fetchers.europepmc import EuropePMCFetcher


class _RxivFetcher(EuropePMCFetcher):
    """Shared logic for bioRxiv and medRxiv."""

    SOURCE_NAME = "biorxiv"
    PUBLISHER = "bioRxiv"

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        scoped = f'({query}) AND SRC:PPR AND PUBLISHER:"{self.PUBLISHER}"'
        articles = self._search_core(scoped, max_results)
        if not articles:
            raise FetchError(
                f"No {self.PUBLISHER} preprints matched your query.", kind="no_results"
            )
        return articles

    def _parse_article(self, record: Dict) -> Optional[Dict]:
        article = super()._parse_article(record)
        doi = (record.get("doi") or "").strip()
        if not article or not doi:
            return None
        # Keyed by DOI, as papers stored before the Europe PMC route were.
        article["article_id"] = doi
        article["journal"] = f"{self.PUBLISHER} preprint"
        return article


class BioRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "biorxiv"
    PUBLISHER = "bioRxiv"


class MedRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "medrxiv"
    PUBLISHER = "medRxiv"
