"""
Main Pipeline
Orchestrates the complete workflow from data fetching to visualization
"""

import json
import os
from typing import List, Dict, Optional, Tuple
import numpy as np

from pubmed_fetcher import PubMedFetcher
from database import ArticleDatabase
from embeddings import EmbeddingEngine, PICOExtractor
from clustering import ArticleClusterer, ClusterLabeler, ClusterVisualizer


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
        email: str = "your.email@example.com"
    ):
        """
        Step 1: Fetch articles from PubMed
        
        Args:
            query: Search query
            max_results: Maximum number of articles to fetch
            email: Your email (required by NCBI)
        """
        print("\n=== Step 1: Fetching Articles ===")
        
        # Initialize fetcher
        fetcher = PubMedFetcher(email=email)
        
        # Search and fetch
        pmids = fetcher.search_pubmed(query, max_results)
        if not pmids:
            print("No articles found")
            return
        
        articles = fetcher.fetch_abstracts(pmids)
        
        # Save to database
        self.db.insert_articles(articles)
        
        print(f"✓ Fetched and stored {len(articles)} articles")
        return articles
    
    def create_embeddings(self):
        """Step 2: Create embeddings for all articles"""
        print("\n=== Step 2: Creating Embeddings ===")
        
        # Get all articles from database
        articles = self.db.get_all_articles()
        if not articles:
            print("No articles in database. Fetch articles first.")
            return
        
        print(f"Creating embeddings for {len(articles)} articles...")
        
        # Create embeddings
        embeddings = self.embedding_engine.embed_articles(articles)
        
        # Save to database
        self.db.insert_embeddings(embeddings, self.embedding_model_name)
        
        print(f"✓ Created and stored embeddings")
        return embeddings
    
    def cluster_articles(self, n_clusters: int = 10, method: str = 'kmeans'):
        """Step 3: Cluster articles"""
        print("\n=== Step 3: Clustering Articles ===")
        
        # Get embeddings from database
        pmids, embeddings = self.db.get_all_embeddings()
        if len(pmids) == 0:
            print("No embeddings found. Create embeddings first.")
            return
        
        # Perform clustering
        clusterer = ArticleClusterer(n_clusters=n_clusters, method=method)
        labels = clusterer.fit(embeddings)

        # Build a lookup from pmid to cluster label, aligned with embeddings
        pmid_to_cluster = {pmid: int(labels[i]) for i, pmid in enumerate(pmids)}

        # Get articles that have embeddings and group by cluster
        articles = self.db.get_all_articles()
        articles_by_cluster = {}
        for article in articles:
            if article['pmid'] not in pmid_to_cluster:
                continue
            cluster_id = pmid_to_cluster[article['pmid']]
            if cluster_id not in articles_by_cluster:
                articles_by_cluster[cluster_id] = []
            articles_by_cluster[cluster_id].append(article)
        
        # Generate cluster labels
        print("Generating cluster labels...")
        cluster_labels = ClusterLabeler.generate_tfidf_labels(articles_by_cluster)
        
        # Save cluster assignments to database
        cluster_assignments = {}
        for pmid, label in zip(pmids, labels):
            cluster_id = int(label)
            cluster_label = cluster_labels.get(cluster_id, f"Cluster {cluster_id}")
            cluster_assignments[pmid] = (cluster_id, cluster_label)
        
        self.db.insert_clusters(cluster_assignments)
        
        print(f"✓ Clustered articles into {n_clusters} clusters")
        print("\nCluster labels:")
        for cluster_id, label in sorted(cluster_labels.items()):
            size = len(articles_by_cluster[cluster_id])
            print(f"  Cluster {cluster_id} ({size} articles): {label}")
        
        return labels, cluster_labels, articles_by_cluster
    
    def create_visualizations(self, output_dir: str = "visualizations"):
        """Step 4: Create visualizations"""
        print("\n=== Step 4: Creating Visualizations ===")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Get embeddings and build a pmid->index lookup
        pmids, embeddings = self.db.get_all_embeddings()

        if len(pmids) == 0:
            print("No embeddings found. Create embeddings first.")
            return

        pmid_to_emb_idx = {pmid: i for i, pmid in enumerate(pmids)}

        # Get cluster information, keeping only articles that have both embeddings and clusters
        articles_all = self.db.get_all_articles()
        articles_with_clusters = []
        labels = []
        cluster_labels = {}
        emb_indices = []

        cursor = self.db.conn.cursor()
        for article in articles_all:
            if article['pmid'] not in pmid_to_emb_idx:
                continue
            cursor.execute(
                "SELECT cluster_id, cluster_label FROM clusters WHERE pmid = ?",
                (article['pmid'],)
            )
            result = cursor.fetchone()
            if result:
                cluster_id, cluster_label = result
                labels.append(cluster_id)
                cluster_labels[cluster_id] = cluster_label
                articles_with_clusters.append(article)
                emb_indices.append(pmid_to_emb_idx[article['pmid']])

        if not labels:
            print("No clusters found. Cluster articles first.")
            return

        labels = np.array(labels)
        # Use only the embeddings that have matching clusters, in the same order
        matched_embeddings = embeddings[emb_indices]

        # Create articles by cluster dict
        articles_by_cluster = {}
        for article, label in zip(articles_with_clusters, labels):
            if label not in articles_by_cluster:
                articles_by_cluster[label] = []
            articles_by_cluster[label].append(article)

        # 1. Reduce dimensions for 2D plot
        print("Creating 2D visualization...")
        embeddings_2d = ClusterVisualizer.reduce_dimensions(matched_embeddings, method='umap', n_components=2)
        
        fig_2d = ClusterVisualizer.plot_2d_clusters(
            embeddings_2d,
            labels,
            cluster_labels,
            articles_with_clusters,
            save_path=os.path.join(output_dir, 'clusters_2d.html')
        )
        
        # 2. Create cluster summary
        print("Creating cluster summary...")
        fig_summary = ClusterVisualizer.plot_cluster_summary(
            articles_by_cluster,
            cluster_labels,
            save_path=os.path.join(output_dir, 'cluster_summary.html')
        )
        
        # 3. Create similarity heatmap
        print("Creating similarity heatmap...")
        similarity_matrix = self.embedding_engine.calculate_similarity_matrix(matched_embeddings)
        fig_heatmap = ClusterVisualizer.plot_similarity_heatmap(
            similarity_matrix,
            labels,
            max_display=100,
            save_path=os.path.join(output_dir, 'similarity_heatmap.png')
        )
        
        print(f"✓ Visualizations saved to {output_dir}")
        
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
        
        # Get embeddings from database
        pmids, article_embeddings = self.db.get_all_embeddings()
        
        if len(pmids) == 0:
            print("No embeddings found. Create embeddings first.")
            return []
        
        # Create query embedding
        query_embedding = self.embedding_engine.embed_query(query_text)
        
        # Find similar articles
        results = self.embedding_engine.find_similar(
            query_embedding,
            article_embeddings,
            pmids,
            top_k=top_k
        )
        
        # Get full article details
        similar_articles = []
        for pmid, similarity in results:
            article = self.db.get_article_by_pmid(pmid)
            if article:
                article['similarity_score'] = similarity
                similar_articles.append(article)
        
        # Print results
        print(f"Top {len(similar_articles)} most similar articles:\n")
        for i, article in enumerate(similar_articles, 1):
            print(f"{i}. [{article['similarity_score']:.3f}] {article['title']}")
            print(f"   {article['year']} | {article['journal']}")
            print(f"   PMID: {article['pmid']}\n")
        
        return similar_articles
    
    def detect_duplicates(self, threshold: float = 0.95) -> List[Tuple]:
        """
        Detect potential duplicate articles
        
        Args:
            threshold: Similarity threshold
            
        Returns:
            List of duplicate pairs
        """
        print(f"\n=== Detecting Duplicates (threshold: {threshold}) ===")
        
        pmids, embeddings = self.db.get_all_embeddings()
        
        if len(pmids) == 0:
            print("No embeddings found.")
            return []
        
        duplicates = self.embedding_engine.detect_duplicates(
            embeddings,
            pmids,
            threshold=threshold
        )
        
        # Print results
        if duplicates:
            print(f"\nFound {len(duplicates)} potential duplicate pairs:\n")
            for pmid1, pmid2, sim in duplicates[:10]:  # Show top 10
                article1 = self.db.get_article_by_pmid(pmid1)
                article2 = self.db.get_article_by_pmid(pmid2)
                print(f"[{sim:.3f}]")
                print(f"  1: {article1['title']}")
                print(f"  2: {article2['title']}\n")
        
        return duplicates
    
    def get_statistics(self) -> Dict:
        """Get database statistics"""
        return self.db.get_statistics()
    
    def close(self):
        """Close database connection"""
        self.db.close()


# Example workflow
if __name__ == "__main__":
    # Initialize pipeline
    pipeline = LiteratureSearchPipeline(
        db_path="articles.db",
        embedding_model='general'  # Use 'pubmedbert' for better biomedical performance
    )
    
    try:
        # Step 1: Fetch articles
        # pipeline.fetch_articles(
        #     query="machine learning healthcare prediction",
        #     max_results=500,
        #     email="your.email@example.com"
        # )
        
        # Step 2: Create embeddings
        # pipeline.create_embeddings()
        
        # Step 3: Cluster articles
        # pipeline.cluster_articles(n_clusters=8, method='kmeans')
        
        # Step 4: Create visualizations
        # pipeline.create_visualizations()
        
        # Search for similar articles
        query = """
        We are studying the effectiveness of deep learning models
        in predicting patient outcomes using electronic health records.
        """
        # pipeline.search_similar(query, top_k=10)
        
        # Detect duplicates
        # pipeline.detect_duplicates(threshold=0.95)
        
        # Get statistics
        stats = pipeline.get_statistics()
        print(f"\nDatabase statistics: {stats}")
        
    finally:
        pipeline.close()
