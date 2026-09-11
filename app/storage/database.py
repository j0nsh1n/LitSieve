"""
Database Module
Handles storage and retrieval of articles and embeddings
"""

import json
import logging
import pickle
import re
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.storage import dbconn

logger = logging.getLogger(__name__)


class ArticleDatabase:
    """SQLite database for storing articles and their embeddings"""

    def __init__(self, db_path: str = "articles.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = dbconn.connect(db_path, check_same_thread=False)
        # WAL reduces "database is locked" under concurrent readers/writers;
        # busy_timeout waits up to 5s before raising instead of failing immediately.
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        # Child tables use ON DELETE CASCADE; upserts use ON CONFLICT DO UPDATE
        # (not INSERT OR REPLACE) so FKs can stay on.
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.Lock()
        self.create_tables()
        self.migrate_schema()
        # Crash / restart leftover: jobs are in-memory, so never auto-swap.
        self.drop_staging_articles()

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
                    ON DELETE CASCADE
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
                    ON DELETE CASCADE
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
                    ON DELETE CASCADE
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
                    ON DELETE CASCADE
            )
        """)

        # Key points (bullets JSON): extractive from abstract, or AI rewrite
        # saved explicitly by the student (origin='ai' survives re-search and
        # re-prepare until the library is cleared on replace-fetch).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS key_points (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                bullets TEXT NOT NULL DEFAULT '[]',
                origin TEXT NOT NULL DEFAULT 'extractive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            )
        """)

        # Reader Mode explanations (per audience): derived, regenerable AI
        # artifacts keyed like key_points. Content and verification are JSON
        # text; the abstract itself is never stored (abstract_hash only).
        # Not preserved across replace-fetch — regenerated on demand.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reader_explanations (
                article_id        TEXT NOT NULL,
                source            TEXT NOT NULL DEFAULT 'pubmed',
                audience          TEXT NOT NULL,
                abstract_hash     TEXT NOT NULL,
                prompt_version    TEXT NOT NULL,
                verifier_version  TEXT NOT NULL DEFAULT 'v1',
                content_json      TEXT NOT NULL,
                verification_json TEXT NOT NULL,
                provider          TEXT,
                model             TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source, audience),
                FOREIGN KEY (article_id, source)
                    REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
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

        # AI-saved key points need an origin flag so extractive re-runs do not
        # overwrite student-approved rewrites on re-search / re-prepare.
        cursor.execute("PRAGMA table_info(key_points)")
        kp_columns = [col[1] for col in cursor.fetchall()]
        if kp_columns and "origin" not in kp_columns:
            cursor.execute(
                "ALTER TABLE key_points ADD COLUMN origin TEXT NOT NULL DEFAULT 'extractive'"
            )

        # Defensive re-create: create_tables() normally makes this table, but
        # a connection opened by older code (or mid-migration) may not have
        # run the newest init block. IF NOT EXISTS keeps this idempotent.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reader_explanations (
                article_id        TEXT NOT NULL,
                source            TEXT NOT NULL DEFAULT 'pubmed',
                audience          TEXT NOT NULL,
                abstract_hash     TEXT NOT NULL,
                prompt_version    TEXT NOT NULL,
                verifier_version  TEXT NOT NULL DEFAULT 'v1',
                content_json      TEXT NOT NULL,
                verification_json TEXT NOT NULL,
                provider          TEXT,
                model             TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source, audience),
                FOREIGN KEY (article_id, source)
                    REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            )
        """)

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

    STAGING_TABLE = "staging_articles"

    def _staging_exists(self, cursor) -> bool:
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (self.STAGING_TABLE,),
        )
        return cursor.fetchone() is not None

    def ensure_staging_articles(self) -> None:
        """Create the replace-fetch staging table (no FKs to live rows)."""
        with self._lock:
            self.conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.STAGING_TABLE} (
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
                """
            )
            self.conn.commit()

    def drop_staging_articles(self) -> None:
        with self._lock:
            self.conn.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
            self.conn.commit()

    def reset_staging_articles(self) -> None:
        self.drop_staging_articles()
        self.ensure_staging_articles()

    def count_staging_articles(self) -> int:
        with self._lock:
            cursor = self.conn.cursor()
            if not self._staging_exists(cursor):
                return 0
            cursor.execute(f"SELECT COUNT(*) FROM {self.STAGING_TABLE}")
            return int(cursor.fetchone()[0] or 0)

    def replace_from_staging(self) -> int:
        """Swap live articles for staging; keep notes/stars/AI key points/screening
        and embeddings for keys that still exist. Drops clusters. No-op if empty.
        """
        with self._lock:
            cursor = self.conn.cursor()
            if not self._staging_exists(cursor):
                return 0
            cursor.execute(f"SELECT COUNT(*) FROM {self.STAGING_TABLE}")
            n = int(cursor.fetchone()[0] or 0)
            if n <= 0:
                cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
                self.conn.commit()
                return 0
            try:
                for tmp in (
                    "_swap_keep_notes",
                    "_swap_keep_ai_kp",
                    "_swap_keep_screening",
                    "_swap_keep_emb",
                ):
                    cursor.execute(f"DROP TABLE IF EXISTS {tmp}")
                cursor.execute(
                    f"""
                    CREATE TABLE _swap_keep_notes AS
                    SELECT n.article_id, n.source, n.note, n.starred, n.updated_at
                    FROM notes n
                    INNER JOIN {self.STAGING_TABLE} s
                      ON n.article_id = s.article_id AND n.source = s.source
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE _swap_keep_ai_kp AS
                    SELECT k.article_id, k.source, k.bullets, k.origin, k.created_at
                    FROM key_points k
                    INNER JOIN {self.STAGING_TABLE} s
                      ON k.article_id = s.article_id AND k.source = s.source
                    WHERE k.origin = 'ai'
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE _swap_keep_screening AS
                    SELECT sc.article_id, sc.source, sc.reason, sc.created_at
                    FROM screening sc
                    INNER JOIN {self.STAGING_TABLE} s
                      ON sc.article_id = s.article_id AND sc.source = s.source
                    """
                )
                cursor.execute(
                    f"""
                    CREATE TABLE _swap_keep_emb AS
                    SELECT e.article_id, e.source, e.embedding, e.dtype, e.shape,
                           e.model_name, e.created_at
                    FROM embeddings e
                    INNER JOIN {self.STAGING_TABLE} s
                      ON e.article_id = s.article_id AND e.source = s.source
                    INNER JOIN articles a
                      ON a.article_id = e.article_id AND a.source = e.source
                    WHERE COALESCE(a.title, '') = COALESCE(s.title, '')
                      AND COALESCE(a.abstract, '') = COALESCE(s.abstract, '')
                    """
                )
                cursor.execute("DELETE FROM key_points")
                cursor.execute("DELETE FROM notes")
                cursor.execute("DELETE FROM screening")
                cursor.execute("DELETE FROM clusters")
                cursor.execute("DELETE FROM embeddings")
                cursor.execute("DELETE FROM articles")
                cursor.execute(
                    f"""
                    INSERT INTO articles
                    (article_id, source, title, abstract, year, authors, journal, created_at)
                    SELECT article_id, source, title, abstract, year, authors, journal, created_at
                    FROM {self.STAGING_TABLE}
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO notes (article_id, source, note, starred, updated_at)
                    SELECT article_id, source, note, starred, updated_at
                    FROM _swap_keep_notes
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO key_points
                    (article_id, source, bullets, origin, created_at)
                    SELECT article_id, source, bullets, origin, created_at
                    FROM _swap_keep_ai_kp
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO screening (article_id, source, reason, created_at)
                    SELECT article_id, source, reason, created_at
                    FROM _swap_keep_screening
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO embeddings
                    (article_id, source, embedding, dtype, shape, model_name, created_at)
                    SELECT article_id, source, embedding, dtype, shape, model_name, created_at
                    FROM _swap_keep_emb
                    """
                )
                cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
                for tmp in (
                    "_swap_keep_notes",
                    "_swap_keep_ai_kp",
                    "_swap_keep_screening",
                    "_swap_keep_emb",
                ):
                    cursor.execute(f"DROP TABLE IF EXISTS {tmp}")
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
            return n

    def clear_all(self):
        """Wipe the library (sample reset / explicit empty).

        Replace-fetch no longer uses this; it stages then swaps so a failed
        fetch cannot leave an empty library. Append fetch and re-prepare leave
        origin=ai rows intact.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM key_points")
            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM screening")
            cursor.execute("DELETE FROM clusters")
            cursor.execute("DELETE FROM embeddings")
            cursor.execute("DELETE FROM articles")
            self.conn.commit()

    def keep_starred_and_noted(self) -> Dict:
        """Start over (option B): drop unmarked papers; keep starred/noted.

        Keeps any article that is starred or has a non-empty (trimmed) note.
        Child rows cascade. Leftover staging is dropped. Idempotent when only
        annotated papers remain.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles")
            before = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                """
                SELECT a.article_id, a.source
                FROM articles a
                INNER JOIN notes n
                  ON n.article_id = a.article_id AND n.source = a.source
                WHERE n.starred = 1 OR TRIM(COALESCE(n.note, '')) != ''
                """
            )
            keep = {(r[0], r[1]) for r in cursor.fetchall()}
            if not keep:
                cursor.execute("DELETE FROM key_points")
                cursor.execute("DELETE FROM notes")
                cursor.execute("DELETE FROM screening")
                cursor.execute("DELETE FROM clusters")
                cursor.execute("DELETE FROM embeddings")
                cursor.execute("DELETE FROM articles")
                cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
                self.conn.commit()
                return {"deleted": before, "remaining": 0, "kept": 0}

            cursor.execute("SELECT article_id, source FROM articles")
            drop = [
                (r[0], r[1])
                for r in cursor.fetchall()
                if (r[0], r[1]) not in keep
            ]
            if drop:
                cursor.executemany(
                    "DELETE FROM articles WHERE article_id = ? AND source = ?",
                    drop,
                )
            cursor.execute(
                """
                DELETE FROM notes
                WHERE starred = 0 AND TRIM(COALESCE(note, '')) = ''
                """
            )
            cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
            self.conn.commit()
            cursor.execute("SELECT COUNT(*) FROM articles")
            remaining = int(cursor.fetchone()[0] or 0)
            deleted = max(0, before - remaining)
            logger.info(
                "keep_starred_and_noted: deleted=%d remaining=%d",
                deleted, remaining,
            )
            return {
                "deleted": deleted,
                "remaining": remaining,
                "kept": remaining,
            }

    @staticmethod
    def _norm_title(title: str) -> str:
        """Normalize title for cheap fetch-time near-duplicate checks."""
        t = (title or "").lower()
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    @staticmethod
    def _norm_doi(article_id: str, source: str) -> str:
        """Normalize DOI-like ids (CrossRef and bare DOI strings)."""
        raw = (article_id or "").strip().lower()
        if not raw:
            return ""
        raw = raw.replace("https://doi.org/", "").replace("http://doi.org/", "")
        raw = raw.replace("doi:", "").strip()
        # CrossRef always uses DOI as id; others only if it looks like one.
        if source == "crossref" or raw.startswith("10."):
            return raw
        return ""

    def insert_articles(
        self, articles: List[Dict], dedupe: bool = True, *, staging: bool = False
    ) -> Dict:
        """
        Upsert articles into the database.

        Uses ON CONFLICT DO UPDATE (not REPLACE) so foreign-key children are
        not cascade-deleted when metadata is refreshed.

        When dedupe=True, skip rows whose normalized title (or DOI) already
        exists under another source in the collection or earlier in this batch.

        staging=True writes replace-fetch rows into staging_articles (dedupe
        against staging only) so the live library stays intact until swap.

        Returns:
            dict with inserted, updated, skipped_duplicates, dropped counts.
        """
        inserted = 0
        updated = 0
        skipped_duplicates = 0
        dropped = 0
        stale_derived = 0
        table = self.STAGING_TABLE if staging else "articles"

        with self._lock:
            cursor = self.conn.cursor()
            existing_titles: set = set()
            existing_dois: set = set()
            if dedupe:
                cursor.execute(f"SELECT article_id, source, title FROM {table}")
                for aid, src, title in cursor.fetchall():
                    nt = self._norm_title(title)
                    if nt:
                        existing_titles.add(nt)
                    doi = self._norm_doi(aid, src)
                    if doi:
                        existing_dois.add(doi)

            batch_titles: set = set()
            batch_dois: set = set()

            for article in articles:
                try:
                    aid = article['article_id']
                    source = article.get('source', 'pubmed')
                    title = article.get('title', '')
                    nt = self._norm_title(title)
                    doi = self._norm_doi(aid, source)

                    cursor.execute(
                        f"SELECT title, abstract FROM {table} "
                        f"WHERE article_id = ? AND source = ?",
                        (aid, source),
                    )
                    prior = cursor.fetchone()
                    existed = prior is not None

                    # Same primary key → upsert OK. Cross-source title/DOI dups skip.
                    if dedupe and not existed:
                        if doi and (doi in existing_dois or doi in batch_dois):
                            skipped_duplicates += 1
                            continue
                        if nt and (nt in existing_titles or nt in batch_titles):
                            skipped_duplicates += 1
                            continue

                    cursor.execute(f"""
                        INSERT INTO {table}
                        (article_id, source, title, abstract, year, authors, journal)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(article_id, source) DO UPDATE SET
                            title = excluded.title,
                            abstract = excluded.abstract,
                            year = excluded.year,
                            authors = excluded.authors,
                            journal = excluded.journal
                    """, (
                        aid,
                        source,
                        title,
                        article.get('abstract', ''),
                        article.get('year', ''),
                        json.dumps(article.get('authors', [])),
                        article.get('journal', '')
                    ))
                    if existed:
                        updated += 1
                        # Title/abstract are what embeddings and extractive
                        # bullets were built from. Notes/stars/AI bullets stay;
                        # ON CONFLICT does not cascade-delete children.
                        if (
                            not staging
                            and (
                                (prior[0] or "") != (title or "")
                                or (prior[1] or "") != (article.get("abstract") or "")
                            )
                        ):
                            cursor.execute(
                                "DELETE FROM embeddings WHERE article_id = ? AND source = ?",
                                (aid, source),
                            )
                            cursor.execute(
                                "DELETE FROM key_points WHERE article_id = ? AND source = ? "
                                "AND origin = 'extractive'",
                                (aid, source),
                            )
                            stale_derived += 1
                    else:
                        inserted += 1
                        if nt:
                            batch_titles.add(nt)
                            existing_titles.add(nt)
                        if doi:
                            batch_dois.add(doi)
                            existing_dois.add(doi)
                except Exception as e:
                    dropped += 1
                    logger.warning("Error inserting article %s: %s", article.get('article_id'), e)
            self.conn.commit()
        logger.info(
            "Articles upsert: inserted=%d updated=%d skipped_dups=%d dropped=%d stale_derived=%d",
            inserted, updated, skipped_duplicates, dropped, stale_derived,
        )
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_duplicates": skipped_duplicates,
            "dropped": dropped,
            "stale_derived": stale_derived,
        }

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

    def get_starred_keys(self) -> List[Tuple[str, str]]:
        """Keys of notes marked starred=1 (order stable by article_id, source)."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT article_id, source FROM notes WHERE starred = 1 "
                "ORDER BY article_id, source"
            )
            return [(r[0], r[1]) for r in cursor.fetchall()]

    def insert_key_points(
        self,
        points: Dict[Tuple[str, str], List[str]],
        *,
        origin: str = "extractive",
    ) -> int:
        """Store key-point bullets for (article_id, source) keys.

        Empty bullet lists are still stored so we do not re-process short
        abstracts on every embed pass. origin is ``extractive`` (default) or
        ``ai`` (student-approved Refine rewrite — protected from overwrite).
        """
        if not points:
            return 0
        origin = "ai" if origin == "ai" else "extractive"
        with self._lock:
            cursor = self.conn.cursor()
            for (article_id, source), bullets in points.items():
                cursor.execute(
                    """
                    INSERT INTO key_points (article_id, source, bullets, origin, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(article_id, source) DO UPDATE SET
                        bullets = excluded.bullets,
                        origin = excluded.origin,
                        created_at = CURRENT_TIMESTAMP
                    """,
                    (article_id, source, json.dumps(list(bullets or [])), origin),
                )
            self.conn.commit()
        logger.info("Stored key points for %d articles (origin=%s)", len(points), origin)
        return len(points)

    def get_key_points_map(self) -> Dict[Tuple[str, str], List[str]]:
        """Map (article_id, source) -> list of bullet strings."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source, bullets FROM key_points")
            rows = cursor.fetchall()
        out: Dict[Tuple[str, str], List[str]] = {}
        for article_id, source, bullets_json in rows:
            try:
                bullets = json.loads(bullets_json) if bullets_json else []
            except (TypeError, json.JSONDecodeError):
                bullets = []
            if not isinstance(bullets, list):
                bullets = []
            out[(article_id, source)] = [str(b) for b in bullets if b]
        return out

    def get_key_points_origin_map(self) -> Dict[Tuple[str, str], str]:
        """Map (article_id, source) -> 'extractive' | 'ai'."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(key_points)")
            cols = {row[1] for row in cursor.fetchall()}
            if "origin" not in cols:
                cursor.execute("SELECT article_id, source FROM key_points")
                return {(row[0], row[1]): "extractive" for row in cursor.fetchall()}
            cursor.execute("SELECT article_id, source, origin FROM key_points")
            rows = cursor.fetchall()
        out: Dict[Tuple[str, str], str] = {}
        for article_id, source, origin in rows:
            out[(article_id, source)] = "ai" if origin == "ai" else "extractive"
        return out

    def get_key_points_keys(self) -> set:
        """Set of (article_id, source) that already have a key_points row."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source FROM key_points")
            return {(row[0], row[1]) for row in cursor.fetchall()}

    def get_ai_key_points_keys(self) -> set:
        """Keys whose key points were explicitly saved from an AI refine."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("PRAGMA table_info(key_points)")
            cols = {row[1] for row in cursor.fetchall()}
            if "origin" not in cols:
                return set()
            cursor.execute(
                "SELECT article_id, source FROM key_points WHERE origin = 'ai'"
            )
            return {(row[0], row[1]) for row in cursor.fetchall()}

    def get_reader_explanation(
        self, article_id: str, source: str, audience: str
    ) -> Optional[Dict]:
        """Fetch one Reader Mode explanation, JSON parsed.

        Returns None on a missing row or unparsable JSON (treated as a cache
        miss so the caller regenerates instead of surfacing corrupt rows).
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT article_id, source, audience, abstract_hash, prompt_version,
                       verifier_version, content_json, verification_json,
                       provider, model, created_at
                FROM reader_explanations
                WHERE article_id = ? AND source = ? AND audience = ?
                """,
                (article_id, source, audience),
            )
            row = cursor.fetchone()
        if not row:
            return None
        try:
            content = json.loads(row[6]) if row[6] else None
            verification = json.loads(row[7]) if row[7] else None
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(content, dict) or not isinstance(verification, dict):
            return None
        return {
            "article_id": row[0],
            "source": row[1],
            "audience": row[2],
            "abstract_hash": row[3],
            "prompt_version": row[4],
            "verifier_version": row[5],
            "content": content,
            "verification": verification,
            "provider": row[8],
            "model": row[9],
            "created_at": row[10],
        }

    def upsert_reader_explanation(
        self,
        article_id: str,
        source: str,
        audience: str,
        abstract_hash: str,
        prompt_version: str,
        content: Dict,
        verification: Dict,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        verifier_version: str = "v1",
    ) -> None:
        """Insert or refresh one Reader Mode explanation row.

        ON CONFLICT DO UPDATE (not INSERT OR REPLACE) keeps the FK alive.
        content/verification are stored as JSON text; the abstract is not.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO reader_explanations (
                    article_id, source, audience, abstract_hash, prompt_version,
                    verifier_version, content_json, verification_json,
                    provider, model, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(article_id, source, audience) DO UPDATE SET
                    abstract_hash = excluded.abstract_hash,
                    prompt_version = excluded.prompt_version,
                    verifier_version = excluded.verifier_version,
                    content_json = excluded.content_json,
                    verification_json = excluded.verification_json,
                    provider = excluded.provider,
                    model = excluded.model,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    article_id,
                    source,
                    audience,
                    abstract_hash,
                    prompt_version,
                    verifier_version,
                    json.dumps(content),
                    json.dumps(verification),
                    provider,
                    model,
                ),
            )
            self.conn.commit()

    def exclude_articles(self, keys: List[Tuple[str, str]], reason: str = 'manual') -> int:
        """Mark articles as screened out (excluded from search/dedup).

        Args:
            keys: list of (article_id, source) tuples
            reason: code from screening_reasons.EXCLUSION_REASONS
                (manual | cluster | duplicate | off_topic | …)

        Returns:
            Number of rows written.
        """
        if not keys:
            return 0
        from app.content.screening_reasons import normalize_reason
        reason = normalize_reason(reason, default="manual")
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

    def get_excluded_items_for_reason(self, reason: str) -> List[Dict[str, str]]:
        """List excluded papers for one screening reason (for Simple-mode Undo)."""
        from app.content.screening_reasons import normalize_reason
        reason = normalize_reason(reason, default="manual")
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT article_id, source FROM screening WHERE reason = ?",
                (reason,),
            )
            return [
                {"article_id": row[0], "source": row[1]}
                for row in cursor.fetchall()
            ]

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

    def get_year_counts(self) -> Dict[str, int]:
        """Papers per publication year (unknown years under 'unknown')."""
        from app.utils import parse_year
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT year FROM articles")
            rows = cursor.fetchall()
        counts: Dict[str, int] = {}
        for (year_raw,) in rows:
            y = parse_year(year_raw)
            key = str(y) if y else "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts

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

            cursor.execute("SELECT year FROM articles")
            year_rows = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM notes WHERE TRIM(note) != ''")
            notes_count = int(cursor.fetchone()[0] or 0)
            cursor.execute("SELECT COUNT(*) FROM notes WHERE starred = 1")
            starred_count = int(cursor.fetchone()[0] or 0)
            cursor.execute(
                "SELECT COUNT(*) FROM key_points WHERE origin = 'ai'"
            )
            ai_key_points = int(cursor.fetchone()[0] or 0)

        from app.utils import parse_year
        year_counts: Dict[str, int] = {}
        for (year_raw,) in year_rows:
            y = parse_year(year_raw)
            key = str(y) if y else "unknown"
            year_counts[key] = year_counts.get(key, 0) + 1

        return {
            'total_articles': article_count,
            'articles_with_embeddings': embedding_count,
            'num_clusters': cluster_count,
            'excluded_articles': excluded_count,
            'sources': sources,
            'year_counts': year_counts,
            'notes': notes_count,
            'starred': starred_count,
            'ai_key_points': ai_key_points,
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
            from app.content.screening_reasons import EXCLUSION_REASONS, normalize_reason
            excluded = {code: 0 for code in EXCLUSION_REASONS}
            excluded["total"] = 0
            for reason, count in reason_rows:
                n = int(count or 0)
                key = normalize_reason(reason, default="manual")
                excluded[key] = excluded.get(key, 0) + n
                excluded["total"] += n

            cursor.execute("SELECT COUNT(*) FROM notes WHERE starred = 1")
            starred = int(cursor.fetchone()[0] or 0)

            cursor.execute(
                "SELECT COUNT(DISTINCT cluster_id) FROM clusters WHERE cluster_id != -1"
            )
            clusters = int(cursor.fetchone()[0] or 0)

            cursor.execute("SELECT year FROM articles")
            year_rows = cursor.fetchall()

        from app.utils import parse_year
        by_year: Dict[str, int] = {}
        for (year_raw,) in year_rows:
            y = parse_year(year_raw)
            key = str(y) if y else "unknown"
            by_year[key] = by_year.get(key, 0) + 1

        included = max(0, total_articles - excluded["total"])
        return {
            "total_articles": total_articles,
            "by_source": by_source,
            "by_year": by_year,
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
