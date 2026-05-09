"""
NASA ADS Fetcher
NASA Astrophysics Data System — astronomy, astrophysics, physics, geosciences
Requires API token (free at https://ui.adsabs.harvard.edu/user/settings/token)
"""

import os
import time
import requests
from typing import List, Dict
from base_fetcher import BaseFetcher


class NASAADSFetcher(BaseFetcher):
    SOURCE_NAME = 'nasa_ads'
    BASE_URL = 'https://api.adsabs.harvard.edu/v1/search/query'

    def __init__(self, email: str = None):
        token = os.getenv('NASA_ADS_TOKEN', '')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token}',
            'User-Agent': f'LiteratureSearchTool/1.0 ({email or "research@example.com"})',
        })

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        start = 0
        rows = min(200, max_results)

        while len(articles) < max_results:
            n = min(rows, max_results - len(articles))
            try:
                r = self.session.get(
                    self.BASE_URL,
                    params={
                        'q': query,
                        'fl': 'title,abstract,author,year,bibcode,pub',
                        'rows': n,
                        'start': start,
                        'fq': 'abstract:*',
                    },
                    timeout=30
                )
                r.raise_for_status()
                data = r.json()
                docs = data.get('response', {}).get('docs', [])
                if not docs:
                    break
                for doc in docs:
                    article = self._parse_doc(doc)
                    if article:
                        articles.append(article)
                if len(docs) < n:
                    break
                start += len(docs)
                time.sleep(0.2)
            except Exception as e:
                print(f"NASA ADS fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_doc(self, doc: Dict) -> Dict:
        try:
            title_list = doc.get('title') or []
            title = (title_list[0] if title_list else '').strip()
            abstract = (doc.get('abstract') or '').strip()
            if not title or not abstract:
                return None

            authors = doc.get('author') or []
            year = str(doc.get('year') or '').strip()
            journal = (doc.get('pub') or '').strip()
            bibcode = (doc.get('bibcode') or '').strip()

            return {
                'article_id': bibcode,
                'source': 'nasa_ads',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
            }
        except Exception as e:
            print(f"NASA ADS parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        return []
