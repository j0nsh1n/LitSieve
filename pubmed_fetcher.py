"""
PubMed Fetcher Module
Fetches research articles from PubMed using the Entrez API
"""

from Bio import Entrez
import time
import json
from typing import List, Dict, Optional
from tqdm import tqdm


class PubMedFetcher:
    """Fetches articles from PubMed database"""
    
    def __init__(self, email: str, api_key: Optional[str] = None):
        """
        Initialize PubMed fetcher
        
        Args:
            email: Your email (required by NCBI)
            api_key: Optional NCBI API key for higher rate limits
        """
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key
        
    def search_pubmed(self, query: str, max_results: int = 1000) -> List[str]:
        """
        Search PubMed and return list of PMIDs
        
        Args:
            query: Search query (e.g., "machine learning healthcare")
            max_results: Maximum number of results to return
            
        Returns:
            List of PubMed IDs
        """
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
    
    def fetch_abstracts(self, pmids: List[str], batch_size: int = 200) -> List[Dict]:
        """
        Fetch article details (title, abstract, etc.) for given PMIDs
        
        Args:
            pmids: List of PubMed IDs
            batch_size: Number of articles to fetch per request
            
        Returns:
            List of article dictionaries with metadata
        """
        articles = []
        
        # Process in batches to avoid overwhelming the API
        for i in tqdm(range(0, len(pmids), batch_size), desc="Fetching abstracts"):
            batch = pmids[i:i + batch_size]
            
            try:
                handle = Entrez.efetch(
                    db="pubmed",
                    id=batch,
                    rettype="xml",
                    retmode="xml"
                )
                records = Entrez.read(handle)
                handle.close()
                
                # Parse each article
                for record in records['PubmedArticle']:
                    article = self._parse_article(record)
                    if article:
                        articles.append(article)
                
                # Be nice to NCBI servers
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error fetching batch: {e}")
                continue
        
        print(f"Successfully fetched {len(articles)} articles")
        return articles
    
    def _parse_article(self, record: Dict) -> Optional[Dict]:
        """Parse a PubMed article record"""
        try:
            article = record['MedlineCitation']['Article']
            
            # Extract PMID
            pmid = str(record['MedlineCitation']['PMID'])
            
            # Extract title
            title = article.get('ArticleTitle', 'No title')
            
            # Extract abstract
            abstract_parts = article.get('Abstract', {}).get('AbstractText', [])
            if isinstance(abstract_parts, list):
                abstract = ' '.join([str(part) for part in abstract_parts])
            else:
                abstract = str(abstract_parts)
            
            # Skip articles without abstracts
            if not abstract or abstract == 'No abstract':
                return None
            
            # Extract publication date
            pub_date = article.get('Journal', {}).get('JournalIssue', {}).get('PubDate', {})
            year = pub_date.get('Year', 'Unknown')
            
            # Extract authors
            authors = []
            author_list = article.get('AuthorList', [])
            for author in author_list[:5]:  # First 5 authors
                last_name = author.get('LastName', '')
                initials = author.get('Initials', '')
                if last_name:
                    authors.append(f"{last_name} {initials}".strip())
            
            # Extract journal name
            journal = article.get('Journal', {}).get('Title', 'Unknown journal')
            
            return {
                'pmid': pmid,
                'title': title,
                'abstract': abstract,
                'year': year,
                'authors': authors,
                'journal': journal
            }
            
        except Exception as e:
            print(f"Error parsing article: {e}")
            return None
    
    def fetch_and_save(self, query: str, max_results: int, output_file: str):
        """
        Complete workflow: search, fetch, and save to JSON
        
        Args:
            query: Search query
            max_results: Maximum number of results
            output_file: Path to save JSON file
        """
        # Search for articles
        pmids = self.search_pubmed(query, max_results)
        
        if not pmids:
            print("No articles found")
            return
        
        # Fetch article details
        articles = self.fetch_abstracts(pmids)
        
        # Save to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, indent=2, ensure_ascii=False)
        
        print(f"Saved {len(articles)} articles to {output_file}")


# Example usage
if __name__ == "__main__":
    # Initialize fetcher (replace with your email)
    fetcher = PubMedFetcher(email="your.email@example.com")
    
    # Example: Fetch machine learning + healthcare papers
    fetcher.fetch_and_save(
        query="machine learning healthcare",
        max_results=100,
        output_file="pubmed_articles.json"
    )
