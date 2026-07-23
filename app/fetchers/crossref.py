"""
CrossRef Fetcher
Broad academic metadata registry — covers all academic disciplines
Free API, no authentication required (mailto improves rate limits)
"""

import re
from typing import Dict, List

from app.fetchers.base import BaseFetcher, HttpClient

_JATS_TAG = re.compile(r'<[^>]+>')


class CrossRefFetcher(BaseFetcher):
    SOURCE_NAME = 'crossref'
    BASE_URL = 'https://api.crossref.org/works'

    def __init__(self, email: str = None):
        self.email = email
        # Polite Pool UA improves rate limits when mailto is present.
        ua = (
            f'LiteratureResearchAide/3.7 (mailto:{email})'
            if email else 'LiteratureResearchAide/3.7'
        )
        self.http = HttpClient(delay=0.5, user_agent=ua)


    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        articles = []
        rows = min(100, max_results)
        offset = 0

        while len(articles) < max_results:
            n = min(rows, max_results - len(articles))
            params = {
                'query': query,
                'rows': n,
                'offset': offset,
                'filter': 'has-abstract:true',
                'select': 'DOI,title,abstract,published,author,container-title',
            }
            if self.email:
                params['mailto'] = self.email

            try:
                r = self.http.get(self.BASE_URL, params=params, timeout=30)
                items = r.json().get('message', {}).get('items', [])
                if not items:
                    break
                for item in items:
                    article = self._parse_item(item)
                    if article:
                        articles.append(article)
                if len(items) < n:
                    break
                offset += n
            except Exception as e:
                print(f"CrossRef fetch error: {e}")
                break

        return articles[:max_results]

    def _parse_item(self, item: Dict) -> Dict:
        try:
            doi = item.get('DOI', '').strip()
            titles = item.get('title', [])
            title = titles[0].strip() if titles else ''

            raw_abstract = item.get('abstract', '') or ''
            abstract = _JATS_TAG.sub('', raw_abstract).strip()

            if not title or not abstract:
                return None

            authors = []
            for a in item.get('author', [])[:10]:
                parts = []
                if a.get('given'):
                    parts.append(a['given'])
                if a.get('family'):
                    parts.append(a['family'])
                if parts:
                    authors.append(' '.join(parts))

            year = ''
            date_parts = item.get('published', {}).get('date-parts', [[]])
            if date_parts and date_parts[0]:
                year = str(date_parts[0][0])

            containers = item.get('container-title', [])
            journal = containers[0] if containers else ''

            return {
                'article_id': doi,
                'source': 'crossref',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
            }
        except Exception as e:
            print(f"CrossRef parse error: {e}")
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
