"""
Semantic Scholar Fetcher
Covers all academic disciplines — broad cross-domain coverage
Free API, no key required for basic use (rate limited)
"""

import logging
import os
from typing import Dict, List, Optional

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.services.work_types import (
    attach_work_fields,
    build_biblio,
    build_location,
    join_provider_types,
    normalize_doi,
    pick_canonical_work_type,
)

logger = logging.getLogger(__name__)


class SemanticScholarFetcher(BaseFetcher):
    SOURCE_NAME = 'semanticscholar'
    BASE_URL = 'https://api.semanticscholar.org/graph/v1'
    FIELDS = (
        'paperId,title,abstract,year,authors,venue,'
        'externalIds,publicationTypes,openAccessPdf,journal,publicationDate'
    )

    def __init__(self, email: Optional[str] = None):
        # Without a key every request shares one public pool and most get 429.
        key = os.getenv('S2_API_KEY', '').strip()
        self.http = HttpClient(
            delay=1.0 if key else 0.5,
            user_agent=user_agent(email),
            headers={'x-api-key': key} if key else None,
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
                papers = json_of(r).get('data', [])
                if not papers:
                    break
                ids.extend(p['paperId'] for p in papers if p.get('paperId'))
                if len(papers) < n:
                    break
                offset += n
            except FetchError:
                raise
            except Exception as e:
                raise FetchError(f"Semantic Scholar search failed: {e}", kind="network") from e

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
                for paper in json_of(r):
                    if paper is None:
                        continue
                    article = self._parse_paper(paper)
                    if article:
                        articles.append(article)
            except FetchError as e:
                reraise_fetch_error(e, articles)
            except Exception as e:
                raise FetchError(
                    f"Semantic Scholar request failed: {e}", kind="network", articles=articles
                ) from e

        return articles

    def _parse_paper(self, paper: Dict) -> Optional[Dict]:
        try:
            paper_id = paper.get('paperId', '')
            title = (paper.get('title') or '').strip()
            abstract = (paper.get('abstract') or '').strip()
            if not title or not abstract:
                return None
            ids_raw = paper.get('externalIds')
            ids = ids_raw if isinstance(ids_raw, dict) else {}
            journal_raw = paper.get('journal')
            journal_info = journal_raw if isinstance(journal_raw, dict) else {}
            pdf_raw = paper.get('openAccessPdf')
            pdf_info = pdf_raw if isinstance(pdf_raw, dict) else {}
            venue = (paper.get('venue') or '').strip()
            journal_name = (journal_info.get('name') or '').strip()
            journal = venue or journal_name
            container = journal_name or venue or None
            raw_types = paper.get('publicationTypes') or []
            pdf_url = (pdf_info.get('url') or '').strip() or None
            loc = build_location(url=pdf_url, kind='pdf', via='semanticscholar')
            article = {
                'article_id': paper_id,
                'source': 'semanticscholar',
                'title': title,
                'abstract': abstract,
                'year': str(paper['year']) if paper.get('year') else '',
                'authors': [a['name'] for a in paper.get('authors', []) if a.get('name')],
                'journal': journal,
            }
            return attach_work_fields(
                article,
                'semanticscholar',
                paper,
                work_type=pick_canonical_work_type('semanticscholar', raw_types),
                provider_type=join_provider_types('semanticscholar', raw_types),
                doi=normalize_doi(ids.get('DOI')),
                container_title=container,
                oa_status='green' if pdf_url else None,
                best_oa_url=pdf_url,
                biblio=build_biblio(
                    volume=journal_info.get('volume'),
                    pages=journal_info.get('pages'),
                    published_date=paper.get('publicationDate'),
                ),
                locations=[loc] if loc else None,
            )
        except Exception as e:
            logger.exception("Semantic Scholar parse error: %s", e)
            return None
