"""
CrossRef Fetcher
Broad academic metadata registry — covers all academic disciplines
Free API, no authentication required (mailto improves rate limits)
"""

import logging
import re
from typing import Dict, List, Optional

from app.fetchers.base import (
    BaseFetcher,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.services.work_types import (
    biblio_json,
    build_biblio,
    build_location,
    canonical_work_type,
    extra_payload,
    normalize_doi,
    provenance_for,
    provider_type_label,
)

logger = logging.getLogger(__name__)


_JATS_TAG = re.compile(r'<[^>]+>')


class CrossRefFetcher(BaseFetcher):
    SOURCE_NAME = 'crossref'
    BASE_URL = 'https://api.crossref.org/works'

    def __init__(self, email: Optional[str] = None):
        self.email = email
        # The polite pool is chosen by the `mailto` query parameter below.
        self.http = HttpClient(delay=0.5, user_agent=user_agent(email))


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
                'select': (
                    'DOI,title,abstract,published,author,container-title,'
                    'type,ISBN,publisher,editor,link,license,volume,issue,page'
                ),
            }
            if self.email:
                params['mailto'] = self.email

            try:
                r = self.http.get(self.BASE_URL, params=params, timeout=30)
                items = json_of(r).get('message', {}).get('items', [])
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
                reraise_fetch_error(e, articles)
                logger.exception("CrossRef fetch error: %s", e)
                break

        return articles[:max_results]

    def _parse_item(self, item: Dict) -> Optional[Dict]:
        try:
            doi = item.get('DOI', '').strip()
            titles = item.get('title', [])
            title = clean_text(titles[0]) if titles else ''

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

            containers = item.get('container-title') or []
            if isinstance(containers, str):
                containers = [containers]
            cleaned_containers = [clean_text(name) for name in containers if clean_text(name)]
            journal = cleaned_containers[0] if cleaned_containers else ''
            # Crossref puts series then book when both exist; the last name is the book.
            container_title = cleaned_containers[-1] if cleaned_containers else None
            raw_type = item.get('type')
            editors = []
            for editor in item.get('editor') or []:
                if not isinstance(editor, dict):
                    continue
                name = ' '.join(
                    part for part in (editor.get('given'), editor.get('family')) if part
                ).strip()
                if name:
                    editors.append(name)
            licenses = item.get('license') or []
            license_url = None
            for entry in licenses:
                if isinstance(entry, dict) and entry.get('URL'):
                    license_url = str(entry['URL']).strip()
                    break
            isbn = item.get('ISBN') or []
            if isinstance(isbn, str):
                isbn = [isbn]
            biblio_obj = build_biblio(
                publisher=item.get('publisher'),
                volume=item.get('volume'),
                issue=item.get('issue'),
                pages=item.get('page'),
                isbn=isbn,
                editors=editors,
                published_date=self._published_date(item),
                license=license_url,
            )
            normalized_doi = normalize_doi(doi)
            article = {
                'article_id': doi,
                'source': 'crossref',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
                'work_type': canonical_work_type('crossref', raw_type),
                'provider_type': provider_type_label('crossref', raw_type),
                'doi': normalized_doi,
                'container_title': container_title,
                'host_name': None,
                'oa_status': None,
                'best_oa_url': None,
                'evidence_basis': 'abstract',
                'biblio': biblio_json(biblio_obj),
            }
            locations = []
            for link in item.get('link') or []:
                if not isinstance(link, dict):
                    continue
                loc = build_location(
                    url=link.get('URL'),
                    kind=link.get('content-type') or link.get('intended-application'),
                    via='crossref',
                )
                if loc:
                    locations.append(loc)
            article['_extra'] = extra_payload(
                'crossref',
                item,
                provenance=provenance_for('crossref', {
                    'work_type': article['work_type'],
                    'provider_type': article['provider_type'],
                    'doi': normalized_doi,
                    'container_title': container_title,
                    'evidence_basis': 'abstract',
                    'biblio': article['biblio'],
                }),
                locations=locations,
            )
            return article
        except Exception as e:
            logger.exception("CrossRef parse error: %s", e)
            return None

    @staticmethod
    def _published_date(item: Dict) -> Optional[str]:
        for key in ('published', 'published-print', 'published-online', 'issued'):
            node = item.get(key)
            if not isinstance(node, dict):
                continue
            parts = (node.get('date-parts') or [[]])
            if not parts or not parts[0]:
                continue
            year, month, day = (list(parts[0]) + [None, None, None])[:3]
            try:
                if year and month and day:
                    return f'{int(year):04d}-{int(month):02d}-{int(day):02d}'
                if year and month:
                    return f'{int(year):04d}-{int(month):02d}'
                if year:
                    return str(int(year))
            except (TypeError, ValueError):
                continue
        return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
