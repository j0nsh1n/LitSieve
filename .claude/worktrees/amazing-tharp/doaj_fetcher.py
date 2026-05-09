"""
DOAJ Fetcher
Directory of Open Access Journals — peer-reviewed open access across all fields
Free API, no authentication required
"""

import time
import requests
from typing import List, Dict
from base_fetcher import BaseFetcher


class DOAJFetcher(BaseFetcher):
    SOURCE_NAME = 'doaj'
    BASE_URL = 'https://doaj.org/api/v3/search/articles'

    def __init__(self, email: str = None):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = (
            f'LiteratureSearchTool/1.0 ({email or "research@example.com"})'
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        page = 1
        page_size = min(100, max_results)

        while len(articles) < max_results:
            n = min(page_size, max_results - len(articles))
            try:
                r = self.session.get(
                    f'{self.BASE_URL}/{requests.utils.quote(query)}',
                    params={'page': page, 'pageSize': n},
                    timeout=30
                )
                r.raise_for_status()
                data = r.json()
                results = data.get('results', [])
                if not results:
                    break
                for result in results:
                    article = self._parse_result(result)
                    if article:
                        articles.append(article)
                if len(results) < n:
                    break
                page += 1
                time.sleep(0.3)
            except Exception as e:
                print(f"DOAJ fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_result(self, result: Dict) -> Dict:
        try:
            bib = result.get('bibjson', {})
            title = (bib.get('title') or '').strip()
            abstract = (bib.get('abstract') or '').strip()
            if not title or not abstract:
                return None

            authors = []
            for a in bib.get('author', []):
                name = (a.get('name') or '').strip()
                if name:
                    authors.append(name)

            year = (bib.get('year') or '').strip()

            journal = ''
            journal_info = bib.get('journal', {})
            if journal_info:
                journal = (journal_info.get('title') or '').strip()

            return {
                'article_id': result.get('id', ''),
                'source': 'doaj',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
            }
        except Exception as e:
            print(f"DOAJ parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        return []
