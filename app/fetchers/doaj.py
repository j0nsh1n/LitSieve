"""
DOAJ Fetcher
Directory of Open Access Journals — peer-reviewed open access across all fields
Free API, no authentication required
"""

import logging
from typing import Dict, List, Optional
from urllib.parse import quote

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.fetchers.querytext import lucene_safe
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


class DOAJFetcher(BaseFetcher):
    SOURCE_NAME = 'doaj'
    BASE_URL = 'https://doaj.org/api/v3/search/articles'
    PAGE_SIZE = 100

    def __init__(self, email: Optional[str] = None):
        self.http = HttpClient(
            delay=0.3,
            user_agent=user_agent(email),
        )

    def search_and_fetch(self, query: str, max_results: int = 500) -> List[Dict]:
        query = lucene_safe(query)
        if not query:
            raise FetchError("DOAJ needs search words.", kind="bad_query")
        articles = []
        page = 1
        # Constant page size: DOAJ pages by number, so a smaller later page
        # would start inside records the earlier pages already returned.
        page_size = self.PAGE_SIZE

        while len(articles) < max_results:
            try:
                r = self.http.get(
                    f'{self.BASE_URL}/{quote(query, safe="")}',
                    params={'page': page, 'pageSize': page_size},
                )
                data = json_of(r)
                results = data.get('results', [])
                if not results:
                    break
                for result in results:
                    article = self._parse_result(result)
                    if article:
                        articles.append(article)
                if len(results) < page_size:
                    break
                page += 1
            except FetchError as e:
                if (
                    e.kind == "http" and str(e).startswith("HTTP 400:")
                    and "disallowed lucene" in str(e).lower()
                ):
                    raise FetchError(
                        "DOAJ couldn't read the search words.", kind="bad_query", articles=articles
                    ) from e
                logger.exception("DOAJ fetch error: %s", e)
                reraise_fetch_error(e, articles)
            except Exception as e:
                logger.exception("DOAJ fetch error: %s", e)
                raise FetchError(
                    f"DOAJ request failed: {e}", kind="network", articles=articles[:max_results]
                ) from e

        return articles[:max_results]

    def _parse_result(self, result: Dict) -> Optional[Dict]:
        try:
            bib = result.get('bibjson', {})
            title = clean_text(bib.get('title'))
            abstract = clean_text(bib.get('abstract'))
            if not title or not abstract:
                return None

            authors = []
            for a in bib.get('author', []):
                name = (a.get('name') or '').strip()
                if name:
                    authors.append(name)

            year = str(bib.get('year') or '').strip()

            journal = ''
            journal_info = bib.get('journal', {}) or {}
            if journal_info:
                journal = (journal_info.get('title') or '').strip()
            publisher = (journal_info.get('publisher') or '').strip() or None

            doi = None
            for ident in bib.get('identifier') or []:
                if isinstance(ident, dict) and str(ident.get('type') or '').lower() == 'doi':
                    doi = normalize_doi(ident.get('id'))
                    if doi:
                        break

            fulltext_url = None
            for link in bib.get('link') or []:
                if isinstance(link, dict) and str(link.get('type') or '').lower() == 'fulltext':
                    fulltext_url = (link.get('url') or '').strip() or None
                    if fulltext_url:
                        break

            biblio_obj = build_biblio(publisher=publisher)
            article = {
                'article_id': result.get('id', ''),
                'source': 'doaj',
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal,
                'work_type': canonical_work_type('doaj', 'journal-article'),
                'provider_type': provider_type_label('doaj', 'journal-article'),
                'doi': doi,
                'container_title': journal or None,
                'host_name': None,
                'oa_status': 'gold' if fulltext_url else None,
                'best_oa_url': fulltext_url,
                'evidence_basis': 'abstract',
                'biblio': biblio_json(biblio_obj),
            }
            locations = []
            loc = build_location(url=fulltext_url, kind='fulltext', via='doaj')
            if loc:
                locations.append(loc)
            article['_extra'] = extra_payload(
                'doaj',
                result,
                provenance=provenance_for('doaj', {
                    'work_type': article['work_type'],
                    'provider_type': article['provider_type'],
                    'doi': doi,
                    'container_title': article['container_title'],
                    'oa_status': article['oa_status'],
                    'best_oa_url': fulltext_url,
                    'evidence_basis': 'abstract',
                    'biblio': article['biblio'],
                }),
                locations=locations,
            )
            return article
        except Exception as e:
            logger.exception("DOAJ parse error: %s", e)
            return None

    def search(self, query: str, max_results: int = 500) -> List[str]:
        return [a['article_id'] for a in self.search_and_fetch(query, max_results)]
