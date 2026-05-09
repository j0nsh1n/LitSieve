"""
Main Pipeline
Orchestrates the complete workflow from data fetching to visualization
"""

import json
import os
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import numpy as np

from pubmed_fetcher import PubMedFetcher
from europepmc_fetcher import EuropePMCFetcher
from clinicaltrials_fetcher import ClinicalTrialsFetcher
from openalex_fetcher import OpenAlexFetcher
from arxiv_fetcher import ArXivFetcher
from semanticscholar_fetcher import SemanticScholarFetcher
from eric_fetcher import ERICFetcher
from zenodo_fetcher import ZenodoFetcher
from crossref_fetcher import CrossRefFetcher
from doaj_fetcher import DOAJFetcher
from nasa_ads_fetcher import NASAADSFetcher
from database import ArticleDatabase
from embeddings import EmbeddingEngine, PICOExtractor
from clustering import ArticleClusterer, ClusterLabeler, ClusterVisualizer

FETCHERS = {
    'pubmed': PubMedFetcher,
    'europepmc': EuropePMCFetcher,
    'clinicaltrials': ClinicalTrialsFetcher,
    'openalex': OpenAlexFetcher,
    'arxiv': ArXivFetcher,
    'semanticscholar': SemanticScholarFetcher,
    'eric': ERICFetcher,
    'zenodo': ZenodoFetcher,
    'crossref': CrossRefFetcher,
    'doaj': DOAJFetcher,
    'nasa_ads': NASAADSFetcher,
}


class LiteratureSearchPipeline:
    """Complete pipeline for literature search and analysis"""

    def __init__(
        self,
        db_path: str = "articles.db",
        embedding_model: str = 'general'
    ):
        """
        Initialize pipeline

        Args:
            db_path: Path to SQLite database
            embedding_model: Name of embedding model to use
        """
        self.db_path = db_path
        self.db = ArticleDatabase(db_path)
        self.embedding_engine = EmbeddingEngine(model_name=embedding_model)
        self.embedding_model_name = embedding_model

    def fetch_articles(
        self,
        query: str,
        max_results: int = 1000,
        email: str = "your.email@example.com",
        source: str = "pubmed"
    ):
        """
        Step 1: Fetch articles from the specified source

        Args:
            query: Search query
            max_results: Maximum number of articles to fetch
            email: Your email (required by some APIs)
            source: Data source ('pubmed', 'europepmc', 'clinicaltrials', 'openalex')
        """
        print(f"\n=== Step 1: Fetching Articles from {source} ===")

        fetcher_cls = FETCHERS.get(source)
        if not fetcher_cls:
            raise ValueError(f"Unknown source: {source}. Available: {list(FETCHERS.keys())}")

        fetcher = fetcher_cls(email=email)
        articles = fetcher.search_and_fetch(query, max_results)

        if not articles:
            print("No articles found")
            return []

        # Save to database
        self.db.insert_articles(articles)

        print(f"Fetched and stored {len(articles)} articles from {source}")
        return articles

    def fetch_articles_parallel(
        self,
        query: str,
        sources: List[str],
        max_results: int = 200,
        email: str = "your.email@example.com",
        progress_callback=None,
    ) -> Dict:
        """
        Fetch from multiple sources concurrently, insert results sequentially.
        progress_callback: callable(done, total) called each time a source completes.
        """
        print(f"\n=== Fetching from {len(sources)} sources in parallel ===")
        lock = threading.Lock()
        completed = [0]
        total = len(sources)

        def fetch_one(source):
            fetcher_cls = FETCHERS.get(source)
            if not fetcher_cls:
                result = (source, [], f"Unknown source: {source}")
            else:
                try:
                    fetcher = fetcher_cls(email=email)
                    articles = fetcher.search_and_fetch(query, max_results)
                    result = (source, articles or [], None)
                except Exception as e:
                    print(f"Error fetching {source}: {e}")
                    result = (source, [], str(e))

            with lock:
                completed[0] += 1
                done = completed[0]
            if progress_callback:
                progress_callback(done, total)
            return result

        results = {}
        with ThreadPoolExecutor(max_workers=min(len(sources), 6)) as executor:
            futures = {executor.submit(fetch_one, src): src for src in sources}
            for future in as_completed(futures):
                source, articles, error = future.result()
                results[source] = {'articles': articles, 'error': error}
                print(f"  {source}: {len(articles)} articles")

        for source, data in results.items():
            if data['articles']:
                self.db.insert_articles(data['articles'])

        return {
            source: {'count': len(data['articles']), 'error': data['error']}
            for source, data in results.items()
        }

    def create_embeddings(self, progress_callback=None):
        """Step 2: Create embeddings for all articles"""
        print("\n=== Step 2: Creating Embeddings ===")

        articles = self.db.get_all_articles()
        if not articles:
            print("No articles in database. Fetch articles first.")
            return

        print(f"Creating embeddings for {len(articles)} articles...")

        embeddings = self.embedding_engine.embed_articles(articles, progress_callback=progress_callback)

        self.db.insert_embeddings(embeddings, self.embedding_model_name)

        print(f"Created and stored embeddings")
        return embeddings

    def cluster_articles(self, n_clusters: int = 10, method: str = 'kmeans'):
        """Step 3: Cluster articles"""
        print("\n=== Step 3: Clustering Articles ===")

        article_ids, embeddings = self.db.get_all_embeddings()
        if len(article_ids) == 0:
            print("No embeddings found. Create embeddings first.")
            return

        # Perform clustering
        clusterer = ArticleClusterer(n_clusters=n_clusters, method=method)
        labels = clusterer.fit(embeddings)

        # Build lookup from (article_id, source) to cluster label
        id_to_cluster = {aid: int(labels[i]) for i, aid in enumerate(article_ids)}

        # Get articles that have embeddings and group by cluster
        articles = self.db.get_all_articles()
        articles_by_cluster = {}
        for article in articles:
            key = (article['article_id'], article['source'])
            if key not in id_to_cluster:
                continue
            cluster_id = id_to_cluster[key]
            if cluster_id not in articles_by_cluster:
                articles_by_cluster[cluster_id] = []
            articles_by_cluster[cluster_id].append(article)

        # Generate cluster labels
        print("Generating cluster labels...")
        cluster_labels = ClusterLabeler.generate_tfidf_labels(articles_by_cluster)

        # Save cluster assignments to database
        cluster_assignments = {}
        for aid, label in zip(article_ids, labels):
            cluster_id = int(label)
            cluster_label = cluster_labels.get(cluster_id, f"Cluster {cluster_id}")
            cluster_assignments[aid] = (cluster_id, cluster_label)

        self.db.insert_clusters(cluster_assignments)

        print(f"Clustered articles into {n_clusters} clusters")
        print("\nCluster labels:")
        for cluster_id, label in sorted(cluster_labels.items()):
            size = len(articles_by_cluster.get(cluster_id, []))
            print(f"  Cluster {cluster_id} ({size} articles): {label}")

        return labels, cluster_labels, articles_by_cluster

    def create_visualizations(self, output_dir: str = "visualizations"):
        """Step 4: Create visualizations"""
        print("\n=== Step 4: Creating Visualizations ===")

        os.makedirs(output_dir, exist_ok=True)
        article_ids, embeddings = self.db.get_all_embeddings()

        if len(article_ids) == 0:
            print("No embeddings found. Create embeddings first.")
            return

        id_to_emb_idx = {aid: i for i, aid in enumerate(article_ids)}

        articles_all = self.db.get_all_articles()
        articles_with_clusters = []
        labels = []
        cluster_labels = {}
        emb_indices = []

        for article in articles_all:
            key = (article['article_id'], article['source'])
            if key not in id_to_emb_idx:
                continue
            cluster_info = self.db.get_cluster_for_article(article['article_id'], article['source'])
            if cluster_info:
                cluster_id = cluster_info['cluster_id']
                labels.append(cluster_id)
                cluster_labels[cluster_id] = cluster_info['cluster_label']
                articles_with_clusters.append(article)
                emb_indices.append(id_to_emb_idx[key])

        if not labels:
            print("No clusters found. Cluster articles first.")
            return

        labels = np.array(labels)
        matched_embeddings = embeddings[emb_indices]

        articles_by_cluster = {}
        for article, label in zip(articles_with_clusters, labels):
            if label not in articles_by_cluster:
                articles_by_cluster[label] = []
            articles_by_cluster[label].append(article)

        print("Creating 2D visualization...")
        embeddings_2d = ClusterVisualizer.reduce_dimensions(matched_embeddings, method='pca', n_components=2)

        fig_2d = ClusterVisualizer.plot_2d_clusters(
            embeddings_2d,
            labels,
            cluster_labels,
            articles_with_clusters,
            save_path=os.path.join(output_dir, 'clusters_2d.html')
        )

        print("Creating cluster summary...")
        fig_summary = ClusterVisualizer.plot_cluster_summary(
            articles_by_cluster,
            cluster_labels,
            save_path=os.path.join(output_dir, 'cluster_summary.html')
        )

        print("Creating similarity heatmap...")
        similarity_matrix = self.embedding_engine.calculate_similarity_matrix(matched_embeddings)
        fig_heatmap = ClusterVisualizer.plot_similarity_heatmap(
            similarity_matrix,
            labels,
            max_display=100,
            save_path=os.path.join(output_dir, 'similarity_heatmap.html')
        )

        print(f"Visualizations saved to {output_dir}")

        return {
            'clusters_2d': fig_2d,
            'summary': fig_summary,
            'heatmap': fig_heatmap
        }

    def search_similar(self, query_text: str, top_k: int = 10) -> List[Dict]:
        """
        Search for articles similar to a query

        Args:
            query_text: User's study description or search query
            top_k: Number of results to return

        Returns:
            List of similar articles with similarity scores
        """
        print(f"\n=== Searching for similar articles ===")
        print(f"Query: {query_text}\n")

        article_ids, article_embeddings = self.db.get_all_embeddings()

        if len(article_ids) == 0:
            print("No embeddings found. Create embeddings first.")
            return []

        # Create query embedding
        query_embedding = self.embedding_engine.embed_query(query_text)

        # Find similar articles
        results = self.embedding_engine.find_similar(
            query_embedding,
            article_embeddings,
            article_ids,
            top_k=top_k
        )

        # Get full article details
        similar_articles = []
        for (article_id, source), similarity in results:
            article = self.db.get_article_by_id(article_id, source)
            if article:
                article['similarity_score'] = similarity
                # Attach cluster info
                cluster_info = self.db.get_cluster_for_article(article_id, source)
                if cluster_info:
                    article['cluster_id'] = cluster_info['cluster_id']
                    article['cluster_label'] = cluster_info['cluster_label']
                else:
                    article['cluster_id'] = None
                    article['cluster_label'] = None
                similar_articles.append(article)

        # Print results
        print(f"Top {len(similar_articles)} most similar articles:\n")
        for i, article in enumerate(similar_articles, 1):
            print(f"{i}. [{article['similarity_score']:.3f}] {article['title']}")
            print(f"   {article['year']} | {article['journal']}")
            print(f"   ID: {article['article_id']} ({article['source']})\n")

        return similar_articles

    def detect_duplicates(self, threshold: float = 0.95) -> List[Tuple]:
        """
        Detect potential duplicate articles

        Args:
            threshold: Similarity threshold

        Returns:
            List of duplicate pairs: ((article_id1, source1), (article_id2, source2), similarity)
        """
        print(f"\n=== Detecting Duplicates (threshold: {threshold}) ===")

        article_ids, embeddings = self.db.get_all_embeddings()

        if len(article_ids) == 0:
            print("No embeddings found.")
            return []

        duplicates = self.embedding_engine.detect_duplicates(
            embeddings,
            article_ids,
            threshold=threshold
        )

        if duplicates:
            print(f"\nFound {len(duplicates)} potential duplicate pairs:\n")
            for id1, id2, sim in duplicates[:10]:
                article1 = self.db.get_article_by_id(*id1)
                article2 = self.db.get_article_by_id(*id2)
                print(f"[{sim:.3f}]")
                if article1:
                    print(f"  1: {article1['title']}")
                if article2:
                    print(f"  2: {article2['title']}\n")

        return duplicates

    def get_statistics(self) -> Dict:
        """Get database statistics"""
        return self.db.get_statistics()

    def close(self):
        """Close database connection"""
        self.db.close()
