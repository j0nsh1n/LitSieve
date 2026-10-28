"""
arXiv Fetcher
Covers physics, mathematics, computer science, quantitative biology, economics
Free API, no authentication required
"""

import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from app.fetchers.base import BaseFetcher, FetchError, HttpClient, reraise_fetch_error, user_agent
from app.fetchers.terms import boolean_terms

logger = logging.getLogger(__name__)


ATOM_NS = 'http://www.w3.org/2005/Atom'
ARXIV_NS = 'http://arxiv.org/schemas/atom'


class ArXivFetcher(BaseFetcher):
    SOURCE_NAME = 'arxiv'
    BASE_URL = 'https://export.arxiv.org/api/query'
    # arXiv asks for no more than one request every three seconds.
    DELAY = 3.0

    def __init__(self, email: Optional[str] = None):
        self.email = email
        self.http = HttpClient(delay=self.DELAY, user_agent=user_agent(email))

    @staticmethod
    def search_query(query: str) -> str:
        """arXiv ORs bare words, so join them with AND (NOT becomes ANDNOT)."""
        parts: List[str] = []
        for term in boolean_terms(query):
            if term == 'NOT':
                if parts and parts[-1] == 'AND':
                    parts.pop()
                parts.append('ANDNOT')
            elif term in ('AND', 'OR'):
                parts.append(term)
            else:
                parts.append(f'all:{term}')
        return ' '.join(parts) or 'all:*'

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        """The search response already holds each entry in full; parse it directly."""
        articles: List[Dict] = []
        ns = {'a': ATOM_NS, 'ax': ARXIV_NS}
        batch = min(200, max_results)
        start = 0
        search_query = self.search_query(query)

        while len(articles) < max_results:
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={'search_query': search_query, 'start': start, 'max_results': batch},
                    timeout=30,
                )
                root = ET.fromstring(r.text)
            except FetchError as e:
                reraise_fetch_error(e, articles)
                raise
            except ET.ParseError as e:
                raise FetchError(
                    f"arXiv sent a reply that could not be read: {e}", kind="network", articles=articles
                ) from e
            entries = root.findall('a:entry', ns)
            if not entries:
                break
            for entry in entries:
                article = self._parse_entry(entry, ns)
                if article:
                    articles.append(article)
            if len(entries) < batch:
                break
            start += len(entries)

        return articles[:max_results]

    def _parse_entry(self, entry, ns) -> Optional[Dict]:
        try:
            id_el = entry.find('a:id', ns)
            if id_el is None or not id_el.text:
                return None
            arxiv_id = id_el.text.split('/abs/')[-1].strip()

            title_el = entry.find('a:title', ns)
            title = ' '.join((title_el.text or '').split()) if title_el is not None else ''

            abstract_el = entry.find('a:summary', ns)
            abstract = ' '.join((abstract_el.text or '').split()) if abstract_el is not None else ''

            if not title or not abstract:
                return None

            authors = []
            for author in entry.findall('a:author', ns):
                name_el = author.find('a:name', ns)
                if name_el is not None:
                    authors.append(name_el.text)

            year = ''
            pub_el = entry.find('a:published', ns)
            if pub_el is not None and pub_el.text:
                year = pub_el.text[:4]

            return {
                'article_id': arxiv_id,
                'source': 'arxiv',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': '',
            }
        except Exception as e:
            logger.exception("arXiv parse error: %s", e)
            return None
