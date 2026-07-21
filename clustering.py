"""
Clustering and Visualization Module
Groups similar articles and creates visualizations
"""

import logging
from collections import Counter
from typing import Dict, List, Optional

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from sklearn.cluster import HDBSCAN, AgglomerativeClustering, KMeans
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

logger = logging.getLogger(__name__)

# When n_clusters is left unset we search this many groupings and keep the one
# that separates best. Capped again by the corpus size at fit time.
AUTO_K_MIN = 2
AUTO_K_MAX = 12
# Silhouette is O(n^2); above this many points we score on a random subsample.
SILHOUETTE_SAMPLE_CAP = 2000

# Density clustering (HDBSCAN) label for points that don't belong to any dense
# region. Surfaced to the user as a real, honest "these didn't fit" bucket.
NOISE_CLUSTER_ID = -1
NOISE_CLUSTER_LABEL = "Miscellaneous (outliers)"
# Sentence-embedding spaces are high-dim (384+); density estimation degrades
# badly there ("curse of dimensionality"), so we reduce before HDBSCAN.
# PCA is aggressive (few dims) + re-normalised: on real corpora, raw PCA output
# collapses HDBSCAN to ~2 clusters, but L2-normalising the low-dim projection
# restores the angular (cosine) separation the embeddings were built with.
DENSITY_PCA_DIMS = 5
DENSITY_UMAP_DIMS = 10


def warm_density_reducer() -> None:
    """Pre-compile UMAP's numba kernels with a tiny throwaway fit.

    The first UMAP call in a process pays ~8s of JIT compilation (measured in
    tools/bench_scale.py); without this, that lands on whichever student first
    clicks Generate Clusters after a server restart. Call from a background
    thread at startup. No-op when UMAP is not installed.
    """
    try:
        import umap

        rs = np.random.RandomState(0)
        pts = rs.normal(size=(50, 16)).astype(np.float32)
        # Mirror the production parameters so the same kernel specialisations
        # get compiled (metric/min_dist/random_state match _reduce_for_density).
        umap.UMAP(
            n_components=2, n_neighbors=10, min_dist=0.0,
            metric='cosine', random_state=0,
        ).fit(pts)
        logger.info("UMAP warm-up complete (numba kernels compiled)")
    except Exception as e:
        logger.info("UMAP warm-up skipped (%s)", type(e).__name__)


class ArticleClusterer:
    """Clusters articles based on their embeddings"""

    def __init__(self, n_clusters: Optional[int] = None, method: str = 'kmeans'):
        """
        Initialize clusterer

        Args:
            n_clusters: Number of clusters to create. Pass None (or a
                non-positive value) to auto-select the count by silhouette score.
            method: Clustering method ('kmeans' or 'hierarchical')
        """
        # Normalise "auto" sentinels (None / 0 / negative) to None.
        self.n_clusters = n_clusters if (n_clusters and n_clusters > 0) else None
        self.method = method
        self.cluster_model = None
        self.labels = None
        # Populated at fit time; lets the caller report what "Auto" resolved to.
        self.resolved_n_clusters = None

    def _build_model(self, k: int):
        if self.method == 'kmeans':
            return KMeans(n_clusters=k, random_state=42, n_init=10)
        elif self.method == 'hierarchical':
            return AgglomerativeClustering(n_clusters=k, linkage='ward')
        raise ValueError(f"Unknown method: {self.method}")

    @staticmethod
    def _reduce_for_density(embeddings: np.ndarray) -> np.ndarray:
        """Reduce dimensionality before density clustering.

        UMAP preserves local neighbourhood structure best (what HDBSCAN needs),
        so use it when installed; otherwise fall back to PCA, which is linear
        and dependency-free but still far better than clustering raw 384-dim
        vectors by density.
        """
        n_samples, n_features = embeddings.shape
        try:
            import umap  # optional; big (numba) dep, so not required
            target = min(DENSITY_UMAP_DIMS, n_features, max(2, n_samples - 1))
            logger.info("Density reduce: UMAP -> %d dims", target)
            reducer = umap.UMAP(
                n_components=target, n_neighbors=min(15, n_samples - 1),
                min_dist=0.0, metric='cosine', random_state=42,
            )
            return reducer.fit_transform(embeddings)
        except Exception as e:
            logger.info("Density reduce: PCA fallback (%s)", type(e).__name__)
            target = min(DENSITY_PCA_DIMS, n_features, max(2, n_samples - 1))
            if target >= n_features:
                return embeddings
            reduced = PCA(n_components=target, random_state=42).fit_transform(embeddings)
            # Re-normalise: restores the cosine/angular separation HDBSCAN needs
            # (raw PCA output collapses to ~2 clusters on real corpora).
            from sklearn.preprocessing import normalize
            return normalize(reduced)

    def _fit_density(self, embeddings: np.ndarray) -> np.ndarray:
        """HDBSCAN density clustering: finds the cluster count itself and marks
        points in no dense region as noise (NOISE_CLUSTER_ID)."""
        n = len(embeddings)
        reduced = self._reduce_for_density(embeddings)
        # min_cluster_size is the main knob: the smallest group we'll call a
        # topic. Scale gently with corpus size, floor at 5.
        min_cluster_size = max(5, n // 40)
        model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=max(2, min_cluster_size // 2),  # lower -> less noise
            metric='euclidean',
        )
        labels = model.fit_predict(reduced)
        n_clusters = len(set(labels) - {NOISE_CLUSTER_ID})
        n_noise = int(np.sum(labels == NOISE_CLUSTER_ID))
        logger.info("HDBSCAN: %d clusters, %d/%d points as noise (min_cluster_size=%d)",
                    n_clusters, n_noise, n, min_cluster_size)
        self.cluster_model = model
        return labels

    def _auto_select_k(self, embeddings: np.ndarray, k_max: int) -> int:
        """Pick the k in [AUTO_K_MIN, k_max] with the best silhouette score.

        Silhouette measures how well each point sits inside its own cluster vs
        the nearest other cluster (higher = cleaner separation), so it rewards
        the grouping that actually reflects structure in the data instead of a
        number the user guessed. Scored on a subsample when the corpus is large.
        """
        n = len(embeddings)
        if n <= AUTO_K_MIN:
            return max(1, n)

        # Subsample for the (expensive) silhouette evaluation only; the final
        # fit still runs on all points.
        if n > SILHOUETTE_SAMPLE_CAP:
            rng = np.random.default_rng(42)
            idx = rng.choice(n, SILHOUETTE_SAMPLE_CAP, replace=False)
            sample = embeddings[idx]
        else:
            sample = embeddings

        best_k, best_score = AUTO_K_MIN, -1.0
        for k in range(AUTO_K_MIN, k_max + 1):
            try:
                labels = self._build_model(k).fit_predict(sample)
            except Exception as e:
                logger.warning("Auto-k: fit failed at k=%d (%s)", k, e)
                continue
            if len(set(labels)) < 2:
                continue
            try:
                score = silhouette_score(sample, labels)
            except Exception:
                continue
            logger.info("Auto-k: k=%d silhouette=%.4f", k, score)
            if score > best_score:
                best_k, best_score = k, score
        logger.info("Auto-k selected %d clusters (silhouette=%.4f)", best_k, best_score)
        return best_k

    def fit(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Perform clustering on embeddings

        Args:
            embeddings: Matrix of article embeddings

        Returns:
            Array of cluster labels
        """
        n_samples = len(embeddings)

        # Density clustering finds its own cluster count (and a noise bucket),
        # so it ignores n_clusters / auto-k entirely.
        if self.method == 'hdbscan':
            self.labels = self._fit_density(embeddings)
            self.resolved_n_clusters = len(set(self.labels) - {NOISE_CLUSTER_ID})
            print(f"Cluster distribution: {dict(sorted(Counter(self.labels).items()))}")
            return self.labels

        if self.n_clusters is None:
            # Never search for more clusters than we could meaningfully support.
            k_max = min(AUTO_K_MAX, max(AUTO_K_MIN, n_samples - 1))
            k = self._auto_select_k(embeddings, k_max)
        else:
            k = min(self.n_clusters, n_samples)

        k = max(1, k)
        self.resolved_n_clusters = k
        print(f"Clustering {n_samples} articles into {k} clusters...")

        self.cluster_model = self._build_model(k)
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
        2. Only keeps human-readable tokens: ASCII letters, length >= 3. This
           drops foreign-script stop-words (κα, με, να), digits, and 2-letter
           abbreviations (gi, pl, abr) that made labels look like noise.
        3. Prefers multi-word phrases ("gut microbiota") over lone jargon words,
           which read as recognisable topics to a non-specialist.
        4. Assigns terms round-robin with a global claimed-set, so a given term
           can appear in at most ONE cluster's label, and skips terms sharing a
           word with one already in the same label.
        5. Formats the result as a Title Case phrase ("Gut Microbiota, Immune
           Response") instead of a "a | b | c" keyword dump.

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
            # Only whole words of >= 3 ASCII letters. Excludes numbers,
            # non-latin scripts, and tiny abbreviations.
            token_pattern=r"(?u)\b[A-Za-z][A-Za-z][A-Za-z]+\b",
        )
        try:
            tfidf = vectorizer.fit_transform(docs)  # rows = clusters
            feature_names = vectorizer.get_feature_names_out()
        except Exception as e:
            print(f"Error generating cluster labels: {e}")
            return fallback

        scores = tfidf.toarray()
        # Rank by a phrase-boosted score so descriptive bigrams win ties against
        # single jargon words, but judge "is this term meaningful at all" on the
        # raw score.
        is_bigram = np.array([' ' in f for f in feature_names])
        rank_scores = scores * np.where(is_bigram, 1.35, 1.0)
        rankings = {
            cid: rank_scores[row].argsort()[::-1]
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
            cid: (', '.join(t.title() for t in terms) if terms else fallback[cid])
            for cid, terms in chosen.items()
        }

    @staticmethod
    def pick_representative_titles(
        article_ids: List,
        embeddings: np.ndarray,
        labels,
        title_by_key: Dict,
    ) -> Dict[int, str]:
        """Pick the most central article's title as each cluster's headline.

        The article whose embedding is closest to its cluster's centroid is the
        most typical member, so its (real, grammatical) title is the clearest
        one-line description of what the cluster is about — far more legible to a
        non-specialist than a keyword list.

        Args:
            article_ids: list of (article_id, source) keys, aligned with rows of
                `embeddings` and entries of `labels`.
            embeddings: 2D array of article embeddings.
            labels: cluster id per article (aligned with article_ids).
            title_by_key: {(article_id, source): title}

        Returns:
            {cluster_id: representative_title}
        """
        labels = np.asarray(labels)
        titles: Dict[int, str] = {}
        for cid in set(int(x) for x in labels):
            member_idx = np.where(labels == cid)[0]
            if len(member_idx) == 0:
                continue
            centroid = embeddings[member_idx].mean(axis=0)
            # Nearest member to the centroid (Euclidean; vectors are unit-norm).
            dists = np.linalg.norm(embeddings[member_idx] - centroid, axis=1)
            best = member_idx[int(np.argmin(dists))]
            key = article_ids[best]
            title = (title_by_key.get(key) or '').strip()
            if title:
                titles[cid] = title
        return titles


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
        print("Reducing dimensions using PCA...")
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
