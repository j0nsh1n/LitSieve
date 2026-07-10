"""
Zenodo Fetcher
CERN open science platform — publications, preprints, datasets across all fields
Free API, no authentication required
"""

import time
import requests
from typing import List, Dict
from base_fetcher import BaseFetcher


class ZenodoFetcher(BaseFetcher):
    SOURCE_NAME = 'zenodo'
    BASE_URL = 'https://zenodo.org/api/records'

    def __init__(self, email: str = None):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = (
            f'LiteratureSearchTool/1.0 ({email or "research@example.com"})'
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        page = 1
        per_page = min(100, max_results)

        while len(articles) < max_results:
            n = min(per_page, max_results - len(articles))
            try:
                r = self.session.get(
                    self.BASE_URL,
                    params={
                        'q': query,
                        'size': n,
                        'page': page,
                        'type': 'publication',
                        'status': 'published',
                    },
                    timeout=30
                )
                r.raise_for_status()
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
                time.sleep(0.3)
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

            # Strip any HTML tags from description
            import re
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

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        return []
