"""
Embeddings Module
Creates semantic embeddings for articles using pre-trained models
Now uses FAISS for fast similarity search (v2.3.0)
"""

import numpy as np
from typing import List, Dict, Tuple
import os

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("⚠️ FAISS not installed — falling back to scikit-learn (slower for large datasets)")

from sklearn.metrics.pairwise import cosine_similarity


class EmbeddingEngine:
    """Handles creation and comparison of semantic embeddings"""

    BIOMEDICAL_MODELS = {
        'pubmedbert': 'pritamdeka/S-PubMedBert-MS-MARCO',
        'biosentbert': 'pritamdeka/BioBERT-mnli-snli-scinli-scitail-mednli-stsb',
        'specter': 'allenai/specter',
        'general': 'sentence-transformers/all-MiniLM-L6-v2'
    }

    def __init__(self, model_name: str = 'general'):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model_path = self.BIOMEDICAL_MODELS.get(self.model_name, self.model_name)
            print(f"Loading model: {model_path}")
            self._model = SentenceTransformer(model_path)
            print("Model loaded successfully")
        return self._model

    def embed_articles(self, articles: List[Dict], batch_size: int = 32, progress_callback=None) -> Dict[Tuple[str, str], np.ndarray]:
        # ... (same as before — unchanged)
        print(f"Creating embeddings for {len(articles)} articles...")

        texts = []
        keys = []
        for article in articles:
            texts.append(f"{article['title']} {article['abstract']}")
            keys.append((article['article_id'], article['source']))

        total = len(texts)
        all_embeddings = []

        for i in range(0, total, batch_size):
            batch = texts[i:i + batch_size]
            batch_emb = self.model.encode(batch, convert_to_numpy=True, show_progress_bar=False)
            all_embeddings.append(batch_emb)
            if progress_callback:
                progress_callback(min(i + batch_size, total), total)

        embeddings = np.concatenate(all_embeddings, axis=0) if all_embeddings else np.array([])
        print(f"Created embeddings of shape: {embeddings.shape}")

        return {key: emb for key, emb in zip(keys, embeddings)}

    def embed_query(self, query_text: str) -> np.ndarray:
        return self.model.encode(query_text, convert_to_numpy=True)

    def find_similar(self, query_embedding: np.ndarray, article_embeddings: np.ndarray, article_ids: list, top_k: int = 10) -> list:
        corpus_size = len(article_ids)
        if corpus_size == 0:
            return []
        top_k = min(top_k, corpus_size)

        if FAISS_AVAILABLE and len(article_embeddings) > 0:
            # Build a transient FAISS index from the supplied embeddings.
            # Defensive copy + cast to float32 so we don't mutate the caller's array
            # (faiss.normalize_L2 normalises in place).
            corpus = np.array(article_embeddings, dtype=np.float32, copy=True)
            faiss.normalize_L2(corpus)
            index = faiss.IndexFlatIP(corpus.shape[1])
            index.add(corpus)

            query = query_embedding.reshape(1, -1).astype(np.float32, copy=True)
            faiss.normalize_L2(query)
            distances, indices = index.search(query, top_k)
            results = []
            for i, idx in enumerate(indices[0]):
                if idx < 0:
                    continue
                results.append((article_ids[idx], float(distances[0][i])))
            return results
        else:
            # Fallback to scikit-learn
            query_embedding = query_embedding.reshape(1, -1)
            similarities = cosine_similarity(query_embedding, article_embeddings)[0]
            top_indices = np.argsort(similarities)[::-1][:top_k]
            return [(article_ids[idx], float(similarities[idx])) for idx in top_indices]

    # detect_duplicates, calculate_similarity_matrix remain the same (unchanged for simplicity)
    def calculate_similarity_matrix(self, embeddings: np.ndarray) -> np.ndarray:
        return cosine_similarity(embeddings)

    def detect_duplicates(self, article_embeddings: np.ndarray, article_ids: list, threshold: float = 0.95) -> list:
        # Same as your original (unchanged)
        print(f"Detecting potential duplicates (threshold: {threshold})...")
        sim_matrix = self.calculate_similarity_matrix(article_embeddings)
        duplicates = []
        n = len(article_ids)
        for i in range(n):
            for j in range(i + 1, n):
                similarity = sim_matrix[i, j]
                if similarity >= threshold:
                    duplicates.append((article_ids[i], article_ids[j], float(similarity)))
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
        sentences = (text or '').split('.')

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
