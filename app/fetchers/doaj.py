"""
DOAJ Fetcher
Directory of Open Access Journals — peer-reviewed open access across all fields
Free API, no authentication required
"""

from typing import Dict, List
from urllib.parse import quote

from app.fetchers.base import BaseFetcher, FetchError, HttpClient


class DOAJFetcher(BaseFetcher):
    SOURCE_NAME = 'doaj'
    BASE_URL = 'https://doaj.org/api/v3/search/articles'

    def __init__(self, email: str = None):
        self.http = HttpClient(
            delay=0.3,
            user_agent=f'LiteratureResearchAide/3.7 ({email or "research@example.com"})',
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        page = 1
        page_size = min(100, max_results)

        while len(articles) < max_results:
            n = min(page_size, max_results - len(articles))
            try:
                r = self.http.get(
                    f'{self.BASE_URL}/{quote(query)}',
                    params={'page': page, 'pageSize': n},
                )
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
            except FetchError as e:
                print(f"DOAJ fetch error: {e}")
                raise
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

            year = str(bib.get('year') or '').strip()

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
