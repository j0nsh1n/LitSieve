"""
ClinicalTrials.gov Fetcher
Fetches clinical trial records from the ClinicalTrials.gov v2 API
"""

import requests
import time
from typing import List, Dict, Optional
from tqdm import tqdm

from base_fetcher import BaseFetcher


class ClinicalTrialsFetcher(BaseFetcher):
    """Fetches clinical trial records from ClinicalTrials.gov"""

    SOURCE_NAME = "clinicaltrials"
    BASE_URL = "https://clinicaltrials.gov/api/v2"

    def __init__(self, email: str = None, **kwargs):
        self.email = email

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search ClinicalTrials.gov, return NCT IDs"""
        print(f"Searching ClinicalTrials.gov for: '{query}'")
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
                resp = requests.get(f"{self.BASE_URL}/studies", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

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
                time.sleep(0.3)

            except Exception as e:
                print(f"Error searching ClinicalTrials.gov: {e}")
                break

        print(f"Found {len(ids[:max_results])} studies")
        return ids[:max_results]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Optimized: search returns enough data to parse directly"""
        print(f"Searching ClinicalTrials.gov for: '{query}'")
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
                resp = requests.get(f"{self.BASE_URL}/studies", params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

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
                time.sleep(0.3)

            except Exception as e:
                print(f"Error fetching from ClinicalTrials.gov: {e}")
                break

        print(f"Successfully fetched {len(articles[:max_results])} studies")
        return articles[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 50) -> List[Dict]:
        """Fetch study details for given NCT IDs"""
        articles = []

        for nct_id in tqdm(ids, desc="Fetching from ClinicalTrials.gov"):
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/studies/{nct_id}",
                    params={"format": "json"},
                    timeout=30
                )
                resp.raise_for_status()
                parsed = self._parse_study(resp.json())
                if parsed:
                    articles.append(parsed)
                time.sleep(0.2)
            except Exception as e:
                print(f"Error fetching {nct_id}: {e}")

        print(f"Successfully fetched {len(articles)} studies")
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
            year = start_date[:4] if start_date and len(start_date) >= 4 else "Unknown"

            # Investigators as authors
            contacts = proto.get("contactsLocationsModule", {})
            authors = []
            for person in contacts.get("overallOfficials", [])[:5]:
                name = person.get("name", "")
                if name:
                    authors.append(name)

            # Lead sponsor as journal equivalent
            sponsor = proto.get("sponsorCollaboratorsModule", {})
            lead = sponsor.get("leadSponsor", {}).get("name", "ClinicalTrials.gov")

            return {
                "article_id": nct_id,
                "source": self.SOURCE_NAME,
                "title": title,
                "abstract": abstract,
                "year": str(year),
                "authors": authors,
                "journal": lead,
            }

        except Exception as e:
            print(f"Error parsing study: {e}")
            return None
