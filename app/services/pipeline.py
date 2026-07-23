"""
Main Pipeline
Orchestrates the complete workflow from data fetching to visualization
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

from app.fetchers.arxiv import ArXivFetcher
from app.fetchers.biorxiv import BioRxivFetcher, MedRxivFetcher
from app.fetchers.clinicaltrials import ClinicalTrialsFetcher
from app.fetchers.core import COREFetcher
from app.fetchers.crossref import CrossRefFetcher
from app.fetchers.dblp import DBLPFetcher
from app.fetchers.doaj import DOAJFetcher
from app.fetchers.eric import ERICFetcher
from app.fetchers.europepmc import EuropePMCFetcher
from app.fetchers.hal import HALFetcher
from app.fetchers.nasa_ads import NASAADSFetcher
from app.fetchers.openaire import OpenAIREFetcher
from app.fetchers.openalex import OpenAlexFetcher
from app.fetchers.plos import PLOSFetcher
from app.fetchers.pubmed import PubMedFetcher
from app.fetchers.semanticscholar import SemanticScholarFetcher
from app.fetchers.zenodo import ZenodoFetcher
from app.services.clustering import (
    NOISE_CLUSTER_ID,
    NOISE_CLUSTER_LABEL,
    ArticleClusterer,
    ClusterLabeler,
)
from app.services.embeddings import EmbeddingEngine
from app.storage.database import ArticleDatabase

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
    'biorxiv': BioRxivFetcher,
    'medrxiv': MedRxivFetcher,
    'dblp': DBLPFetcher,
    'openaire': OpenAIREFetcher,
    'plos': PLOSFetcher,
    'hal': HALFetcher,
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
        # Search hot-path cache: embeddings matrix + excluded set. Bumped when
        # the corpus changes (fetch / embed / screening).
        self._corpus_cache_lock = threading.Lock()
        self._corpus_cache_gen = 0
        self._cached_emb_ids = None
        self._cached_emb_matrix = None
        self._cached_excluded = None
        self._cached_excluded_gen = -1
        self._cached_emb_gen = -1

    def invalidate_corpus_cache(self) -> None:
        """Call after mutations that change embeddings, screening, or articles."""
        with self._corpus_cache_lock:
            self._corpus_cache_gen += 1

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
        self.db.insert_articles(articles, dedupe=True)
        self.invalidate_corpus_cache()

        logger.info(f"Fetched and stored {len(articles)} articles from {source}")
        return articles

    def fetch_articles_parallel(
        self,
        query: str,
        sources: List[str],
        max_results: int = 100,
        email: str = "your.email@example.com",
        progress_callback=None,
        cancel_check=None,
    ) -> Dict:
        """
        Fetch from multiple sources concurrently; insert each source as it completes.

        progress_callback: callable(done, total, **extra) — extra may include
            articles_so_far, source, source_count, error_kind.
        cancel_check: optional zero-arg callable returning True if the job
            should stop between sources.
        """
        from app.fetchers.base import FetchError, classify_error

        logger.info(f"\n=== Fetching from {len(sources)} sources in parallel ===")
        lock = threading.Lock()
        completed = [0]
        articles_so_far = [0]
        total = len(sources)
        cancelled = [False]

        def fetch_one(source):
            if cancel_check and cancel_check():
                return (source, [], "Cancelled", "cancelled")
            fetcher_cls = FETCHERS.get(source)
            if not fetcher_cls:
                return (source, [], "Unknown source", "error")
            try:
                fetcher = fetcher_cls(email=email)
                articles = fetcher.search_and_fetch(query, max_results) or []
                if not articles:
                    return (source, [], None, "no_results")
                return (source, articles, None, None)
            except FetchError as e:
                logger.error("Error fetching %s: %s", source, e)
                return (source, [], str(e), e.kind)
            except Exception as e:
                logger.error("Error fetching %s: %s", source, e)
                return (source, [], str(e), classify_error(e))

        results = {}
        with ThreadPoolExecutor(max_workers=min(len(sources), 6)) as executor:
            futures = {executor.submit(fetch_one, src): src for src in sources}
            for future in as_completed(futures):
                if cancel_check and cancel_check():
                    cancelled[0] = True
                    # Best-effort: do not wait on remaining futures beyond this.
                    for f in futures:
                        f.cancel()

                source, articles, error, error_kind = future.result()
                # Insert immediately so a hung source does not block others' data.
                inserted = 0
                skipped_dups = 0
                if articles and not (cancel_check and cancel_check() and error == "Cancelled"):
                    insert_stats = self.db.insert_articles(articles, dedupe=True)
                    if isinstance(insert_stats, dict):
                        inserted = int(insert_stats.get("inserted") or 0)
                        skipped_dups = int(insert_stats.get("skipped_duplicates") or 0)
                    else:
                        inserted = len(articles)

                # Prefer stored count; fall back to fetched length when insert
                # only reports dropped rows (legacy).
                count = inserted if articles else 0
                if articles and inserted == 0 and not skipped_dups:
                    count = len(articles)

                # no_results is not a hard error for the report
                report_error = error
                if error_kind == "no_results" and not error:
                    report_error = None

                results[source] = {
                    'count': count,
                    'fetched': len(articles),
                    'skipped_duplicates': skipped_dups,
                    'error': report_error,
                    'error_kind': error_kind if report_error or error_kind == "no_results" else None,
                }
                logger.info(
                    "  %s: %d articles (kind=%s)",
                    source, count, error_kind or "ok",
                )

                with lock:
                    completed[0] += 1
                    articles_so_far[0] += count
                    done = completed[0]
                    total_arts = articles_so_far[0]
                if progress_callback:
                    progress_callback(
                        done, total,
                        articles_so_far=total_arts,
                        source=source,
                        source_count=count,
                        error_kind=error_kind,
                    )

                if cancelled[0]:
                    break

        # Ensure every requested source appears in the report
        for src in sources:
            if src not in results:
                results[src] = {
                    'count': 0,
                    'fetched': 0,
                    'skipped_duplicates': 0,
                    'error': 'Cancelled' if cancelled[0] else None,
                    'error_kind': 'cancelled' if cancelled[0] else None,
                }

        return {
            source: {
                'count': data['count'],
                'error': data['error'],
                'error_kind': data.get('error_kind'),
                'skipped_duplicates': data.get('skipped_duplicates', 0),
            }
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

        from app.services.embeddings import select_device

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
            # Still fill any missing key points (e.g. corpus prepared before
            # this feature shipped).
            kp = self._generate_key_points(articles=articles, only_missing=True)
            return {
                "embeddings_created": 0,
                "skipped_existing": skipped,
                "key_points_created": kp,
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
        self.invalidate_corpus_cache()

        # Extractive key points reuse the loaded model (structured abstracts
        # skip encoding). On model switch re-generate everything; otherwise
        # only fill missing rows so stragglers from older corpora catch up.
        key_points_created = self._generate_key_points(
            articles=articles,
            only_missing=not force_all,
        )

        seconds = round(time.perf_counter() - t0, 2)

        logger.info("Created and stored embeddings in %.2fs on %s", seconds, device)
        return {
            "embeddings_created": len(embeddings),
            "skipped_existing": skipped,
            "key_points_created": key_points_created,
            "seconds": seconds,
            "model": model_name,
            "device": device,
        }

    def _encode_texts(self, texts: List[str]) -> np.ndarray:
        """Encode plain strings with the current embedding engine (normalized)."""
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        with self._engine_lock:
            return self.embedding_engine.model.encode(
                texts,
                convert_to_numpy=True,
                show_progress_bar=False,
                normalize_embeddings=True,
            )

    def _generate_key_points(
        self,
        articles: Optional[List[Dict]] = None,
        only_missing: bool = True,
    ) -> int:
        """Compute and store extractive key points for articles.

        Returns the number of articles written to the key_points table.
        """
        from app.services.summarize import extract_key_points_batch

        pool = articles if articles is not None else self.db.get_all_articles()
        if not pool:
            return 0
        if only_missing:
            existing = self.db.get_key_points_keys()
            pool = [
                a for a in pool
                if (a["article_id"], a["source"]) not in existing
            ]
        if not pool:
            return 0

        logger.info("Generating key points for %d articles…", len(pool))
        points = extract_key_points_batch(pool, encode_fn=self._encode_texts)
        return self.db.insert_key_points(points)

    def generate_key_points(self, only_missing: bool = True) -> Dict:
        """Public backfill: generate key points for stragglers (or all)."""
        n = self._generate_key_points(articles=None, only_missing=only_missing)
        return {"key_points_created": n, "only_missing": only_missing}

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

    def _load_embeddings_cached(self) -> Tuple[List[Tuple[str, str]], np.ndarray]:
        """Return (ids, matrix), reusing the last load until cache invalidation."""
        with self._corpus_cache_lock:
            gen = self._corpus_cache_gen
            if self._cached_emb_gen == gen and self._cached_emb_ids is not None:
                return self._cached_emb_ids, self._cached_emb_matrix
        ids, matrix = self.db.get_all_embeddings()
        with self._corpus_cache_lock:
            self._cached_emb_ids = ids
            self._cached_emb_matrix = matrix
            self._cached_emb_gen = self._corpus_cache_gen
        return ids, matrix

    def _load_excluded_cached(self) -> set:
        with self._corpus_cache_lock:
            gen = self._corpus_cache_gen
            if self._cached_excluded_gen == gen and self._cached_excluded is not None:
                return set(self._cached_excluded)
        excluded = set(self.db.get_excluded_keys())
        with self._corpus_cache_lock:
            self._cached_excluded = set(excluded)
            self._cached_excluded_gen = self._corpus_cache_gen
        return excluded

    def _candidate_pool(
        self,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        extra_exclude: Optional[set] = None,
    ) -> Tuple[List[Tuple[str, str]], np.ndarray, Dict]:
        """Embeddings + metadata after screening / source / cluster / year filters."""
        from app.utils import parse_year

        article_ids, article_embeddings = self._load_embeddings_cached()
        empty_meta: Dict = {}
        if len(article_ids) == 0:
            return [], article_embeddings, empty_meta

        # Excluded keys are cheap to load and change often during triage —
        # always read fresh. Embeddings stay cached.
        excluded = set(self.db.get_excluded_keys())
        if extra_exclude:
            excluded |= set(extra_exclude)
        if excluded:
            keep = [i for i, key in enumerate(article_ids) if key not in excluded]
            if not keep:
                return [], article_embeddings[:0], empty_meta
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        if source_filter:
            allowed = set(source_filter)
            keep = [i for i, (_, src) in enumerate(article_ids) if src in allowed]
            if not keep:
                return [], article_embeddings[:0], empty_meta
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        articles_all = self.db.get_all_articles_with_clusters()

        if cluster_filter:
            wanted = set(cluster_filter)
            keep = [
                i for i, key in enumerate(article_ids)
                if (articles_all.get(key) or {}).get('cluster_id') in wanted
            ]
            if not keep:
                return [], article_embeddings[:0], empty_meta
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        # When either year bound is set, unknown/unparseable years are excluded.
        if year_min is not None or year_max is not None:
            keep = []
            for i, key in enumerate(article_ids):
                y = parse_year((articles_all.get(key) or {}).get('year'))
                if y == 0:
                    continue
                if year_min is not None and y < year_min:
                    continue
                if year_max is not None and y > year_max:
                    continue
                keep.append(i)
            if not keep:
                return [], article_embeddings[:0], empty_meta
            article_ids = [article_ids[i] for i in keep]
            article_embeddings = article_embeddings[keep]

        return article_ids, article_embeddings, articles_all

    @staticmethod
    def _minmax(values: List[float]) -> List[float]:
        if not values:
            return []
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return [0.5] * len(values)
        return [(v - lo) / (hi - lo) for v in values]

    def _hybrid_rerank(
        self,
        query_text: str,
        ranked: List[Tuple[Tuple[str, str], float]],
        articles_all: Dict,
        top_k: int,
    ) -> List[Dict]:
        """Blend semantic cosine with TF-IDF lexical scores; cut to top_k.

        TF-IDF is fit only on the semantic shortlist (typically <= ~250 docs),
        not the full corpus, so rebuilding per query is intentional and cheap.
        Full-corpus embedding loads are cached on the pipeline (see
        _load_embeddings_cached) and invalidated when the corpus changes.
        """
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sk_cosine

        keys = [k for k, _ in ranked]
        sem_scores = [float(s) for _, s in ranked]
        docs = []
        for key in keys:
            a = articles_all.get(key) or {}
            docs.append(f"{a.get('title') or ''} {a.get('abstract') or ''}".strip())

        try:
            vec = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
            mat = vec.fit_transform(docs)
            q = vec.transform([query_text or ''])
            lex = sk_cosine(q, mat).ravel().tolist()
        except Exception as e:
            logger.warning("Lexical boost failed (%s); pure semantic ranking.", e)
            lex = None

        if lex is None:
            # Keep semantic order; expose neutral lexical scores.
            lex_norm = [0.5] * len(sem_scores)
            order = list(range(len(keys)))
        else:
            sem_norm = self._minmax(sem_scores)
            lex_norm = self._minmax(lex)
            blended = [0.7 * s + 0.3 * L for s, L in zip(sem_norm, lex_norm)]
            order = sorted(range(len(keys)), key=lambda i: blended[i], reverse=True)

        out: List[Dict] = []
        for i in order[:top_k]:
            key = keys[i]
            if key not in articles_all:
                continue
            article = dict(articles_all[key])
            article['similarity_score'] = float(sem_scores[i])
            article['lexical_score'] = round(float(lex_norm[i]), 4)
            out.append(article)
        return out

    def search_similar(
        self,
        query_text: str,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        lexical_boost: bool = True,
        query_embedding: Optional[np.ndarray] = None,
        extra_exclude: Optional[set] = None,
    ) -> List[Dict]:
        """
        Search for articles similar to a query (or a provided query embedding).

        Filters (screening, source, cluster, year) apply BEFORE ranking.
        When lexical_boost is True, re-rank a wider semantic shortlist with TF-IDF.
        """
        logger.info("\n=== Searching for similar articles ===")
        logger.info(f"Query: {query_text}\n")

        article_ids, article_embeddings, articles_all = self._candidate_pool(
            source_filter=source_filter,
            cluster_filter=cluster_filter,
            year_min=year_min,
            year_max=year_max,
            extra_exclude=extra_exclude,
        )
        if len(article_ids) == 0:
            logger.info("No embeddings match the current filters.")
            return []

        if query_embedding is None:
            stored_model = self.db.get_embedding_model()
            with self._engine_lock:
                if stored_model and stored_model != self.embedding_model_name:
                    logger.info(
                        "Query embedder '%s' differs from stored embeddings' model '%s'; switching.",
                        self.embedding_model_name, stored_model,
                    )
                    self.embedding_engine = EmbeddingEngine(model_name=stored_model)
                    self.embedding_model_name = stored_model
                query_embedding = self.embedding_engine.embed_query(query_text)

        if query_embedding.shape[-1] != article_embeddings.shape[1]:
            raise ValueError(
                "Embedding dimension mismatch between the query and stored "
                "articles. Re-create embeddings on the Data Management page."
            )

        use_hybrid = bool(lexical_boost) and bool((query_text or "").strip())
        k0 = min(len(article_ids), max(top_k * 5, 50)) if use_hybrid else top_k
        ranked = self.embedding_engine.find_similar(
            query_embedding,
            article_embeddings,
            article_ids,
            top_k=k0,
        )

        if use_hybrid and ranked:
            similar_articles = self._hybrid_rerank(
                query_text, ranked, articles_all, top_k=top_k,
            )
        else:
            similar_articles = []
            for (article_id, source), similarity in ranked[:top_k]:
                key = (article_id, source)
                if key in articles_all:
                    article = dict(articles_all[key])
                    article['similarity_score'] = float(similarity)
                    similar_articles.append(article)

        logger.info(f"Top {len(similar_articles)} most similar articles:\n")
        for i, article in enumerate(similar_articles, 1):
            logger.info(f"{i}. [{article['similarity_score']:.3f}] {article['title']}")
            logger.info(f"   {article['year']} | {article['journal']}")
            logger.info(f"   ID: {article['article_id']} ({article['source']})\n")

        return similar_articles

    def search_from_starred(
        self,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
    ) -> Dict:
        """Rank papers near the centroid of the user's starred embeddings."""
        starred_keys = self.db.get_starred_keys()
        if not starred_keys:
            raise ValueError("Star some papers first")

        all_ids, all_emb = self.db.get_all_embeddings()
        if len(all_ids) == 0:
            return {"results": [], "seed_count": len(starred_keys)}

        id_to_idx = {k: i for i, k in enumerate(all_ids)}
        star_vecs = []
        for key in starred_keys:
            i = id_to_idx.get(key)
            if i is not None:
                star_vecs.append(all_emb[i])
        if not star_vecs:
            raise ValueError(
                "Starred papers have no embeddings yet. Create embeddings first."
            )

        centroid = np.mean(np.stack(star_vecs, axis=0), axis=0).astype(np.float32)
        norm = float(np.linalg.norm(centroid))
        if norm > 0:
            centroid = centroid / norm

        results = self.search_similar(
            query_text="",
            top_k=top_k,
            source_filter=source_filter,
            cluster_filter=cluster_filter,
            year_min=year_min,
            year_max=year_max,
            lexical_boost=False,
            query_embedding=centroid,
            extra_exclude=set(starred_keys),
        )
        return {"results": results, "seed_count": len(starred_keys)}

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
        from app.utils import duplicate_quality_key
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
        self.invalidate_corpus_cache()
        logger.info("Resolved %d duplicate groups: excluded %d redundant copies",
                    n_groups, len(losers))
        return {'groups': n_groups, 'excluded': len(losers)}

    def search_by_seed(
        self,
        seed: str,
        top_k: int = 10,
        source_filter: Optional[List[str]] = None,
        cluster_filter: Optional[List[int]] = None,
        year_min: Optional[int] = None,
        year_max: Optional[int] = None,
        lexical_boost: bool = True,
    ) -> Dict:
        """Find a local seed article (by id/title), then rank similar papers."""
        article = self.db.find_article_by_seed(seed)
        if not article:
            raise ValueError(
                "No matching article in your collection. Fetch papers first, "
                "or try a different id / title fragment."
            )
        query = f"{article.get('title') or ''}. {article.get('abstract') or ''}".strip()
        seed_key = (article["article_id"], article["source"])
        results = self.search_similar(
            query, top_k=top_k + 1,
            source_filter=source_filter,
            cluster_filter=cluster_filter,
            year_min=year_min,
            year_max=year_max,
            lexical_boost=lexical_boost,
            extra_exclude={seed_key},
        )[:top_k]
        return {"seed": article, "results": results}

    def get_cluster_briefings(self) -> List[Dict]:
        """Rule-based topic overview cards for each cluster."""
        from app.utils import build_cluster_briefing
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
