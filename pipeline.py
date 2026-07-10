"""
Main Pipeline
Orchestrates the complete workflow from data fetching to visualization
"""

import logging
import os
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import numpy as np

logger = logging.getLogger(__name__)

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
from core_fetcher import COREFetcher
from database import ArticleDatabase
from embeddings import EmbeddingEngine
from clustering import (
    ArticleClusterer, ClusterLabeler, ClusterVisualizer,
    NOISE_CLUSTER_ID, NOISE_CLUSTER_LABEL,
)

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
    'core': COREFetcher,
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
        # One pipeline instance is shared across concurrent requests for the same
        # user (see the pipeline cache in main.py). This lock guards the mutable
        # embedding engine so a search can't swap the model out from under an
        # in-flight embedding job (or vice versa), which would otherwise mix
        # vectors from two different models.
        self._engine_lock = threading.Lock()

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
        logger.info(f"\n=== Step 1: Fetching Articles from {source} ===")

        fetcher_cls = FETCHERS.get(source)
        if not fetcher_cls:
            raise ValueError(f"Unknown source: {source}. Available: {list(FETCHERS.keys())}")

        fetcher = fetcher_cls(email=email)
        articles = fetcher.search_and_fetch(query, max_results)

        if not articles:
            logger.info("No articles found")
            return []

        # Save to database
        self.db.insert_articles(articles)

        logger.info(f"Fetched and stored {len(articles)} articles from {source}")
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
        logger.info(f"\n=== Fetching from {len(sources)} sources in parallel ===")
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
                    logger.error(f"Error fetching {source}: {e}")
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
                logger.info(f"  {source}: {len(articles)} articles")

        for source, data in results.items():
            if data['articles']:
                self.db.insert_articles(data['articles'])

        return {
            source: {'count': len(data['articles']), 'error': data['error']}
            for source, data in results.items()
        }

    def create_embeddings(
        self,
        model: Optional[str] = None,
        progress_callback=None,
        only_missing: bool = True,
    ):
        """Step 2: Create embeddings for articles.

        Args:
            model: If given, switch the embedding engine to this model before
                embedding. Doing the swap here (under the engine lock) keeps it
                atomic with the embedding pass, instead of mutating the shared
                pipeline from the request handler.
            only_missing: When True (default), skip articles that already have
                embeddings — much faster after an incremental fetch. If the
                requested model differs from the stored model, everything is
                re-embedded so dimensions stay consistent.
        """
        import time
        from embeddings import select_device

        logger.info("\n=== Step 2: Creating Embeddings ===")
        t0 = time.perf_counter()

        articles = self.db.get_all_articles()
        if not articles:
            logger.info("No articles in database. Fetch articles first.")
            return {
                "embeddings_created": 0,
                "skipped_existing": 0,
                "seconds": 0.0,
                "model": model or self.embedding_model_name,
                "device": select_device(),
            }

        stored_model = self.db.get_embedding_model()
        target_model = model or self.embedding_model_name
        # Switching models invalidates prior vectors (different dims/spaces).
        force_all = bool(stored_model and target_model and stored_model != target_model)
        if force_all:
            only_missing = False
            logger.info(
                "Model change %s → %s: re-embedding all articles",
                stored_model, target_model,
            )

        existing = self.db.get_embedding_keys() if only_missing else set()
        if only_missing and existing:
            to_embed = [
                a for a in articles
                if (a["article_id"], a["source"]) not in existing
            ]
            skipped = len(articles) - len(to_embed)
        else:
            to_embed = articles
            skipped = 0

        if not to_embed:
            logger.info("All articles already have embeddings; nothing to do.")
            return {
                "embeddings_created": 0,
                "skipped_existing": skipped,
                "seconds": round(time.perf_counter() - t0, 2),
                "model": stored_model or target_model,
                "device": select_device(),
            }

        logger.info(
            "Creating embeddings for %d articles (%d already embedded, skipped=%s)...",
            len(to_embed), skipped, only_missing,
        )

        # Hold the engine lock across the swap AND the embedding pass so a
        # concurrent search can't replace the engine while embed_articles runs.
        with self._engine_lock:
            if model and model != self.embedding_model_name:
                self.embedding_engine = EmbeddingEngine(model_name=model)
                self.embedding_model_name = model
            model_name = self.embedding_model_name
            embeddings = self.embedding_engine.embed_articles(
                to_embed, progress_callback=progress_callback
            )
            device = getattr(self.embedding_engine, "device", None) or select_device()

        self.db.insert_embeddings(embeddings, model_name)
        seconds = round(time.perf_counter() - t0, 2)

        logger.info("Created and stored embeddings in %.2fs on %s", seconds, device)
        return {
            "embeddings_created": len(embeddings),
            "skipped_existing": skipped,
            "seconds": seconds,
            "model": model_name,
            "device": device,
        }

    def cluster_articles(self, n_clusters: Optional[int] = None, method: str = 'kmeans'):
        """Step 3: Cluster articles.

        n_clusters=None (or <= 0) auto-selects the count by silhouette score.
        Returns (labels, cluster_labels, articles_by_cluster, resolved_n_clusters).
        """
        logger.info("\n=== Step 3: Clustering Articles ===")

        article_ids, embeddings = self.db.get_all_embeddings()
        if len(article_ids) == 0:
            logger.info("No embeddings found. Create embeddings first.")
            return

        # ArticleClusterer handles auto-selection (None) and clamping to the
        # number of samples internally.
        clusterer = ArticleClusterer(n_clusters=n_clusters, method=method)
        labels = clusterer.fit(embeddings)
        resolved_n = clusterer.resolved_n_clusters

        # Build lookup from (article_id, source) to cluster label
        id_to_cluster = {aid: int(labels[i]) for i, aid in enumerate(article_ids)}

        # Get articles that have embeddings and group by cluster
        articles = self.db.get_all_articles()
        title_by_key = {(a['article_id'], a['source']): a.get('title', '') for a in articles}
        articles_by_cluster = {}
        for article in articles:
            key = (article['article_id'], article['source'])
            if key not in id_to_cluster:
                continue
            cluster_id = id_to_cluster[key]
            if cluster_id not in articles_by_cluster:
                articles_by_cluster[cluster_id] = []
            articles_by_cluster[cluster_id].append(article)

        # Generate cluster labels + a representative (most central) title each.
        logger.info("Generating cluster labels...")
        cluster_labels = ClusterLabeler.generate_tfidf_labels(articles_by_cluster)
        cluster_titles = ClusterLabeler.pick_representative_titles(
            article_ids, embeddings, labels, title_by_key
        )
        # The HDBSCAN noise bucket isn't a coherent topic — give it an honest
        # fixed label and no representative headline.
        if NOISE_CLUSTER_ID in articles_by_cluster:
            cluster_labels[NOISE_CLUSTER_ID] = NOISE_CLUSTER_LABEL
            cluster_titles.pop(NOISE_CLUSTER_ID, None)

        # Save cluster assignments to database
        cluster_assignments = {}
        for aid, label in zip(article_ids, labels):
            cluster_id = int(label)
            cluster_label = cluster_labels.get(cluster_id, f"Cluster {cluster_id}")
            cluster_assignments[aid] = (cluster_id, cluster_label)

        self.db.insert_clusters(cluster_assignments, cluster_titles)

        logger.info(f"Clustered articles into {resolved_n} clusters")
        logger.info("\nCluster labels:")
        for cluster_id, label in sorted(cluster_labels.items()):
            size = len(articles_by_cluster.get(cluster_id, []))
            logger.info(f"  Cluster {cluster_id} ({size} articles): {label}")

        return labels, cluster_labels, articles_by_cluster, resolved_n

    def create_visualizations(self, output_dir: str = "visualizations"):
        """Step 4: Create visualizations"""
        logger.info("\n=== Step 4: Creating Visualizations ===")

        os.makedirs(output_dir, exist_ok=True)
        article_ids, embeddings = self.db.get_all_embeddings()

        if len(article_ids) == 0:
            logger.info("No embeddings found. Create embeddings first.")
            return

        id_to_emb_idx = {aid: i for i, aid in enumerate(article_ids)}

        # Batch-fetch all articles with cluster info in one query (not O(N) queries)
        articles_all_with_clusters = self.db.get_all_articles_with_clusters()
        
        articles_with_clusters = []
        labels = []
        cluster_labels = {}
        emb_indices = []

        for key, article in articles_all_with_clusters.items():
            if key not in id_to_emb_idx:
                continue
            if article['cluster_id'] is not None:
                cluster_id = article['cluster_id']
                labels.append(cluster_id)
                cluster_labels[cluster_id] = article['cluster_label']
                articles_with_clusters.append(article)
                emb_indices.append(id_to_emb_idx[key])

        if not labels:
            logger.info("No clusters found. Cluster articles first.")
            return

        labels = np.array(labels)
        matched_embeddings = embeddings[emb_indices]

        articles_by_cluster = {}
        for article, label in zip(articles_with_clusters, labels):
            if label not in articles_by_cluster:
                articles_by_cluster[label] = []
            articles_by_cluster[label].append(article)

        logger.info("Creating 2D visualization...")
        embeddings_2d = ClusterVisualizer.reduce_dimensions(matched_embeddings, method='pca', n_components=2)

        fig_2d = ClusterVisualizer.plot_2d_clusters(
            embeddings_2d,
            labels,
            cluster_labels,
            articles_with_clusters,
            save_path=os.path.join(output_dir, 'clusters_2d.html')
        )

        logger.info("Creating cluster summary...")
        fig_summary = ClusterVisualizer.plot_cluster_summary(
            articles_by_cluster,
            cluster_labels,
            save_path=os.path.join(output_dir, 'cluster_summary.html')
        )

        logger.info("Creating similarity heatmap...")
        # The heatmap only ever displays up to `heatmap_n` articles, so compute
        # the similarity matrix on that bounded subset instead of materialising
        # the full O(N^2) matrix for the whole corpus.
        heatmap_n = min(100, len(matched_embeddings))
        similarity_matrix = self.embedding_engine.calculate_similarity_matrix(
            matched_embeddings[:heatmap_n]
        )
        fig_heatmap = ClusterVisualizer.plot_similarity_heatmap(
            similarity_matrix,
            labels[:heatmap_n],
            max_display=heatmap_n,
            save_path=os.path.join(output_dir, 'similarity_heatmap.html')
        )

        logger.info(f"Visualizations saved to {output_dir}")

        return {
            'clusters_2d': fig_2d,
            'summary': fig_summary,
            'heatmap': fig_heatmap
        }

    def search_similar(
        self,
        query_text: str,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
    ) -> List[Dict]:
        """
        Search for articles similar to a query

        Args:
            query_text: User's study description or search query
            top_k: Number of results to return
            source_filter: If given, only rank articles whose source is in this
                list. Filtering happens BEFORE the top-k cut so a narrow source
                selection still returns up to top_k results rather than however
                many survive a post-hoc filter.
            cluster_filter: If given, only rank articles whose cluster_id is in
                this list. Like source_filter, this is applied BEFORE the top-k
                cut so the caller still gets up to top_k results from the chosen
                clusters.

        Returns:
            List of similar articles with similarity scores
        """
        logger.info(f"\n=== Searching for similar articles ===")
        logger.info(f"Query: {query_text}\n")

        article_ids, article_embeddings = self.db.get_all_embeddings()

        if len(article_ids) == 0:
            logger.info("No embeddings found. Create embeddings first.")
            return []

        # Screened-out articles (excluded clusters, resolved duplicates, manual
        # exclusions) never participate in ranking.
        excluded = self.db.get_excluded_keys()
        if excluded:
            keep = [i for i, key in enumerate(article_ids) if key not in excluded]
            if not keep:
                logger.info("All embedded articles are currently excluded.")
                return []
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        # Restrict the candidate pool to the requested sources before ranking.
        if source_filter:
            allowed = set(source_filter)
            keep = [i for i, (_, src) in enumerate(article_ids) if src in allowed]
            if not keep:
                logger.info("No embeddings match the requested sources.")
                return []
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        # Restrict the candidate pool to the requested clusters before ranking,
        # for the same reason as source_filter above.
        if cluster_filter:
            wanted = set(cluster_filter)
            cluster_map = self.db.get_all_articles_with_clusters()
            keep = [
                i for i, key in enumerate(article_ids)
                if (cluster_map.get(key) or {}).get('cluster_id') in wanted
            ]
            if not keep:
                logger.info("No embeddings match the requested clusters.")
                return []
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        # The query must be embedded with the SAME model that built the stored
        # vectors — different models have different dimensions, and the pipeline
        # may have been recreated with the default model since embedding (e.g.
        # after re-login). Re-sync to the stored model before embedding.
        #
        # Hold the engine lock across the re-sync AND the query embedding so a
        # concurrent create_embeddings can't swap the engine between the two and
        # leave us embedding the query with the wrong model.
        stored_model = self.db.get_embedding_model()
        with self._engine_lock:
            if stored_model and stored_model != self.embedding_model_name:
                logger.info(
                    "Query embedder '%s' differs from stored embeddings' model '%s'; switching.",
                    self.embedding_model_name, stored_model,
                )
                self.embedding_engine = EmbeddingEngine(model_name=stored_model)
                self.embedding_model_name = stored_model

            # Create query embedding
            query_embedding = self.embedding_engine.embed_query(query_text)

        # Defensive: if the dimensions still disagree (e.g. corrupt/mixed-model
        # embeddings), fail with a clear, actionable message instead of a cryptic
        # FAISS assertion deep in the search call.
        if query_embedding.shape[-1] != article_embeddings.shape[1]:
            raise ValueError(
                "Embedding dimension mismatch between the query and stored "
                "articles. Re-create embeddings on the Data Management page."
            )

        # Find similar articles
        results = self.embedding_engine.find_similar(
            query_embedding,
            article_embeddings,
            article_ids,
            top_k=top_k
        )

        # Batch-fetch all articles with clusters for efficiency
        articles_all_with_clusters = self.db.get_all_articles_with_clusters()

        # Get full article details
        similar_articles = []
        for (article_id, source), similarity in results:
            key = (article_id, source)
            if key in articles_all_with_clusters:
                article = articles_all_with_clusters[key]
                article['similarity_score'] = similarity
                similar_articles.append(article)

        # Print results
        logger.info(f"Top {len(similar_articles)} most similar articles:\n")
        for i, article in enumerate(similar_articles, 1):
            logger.info(f"{i}. [{article['similarity_score']:.3f}] {article['title']}")
            logger.info(f"   {article['year']} | {article['journal']}")
            logger.info(f"   ID: {article['article_id']} ({article['source']})\n")

        return similar_articles

    def detect_duplicates(self, threshold: float = 0.95) -> List[Tuple]:
        """
        Detect potential duplicate articles

        Args:
            threshold: Similarity threshold

        Returns:
            List of duplicate pairs: ((article_id1, source1), (article_id2, source2), similarity)
        """
        logger.info(f"\n=== Detecting Duplicates (threshold: {threshold}) ===")

        article_ids, embeddings = self.db.get_all_embeddings()

        # Excluded articles don't participate: once a duplicate group is
        # resolved (losers excluded), re-running detection only reports the
        # groups that still need attention.
        excluded = self.db.get_excluded_keys()
        if excluded and len(article_ids) > 0:
            keep = [i for i, key in enumerate(article_ids) if key not in excluded]
            article_ids = [article_ids[i] for i in keep]
            embeddings = embeddings[keep] if keep else embeddings[:0]

        if len(article_ids) == 0:
            logger.info("No embeddings found.")
            return []

        duplicates = self.embedding_engine.detect_duplicates(
            embeddings,
            article_ids,
            threshold=threshold
        )

        if duplicates:
            logger.info(f"\nFound {len(duplicates)} potential duplicate pairs:\n")
            for id1, id2, sim in duplicates[:10]:
                article1 = self.db.get_article_by_id(*id1)
                article2 = self.db.get_article_by_id(*id2)
                logger.info(f"[{sim:.3f}]")
                if article1:
                    logger.info(f"  1: {article1['title']}")
                if article2:
                    logger.info(f"  2: {article2['title']}\n")

        return duplicates

    def resolve_duplicates(self, threshold: float = 0.95) -> Dict:
        """
        Auto-resolve duplicate groups: keep the best copy, exclude the rest.

        Duplicate pairs are grouped transitively (union-find). Within each group
        the winner is the LONGEST ABSTRACT, then preferred SOURCE_PRIORITY
        (PubMed before secondary databases), then stable ids. Losers are marked
        excluded reason='duplicate' (hidden from search/detection; reversible).

        Returns:
            {'groups': n_groups_resolved, 'excluded': n_articles_excluded}
        """
        duplicates = self.detect_duplicates(threshold=threshold)
        if not duplicates:
            return {'groups': 0, 'excluded': 0}

        # Union-find over (article_id, source) keys.
        parent = {}

        def find(k):
            parent.setdefault(k, k)
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        def union(a, b):
            parent[find(a)] = find(b)

        for id1, id2, _sim in duplicates:
            union(id1, id2)

        groups: Dict = {}
        for key in list(parent):
            groups.setdefault(find(key), []).append(key)

        articles = self.db.get_all_articles_with_clusters()
        from utils import duplicate_quality_key
        losers = []
        n_groups = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            n_groups += 1
            # Longest abstract wins; preferred source (PubMed > …) breaks ties.
            keeper = max(
                members,
                key=lambda k: duplicate_quality_key(articles.get(k), k),
            )
            losers.extend(k for k in members if k != keeper)

        self.db.exclude_articles(losers, reason='duplicate')
        logger.info("Resolved %d duplicate groups: excluded %d redundant copies",
                    n_groups, len(losers))
        return {'groups': n_groups, 'excluded': len(losers)}

    def search_by_seed(
        self,
        seed: str,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
    ) -> Dict:
        """Find a local seed article (by id/title), then rank similar papers."""
        article = self.db.find_article_by_seed(seed)
        if not article:
            raise ValueError(
                "No matching article in your collection. Fetch papers first, "
                "or try a different id / title fragment."
            )
        query = f"{article.get('title') or ''}. {article.get('abstract') or ''}".strip()
        results = self.search_similar(
            query, top_k=top_k + 1,
            source_filter=source_filter,
            cluster_filter=cluster_filter,
        )
        seed_key = (article["article_id"], article["source"])
        results = [
            r for r in results
            if (r.get("article_id"), r.get("source")) != seed_key
        ][:top_k]
        return {"seed": article, "results": results}

    def get_cluster_briefings(self) -> List[Dict]:
        """Rule-based topic overview cards for each cluster."""
        from utils import build_cluster_briefing
        clusters = self.db.get_all_clusters()
        briefings = []
        for c in clusters:
            cid = c["cluster_id"]
            arts = self.db.get_articles_by_cluster(cid)
            titles = [a.get("title") or "" for a in arts]
            years = [a.get("year") for a in arts]
            briefing = build_cluster_briefing(
                cid,
                c.get("cluster_label") or "",
                titles,
                years,
                c.get("article_count") or len(arts),
                representative_title=c.get("representative_title"),
            )
            briefing["cluster_id"] = cid
            briefing["excluded_count"] = c.get("excluded_count") or 0
            briefings.append(briefing)
        return briefings

    def get_statistics(self) -> Dict:
        """Get database statistics plus embedding status fields."""
        stats = self.db.get_statistics()
        emb = self.db.get_embedding_status()
        stats["embedding_model"] = emb.get("model")
        stats["missing_embeddings"] = emb.get("missing_embeddings")
        return stats

    def close(self):
        """Close database connection"""
        self.db.close()
