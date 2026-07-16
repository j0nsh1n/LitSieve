"""
arXiv Fetcher
Covers physics, mathematics, computer science, quantitative biology, economics
Free API, no authentication required
"""

import xml.etree.ElementTree as ET
from typing import List, Dict, Optional
from base_fetcher import BaseFetcher, HttpClient, FetchError

ATOM_NS = 'http://www.w3.org/2005/Atom'
ARXIV_NS = 'http://arxiv.org/schemas/atom'


class ArXivFetcher(BaseFetcher):
    SOURCE_NAME = 'arxiv'
    BASE_URL = 'https://export.arxiv.org/api/query'

    def __init__(self, email: str = None):
        self.email = email

        self.http = HttpClient(delay=0.3)


    def search(self, query: str, max_results: int = 500) -> List[str]:
        ids = []
        batch = min(200, max_results)
        start = 0
        ns = {'a': ATOM_NS}

        while len(ids) < max_results:
            n = min(batch, max_results - len(ids))
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={'search_query': f'all:{query}', 'start': start, 'max_results': n},
                    timeout=30
                )
                root = ET.fromstring(r.text)
                entries = root.findall('a:entry', ns)
                if not entries:
                    break
                for entry in entries:
                    id_el = entry.find('a:id', ns)
                    if id_el is not None:
                        ids.append(id_el.text.split('/abs/')[-1].strip())
                if len(entries) < n:
                    break
                start += len(entries)
            except Exception as e:
                print(f"arXiv search error: {e}")
                break

        return ids[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 100) -> List[Dict]:
        articles = []
        ns = {'a': ATOM_NS, 'ax': ARXIV_NS}

        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            try:
                r = self.http.get(
                    self.BASE_URL,
                    params={'id_list': ','.join(batch), 'max_results': len(batch)},
                    timeout=30
                )
                root = ET.fromstring(r.text)
                for entry in root.findall('a:entry', ns):
                    article = self._parse_entry(entry, ns)
                    if article:
                        articles.append(article)
            except Exception as e:
                print(f"arXiv fetch_details error: {e}")

        return articles

    def _parse_entry(self, entry, ns) -> Optional[Dict]:
        try:
            id_el = entry.find('a:id', ns)
            if id_el is None:
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

            journal = ''
            cat_el = entry.find('ax:primary_category', ns)
            if cat_el is not None:
                journal = f"arXiv:{cat_el.get('term', '')}"

            return {
                'article_id': arxiv_id,
                'source': 'arxiv',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
            }
        except Exception as e:
            print(f"arXiv parse error: {e}")
            return None
