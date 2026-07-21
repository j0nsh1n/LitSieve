"""
Zenodo Fetcher
CERN open science platform — publications, preprints, datasets across all fields
Free API, no authentication required
"""

import re
from typing import Dict, List

from base_fetcher import BaseFetcher, FetchError, HttpClient


class ZenodoFetcher(BaseFetcher):
    SOURCE_NAME = 'zenodo'
    BASE_URL = 'https://zenodo.org/api/records'

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.3,
            user_agent=f'LiteratureResearchAide/3.7 ({email or "research@example.com"})',
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        page = 1
        # Unauthenticated Zenodo caps page size at 25 (HTTP 400 above that).
        # Authenticated tokens can go higher; we stay polite at 25 for all users.
        per_page = min(25, max_results)

        while len(articles) < max_results:
            n = min(per_page, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        'q': query,
                        'size': n,
                        'page': page,
                        'type': 'publication',
                        'status': 'published',
                    },
                )
                hits = r.json().get('hits', {}).get('hits', [])
                if not hits:
                    break
                for hit in hits:
                    article = self._parse_record(hit)
                    if article:
                        articles.append(article)
                if len(hits) < n:
                    break
                page += 1
            except FetchError as e:
                print(f"Zenodo fetch error: {e}")
                raise
            except Exception as e:
                print(f"Zenodo fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_record(self, record: Dict) -> Dict:
        try:
            meta = record.get('metadata', {})
            title = (meta.get('title') or '').strip()
            abstract = (meta.get('description') or '').strip()
            if not title or not abstract:
                return None

            abstract = re.sub(r'<[^>]+>', '', abstract).strip()
            if not abstract:
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
            print(f"Zenodo parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
