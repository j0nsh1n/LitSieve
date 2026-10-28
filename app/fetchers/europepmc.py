"""
Europe PMC Fetcher
Fetches articles from Europe PMC REST API
"""

import logging
from datetime import date
from typing import Dict, List, Mapping, Optional, Tuple

from app.fetchers.base import (
    BaseFetcher,
    FetchError,
    HttpClient,
    clean_text,
    json_of,
    reraise_fetch_error,
    user_agent,
)
from app.services.work_types import (
    as_list,
    attach_work_fields,
    build_biblio,
    build_location,
    join_provider_types,
    normalize_doi,
    pick_canonical_work_type,
)

logger = logging.getLogger(__name__)


class EuropePMCFetcher(BaseFetcher):
    """Fetches articles from Europe PMC"""

    SOURCE_NAME = "europepmc"
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self, email: Optional[str] = None, **kwargs):
        self.email = email
        self.http = HttpClient(delay=0.3, user_agent=user_agent(email))

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        return [a["article_id"] for a in self.search_and_fetch(query, max_results)]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Europe PMC search with resultType=core returns full records."""
        return self._search_core(query, max_results)

    def _search_core(self, query: str, max_results: int) -> List[Dict]:
        logger.info("Searching %s for: '%s'", self.SOURCE_NAME, query)
        articles: List[Dict] = []
        page_size = min(max_results, 1000)
        cursor_mark = "*"

        while len(articles) < max_results:
            params = {
                "query": query,
                "format": "json",
                "pageSize": page_size,
                "cursorMark": cursor_mark,
                "resultType": "core",
            }
            try:
                resp = self.http.get(f"{self.BASE_URL}/search", params=params, timeout=30)
                data = json_of(resp)
            except FetchError as e:
                reraise_fetch_error(e, articles)
                raise
            except Exception as e:
                raise FetchError(
                    f"{self.SOURCE_NAME} request failed: {e}", kind="network", articles=articles
                ) from e

            results = (data.get("resultList") or {}).get("result") or []
            if not results:
                break
            for result in results:
                parsed = self._parse_article(result)
                if parsed:
                    articles.append(parsed)

            next_cursor = data.get("nextCursorMark")
            if not next_cursor or next_cursor == cursor_mark:
                break
            cursor_mark = next_cursor

        logger.info("Fetched %s articles from %s", len(articles[:max_results]), self.SOURCE_NAME)
        return articles[:max_results]

    @staticmethod
    def _year(record: Dict) -> str:
        # Some records carry a future year in every publication field (live
        # 42680123: 2028, where PubMed says 2026); then the indexing date wins.
        years = [
            str(record.get(field) or "").strip()[:4]
            for field in ("pubYear", "firstPublicationDate", "firstIndexDate", "dateOfCreation")
        ]
        years = [y for y in years if y.isdigit()]
        for year in years:
            if int(year) <= date.today().year:
                return year
        return years[0] if years else ""

    @staticmethod
    def _journal(record: Dict) -> str:
        # resultType=core puts the journal under journalInfo; lite uses journalTitle.
        journal = ((record.get("journalInfo") or {}).get("journal") or {}).get("title")
        journal = journal or record.get("journalTitle")
        if journal:
            return clean_text(journal)
        return ""

    @staticmethod
    def _authors(record: Dict) -> List[str]:
        authors = []
        for author in (record.get("authorList") or {}).get("author") or []:
            name = (author.get("fullName") or author.get("collectiveName") or "").strip()
            if name:
                authors.append(name)
        return authors

    @staticmethod
    def _pub_types(record: Dict) -> List[str]:
        raw = (record.get("pubTypeList") or {}).get("pubType")
        return [str(item).strip() for item in as_list(raw) if str(item).strip()]

    @staticmethod
    def _oa_claim(record: Dict) -> Tuple[Optional[str], Optional[str]]:
        pmcid = str(record.get("pmcid") or "").strip()
        is_oa = str(record.get("isOpenAccess") or "").strip().upper() == "Y"
        pdf = None
        html = None
        for item in as_list((record.get("fullTextUrlList") or {}).get("fullTextUrl")):
            if not isinstance(item, Mapping):
                continue
            href = str(item.get("url") or "").strip()
            if not href:
                continue
            code = str(item.get("availabilityCode") or "").upper()
            style = str(item.get("documentStyle") or "").lower()
            if code != "F":
                continue
            if style == "pdf" and not pdf:
                pdf = href
            elif not html:
                html = href
        if not (is_oa or pmcid):
            return None, None
        url = pdf or html
        if not url and pmcid:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        if not url:
            return None, None
        return "green", url

    def _parse_article(self, record: Dict) -> Optional[Dict]:
        article_id = record.get("id", "")
        title = clean_text(record.get("title"))
        abstract = clean_text(record.get("abstractText"))
        if not article_id or not title or not abstract:
            return None
        journal = self._journal(record)
        raw_types = self._pub_types(record)
        oa_status, best_oa_url = self._oa_claim(record)
        journal_info = record.get("journalInfo") or {}
        if not isinstance(journal_info, Mapping):
            journal_info = {}
        locations = []
        loc = build_location(
            url=best_oa_url,
            kind="pdf" if best_oa_url and "pdf" in best_oa_url.lower() else "fulltext",
            via=self.SOURCE_NAME,
        )
        if loc:
            locations.append(loc)
        article = {
            "article_id": article_id,
            "source": self.SOURCE_NAME,
            "title": title,
            "abstract": abstract,
            "year": self._year(record),
            "authors": self._authors(record),
            "journal": journal,
        }
        return attach_work_fields(
            article,
            self.SOURCE_NAME,
            record,
            work_type=pick_canonical_work_type("europepmc", raw_types),
            provider_type=join_provider_types(self.SOURCE_NAME, raw_types),
            doi=normalize_doi(record.get("doi")),
            container_title=journal or None,
            oa_status=oa_status,
            best_oa_url=best_oa_url,
            biblio=build_biblio(
                volume=journal_info.get("volume"),
                issue=journal_info.get("issue") or journal_info.get("issueNumber"),
                pages=record.get("pageInfo"),
                published_date=record.get("firstPublicationDate"),
                license=record.get("license"),
            ),
            locations=locations,
        )
