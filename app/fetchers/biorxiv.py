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
from app.services.work_types import (
    attach_work_fields,
    build_location,
    join_provider_types,
    normalize_doi,
)


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
        article["journal"] = ""
        normalized = normalize_doi(doi)
        pdf = f"https://www.{self.SOURCE_NAME}.org/content/{normalized or doi}.full.pdf"
        loc = build_location(url=pdf, kind="pdf", host=self.PUBLISHER, via=self.SOURCE_NAME)
        return attach_work_fields(
            article,
            self.SOURCE_NAME,
            record,
            work_type="preprint",
            provider_type=join_provider_types(self.SOURCE_NAME, ["preprint"]),
            doi=normalized,
            container_title=None,
            host_name=self.PUBLISHER,
            oa_status="green",
            best_oa_url=pdf,
            locations=[loc] if loc else None,
        )


class BioRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "biorxiv"
    PUBLISHER = "bioRxiv"


class MedRxivFetcher(_RxivFetcher):
    SOURCE_NAME = "medrxiv"
    PUBLISHER = "medRxiv"
