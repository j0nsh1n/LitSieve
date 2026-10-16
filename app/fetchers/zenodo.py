"""
Zenodo Fetcher
CERN open science platform — publications, preprints, datasets across all fields
Free API, no authentication required
"""

import logging
from typing import Dict, List, Optional

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)

logger = logging.getLogger(__name__)


class ZenodoFetcher(BaseFetcher):
    SOURCE_NAME = 'zenodo'
    BASE_URL = 'https://zenodo.org/api/records'
    PAGE_SIZE = 25

    def __init__(self, email: Optional[str] = None):
        self.http = HttpClient(
            delay=0.3,
            user_agent=user_agent(email),
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        page = 1
        # Unauthenticated Zenodo caps page size at 25 (HTTP 400 above that).
        # Authenticated tokens can go higher; we stay polite at 25 for all users.
        # The size stays constant: Zenodo pages by number, so a smaller later
        # page would start inside records the earlier pages already returned.
        per_page = self.PAGE_SIZE

        while len(articles) < max_results:
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        'q': query,
                        'size': per_page,
                        'page': page,
                        'type': 'publication',
                        'status': 'published',
                    },
                )
                hits = json_of(r).get('hits', {}).get('hits', [])
                if not hits:
                    break
                for hit in hits:
                    article = self._parse_record(hit)
                    if article:
                        articles.append(article)
                if len(hits) < per_page:
                    break
                page += 1
            except FetchError as e:
                logger.exception("Zenodo fetch error: %s", e)
                reraise_fetch_error(e, articles)
            except Exception as e:
                logger.exception("Zenodo fetch error: %s", e)
                raise FetchError(
                    f"Zenodo request failed: {e}", kind="network", articles=articles[:max_results]
                ) from e

        return articles[:max_results]

    def _parse_record(self, record: Dict) -> Optional[Dict]:
        try:
            meta = record.get('metadata', {})
            title = clean_text(meta.get('title'))
            abstract = clean_text(meta.get('description'))
            if not title or not abstract:
                return None

            authors = []
            for creator in meta.get('creators', []):
                name = creator.get('name', '').strip()
                if name:
                    authors.append(name)

            pub_date = meta.get('publication_date', '')
            year = pub_date[:4] if pub_date else ''

            journal = ''
            journal_info = meta.get('journal', {})
            if journal_info:
                journal = journal_info.get('title', '') or ''
            if not journal:
                journal = meta.get('imprint', {}).get('publisher', '') or ''

            return {
                'article_id': str(record.get('id', '')),
                'source': 'zenodo',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
            }
        except Exception as e:
            logger.exception("Zenodo parse error: %s", e)
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
