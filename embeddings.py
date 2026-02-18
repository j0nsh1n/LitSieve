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
        Initialize embedding model (lazy-loaded on first use)

        Args:
            model_name: Name of model to use (pubmedbert, biosentbert, specter, or general)
        """
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            if self.model_name in self.BIOMEDICAL_MODELS:
                model_path = self.BIOMEDICAL_MODELS[self.model_name]
            else:
                model_path = self.model_name
            print(f"Loading model: {model_path}")
            self._model = SentenceTransformer(model_path)
            print("Model loaded successfully")
        return self._model

    def embed_articles(self, articles: List[Dict], batch_size: int = 32) -> Dict[Tuple[str, str], np.ndarray]:
        """
        Create embeddings for a list of articles

        Args:
            articles: List of article dictionaries with 'article_id', 'source', 'title', 'abstract'
            batch_size: Number of articles to process at once

        Returns:
            Dictionary mapping (article_id, source) tuples to embedding vectors
        """
        print(f"Creating embeddings for {len(articles)} articles...")

        # Combine title and abstract for better representation
        texts = []
        keys = []

        for article in articles:
            text = f"{article['title']} {article['abstract']}"
            texts.append(text)
            keys.append((article['article_id'], article['source']))

        # Generate embeddings in batches
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True
        )

        # Create dictionary mapping (article_id, source) to embeddings
        embedding_dict = {key: emb for key, emb in zip(keys, embeddings)}

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
        article_ids: list,
        top_k: int = 10
    ) -> list:
        """
        Find most similar articles to a query

        Args:
            query_embedding: Query vector
            article_embeddings: Matrix of article embeddings
            article_ids: List of identifiers corresponding to embeddings
            top_k: Number of results to return

        Returns:
            List of (identifier, similarity_score) tuples, sorted by similarity
        """
        # Calculate cosine similarity
        query_embedding = query_embedding.reshape(1, -1)
        similarities = cosine_similarity(query_embedding, article_embeddings)[0]

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # Create results
        results = [
            (article_ids[idx], float(similarities[idx]))
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
        article_ids: list,
        threshold: float = 0.95
    ) -> list:
        """
        Find potential duplicate or highly similar articles

        Args:
            article_embeddings: Matrix of article embeddings
            article_ids: List of identifiers
            threshold: Similarity threshold for flagging duplicates

        Returns:
            List of (id1, id2, similarity) for pairs above threshold
        """
        print(f"Detecting potential duplicates (threshold: {threshold})...")

        # Calculate similarity matrix
        sim_matrix = self.calculate_similarity_matrix(article_embeddings)

        # Find pairs above threshold (excluding self-similarity)
        duplicates = []
        n = len(article_ids)

        for i in range(n):
            for j in range(i + 1, n):  # Only check upper triangle
                similarity = sim_matrix[i, j]
                if similarity >= threshold:
                    duplicates.append((
                        article_ids[i],
                        article_ids[j],
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

            if any(kw in sent_lower for kw in PICOExtractor.POPULATION_KEYWORDS):
                pico['population'].append(sentence.strip())

            if any(kw in sent_lower for kw in PICOExtractor.INTERVENTION_KEYWORDS):
                pico['intervention'].append(sentence.strip())

            if any(kw in sent_lower for kw in PICOExtractor.COMPARISON_KEYWORDS):
                pico['comparison'].append(sentence.strip())

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
