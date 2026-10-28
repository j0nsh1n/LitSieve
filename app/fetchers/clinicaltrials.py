"""
ClinicalTrials.gov Fetcher
Fetches clinical trial records from the ClinicalTrials.gov v2 API
"""

import logging
from typing import Dict, List, Optional

from app.fetchers.base import BaseFetcher, HttpClient, json_of, reraise_fetch_error
from app.services.work_types import attach_work_fields, join_provider_types

logger = logging.getLogger(__name__)


class ClinicalTrialsFetcher(BaseFetcher):
    """Fetches clinical trial records from ClinicalTrials.gov"""

    SOURCE_NAME = "clinicaltrials"
    BASE_URL = "https://clinicaltrials.gov/api/v2"

    def __init__(self, email: Optional[str] = None, **kwargs):
        self.email = email

        self.http = HttpClient(delay=0.3)


    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search ClinicalTrials.gov, return NCT IDs"""
        logger.info("Searching ClinicalTrials.gov for: '%s'", query)
        ids = []
        page_token = None

        while len(ids) < max_results:
            params = {
                "query.term": query,
                "pageSize": min(max_results - len(ids), 100),
                "format": "json",
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = self.http.get(f"{self.BASE_URL}/studies", params=params, timeout=30)
                data = json_of(resp)

                studies = data.get("studies", [])
                if not studies:
                    break

                for study in studies:
                    nct_id = study.get("protocolSection", {}).get(
                        "identificationModule", {}
                    ).get("nctId", "")
                    if nct_id:
                        ids.append(nct_id)

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            except Exception as e:
                reraise_fetch_error(e)
                logger.exception("Error searching ClinicalTrials.gov: %s", e)
                break

        logger.info("Found %s studies", len(ids[:max_results]))
        return ids[:max_results]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Optimized: search returns enough data to parse directly"""
        logger.info("Searching ClinicalTrials.gov for: '%s'", query)
        articles = []
        page_token = None

        while len(articles) < max_results:
            params = {
                "query.term": query,
                "pageSize": min(max_results - len(articles), 100),
                "format": "json",
            }
            if page_token:
                params["pageToken"] = page_token

            try:
                resp = self.http.get(f"{self.BASE_URL}/studies", params=params, timeout=30)
                data = json_of(resp)

                studies = data.get("studies", [])
                if not studies:
                    break

                for study in studies:
                    parsed = self._parse_study(study)
                    if parsed:
                        articles.append(parsed)

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            except Exception as e:
                reraise_fetch_error(e, articles)
                logger.exception("Error fetching from ClinicalTrials.gov: %s", e)
                break

        logger.info("Successfully fetched %s studies", len(articles[:max_results]))
        return articles[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 50) -> List[Dict]:
        """Fetch study details for given NCT IDs"""
        articles = []

        for nct_id in ids:
            try:
                resp = self.http.get(
                    f"{self.BASE_URL}/studies/{nct_id}",
                    params={"format": "json"},
                    timeout=30
                )
                parsed = self._parse_study(json_of(resp))
                if parsed:
                    articles.append(parsed)
            except Exception as e:
                reraise_fetch_error(e, articles)
                logger.exception("Error fetching %s: %s", nct_id, e)

        logger.info("Successfully fetched %s studies", len(articles))
        return articles

    def _parse_study(self, record: Dict) -> Optional[Dict]:
        """Parse a ClinicalTrials.gov study record"""
        try:
            proto = record.get("protocolSection", {})
            ident = proto.get("identificationModule", {})
            desc = proto.get("descriptionModule", {})

            nct_id = ident.get("nctId", "")
            title = ident.get("briefTitle", ident.get("officialTitle", "No title"))

            # Use detailed description or brief summary as abstract
            abstract = desc.get("detailedDescription", desc.get("briefSummary", ""))
            if not abstract:
                return None

            # Year from start date
            status = proto.get("statusModule", {})
            start_date = status.get("startDateStruct", {}).get("date", "")
            year = start_date[:4] if start_date and len(start_date) >= 4 else ""

            # Investigators as authors
            contacts = proto.get("contactsLocationsModule", {})
            authors = []
            for person in contacts.get("overallOfficials", []):
                name = person.get("name", "")
                if name:
                    authors.append(name)

            article = {
                "article_id": nct_id,
                "source": self.SOURCE_NAME,
                "title": title,
                "abstract": abstract,
                "year": str(year),
                "authors": authors,
                "journal": "ClinicalTrials.gov",
            }
            return attach_work_fields(
                article,
                self.SOURCE_NAME,
                record,
                work_type="registry-record",
                provider_type=join_provider_types(self.SOURCE_NAME, "registry-record"),
                doi=None,
                container_title=None,
                host_name="ClinicalTrials.gov",
            )

        except Exception as e:
            logger.exception("Error parsing study: %s", e)
            return None
