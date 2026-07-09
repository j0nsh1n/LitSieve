"""
Clustering and Visualization Module
Groups similar articles and creates visualizations
"""

import numpy as np
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.decomposition import PCA
from collections import Counter
from typing import List, Dict
import plotly.graph_objects as go
import plotly.express as px
from sklearn.feature_extraction.text import TfidfVectorizer


class ArticleClusterer:
    """Clusters articles based on their embeddings"""
    
    def __init__(self, n_clusters: int = 10, method: str = 'kmeans'):
        """
        Initialize clusterer
        
        Args:
            n_clusters: Number of clusters to create
            method: Clustering method ('kmeans' or 'hierarchical')
        """
        self.n_clusters = n_clusters
        self.method = method
        self.cluster_model = None
        self.labels = None
    
    def fit(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Perform clustering on embeddings
        
        Args:
            embeddings: Matrix of article embeddings
            
        Returns:
            Array of cluster labels
        """
        print(f"Clustering {len(embeddings)} articles into {self.n_clusters} clusters...")
        
        if self.method == 'kmeans':
            self.cluster_model = KMeans(
                n_clusters=self.n_clusters,
                random_state=42,
                n_init=10
            )
        elif self.method == 'hierarchical':
            self.cluster_model = AgglomerativeClustering(
                n_clusters=self.n_clusters,
                linkage='ward'
            )
        else:
            raise ValueError(f"Unknown method: {self.method}")
        
        self.labels = self.cluster_model.fit_predict(embeddings)
        
        # Print cluster distribution
        cluster_counts = Counter(self.labels)
        print(f"Cluster distribution: {dict(sorted(cluster_counts.items()))}")
        
        return self.labels
    
    def get_cluster_assignments(self) -> np.ndarray:
        """Get cluster labels"""
        if self.labels is None:
            raise ValueError("Must fit model first")
        return self.labels


class ClusterLabeler:
    """Generates human-readable labels for clusters"""

    @staticmethod
    def _overlaps(term: str, chosen: List[str]) -> bool:
        """True if term shares a word stem with any already-chosen term.

        Blocks near-duplicate picks inside one label like "cancer" alongside
        "cancer patients", or "therapy" alongside "gene therapy".
        """
        term_words = set(term.split())
        for other in chosen:
            if term_words & set(other.split()):
                return True
        return False

    @staticmethod
    def generate_tfidf_labels(
        articles_by_cluster: Dict[int, List[Dict]],
        top_n_terms: int = 3
    ) -> Dict[int, str]:
        """
        Generate cluster labels that are DISTINCT across clusters.

        Old behaviour ran TF-IDF within each cluster independently, so generic
        corpus-wide terms ("patients", "treatment") dominated every label and
        clusters looked interchangeable. This version:

        1. Builds ONE document per cluster and fits TF-IDF across those docs,
           so the idf term punishes words that appear in many clusters — the
           score now measures "how characteristic of THIS cluster vs the
           others", not just "how frequent inside it".
        2. Assigns terms round-robin with a global claimed-set, so a given
           term can appear in at most ONE cluster's label.
        3. Skips terms that share a word with a term already in the same
           label (no "cancer | cancer patients").

        Args:
            articles_by_cluster: Dictionary mapping cluster IDs to lists of articles
            top_n_terms: Number of top terms to use in label

        Returns:
            Dictionary mapping cluster IDs to label strings
        """
        cluster_ids = sorted(articles_by_cluster.keys())
        if not cluster_ids:
            return {}

        fallback = {cid: f"Cluster {cid}" for cid in cluster_ids}

        # One combined document per cluster.
        docs = [
            ' '.join(f"{a.get('title', '')} {a.get('abstract', '')}"
                     for a in articles_by_cluster[cid])
            for cid in cluster_ids
        ]

        vectorizer = TfidfVectorizer(
            max_features=2000,
            stop_words='english',
            ngram_range=(1, 2),
            sublinear_tf=True,  # tame huge clusters dominating on raw counts
        )
        try:
            tfidf = vectorizer.fit_transform(docs)  # rows = clusters
            feature_names = vectorizer.get_feature_names_out()
        except Exception as e:
            print(f"Error generating cluster labels: {e}")
            return fallback

        # Per-cluster term ranking (indices sorted by descending score).
        scores = tfidf.toarray()
        rankings = {
            cid: scores[row].argsort()[::-1]
            for row, cid in enumerate(cluster_ids)
        }

        # Round-robin claiming: each round, every cluster (largest first, so
        # big clusters don't lose all their best terms to tiny ones) claims its
        # best still-unclaimed, non-overlapping term. Global uniqueness is
        # enforced by the shared `claimed` set.
        order = sorted(cluster_ids, key=lambda c: -len(articles_by_cluster[c]))
        claimed = set()
        chosen: Dict[int, List[str]] = {cid: [] for cid in cluster_ids}
        cursor = {cid: 0 for cid in cluster_ids}

        for _round in range(top_n_terms):
            for cid in order:
                row = cluster_ids.index(cid)
                ranking = rankings[cid]
                while cursor[cid] < len(ranking):
                    idx = ranking[cursor[cid]]
                    cursor[cid] += 1
                    term = feature_names[idx]
                    if scores[row][idx] <= 0:
                        cursor[cid] = len(ranking)  # nothing meaningful left
                        break
                    if term in claimed or ClusterLabeler._overlaps(term, chosen[cid]):
                        continue
                    claimed.add(term)
                    chosen[cid].append(term)
                    break

        return {
            cid: (' | '.join(terms) if terms else fallback[cid])
            for cid, terms in chosen.items()
        }


class ClusterVisualizer:
    """Creates visualizations of clustered articles"""
    
    @staticmethod
    def reduce_dimensions(embeddings: np.ndarray, method: str = 'pca', n_components: int = 2) -> np.ndarray:
        """
        Reduce high-dimensional embeddings to 2D or 3D using PCA

        Args:
            embeddings: High-dimensional embeddings
            method: 'pca' (kept for API compatibility)
            n_components: Number of dimensions (2 or 3)

        Returns:
            Reduced embeddings
        """
        print(f"Reducing dimensions using PCA...")
        reducer = PCA(n_components=n_components, random_state=42)
        reduced = reducer.fit_transform(embeddings)
        return reduced
    
    @staticmethod
    def plot_2d_clusters(
        embeddings_2d: np.ndarray,
        labels: np.ndarray,
        cluster_labels: Dict[int, str],
        articles: List[Dict],
        save_path: str = None
    ):
        """
        Create 2D scatter plot of clusters
        
        Args:
            embeddings_2d: 2D embeddings
            labels: Cluster labels
            cluster_labels: Dictionary mapping cluster IDs to names
            articles: List of articles for hover text
            save_path: Path to save plot
        """
        # Create hover text with article titles
        hover_texts = []
        for a in articles:
            title = a.get('title') or ''
            if len(title) > 100:
                hover_texts.append(f"{title[:100]}...")
            else:
                hover_texts.append(title)
        
        # Create dataframe-like structure for plotly
        fig = go.Figure()
        
        # Plot each cluster
        unique_labels = np.unique(labels)
        colors = px.colors.qualitative.Plotly
        
        for i, cluster_id in enumerate(unique_labels):
            mask = labels == cluster_id
            cluster_name = cluster_labels.get(cluster_id, f"Cluster {cluster_id}")
            
            fig.add_trace(go.Scatter(
                x=embeddings_2d[mask, 0],
                y=embeddings_2d[mask, 1],
                mode='markers',
                name=cluster_name,
                text=[hover_texts[j] for j in range(len(hover_texts)) if mask[j]],
                hovertemplate='%{text}<extra></extra>',
                marker=dict(
                    size=8,
                    color=colors[i % len(colors)],
                    opacity=0.7
                )
            ))
        
        fig.update_layout(
            title='Article Clusters (2D Visualization)',
            xaxis_title='Dimension 1',
            yaxis_title='Dimension 2',
            hovermode='closest',
            width=1000,
            height=700
        )
        
        if save_path:
            fig.write_html(save_path)
            print(f"Saved plot to {save_path}")
        
        return fig
    
    @staticmethod
    def plot_similarity_heatmap(
        similarity_matrix: np.ndarray,
        labels: np.ndarray,
        max_display: int = 100,
        save_path: str = None
    ):
        """
        Create heatmap of similarity matrix using plotly

        Args:
            similarity_matrix: Pairwise similarity matrix
            labels: Cluster labels
            max_display: Maximum number of articles to display
            save_path: Path to save plot (saves as .html)
        """
        # Limit size for visualization
        n = min(max_display, len(similarity_matrix))
        sim_subset = similarity_matrix[:n, :n]
        labels_subset = labels[:n]

        # Sort by cluster for better visualization
        sorted_indices = np.argsort(labels_subset)
        sim_sorted = sim_subset[sorted_indices][:, sorted_indices]

        fig = go.Figure(data=go.Heatmap(
            z=sim_sorted,
            colorscale='RdYlBu_r',
            zmin=0,
            zmax=1,
            colorbar=dict(title='Cosine Similarity')
        ))

        fig.update_layout(
            title=f'Article Similarity Heatmap (First {n} articles, sorted by cluster)',
            xaxis_title='Article Index',
            yaxis_title='Article Index',
            width=800,
            height=700
        )

        if save_path:
            # Save as .html instead of .png (no kaleido dependency needed)
            html_path = save_path.replace('.png', '.html')
            fig.write_html(html_path)
            print(f"Saved heatmap to {html_path}")

        return fig
    
    @staticmethod
    def plot_cluster_summary(
        articles_by_cluster: Dict[int, List[Dict]],
        cluster_labels: Dict[int, str],
        save_path: str = None
    ):
        """
        Create bar chart showing cluster sizes
        
        Args:
            articles_by_cluster: Dictionary mapping cluster IDs to articles
            cluster_labels: Dictionary mapping cluster IDs to names
            save_path: Path to save plot
        """
        cluster_ids = sorted(articles_by_cluster.keys())
        cluster_sizes = [len(articles_by_cluster[cid]) for cid in cluster_ids]
        cluster_names = [cluster_labels.get(cid, f"Cluster {cid}") for cid in cluster_ids]
        
        fig = go.Figure(data=[
            go.Bar(
                x=cluster_names,
                y=cluster_sizes,
                text=cluster_sizes,
                textposition='auto',
            )
        ])
        
        fig.update_layout(
            title='Articles per Cluster',
            xaxis_title='Cluster',
            yaxis_title='Number of Articles',
            xaxis_tickangle=-45,
            height=500
        )
        
        if save_path:
            fig.write_html(save_path)
            print(f"Saved cluster summary to {save_path}")
        
        return fig
