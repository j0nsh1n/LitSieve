"""
Semantic Scholar Fetcher
Covers all academic disciplines — broad cross-domain coverage
Free API, no key required for basic use (rate limited)
"""

from typing import Dict, List

from base_fetcher import BaseFetcher, FetchError, HttpClient


class SemanticScholarFetcher(BaseFetcher):
    SOURCE_NAME = 'semanticscholar'
    BASE_URL = 'https://api.semanticscholar.org/graph/v1'
    FIELDS = 'paperId,title,abstract,year,authors,venue'

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.5,
            user_agent=f'LiteratureResearchAide/3.7 ({email or "research@example.com"})',
        )

    def search(self, query: str, max_results: int = 500) -> List[str]:
        ids = []
        limit = 100
        offset = 0

        while len(ids) < max_results:
            n = min(limit, max_results - len(ids))
            try:
                r = self.http.get(
                    f'{self.BASE_URL}/paper/search',
                    params={'query': query, 'limit': n, 'offset': offset, 'fields': 'paperId'},
                )
                papers = r.json().get('data', [])
                if not papers:
                    break
                ids.extend(p['paperId'] for p in papers if p.get('paperId'))
                if len(papers) < n:
                    break
                offset += n
            except FetchError as e:
                print(f"Semantic Scholar search error: {e}")
                raise
            except Exception as e:
                print(f"Semantic Scholar search error: {e}")
                break

        return ids[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        articles = []
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            try:
                r = self.http.post(
                    f'{self.BASE_URL}/paper/batch',
                    params={'fields': self.FIELDS},
                    json={'ids': batch},
                )
                for paper in r.json():
                    if paper is None:
                        continue
                    article = self._parse_paper(paper)
                    if article:
                        articles.append(article)
            except FetchError as e:
                print(f"Semantic Scholar fetch error: {e}")
                raise
            except Exception as e:
                print(f"Semantic Scholar fetch error: {e}")

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
