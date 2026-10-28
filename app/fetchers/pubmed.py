"""
PubMed Fetcher Module
Fetches research articles from PubMed through NCBI E-utilities.

Requests go through HttpClient (timeouts, retries, the source budget and job
cancel); Biopython only parses the XML.
"""

import io
import logging
import os
import re
from typing import Any, Dict, List, Optional, cast

from Bio import Entrez

from app.fetchers.base import BaseFetcher, FetchError, HttpClient, reraise_fetch_error, user_agent
from app.services.work_types import (
    attach_work_fields,
    build_biblio,
    join_provider_types,
    normalize_doi,
    pick_canonical_work_type,
)

logger = logging.getLogger(__name__)

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def _entrez_read(content: bytes) -> Any:
    try:
        return Entrez.read(io.BytesIO(content))
    except Exception as e:
        raise FetchError(f"PubMed sent a reply that could not be read: {e}", kind="network") from e


class PubMedFetcher(BaseFetcher):
    """Fetches articles from PubMed database"""

    SOURCE_NAME = "pubmed"

    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None):
        self.email = (email or "").strip()
        self.api_key = (api_key or os.getenv("NCBI_API_KEY", "")).strip()
        # NCBI allows 3 requests a second without a key and 10 with one.
        self.http = HttpClient(delay=0.12 if self.api_key else 0.35, user_agent=user_agent(email))

    def _params(self, **params: Any) -> Dict[str, Any]:
        params.update(db="pubmed", tool="litsieve")
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search PubMed and return list of PMIDs"""
        logger.info("Searching PubMed for: '%s'", query)
        resp = self.http.get(
            f"{EUTILS}/esearch.fcgi",
            params=self._params(term=query, retmax=max_results, sort="relevance"),
        )
        record = cast(Dict[str, Any], _entrez_read(resp.content))
        pmids = [str(p) for p in record.get("IdList", [])]
        logger.info("Found %s articles", len(pmids))
        return pmids

    def fetch_details(self, ids: List[str], batch_size: int = 200) -> List[Dict]:
        """Fetch article details for given PMIDs"""
        articles: List[Dict] = []
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            try:
                resp = self.http.post(
                    f"{EUTILS}/efetch.fcgi",
                    data=self._params(id=",".join(batch), rettype="xml", retmode="xml"),
                )
                records = cast(Dict[str, List[Dict]], _entrez_read(resp.content))
            except FetchError as e:
                reraise_fetch_error(e, articles)
                raise
            for record in records.get("PubmedArticle", []):
                article = self._parse_article(record)
                if article:
                    articles.append(article)

        logger.info("Successfully fetched %s articles", len(articles))
        return articles

    @staticmethod
    def _year(article: Dict) -> str:
        pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
        year = str(pub_date.get("Year", ""))
        if year.isdigit():
            return year
        # Older records give a range such as "1990 Dec 3-17" instead of a Year.
        match = _YEAR.search(str(pub_date.get("MedlineDate", "")))
        if match:
            return match.group(1)
        for electronic in article.get("ArticleDate", []) or []:
            year = str(electronic.get("Year", ""))
            if year.isdigit():
                return year
        return ""

    @staticmethod
    def _authors(article: Dict) -> List[str]:
        authors = []
        for author in article.get("AuthorList", []):
            last_name = author.get("LastName", "")
            if last_name:
                authors.append(f"{last_name} {author.get('Initials', '')}".strip())
            elif author.get("CollectiveName"):
                authors.append(str(author["CollectiveName"]))
        return authors

    @staticmethod
    def _attr(node: Any, name: str) -> str:
        attrs = getattr(node, "attributes", None)
        if isinstance(attrs, dict) and name in attrs:
            return str(attrs[name] or "")
        if isinstance(node, dict):
            return str(node.get(name) or node.get(f"@{name}") or "")
        return ""

    def _id_of(self, nodes: Any, attr: str, wanted: str) -> str:
        for node in nodes or []:
            if self._attr(node, attr).lower() == wanted:
                return str(node).strip()
        return ""

    def _parse_article(self, record: Dict) -> Optional[Dict]:
        """Parse a PubMed article record"""
        try:
            article = record['MedlineCitation']['Article']

            pmid = str(record['MedlineCitation']['PMID'])
            title = article.get('ArticleTitle', 'No title')

            abstract_parts = article.get('Abstract', {}).get('AbstractText', [])
            if isinstance(abstract_parts, list):
                abstract = ' '.join([str(part) for part in abstract_parts])
            else:
                abstract = str(abstract_parts)

            if not abstract or abstract == 'No abstract':
                return None

            journal = str(article.get('Journal', {}).get('Title', ''))
            issue = (article.get('Journal') or {}).get('JournalIssue') or {}
            pages = str((article.get('Pagination') or {}).get('MedlinePgn') or '').strip() or None
            raw_types = [str(item) for item in (article.get('PublicationTypeList') or []) if str(item).strip()]
            doi = normalize_doi(
                self._id_of(article.get('ELocationID'), 'EIdType', 'doi')
                or self._id_of((record.get('PubmedData') or {}).get('ArticleIdList'), 'IdType', 'doi')
            )
            pmc = self._id_of((record.get('PubmedData') or {}).get('ArticleIdList'), 'IdType', 'pmc') or None
            parsed = {
                'article_id': pmid,
                'source': self.SOURCE_NAME,
                'title': str(title),
                'abstract': abstract,
                'year': self._year(article),
                'authors': self._authors(article),
                'journal': journal,
            }
            return attach_work_fields(
                parsed,
                self.SOURCE_NAME,
                {
                    'pmid': pmid,
                    'doi': doi,
                    'pmc': pmc,
                    'publication_types': raw_types,
                    'journal': journal or None,
                    'volume': str(issue.get('Volume') or '').strip() or None,
                    'issue': str(issue.get('Issue') or '').strip() or None,
                    'pages': pages,
                    'year': parsed['year'] or None,
                },
                work_type=pick_canonical_work_type(self.SOURCE_NAME, raw_types),
                provider_type=join_provider_types(self.SOURCE_NAME, raw_types),
                doi=doi,
                container_title=journal or None,
                biblio=build_biblio(
                    volume=issue.get('Volume'),
                    issue=issue.get('Issue'),
                    pages=pages,
                    published_date=parsed['year'] or None,
                ),
            )

        except Exception as e:
            logger.exception("Error parsing article: %s", e)
            return None
