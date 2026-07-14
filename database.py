"""
Database Module
Handles storage and retrieval of articles and embeddings
"""

import sqlite3
import json
import logging
import pickle
import threading
import numpy as np
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ArticleDatabase:
    """SQLite database for storing articles and their embeddings"""

    def __init__(self, db_path: str = "articles.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL reduces "database is locked" under concurrent readers/writers;
        # busy_timeout waits up to 5s before raising instead of failing immediately.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()
        self.create_tables()
        self.migrate_schema()

    def create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()

        # Articles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                year TEXT,
                authors TEXT,
                journal TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source)
            )
        """)

        # Embeddings table. Embeddings are stored as raw numpy bytes plus the
        # dtype and shape needed to reconstruct them (no pickle — see S3).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                embedding BLOB NOT NULL,
                dtype TEXT,
                shape TEXT,
                model_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
            )
        """)

        # Clusters table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clusters (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                cluster_id INTEGER,
                cluster_label TEXT,
                representative_title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
            )
        """)

        # Screening table: presence of a row means the article is EXCLUDED from
        # search/dedup (screened out). reason records why: 'manual', 'cluster'
        # (bulk cluster exclusion) or 'duplicate' (auto-resolve kept a better
        # copy). Including an article back just deletes its row.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screening (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                reason TEXT NOT NULL DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
            )
        """)

        # Private notes / bookmarks (per article, per user DB).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                note TEXT NOT NULL DEFAULT '',
                starred INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
            )
        """)

        self.conn.commit()

    def migrate_schema(self):
        """Migrate old pmid-based schema to article_id+source schema"""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(articles)")
        columns = [col[1] for col in cursor.fetchall()]

        # Add dtype/shape columns to embeddings if missing (S3: numpy instead of pickle).
        cursor.execute("PRAGMA table_info(embeddings)")
        emb_columns = [col[1] for col in cursor.fetchall()]
        if emb_columns and 'dtype' not in emb_columns:
            cursor.execute("ALTER TABLE embeddings ADD COLUMN dtype TEXT")
        if emb_columns and 'shape' not in emb_columns:
            cursor.execute("ALTER TABLE embeddings ADD COLUMN shape TEXT")

        # Add representative_title to clusters if an older DB predates it.
        cursor.execute("PRAGMA table_info(clusters)")
        cluster_columns = [col[1] for col in cursor.fetchall()]
        if cluster_columns and 'representative_title' not in cluster_columns:
            cursor.execute("ALTER TABLE clusters ADD COLUMN representative_title TEXT")

        self.conn.commit()

        # Convert any legacy rows that still hold pickle.dumps(...) blobs (no
        # dtype/shape) into the raw-numpy-bytes format. Rows whose blob is not a
        # valid pickle are deleted so users regenerate them rather than reading
        # back silently-corrupted vectors (Codex review).
        if emb_columns:
            cursor.execute(
                "SELECT article_id, source, embedding FROM embeddings "
                "WHERE dtype IS NULL OR shape IS NULL"
            )
            legacy_rows = cursor.fetchall()
            converted = 0
            deleted = 0
            for article_id, source, blob in legacy_rows:
                try:
                    arr = np.asarray(pickle.loads(blob))
                except Exception:
                    cursor.execute(
                        "DELETE FROM embeddings WHERE article_id = ? AND source = ?",
                        (article_id, source),
                    )
                    deleted += 1
                    continue
                cursor.execute(
                    "UPDATE embeddings SET embedding = ?, dtype = ?, shape = ? "
                    "WHERE article_id = ? AND source = ?",
                    (arr.tobytes(), str(arr.dtype), json.dumps(list(arr.shape)),
                     article_id, source),
                )
                converted += 1
            if converted or deleted:
                self.conn.commit()
                logger.info(
                    "Embedding migration: converted %d legacy pickle rows, "
                    "deleted %d unrecoverable rows", converted, deleted
                )

        if 'pmid' in columns and 'source' not in columns:
            logger.info("Migrating database schema from pmid to article_id+source...")
            cursor.execute("ALTER TABLE articles RENAME TO articles_old")
            cursor.execute("ALTER TABLE embeddings RENAME TO embeddings_old")
            cursor.execute("ALTER TABLE clusters RENAME TO clusters_old")

            # Recreate tables with new schema
            cursor.execute("""
                CREATE TABLE articles (
                    article_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'pubmed',
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL,
                    year TEXT,
                    authors TEXT,
                    journal TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (article_id, source)
                )
            """)
            cursor.execute("""
                CREATE TABLE embeddings (
                    article_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'pubmed',
                    embedding BLOB NOT NULL,
                    model_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (article_id, source),
                    FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                )
            """)
            cursor.execute("""
                CREATE TABLE clusters (
                    article_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'pubmed',
                    cluster_id INTEGER,
                    cluster_label TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (article_id, source),
                    FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                )
            """)

            # Copy data with source='pubmed'
            cursor.execute("""
                INSERT INTO articles (article_id, source, title, abstract, year, authors, journal, created_at)
                SELECT pmid, 'pubmed', title, abstract, year, authors, journal, created_at
                FROM articles_old
            """)
            cursor.execute("""
                INSERT INTO embeddings (article_id, source, embedding, model_name, created_at)
                SELECT pmid, 'pubmed', embedding, model_name, created_at
                FROM embeddings_old
            """)
            cursor.execute("""
                INSERT INTO clusters (article_id, source, cluster_id, cluster_label, created_at)
                SELECT pmid, 'pubmed', cluster_id, cluster_label, created_at
                FROM clusters_old
            """)

            # Drop old tables
            cursor.execute("DROP TABLE clusters_old")
            cursor.execute("DROP TABLE embeddings_old")
            cursor.execute("DROP TABLE articles_old")

            self.conn.commit()
            logger.info("Schema migration complete.")

    def clear_all(self):
        """Delete all articles, embeddings, clusters, screening, and notes."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM screening")
            cursor.execute("DELETE FROM clusters")
            cursor.execute("DELETE FROM embeddings")
            cursor.execute("DELETE FROM articles")
            self.conn.commit()

    def insert_articles(self, articles: List[Dict]) -> int:
        """
        Insert articles into database.

        Args:
            articles: List of article dictionaries with 'article_id' and 'source' keys

        Returns:
            Number of articles that were dropped due to insertion errors.
        """
        dropped = 0
        with self._lock:
            cursor = self.conn.cursor()
            for article in articles:
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO articles
                        (article_id, source, title, abstract, year, authors, journal)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        article['article_id'],
                        article.get('source', 'pubmed'),
                        article.get('title', ''),
                        article.get('abstract', ''),
                        article.get('year', ''),
                        json.dumps(article.get('authors', [])),
                        article.get('journal', '')
                    ))
                except Exception as e:
                    dropped += 1
                    logger.warning("Error inserting article %s: %s", article.get('article_id'), e)
            self.conn.commit()
        logger.info("Inserted %d articles (%d dropped)", len(articles) - dropped, dropped)
        return dropped

    def get_all_articles(self) -> List[Dict]:
        """Retrieve all articles from database"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source, title, abstract, year, authors, journal FROM articles")
            rows = cursor.fetchall()

        articles = []
        for row in rows:
            articles.append({
                'article_id': row[0],
                'source': row[1],
                'title': row[2],
                'abstract': row[3],
                'year': row[4],
                'authors': json.loads(row[5]) if row[5] else [],
                'journal': row[6]
            })

        return articles

    def get_article_by_id(self, article_id: str, source: str) -> Optional[Dict]:
        """Retrieve a specific article by article_id and source"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT article_id, source, title, abstract, year, authors, journal FROM articles WHERE article_id = ? AND source = ?",
                (article_id, source)
            )
            row = cursor.fetchone()
        if row:
            return {
                'article_id': row[0],
                'source': row[1],
                'title': row[2],
                'abstract': row[3],
                'year': row[4],
                'authors': json.loads(row[5]) if row[5] else [],
                'journal': row[6]
            }
        return None

    def insert_embeddings(self, embeddings: Dict, model_name: str):
        """
        Store embeddings for articles

        Args:
            embeddings: Dictionary mapping (article_id, source) tuples to embedding vectors
            model_name: Name of the embedding model used
        """
        with self._lock:
            cursor = self.conn.cursor()
            for key, embedding in embeddings.items():
                article_id, source = key
                arr = np.asarray(embedding)
                embedding_bytes = arr.tobytes()
                cursor.execute("""
                    INSERT OR REPLACE INTO embeddings
                    (article_id, source, embedding, dtype, shape, model_name)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (article_id, source, embedding_bytes, str(arr.dtype),
                      json.dumps(list(arr.shape)), model_name))
            self.conn.commit()
        logger.info("Inserted embeddings for %d articles", len(embeddings))

    def get_all_embeddings(self) -> Tuple[List[Tuple[str, str]], np.ndarray]:
        """
        Retrieve all embeddings

        Returns:
            Tuple of (list of (article_id, source) tuples, numpy array of embeddings)
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source, embedding, dtype, shape FROM embeddings")
            rows = cursor.fetchall()

            ids = []
            embeddings = []
            stale = []

            for row in rows:
                # A row missing dtype/shape escaped migration (e.g. written by
                # an older path). We cannot reconstruct it reliably, so drop it
                # rather than feed raw bytes to np.frombuffer (Codex review).
                if row[3] is None or row[4] is None:
                    stale.append((row[0], row[1]))
                    continue
                try:
                    dtype = np.dtype(row[3])
                    shape = tuple(json.loads(row[4]))
                    embedding = np.frombuffer(row[2], dtype=dtype).reshape(shape)
                except Exception:
                    stale.append((row[0], row[1]))
                    continue
                ids.append((row[0], row[1]))
                embeddings.append(embedding)

            if stale:
                cursor.executemany(
                    "DELETE FROM embeddings WHERE article_id = ? AND source = ?",
                    stale,
                )
                self.conn.commit()
                logger.warning("Dropped %d embedding rows with missing/invalid dtype or shape", len(stale))

        if embeddings:
            return ids, np.array(embeddings)
        return [], np.array([])

    def get_embedding_model(self) -> Optional[str]:
        """Return the model name the stored embeddings were built with.

        Used so a search query is embedded with the same model as the corpus
        (different models produce different vector dimensions). Returns the most
        common model_name across stored embeddings, or None if there are none.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT model_name, COUNT(*) AS c FROM embeddings "
                "WHERE model_name IS NOT NULL "
                "GROUP BY model_name ORDER BY c DESC LIMIT 1"
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def get_embedding_keys(self) -> set:
        """Set of (article_id, source) keys that already have embeddings."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source FROM embeddings")
            return {(row[0], row[1]) for row in cursor.fetchall()}

    def get_embedding_status(self) -> Dict:
        """Counts + model for the embeddings step UI."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            with_emb = cursor.fetchone()[0]
        return {
            "total_articles": total,
            "with_embeddings": with_emb,
            "missing_embeddings": max(0, total - with_emb),
            "model": self.get_embedding_model(),
        }

    def find_article_by_seed(self, seed: str) -> Optional[Dict]:
        """Locate an article by DOI/id substring or title substring (case-insensitive)."""
        seed = (seed or "").strip()
        if not seed:
            return None
        like = f"%{seed}%"
        with self._lock:
            cursor = self.conn.cursor()
            # Prefer exact id match, then id substring, then title substring.
            cursor.execute(
                "SELECT article_id, source, title, abstract, year, authors, journal "
                "FROM articles WHERE article_id = ? COLLATE NOCASE LIMIT 1",
                (seed,),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    "SELECT article_id, source, title, abstract, year, authors, journal "
                    "FROM articles WHERE article_id LIKE ? COLLATE NOCASE "
                    "OR title LIKE ? COLLATE NOCASE LIMIT 1",
                    (like, like),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return {
            "article_id": row[0],
            "source": row[1],
            "title": row[2],
            "abstract": row[3],
            "year": row[4],
            "authors": json.loads(row[5]) if row[5] else [],
            "journal": row[6],
        }

    def get_library_export_rows(self, scope: str = "all") -> List[Dict]:
        """Articles with cluster + screening + note metadata for CSV export.

        scope: 'all' | 'included' | 'excluded' | 'starred'
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT a.article_id, a.source, a.title, a.abstract, a.year, a.authors, a.journal,
                       c.cluster_id, c.cluster_label,
                       s.reason,
                       n.note, n.starred
                FROM articles a
                LEFT JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
                LEFT JOIN screening s ON a.article_id = s.article_id AND a.source = s.source
                LEFT JOIN notes n ON a.article_id = n.article_id AND a.source = n.source
                ORDER BY a.year DESC, a.title ASC
            """)
            rows = cursor.fetchall()

        out = []
        for row in rows:
            excluded = row[9] is not None
            starred = bool(row[11])
            if scope == "included" and excluded:
                continue
            if scope == "excluded" and not excluded:
                continue
            if scope == "starred" and not starred:
                continue
            out.append({
                "article_id": row[0],
                "source": row[1],
                "title": row[2],
                "abstract": row[3],
                "year": row[4],
                "authors": json.loads(row[5]) if row[5] else [],
                "journal": row[6],
                "cluster_id": row[7],
                "cluster_label": row[8],
                "excluded": excluded,
                "exclusion_reason": row[9] or "",
                "note": row[10] or "",
                "starred": starred,
            })
        return out

    def get_note(self, article_id: str, source: str) -> Dict:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT note, starred FROM notes WHERE article_id = ? AND source = ?",
                (article_id, source),
            )
            row = cursor.fetchone()
        if not row:
            return {"article_id": article_id, "source": source, "note": "", "starred": False}
        return {
            "article_id": article_id,
            "source": source,
            "note": row[0] or "",
            "starred": bool(row[1]),
        }

    def upsert_note(self, article_id: str, source: str, note: Optional[str] = None,
                    starred: Optional[bool] = None) -> Dict:
        """Create/update a note. Pass only the fields you want to change."""
        current = self.get_note(article_id, source)
        new_note = current["note"] if note is None else note
        new_star = current["starred"] if starred is None else bool(starred)
        # Drop empty unstarred rows to keep the table small.
        if not new_note and not new_star:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute(
                    "DELETE FROM notes WHERE article_id = ? AND source = ?",
                    (article_id, source),
                )
                self.conn.commit()
            return {"article_id": article_id, "source": source, "note": "", "starred": False}
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO notes (article_id, source, note, starred, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(article_id, source) DO UPDATE SET
                    note = excluded.note,
                    starred = excluded.starred,
                    updated_at = CURRENT_TIMESTAMP
            """, (article_id, source, new_note, 1 if new_star else 0))
            self.conn.commit()
        return {"article_id": article_id, "source": source, "note": new_note, "starred": new_star}

    def get_notes_map(self) -> Dict[Tuple[str, str], Dict]:
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source, note, starred FROM notes")
            rows = cursor.fetchall()
        return {
            (r[0], r[1]): {"note": r[2] or "", "starred": bool(r[3])}
            for r in rows
        }

    def exclude_articles(self, keys: List[Tuple[str, str]], reason: str = 'manual') -> int:
        """Mark articles as screened out (excluded from search/dedup).

        Args:
            keys: list of (article_id, source) tuples
            reason: 'manual' | 'cluster' | 'duplicate'

        Returns:
            Number of rows written.
        """
        if not keys:
            return 0
        with self._lock:
            cursor = self.conn.cursor()
            cursor.executemany(
                "INSERT OR REPLACE INTO screening (article_id, source, reason) VALUES (?, ?, ?)",
                [(aid, src, reason) for aid, src in keys],
            )
            self.conn.commit()
        logger.info("Excluded %d articles (reason=%s)", len(keys), reason)
        return len(keys)

    def include_articles(self, keys: List[Tuple[str, str]]) -> int:
        """Undo exclusion for the given (article_id, source) keys."""
        if not keys:
            return 0
        with self._lock:
            cursor = self.conn.cursor()
            cursor.executemany(
                "DELETE FROM screening WHERE article_id = ? AND source = ?",
                keys,
            )
            self.conn.commit()
        return len(keys)

    def get_excluded_keys(self) -> set:
        """Return the set of (article_id, source) keys currently screened out."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source FROM screening")
            return {(row[0], row[1]) for row in cursor.fetchall()}

    def get_cluster_article_keys(self, cluster_id: int) -> List[Tuple[str, str]]:
        """Return (article_id, source) keys for every article in a cluster."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT article_id, source FROM clusters WHERE cluster_id = ?",
                (cluster_id,),
            )
            return [(row[0], row[1]) for row in cursor.fetchall()]

    def insert_clusters(self, cluster_assignments: Dict, cluster_titles: Optional[Dict] = None):
        """
        Store cluster assignments

        Args:
            cluster_assignments: Dict mapping (article_id, source) tuples to (cluster_id, cluster_label)
            cluster_titles: Optional {cluster_id: representative_title} — a real
                article title used as the cluster's human-readable headline.

        Re-clustering replaces assignments; wipe the old ones first so stale
        clusters (e.g. from a larger previous k) don't linger.
        """
        cluster_titles = cluster_titles or {}
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM clusters")
            for key, (cluster_id, label) in cluster_assignments.items():
                article_id, source = key
                cursor.execute("""
                    INSERT OR REPLACE INTO clusters
                    (article_id, source, cluster_id, cluster_label, representative_title)
                    VALUES (?, ?, ?, ?, ?)
                """, (article_id, source, cluster_id, label, cluster_titles.get(cluster_id)))
            self.conn.commit()
        logger.info("Inserted cluster assignments for %d articles", len(cluster_assignments))

    def get_articles_by_cluster(self, cluster_id: int) -> List[Dict]:
        """Get all articles in a specific cluster"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT a.article_id, a.source, a.title, a.abstract, a.year, a.authors, a.journal, c.cluster_label,
                       s.article_id IS NOT NULL AS excluded
                FROM articles a
                JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
                LEFT JOIN screening s ON a.article_id = s.article_id AND a.source = s.source
                WHERE c.cluster_id = ?
            """, (cluster_id,))
            rows = cursor.fetchall()

        articles = []
        for row in rows:
            articles.append({
                'article_id': row[0],
                'source': row[1],
                'title': row[2],
                'abstract': row[3],
                'year': row[4],
                'authors': json.loads(row[5]) if row[5] else [],
                'journal': row[6],
                'cluster_label': row[7],
                'excluded': bool(row[8])
            })

        return articles

    def get_all_clusters(self) -> List[Dict]:
        """Get summary of all clusters with article counts"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT c.cluster_id, c.cluster_label, COUNT(*) as article_count,
                       SUM(CASE WHEN s.article_id IS NOT NULL THEN 1 ELSE 0 END) as excluded_count,
                       MAX(c.representative_title) as representative_title
                FROM clusters c
                LEFT JOIN screening s ON c.article_id = s.article_id AND c.source = s.source
                GROUP BY c.cluster_id, c.cluster_label
                ORDER BY c.cluster_id
            """)
            rows = cursor.fetchall()
        return [
            {'cluster_id': row[0], 'cluster_label': row[1], 'article_count': row[2],
             'excluded_count': row[3] or 0, 'representative_title': row[4]}
            for row in rows
        ]

    def get_all_articles_with_clusters(self) -> Dict[Tuple[str, str], Dict]:
        """Retrieve all articles with their cluster info in one query (avoids O(N) calls)"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT a.article_id, a.source, a.title, a.abstract, a.year, a.authors, a.journal,
                       c.cluster_id, c.cluster_label
                FROM articles a
                LEFT JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
            """)
            rows = cursor.fetchall()

        result = {}
        for row in rows:
            key = (row[0], row[1])
            result[key] = {
                'article_id': row[0],
                'source': row[1],
                'title': row[2],
                'abstract': row[3],
                'year': row[4],
                'authors': json.loads(row[5]) if row[5] else [],
                'journal': row[6],
                'cluster_id': row[7],
                'cluster_label': row[8]
            }
        return result

    def get_statistics(self) -> Dict:
        """Get database statistics"""
        with self._lock:
            cursor = self.conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM articles")
            article_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM embeddings")
            embedding_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT cluster_id) FROM clusters")
            cluster_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM screening")
            excluded_count = cursor.fetchone()[0]

            # Source breakdown
            cursor.execute("SELECT source, COUNT(*) FROM articles GROUP BY source")
            sources = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            'total_articles': article_count,
            'articles_with_embeddings': embedding_count,
            'num_clusters': cluster_count,
            'excluded_articles': excluded_count,
            'sources': sources
        }

    def build_screening_report_counts(self) -> Dict:
        """Counts for PRISMA-style screening report (empty DB → all zeros)."""
        with self._lock:
            cursor = self.conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM articles")
            total_articles = int(cursor.fetchone()[0] or 0)

            cursor.execute("SELECT source, COUNT(*) FROM articles GROUP BY source")
            by_source = {row[0]: int(row[1]) for row in cursor.fetchall()}

            cursor.execute("SELECT COUNT(*) FROM embeddings")
            with_embeddings = int(cursor.fetchone()[0] or 0)

            cursor.execute(
                "SELECT reason, COUNT(*) FROM screening GROUP BY reason"
            )
            reason_rows = cursor.fetchall()
            excluded = {"duplicate": 0, "cluster": 0, "manual": 0, "total": 0}
            for reason, count in reason_rows:
                n = int(count or 0)
                key = (reason or "manual").strip().lower()
                if key in ("duplicate", "cluster", "manual"):
                    excluded[key] += n
                else:
                    # Unknown reasons still count toward total and manual bucket.
                    excluded["manual"] += n
                excluded["total"] += n

            cursor.execute("SELECT COUNT(*) FROM notes WHERE starred = 1")
            starred = int(cursor.fetchone()[0] or 0)

            cursor.execute(
                "SELECT COUNT(DISTINCT cluster_id) FROM clusters WHERE cluster_id != -1"
            )
            clusters = int(cursor.fetchone()[0] or 0)

        included = max(0, total_articles - excluded["total"])
        return {
            "total_articles": total_articles,
            "by_source": by_source,
            "with_embeddings": with_embeddings,
            "excluded": excluded,
            "included": included,
            "starred": starred,
            "clusters": clusters,
        }

    def close(self):
        """Close database connection"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
