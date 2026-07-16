"""
OpenAlex Fetcher
Fetches scholarly works from OpenAlex API
"""

from typing import List, Dict, Optional
from tqdm import tqdm

from base_fetcher import BaseFetcher, HttpClient, FetchError


class OpenAlexFetcher(BaseFetcher):
    """Fetches scholarly works from OpenAlex"""

    SOURCE_NAME = "openalex"
    BASE_URL = "https://api.openalex.org"

    def __init__(self, email: str = None, **kwargs):
        """Email is optional but gets you into the polite pool"""
        self.email = email

        self.http = HttpClient(delay=0.2)


    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search OpenAlex, return work IDs"""
        print(f"Searching OpenAlex for: '{query}'")
        ids = []
        page = 1
        per_page = min(max_results, 200)

        while len(ids) < max_results:
            params = {
                "search": query,
                "filter": "has_abstract:true,type:article",
                "per_page": per_page,
                "page": page,
            }
            if self.email:
                params["mailto"] = self.email

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                data = resp.json()

                results = data.get("results", [])
                if not results:
                    break

                for work in results:
                    openalex_id = work.get("id", "").replace("https://openalex.org/", "")
                    if openalex_id:
                        ids.append(openalex_id)

                page += 1

            except Exception as e:
                print(f"Error searching OpenAlex: {e}")
                break

        print(f"Found {len(ids[:max_results])} works")
        return ids[:max_results]

    def search_and_fetch(self, query: str, max_results: int = 1000) -> List[Dict]:
        """Optimized: OpenAlex search returns full records"""
        print(f"Searching OpenAlex for: '{query}'")
        articles = []
        page = 1
        per_page = min(max_results, 200)

        while len(articles) < max_results:
            params = {
                "search": query,
                "filter": "has_abstract:true,type:article",
                "per_page": per_page,
                "page": page,
            }
            if self.email:
                params["mailto"] = self.email

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                results = resp.json().get("results", [])

                if not results:
                    break

                for work in results:
                    parsed = self._parse_work(work)
                    if parsed:
                        articles.append(parsed)

                page += 1

            except Exception as e:
                print(f"Error fetching from OpenAlex: {e}")
                break

        print(f"Successfully fetched {len(articles[:max_results])} works")
        return articles[:max_results]

    def fetch_details(self, ids: List[str], batch_size: int = 50) -> List[Dict]:
        """Fetch work details by OpenAlex IDs"""
        articles = []

        for i in tqdm(range(0, len(ids), batch_size), desc="Fetching from OpenAlex"):
            batch = ids[i:i + batch_size]
            id_filter = "|".join(batch)

            params = {
                "filter": f"openalex_id:{id_filter}",
                "per_page": batch_size,
            }
            if self.email:
                params["mailto"] = self.email

            try:
                resp = self.http.get(f"{self.BASE_URL}/works", params=params, timeout=30)
                for work in resp.json().get("results", []):
                    parsed = self._parse_work(work)
                    if parsed:
                        articles.append(parsed)
            except Exception as e:
                print(f"Error fetching batch: {e}")

        print(f"Successfully fetched {len(articles)} works")
        return articles

    def _parse_work(self, work: Dict) -> Optional[Dict]:
        """Parse an OpenAlex work record"""
        openalex_id = work.get("id", "").replace("https://openalex.org/", "")
        title = work.get("title", "No title")

        if not title:
            return None

        # Reconstruct abstract from inverted index
        abstract_inv = work.get("abstract_inverted_index", {})
        if not abstract_inv:
            return None
        abstract = self._reconstruct_abstract(abstract_inv)
        if not abstract:
            return None

        year = str(work.get("publication_year", "Unknown"))

        # Journal
        primary_location = work.get("primary_location", {}) or {}
        source_info = primary_location.get("source", {}) or {}
        journal = source_info.get("display_name", "Unknown journal")

        # Authors
        authors = []
        for authorship in work.get("authorships", [])[:5]:
            name = authorship.get("author", {}).get("display_name", "")
            if name:
                authors.append(name)

        return {
            "article_id": openalex_id,
            "source": self.SOURCE_NAME,
            "title": title,
            "abstract": abstract,
            "year": year,
            "authors": authors,
            "journal": journal,
        }

    @staticmethod
    def _reconstruct_abstract(inverted_index: Dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index format"""
        if not inverted_index:
            return ""
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(word for _, word in word_positions)
