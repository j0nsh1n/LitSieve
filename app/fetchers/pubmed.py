"""
PubMed Fetcher Module
Fetches research articles from PubMed using the Entrez API
"""

import socket
from typing import Dict, List, Optional

from Bio import Entrez
from tqdm import tqdm

from app.fetchers.base import BaseFetcher, polite_sleep

# Entrez uses urllib under the hood, which has no default timeout. Without this,
# a stalled NCBI connection hangs the worker thread indefinitely.
socket.setdefaulttimeout(30)


class PubMedFetcher(BaseFetcher):
    """Fetches articles from PubMed database"""

    SOURCE_NAME = "pubmed"

    def __init__(self, email: str = "user@example.com", api_key: Optional[str] = None):
        """
        Initialize PubMed fetcher

        Args:
            email: Your email (required by NCBI)
            api_key: Optional NCBI API key for higher rate limits
        """
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key

    def search(self, query: str, max_results: int = 1000) -> List[str]:
        """Search PubMed and return list of PMIDs"""
        print(f"Searching PubMed for: '{query}'")

        try:
            handle = Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=max_results,
                sort="relevance"
            )
            record = Entrez.read(handle)
            handle.close()

            pmids = record["IdList"]
            print(f"Found {len(pmids)} articles")
            return pmids

        except Exception as e:
            print(f"Error searching PubMed: {e}")
            return []

    def fetch_details(self, ids: List[str], batch_size: int = 200) -> List[Dict]:
        """Fetch article details for given PMIDs"""
        articles = []

        for i in tqdm(range(0, len(ids), batch_size), desc="Fetching abstracts"):
            batch = ids[i:i + batch_size]

            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=batch,
                    rettype="xml",
                    retmode="xml"
                )
                records = Entrez.read(handle)
                handle.close()

                for record in records['PubmedArticle']:
                    article = self._parse_article(record)
                    if article:
                        articles.append(article)

                polite_sleep(0.5)

            except Exception as e:
                print(f"Error fetching batch: {e}")
                continue

        print(f"Successfully fetched {len(articles)} articles")
        return articles

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

            pub_date = article.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {})
            year = pub_date.get('Year', 'Unknown')

            authors = []
            author_list = article.get('AuthorList', [])
            for author in author_list[:5]:
                last_name = author.get('LastName', '')
                initials = author.get('Initials', '')
                if last_name:
                    authors.append(f"{last_name} {initials}".strip())

            journal = article.get('Journal', {}).get('Title', 'Unknown journal')

            return {
                'article_id': pmid,
                'source': self.SOURCE_NAME,
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal
            }

        except Exception as e:
            print(f"Error parsing article: {e}")
            return None
