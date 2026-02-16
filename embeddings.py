"""
Embeddings Module
Creates semantic embeddings for articles using pre-trained models
"""

import numpy as np
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Tuple
from sklearn.metrics.pairwise import cosine_similarity
from tqdm import tqdm


class EmbeddingEngine:
    """Handles creation and comparison of semantic embeddings"""
    
    # Recommended models for biomedical text
    BIOMEDICAL_MODELS = {
        'pubmedbert': 'pritamdeka/S-PubMedBert-MS-MARCO',
        'biosentbert': 'pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb',
        'specter': 'allenai/specter',
        'general': 'sentence-transformers/all-MiniLM-L6-v2'  # Fast, general purpose
    }
    
    def __init__(self, model_name: str = 'general'):
        """
        Initialize embedding model
        
        Args:
            model_name: Name of model to use (pubmedbert, biosentbert, specter, or general)
        """
        if model_name in self.BIOMEDICAL_MODELS:
            model_path = self.BIOMEDICAL_MODELS[model_name]
        else:
            model_path = model_name  # Allow custom model paths
        
        print(f"Loading model: {model_path}")
        self.model = SentenceTransformer(model_path)
        self.model_name = model_name
        print("Model loaded successfully")
    
    def embed_articles(self, articles: List[Dict], batch_size: int = 32) -> Dict[str, np.ndarray]:
        """
        Create embeddings for a list of articles
        
        Args:
            articles: List of article dictionaries with 'pmid', 'title', 'abstract'
            batch_size: Number of articles to process at once
            
        Returns:
            Dictionary mapping PMIDs to embedding vectors
        """
        print(f"Creating embeddings for {len(articles)} articles...")
        
        # Combine title and abstract for better representation
        texts = []
        pmids = []
        
        for article in articles:
            # Create a combined text representation
            text = f"{article['title']} {article['abstract']}"
            texts.append(text)
            pmids.append(article['pmid'])
        
        # Generate embeddings in batches
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        
        # Create dictionary mapping PMIDs to embeddings
        embedding_dict = {pmid: emb for pmid, emb in zip(pmids, embeddings)}
        
        print(f"Created embeddings of shape: {embeddings.shape}")
        return embedding_dict
    
    def embed_query(self, query_text: str) -> np.ndarray:
        """
        Create embedding for a single query text
        
        Args:
            query_text: Text to embed (e.g., user's study description)
            
        Returns:
            Embedding vector
        """
        embedding = self.model.encode(query_text, convert_to_numpy=True)
        return embedding
    
    def find_similar(
        self,
        query_embedding: np.ndarray,
        article_embeddings: np.ndarray,
        article_pmids: List[str],
        top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """
        Find most similar articles to a query
        
        Args:
            query_embedding: Query vector
            article_embeddings: Matrix of article embeddings
            article_pmids: List of PMIDs corresponding to embeddings
            top_k: Number of results to return
            
        Returns:
            List of (pmid, similarity_score) tuples, sorted by similarity
        """
        # Calculate cosine similarity
        query_embedding = query_embedding.reshape(1, -1)
        similarities = cosine_similarity(query_embedding, article_embeddings)[0]
        
        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]
        
        # Create results
        results = [
            (article_pmids[idx], float(similarities[idx]))
            for idx in top_indices
        ]
        
        return results
    
    def calculate_similarity_matrix(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Calculate pairwise similarity matrix for all embeddings
        
        Args:
            embeddings: Matrix of embeddings
            
        Returns:
            Similarity matrix
        """
        return cosine_similarity(embeddings)
    
    def detect_duplicates(
        self,
        article_embeddings: np.ndarray,
        article_pmids: List[str],
        threshold: float = 0.95
    ) -> List[Tuple[str, str, float]]:
        """
        Find potential duplicate or highly similar articles
        
        Args:
            article_embeddings: Matrix of article embeddings
            article_pmids: List of PMIDs
            threshold: Similarity threshold for flagging duplicates
            
        Returns:
            List of (pmid1, pmid2, similarity) for pairs above threshold
        """
        print(f"Detecting potential duplicates (threshold: {threshold})...")
        
        # Calculate similarity matrix
        sim_matrix = self.calculate_similarity_matrix(article_embeddings)
        
        # Find pairs above threshold (excluding self-similarity)
        duplicates = []
        n = len(article_pmids)
        
        for i in range(n):
            for j in range(i + 1, n):  # Only check upper triangle
                similarity = sim_matrix[i, j]
                if similarity >= threshold:
                    duplicates.append((
                        article_pmids[i],
                        article_pmids[j],
                        float(similarity)
                    ))
        
        # Sort by similarity
        duplicates.sort(key=lambda x: x[2], reverse=True)
        
        print(f"Found {len(duplicates)} potential duplicate pairs")
        return duplicates


class PICOExtractor:
    """Simple rule-based PICO (Population, Intervention, Comparison, Outcome) extractor"""
    
    # Common PICO keywords
    POPULATION_KEYWORDS = [
        'patients', 'participants', 'subjects', 'adults', 'children',
        'elderly', 'men', 'women', 'cohort', 'sample'
    ]
    
    INTERVENTION_KEYWORDS = [
        'treatment', 'therapy', 'intervention', 'drug', 'medication',
        'procedure', 'surgery', 'training', 'program'
    ]
    
    COMPARISON_KEYWORDS = [
        'versus', 'vs', 'compared', 'placebo', 'control', 'standard care'
    ]
    
    OUTCOME_KEYWORDS = [
        'outcome', 'mortality', 'survival', 'efficacy', 'effectiveness',
        'improvement', 'reduction', 'increase', 'change'
    ]
    
    @staticmethod
    def extract_pico(text: str) -> Dict[str, List[str]]:
        """
        Extract PICO elements from text using keyword matching
        
        Args:
            text: Abstract or study description
            
        Returns:
            Dictionary with PICO components
        """
        text_lower = text.lower()
        sentences = text.split('.')
        
        pico = {
            'population': [],
            'intervention': [],
            'comparison': [],
            'outcome': []
        }
        
        # Simple keyword-based extraction
        for sentence in sentences:
            sent_lower = sentence.lower()
            
            # Check for population keywords
            if any(kw in sent_lower for kw in PICOExtractor.POPULATION_KEYWORDS):
                pico['population'].append(sentence.strip())
            
            # Check for intervention keywords
            if any(kw in sent_lower for kw in PICOExtractor.INTERVENTION_KEYWORDS):
                pico['intervention'].append(sentence.strip())
            
            # Check for comparison keywords
            if any(kw in sent_lower for kw in PICOExtractor.COMPARISON_KEYWORDS):
                pico['comparison'].append(sentence.strip())
            
            # Check for outcome keywords
            if any(kw in sent_lower for kw in PICOExtractor.OUTCOME_KEYWORDS):
                pico['outcome'].append(sentence.strip())
        
        return pico
    
    @staticmethod
    def pico_to_text(pico: Dict[str, List[str]]) -> str:
        """Convert PICO dictionary to formatted text"""
        parts = []
        
        for component, sentences in pico.items():
            if sentences:
                parts.append(f"{component.upper()}: {' '.join(sentences[:2])}")
        
        return '\n'.join(parts)


# Example usage
if __name__ == "__main__":
    # Create some sample articles
    sample_articles = [
        {
            'pmid': '12345',
            'title': 'Machine learning for disease prediction',
            'abstract': 'This study uses machine learning algorithms to predict disease outcomes in patients.'
        },
        {
            'pmid': '67890',
            'title': 'Deep learning in medical imaging',
            'abstract': 'Deep neural networks are applied to analyze medical images for cancer detection.'
        }
    ]
    
    # Initialize embedding engine
    engine = EmbeddingEngine(model_name='general')
    
    # Create embeddings
    embeddings = engine.embed_articles(sample_articles)
    
    # Create query embedding
    query = "Using AI to diagnose diseases from patient data"
    query_emb = engine.embed_query(query)
    
    # Find similar articles
    pmids = list(embeddings.keys())
    emb_matrix = np.array([embeddings[pmid] for pmid in pmids])
    
    results = engine.find_similar(query_emb, emb_matrix, pmids, top_k=2)
    print(f"Most similar articles: {results}")
