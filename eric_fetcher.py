"""
ERIC Fetcher
Education Resources Information Center — US Dept of Education
Covers: education, psychology, social sciences, history, literature
Free API, no authentication required
"""

from typing import List, Dict
from base_fetcher import BaseFetcher, HttpClient, FetchError


class ERICFetcher(BaseFetcher):
    SOURCE_NAME = 'eric'
    BASE_URL = 'https://api.ies.ed.gov/eric/'

    def __init__(self, email: str = None):
        self.email = email
        self.http = HttpClient(delay=0.3)

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        rows = min(200, max_results)
        start = 0

        while len(articles) < max_results:
            n = min(rows, max_results - len(articles))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={
                        'search': query,
                        'fields': 'id,title,description,publicationdateyear,author,source',
                        'format': 'json',
                        'rows': n,
                        'start': start,
                    },
                )
                docs = r.json().get('response', {}).get('docs', [])
                if not docs:
                    break
                for doc in docs:
                    article = self._parse_doc(doc)
                    if article:
                        articles.append(article)
                if len(docs) < n:
                    break
                start += len(docs)
            except FetchError as e:
                print(f"ERIC fetch error: {e}")
                raise
            except Exception as e:
                print(f"ERIC fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_doc(self, doc: Dict) -> Dict:
        try:
            title = (doc.get('title') or '').strip()
            abstract = (doc.get('description') or '').strip()
            if not title or not abstract:
                return None

            raw_authors = doc.get('author') or ''
            if isinstance(raw_authors, list):
                authors = [a.strip() for a in raw_authors if a.strip()]
            else:
                authors = [a.strip() for a in raw_authors.split(';') if a.strip()]

            year = doc.get('publicationdateyear')
            return {
                'article_id': doc.get('id', ''),
                'source': 'eric',
                'title': title,
                'abstract': abstract,
                'year': str(year) if year else '',
                'authors': authors,
                'journal': doc.get('source', '') or '',
            }
        except Exception as e:
            print(f"ERIC parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
