"""
Semantic Scholar Fetcher
Covers all academic disciplines — broad cross-domain coverage
Free API, no key required for basic use (rate limited)
"""

import time
import requests
from typing import List, Dict
from base_fetcher import BaseFetcher


class SemanticScholarFetcher(BaseFetcher):
    SOURCE_NAME = 'semanticscholar'
    BASE_URL = 'https://api.semanticscholar.org/graph/v1'
    FIELDS = 'paperId,title,abstract,year,authors,venue'

    def __init__(self, email: str = None):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = (
            f'LiteratureSearchTool/1.0 ({email or "research@example.com"})'
        )

    MAX_429_RETRIES = 5

    def search(self, query: str, max_results: int = 500) -> List[str]:
        ids = []
        limit = 100
        offset = 0
        retries_429 = 0

        while len(ids) < max_results:
            n = min(limit, max_results - len(ids))
            try:
                r = self.session.get(
                    f'{self.BASE_URL}/paper/search',
                    params={'query': query, 'limit': n, 'offset': offset, 'fields': 'paperId'},
                    timeout=30
                )
                if r.status_code == 429:
                    retries_429 += 1
                    if retries_429 > self.MAX_429_RETRIES:
                        print(f"Semantic Scholar: giving up after {self.MAX_429_RETRIES} consecutive 429s")
                        break
                    time.sleep(3 * retries_429)
                    continue
                retries_429 = 0
                r.raise_for_status()
                papers = r.json().get('data', [])
                if not papers:
                    break
                ids.extend(p['paperId'] for p in papers if p.get('paperId'))
                if len(papers) < n:
                    break
                offset += n
                time.sleep(0.5)
            except Exception as e:
                print(f"Semantic Scholar search error: {e}")
                break

        return ids[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        articles = []
        i = 0
        retries_429 = 0

        while i < len(ids):
            batch = ids[i:i + batch_size]
            try:
                r = self.session.post(
                    f'{self.BASE_URL}/paper/batch',
                    params={'fields': self.FIELDS},
                    json={'ids': batch},
                    timeout=30
                )
                if r.status_code == 429:
                    retries_429 += 1
                    if retries_429 > self.MAX_429_RETRIES:
                        print(f"Semantic Scholar: giving up after {self.MAX_429_RETRIES} consecutive 429s")
                        break
                    time.sleep(3 * retries_429)
                    continue
                retries_429 = 0
                r.raise_for_status()
                for paper in r.json():
                    if paper is None:
                        continue
                    article = self._parse_paper(paper)
                    if article:
                        articles.append(article)
                time.sleep(0.5)
            except Exception as e:
                print(f"Semantic Scholar fetch error: {e}")
            i += batch_size

        return articles

    def _parse_paper(self, paper: Dict) -> Dict:
        try:
            paper_id = paper.get('paperId', '')
            title = (paper.get('title') or '').strip()
            abstract = (paper.get('abstract') or '').strip()
            if not title or not abstract:
                return None
            return {
                'article_id': paper_id,
                'source': 'semanticscholar',
                'title': title,
                'abstract': abstract,
                'year': str(paper['year']) if paper.get('year') else '',
                'authors': [a['name'] for a in paper.get('authors', []) if a.get('name')],
                'journal': paper.get('venue') or '',
            }
        except Exception as e:
            print(f"Semantic Scholar parse error: {e}")
            return None
