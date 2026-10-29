"""
Database Module
Handles storage and retrieval of articles and embeddings
"""

import json
import logging
import pickle
import re
import threading
import unicodedata
import zlib
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app.services.citations import _is_placeholder_journal
from app.services.work_types import normalize_doi, work_type_count_key
from app.storage import dbconn

logger = logging.getLogger(__name__)


ARTICLE_COLUMNS = (
    "article_id", "source", "title", "abstract", "year", "authors", "journal",
    "work_type", "provider_type", "doi", "container_title", "host_name",
    "oa_status", "best_oa_url", "evidence_basis", "biblio",
)
SEARCH_ARTICLE_COLUMNS = ARTICLE_COLUMNS[:7]
_MERGE_COLUMNS = ARTICLE_COLUMNS[7:]
_GENERIC_TITLES = frozenset({
    "introduction",
    "conclusion",
    "preface",
    "foreword",
    "index",
    "front matter",
    "back matter",
    "bibliography",
    "references",
    "epilogue",
    "prologue",
    "acknowledgments",
    "acknowledgements",
    "editorial",
    "einleitung",
    "chapter one",
    "chapter two",
    "chapter three",
    "chapter four",
    "chapter five",
    "chapter six",
    "chapter seven",
    "chapter eight",
    "chapter nine",
    "chapter ten",
    "chapter eleven",
    "chapter twelve",
})
_CHAPTER_TITLE = re.compile(
    r"^chapter (?:\d+|i{1,3}|iv|vi{0,3}|ix|xi{0,3}|xiv|xvi{0,3}|xix|xx)$"
)
_INITIALS_TOKEN = re.compile(r"^[A-Za-z](?:[.\s]*[A-Za-z]){0,2}\.?$")
_INCOMPATIBLE_WORK_TYPES = frozenset({
    frozenset({"book", "book-review"}),
    frozenset({"book", "book-chapter"}),
    frozenset({"book", "review-article"}),
    frozenset({"preprint", "journal-article"}),
    frozenset({"dataset", "journal-article"}),
})
_IDENTITY_TYPE_ALIASES = {
    "article": "journal-article",
    "chapter": "book-chapter",
    "edited-book": "book",
}


def _row_to_article(row, columns: Tuple[str, ...] = ARTICLE_COLUMNS) -> Dict:
    article = dict(zip(columns, row))
    if "authors" in article:
        article["authors"] = json.loads(article["authors"]) if article["authors"] else []
    return article


def omit_null_metadata(article: Dict) -> Dict:
    """Omit unset work-metadata keys so public payloads keep the pre-P1.1 shape."""
    for name in ARTICLE_COLUMNS[7:]:
        if article.get(name) is None:
            article.pop(name, None)
    article.pop("_extra", None)
    return article


def encode_provider_record(record: Dict) -> Tuple[Optional[bytes], Optional[str]]:
    """zlib-compress UTF-8 JSON; over 4096 compressed bytes is NULL plus too_large."""
    encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    compressed = zlib.compress(encoded)
    if len(compressed) > 4096:
        return None, "too_large"
    return compressed, None


def _article_table_ddl(table: str) -> str:
    definitions = {
        "article_id": "TEXT NOT NULL",
        "source": "TEXT NOT NULL DEFAULT 'pubmed'",
        "title": "TEXT NOT NULL",
        "abstract": "TEXT NOT NULL",
    }
    columns = ", ".join(f"{name} {definitions.get(name, 'TEXT')}" for name in ARTICLE_COLUMNS)
    return f"""
        CREATE TABLE IF NOT EXISTS {table} (
            {columns},
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (article_id, source)
        )
    """


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

    @contextmanager
    def _writing(self):
        """Hold the lock for a write; roll back on any error.

        A failure mid-batch (a foreign-key error, say) used to leave the
        transaction open on the shared connection, so the next caller's
        commit wrote half a batch (audit 20.5).
        """
        with self._lock:
            try:
                yield
            except BaseException:
                self.conn.rollback()
                raise

    def compact(self) -> None:
        """Give the space of deleted rows back to the disk (audit 20.1).

        Quota counts bytes on disk, and SQLite keeps freed pages inside the
        file, so start over, a replace fetch or a clear freed nothing.
        """
        with self._lock:
            try:
                self.conn.commit()
                self.conn.execute("VACUUM")
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                # Another connection's open read can block it; the space comes
                # back at the next compact.
                logger.warning("Could not compact %s: %s", self.db_path, e)

    def create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()

        # Articles table
        cursor.execute(_article_table_ddl("articles"))
        self._create_article_extra()

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

        self._ensure_run_record_tables(cursor)
        self.conn.commit()

    def _ensure_run_record_tables(self, cursor) -> None:
        """Collect inputs and Search questions. Not cloned; Start over clears them."""
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fetch_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                raw_input TEXT NOT NULL,
                sources_json TEXT NOT NULL,
                topics_json TEXT NOT NULL DEFAULT '[]',
                areas_json TEXT NOT NULL DEFAULT '[]',
                mode TEXT NOT NULL,
                max_results INTEGER,
                outcome TEXT,
                app_version TEXT NOT NULL,
                per_source_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS question_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                question_text TEXT NOT NULL,
                filters_json TEXT NOT NULL DEFAULT '{}',
                embedding_model TEXT,
                ranker_version TEXT NOT NULL,
                result_keys_json TEXT NOT NULL DEFAULT '[]'
            )
        """)

    def _prune_run_record_table(self, cursor, table: str, keep: int = 50) -> None:
        cursor.execute(
            f"""
            DELETE FROM {table}
            WHERE id NOT IN (
                SELECT id FROM {table} ORDER BY id DESC LIMIT ?
            )
            """,
            (keep,),
        )

    def insert_fetch_run(
        self,
        *,
        started_at: str,
        raw_input: str,
        sources: List,
        topics: List,
        areas: List,
        mode: str,
        max_results: Optional[int],
        app_version: str,
    ) -> int:
        from app.storage.run_record import KEEP_ROWS, json_text

        with self._writing():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO fetch_runs (
                    started_at, raw_input, sources_json, topics_json, areas_json,
                    mode, max_results, app_version, per_source_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}')
                """,
                (
                    started_at,
                    raw_input,
                    json_text(sources),
                    json_text(topics),
                    json_text(areas),
                    mode,
                    max_results,
                    app_version,
                ),
            )
            run_id = cursor.lastrowid
            if run_id is None:
                raise RuntimeError("fetch_runs insert produced no id")
            self._prune_run_record_table(cursor, "fetch_runs", KEEP_ROWS)
            self.conn.commit()
            return int(run_id)

    def update_fetch_run(
        self,
        run_id: int,
        *,
        finished_at: str,
        outcome: str,
        per_source: Dict,
    ) -> None:
        from app.storage.run_record import json_text

        with self._writing():
            self.conn.execute(
                """
                UPDATE fetch_runs
                SET finished_at = ?, outcome = ?, per_source_json = ?
                WHERE id = ?
                """,
                (finished_at, outcome, json_text(per_source), run_id),
            )
            self.conn.commit()

    def insert_question_log(
        self,
        *,
        created_at: str,
        kind: str,
        question_text: str,
        filters: Dict,
        embedding_model: Optional[str],
        result_keys: List,
    ) -> None:
        from app.storage.run_record import KEEP_ROWS, RANKER_VERSION, json_text

        with self._writing():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                INSERT INTO question_log (
                    created_at, kind, question_text, filters_json,
                    embedding_model, ranker_version, result_keys_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    kind,
                    question_text,
                    json_text(filters),
                    embedding_model,
                    RANKER_VERSION,
                    json_text(result_keys),
                ),
            )
            self._prune_run_record_table(cursor, "question_log", KEEP_ROWS)
            self.conn.commit()

    def clear_run_records(self, cursor=None) -> None:
        if cursor is not None:
            cursor.execute("DELETE FROM fetch_runs")
            cursor.execute("DELETE FROM question_log")
            return
        with self._writing():
            self.conn.execute("DELETE FROM fetch_runs")
            self.conn.execute("DELETE FROM question_log")
            self.conn.commit()

    def _create_article_extra(self, *, staging: bool = False) -> None:
        table = "staging_article_extra" if staging else "article_extra"
        foreign_key = "" if staging else """,
            FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                ON DELETE CASCADE
        """
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL,
                provenance TEXT NOT NULL DEFAULT '{{}}',
                locations TEXT NOT NULL DEFAULT '[]',
                related TEXT NOT NULL DEFAULT '[]',
                provider_record BLOB,
                raw_status TEXT,
                fetch_run_id INTEGER,
                PRIMARY KEY (article_id, source)
                {foreign_key}
            )
        """)

    def store_provider_record(
        self, article_id: str, source: str, record: Dict, *, staging: bool = False
    ) -> None:
        """Store an already-trimmed record, or mark it too large without truncation."""
        blob, status = encode_provider_record(record)
        table = "staging_article_extra" if staging else "article_extra"
        with self._writing():
            self.conn.execute(f"""
                INSERT INTO {table} (article_id, source, provider_record, raw_status)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(article_id, source) DO UPDATE SET
                    provider_record = excluded.provider_record,
                    raw_status = excluded.raw_status
            """, (article_id, source, blob, status))
            self.conn.commit()

    def _write_article_extra(self, cursor, article_id: str, source: str, extra: Dict, *, staging: bool) -> None:
        table = "staging_article_extra" if staging else "article_extra"
        record = extra.get("provider_record")
        blob = status = None
        if isinstance(record, dict):
            blob, status = encode_provider_record(record)
        provenance = extra.get("provenance") or {}
        locations = extra.get("locations") or []
        cursor.execute(f"""
            INSERT INTO {table} (article_id, source, provenance, locations, provider_record, raw_status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id, source) DO UPDATE SET
                provenance = excluded.provenance,
                locations = excluded.locations,
                provider_record = excluded.provider_record,
                raw_status = excluded.raw_status
        """, (
            article_id,
            source,
            json.dumps(provenance, ensure_ascii=False, separators=(",", ":")),
            json.dumps(locations, ensure_ascii=False, separators=(",", ":")),
            blob,
            status,
        ))

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
            cursor.execute(_article_table_ddl("articles"))
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
            legacy_columns = ", ".join((*ARTICLE_COLUMNS[:7], "created_at"))
            legacy_values = ", ".join(("pmid", "'pubmed'", *ARTICLE_COLUMNS[2:7], "created_at"))
            cursor.execute(f"""
                INSERT INTO articles ({legacy_columns})
                SELECT {legacy_values}
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

        for table in ("articles", self.STAGING_TABLE):
            cursor.execute(f"PRAGMA table_info({table})")
            article_columns = {col[1] for col in cursor.fetchall()}
            if article_columns:
                for name in ARTICLE_COLUMNS[7:]:
                    if name not in article_columns:
                        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT")
                cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_doi ON {table} (doi)")
        self._create_article_extra()
        if self._staging_exists(cursor):
            self._create_article_extra(staging=True)
        self._ensure_run_record_tables(cursor)
        self.conn.commit()

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
            self.conn.execute(_article_table_ddl(self.STAGING_TABLE))
            self.conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{self.STAGING_TABLE}_doi "
                f"ON {self.STAGING_TABLE} (doi)"
            )
            self._create_article_extra(staging=True)
            self.conn.commit()

    def drop_staging_articles(self) -> None:
        with self._lock:
            self.conn.execute("DROP TABLE IF EXISTS staging_article_extra")
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
                cursor.execute("DROP TABLE IF EXISTS staging_article_extra")
                cursor.execute(f"DROP TABLE IF EXISTS {self.STAGING_TABLE}")
                self.conn.commit()
                return 0
            try:
                cursor.execute("BEGIN")
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
                article_columns = ", ".join((*ARTICLE_COLUMNS, "created_at"))
                cursor.execute(
                    f"""
                    INSERT INTO articles ({article_columns})
                    SELECT {article_columns}
                    FROM {self.STAGING_TABLE}
                    """
                )
                extra_columns = (
                    "article_id, source, provenance, locations, related, "
                    "provider_record, raw_status, fetch_run_id"
                )
                cursor.execute(f"""
                    INSERT INTO article_extra ({extra_columns})
                    SELECT {extra_columns} FROM staging_article_extra
                """)
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
                cursor.execute("DROP TABLE IF EXISTS staging_article_extra")
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
                for tmp in (
                    "_swap_keep_notes",
                    "_swap_keep_ai_kp",
                    "_swap_keep_screening",
                    "_swap_keep_emb",
                ):
                    cursor.execute(f"DROP TABLE IF EXISTS {tmp}")
                self.conn.commit()
                raise
        self.compact()
        return n

    def clear_all(self):
        """Wipe the library (sample reset / explicit empty).

        Replace-fetch no longer uses this; it stages then swaps so a failed
        fetch cannot leave an empty library. Append fetch and re-prepare leave
        origin=ai rows intact.
        """
        with self._writing():
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM key_points")
            cursor.execute("DELETE FROM notes")
            cursor.execute("DELETE FROM screening")
            cursor.execute("DELETE FROM clusters")
            cursor.execute("DELETE FROM embeddings")
            cursor.execute("DELETE FROM articles")
            self.conn.commit()
        self.compact()

    def keep_starred_and_noted(self) -> Dict:
        """Start over, then give the freed pages back to the disk (audit 20.1)."""
        result = self._keep_starred_and_noted()
        if result.get("deleted"):
            self.compact()
        return result

    def _keep_starred_and_noted(self) -> Dict:
        """Start over (option B): drop unmarked papers; keep starred/noted.

        Keeps any article that is starred or has a non-empty (trimmed) note.
        Child rows cascade. Leftover staging is dropped. Idempotent when only
        annotated papers remain.
        """
        with self._writing():
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
                self.clear_run_records(cursor)
                cursor.execute("DROP TABLE IF EXISTS staging_article_extra")
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
            self.clear_run_records(cursor)
            cursor.execute("DROP TABLE IF EXISTS staging_article_extra")
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
        """Normalize title for identity: casefold, NFKD, keep letters and digits."""
        t = unicodedata.normalize("NFKD", title or "").casefold()
        chars = [
            ch if ch.isalnum() or ch.isspace() else " "
            for ch in t
            if not unicodedata.combining(ch)
        ]
        return re.sub(r"\s+", " ", "".join(chars)).strip()

    @staticmethod
    def _article_doi(article: Dict) -> str:
        """Bare DOI from the doi column, else a DOI-shaped article_id."""
        return (
            normalize_doi(article.get("doi"))
            or normalize_doi(article.get("article_id"))
            or ""
        )

    @staticmethod
    def _norm_doi(article_id: str, source: str, doi: Optional[str] = None) -> str:
        """Normalize a DOI from the doi column or a DOI-shaped article_id."""
        return ArticleDatabase._article_doi(
            {"article_id": article_id, "source": source, "doi": doi}
        )

    @staticmethod
    def _is_generic_title(nt: str) -> bool:
        if not nt:
            return True
        if nt in _GENERIC_TITLES or _CHAPTER_TITLE.match(nt):
            return True
        parts = nt.split()
        return len(parts) < 4 and all(part.isascii() for part in parts)

    @staticmethod
    def _year_int(year: Any) -> Optional[int]:
        if year is None:
            return None
        match = re.search(r"\b(\d{4})\b", str(year))
        return int(match.group(1)) if match else None

    @staticmethod
    def _is_initials_given(text: str) -> bool:
        compact = re.sub(r"[.\s]", "", text)
        if not compact.isalpha() or len(compact) > 3:
            return False
        if len(compact) == 1:
            return True
        return compact.isupper() or "." in text

    @staticmethod
    def _given_initials(given: str) -> str:
        text = (given or "").strip()
        if not text:
            return ""
        if ArticleDatabase._is_initials_given(text):
            return re.sub(r"[.\s]", "", text).casefold()
        parts = re.findall(r"[^\W\d_]+", text, flags=re.UNICODE)
        return "".join(part[0] for part in parts if part).casefold()

    @staticmethod
    def _given_fields(given: str) -> Tuple[str, str]:
        """Return (full given name, initials). Full name is empty for initials-only."""
        text = (given or "").strip()
        initials = ArticleDatabase._given_initials(text)
        if not text or ArticleDatabase._is_initials_token(text) or (
            ArticleDatabase._is_initials_given(text)
        ):
            return "", initials
        return ArticleDatabase._norm_title(text), initials

    @staticmethod
    def _is_initials_token(token: str) -> bool:
        text = (token or "").strip()
        if not text or not _INITIALS_TOKEN.match(text):
            return False
        letters = re.sub(r"[.\s]", "", text)
        if not letters.isalpha() or len(letters) > 3:
            return False
        if len(letters) == 1:
            return True
        return letters.isupper() or "." in text

    @staticmethod
    def _parse_person_name(name: Any) -> Tuple[str, str, str]:
        """Return (family, full given name, initials) for a first-author value."""
        if isinstance(name, dict):
            family = name.get("family") or name.get("last") or ""
            given = name.get("given") or name.get("first") or ""
            if family:
                full, initials = ArticleDatabase._given_fields(str(given))
                return ArticleDatabase._norm_title(str(family)), full, initials
            name = name.get("name") or name.get("display_name") or ""
        text = str(name or "").strip()
        if not text:
            return "", "", ""
        if "," in text:
            family, given = text.split(",", 1)
            full, initials = ArticleDatabase._given_fields(given)
            return ArticleDatabase._norm_title(family), full, initials
        parts = text.split()
        if len(parts) >= 2 and ArticleDatabase._is_initials_token(parts[-1]):
            full, initials = ArticleDatabase._given_fields(parts[-1])
            return (
                ArticleDatabase._norm_title(" ".join(parts[:-1])),
                full,
                initials,
            )
        if len(parts) == 1:
            return ArticleDatabase._norm_title(parts[0]), "", ""
        full, initials = ArticleDatabase._given_fields(" ".join(parts[:-1]))
        return ArticleDatabase._norm_title(parts[-1]), full, initials

    @staticmethod
    def _author_list(authors: Any) -> List:
        if not authors:
            return []
        if isinstance(authors, str):
            try:
                authors = json.loads(authors)
            except json.JSONDecodeError:
                authors = [authors]
        return authors if isinstance(authors, list) else []

    @staticmethod
    def _first_author(authors: Any) -> Tuple[str, str, str]:
        names = ArticleDatabase._author_list(authors)
        if not names:
            return "", "", ""
        return ArticleDatabase._parse_person_name(names[0])

    @staticmethod
    def _first_author_family(authors: Any) -> str:
        family, _given, _initials = ArticleDatabase._first_author(authors)
        return family

    @staticmethod
    def _initials_compatible(left: str, right: str) -> bool:
        if not left or not right:
            return True
        return left.startswith(right) or right.startswith(left)

    @staticmethod
    def _authors_conflict(existing: Any, incoming: Any) -> bool:
        existing_family, existing_given, existing_initials = (
            ArticleDatabase._first_author(existing)
        )
        incoming_family, incoming_given, incoming_initials = (
            ArticleDatabase._first_author(incoming)
        )
        if not existing_family or not incoming_family:
            return False
        if existing_family != incoming_family:
            return True
        if existing_given and incoming_given and existing_given != incoming_given:
            return True
        return not ArticleDatabase._initials_compatible(
            existing_initials, incoming_initials
        )

    @staticmethod
    def _authors_match(existing: Any, incoming: Any) -> bool:
        existing_family, existing_given, existing_initials = (
            ArticleDatabase._first_author(existing)
        )
        incoming_family, incoming_given, incoming_initials = (
            ArticleDatabase._first_author(incoming)
        )
        if not existing_family or not incoming_family:
            return False
        if existing_family != incoming_family:
            return False
        if existing_given and incoming_given and existing_given != incoming_given:
            return False
        return ArticleDatabase._initials_compatible(
            existing_initials, incoming_initials
        )

    @staticmethod
    def _identity_work_type(work_type: Any) -> str:
        text = str(work_type or "").strip()
        return _IDENTITY_TYPE_ALIASES.get(text, text)

    @staticmethod
    def _work_types_incompatible(existing: Any, incoming: Any) -> bool:
        left = ArticleDatabase._identity_work_type(existing)
        right = ArticleDatabase._identity_work_type(incoming)
        if not left or not right or left == right:
            return False
        return frozenset({left, right}) in _INCOMPATIBLE_WORK_TYPES

    def _effective_container(self, article: Dict) -> str:
        container = (article.get("container_title") or "").strip()
        if container:
            return self._norm_title(container)
        journal = (article.get("journal") or "").strip()
        if journal and not _is_placeholder_journal(journal):
            return self._norm_title(journal)
        return ""

    @staticmethod
    def _value_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if isinstance(value, (list, dict)) and not value:
            return True
        return False

    @staticmethod
    def _parse_biblio(value: Any) -> Dict:
        if value is None or value == "":
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        return {}

    @staticmethod
    def _field_equal(left: Any, right: Any) -> bool:
        if isinstance(left, str) or isinstance(right, str):
            return str(left or "").strip() == str(right or "").strip()
        return left == right

    @staticmethod
    def _merge_locations(existing: Any, incoming: Any) -> List[Dict]:
        out: List[Dict] = []
        seen: set = set()
        for loc in list(existing or []) + list(incoming or []):
            if not isinstance(loc, dict):
                continue
            url = str(loc.get("url") or loc.get("URL") or "")
            if url:
                if url in seen:
                    continue
                seen.add(url)
                out.append(loc)
            elif loc not in out:
                out.append(loc)
        return out

    def _title_same_work(self, existing: Dict, incoming: Dict) -> bool:
        """Title-path identity: veto on DOI conflict; year ±1; author; container."""
        existing_doi = self._article_doi(existing)
        incoming_doi = self._article_doi(incoming)
        if existing_doi and incoming_doi:
            return existing_doi == incoming_doi
        existing_year = self._year_int(existing.get("year"))
        incoming_year = self._year_int(incoming.get("year"))
        if existing_year is None or incoming_year is None:
            return False
        if abs(existing_year - incoming_year) > 1:
            return False
        if self._authors_conflict(existing.get("authors"), incoming.get("authors")):
            return False
        existing_container = self._effective_container(existing)
        incoming_container = self._effective_container(incoming)
        if (
            existing_container
            and incoming_container
            and existing_container != incoming_container
        ):
            return False
        if self._work_types_incompatible(
            existing.get("work_type"), incoming.get("work_type")
        ):
            return False
        authors_match = self._authors_match(
            existing.get("authors"), incoming.get("authors")
        )
        containers_match = bool(
            existing_container and incoming_container
            and existing_container == incoming_container
        )
        return authors_match or containers_match

    @staticmethod
    def _ensure_identity_cache(article: Dict) -> Tuple[str, bool, str]:
        nt = article.get("_cached_norm_title")
        generic = article.get("_cached_generic")
        if "_cached_doi" not in article or nt is None or generic is None:
            nt = ArticleDatabase._norm_title(article.get("title") or "")
            article["_cached_norm_title"] = nt
            article["_cached_generic"] = (not nt) or ArticleDatabase._is_generic_title(nt)
            article["_cached_doi"] = ArticleDatabase._article_doi(article)
        return (
            article["_cached_norm_title"],
            article["_cached_generic"],
            article["_cached_doi"],
        )

    @staticmethod
    def _doi_owners(
        doi_index: Dict[str, List[Tuple[str, str]]], doi: str
    ) -> List[Tuple[str, str]]:
        return doi_index.get(doi) or []

    def _find_duplicate_key(
        self,
        article: Dict,
        doi_index: Dict[str, List[Tuple[str, str]]],
        title_index: Dict[str, List[Tuple[str, str]]],
        records: Dict[Tuple[str, str], Dict],
    ) -> Optional[Tuple[str, str]]:
        nt, generic, incoming_doi = self._ensure_identity_cache(article)
        for owner in self._doi_owners(doi_index, incoming_doi):
            if owner in records:
                return owner
        if not nt or generic:
            return None
        for key in title_index.get(nt, ()):
            existing = records.get(key)
            if existing is None:
                continue
            _existing_nt, existing_generic, existing_doi = self._ensure_identity_cache(
                existing
            )
            if incoming_doi and existing_doi and incoming_doi != existing_doi:
                continue
            if existing_generic:
                continue
            if self._title_same_work(existing, article):
                return key
        return None

    def _unindex_key(
        self,
        key: Tuple[str, str],
        doi_index: Dict[str, List[Tuple[str, str]]],
        title_index: Dict[str, List[Tuple[str, str]]],
        records: Dict[Tuple[str, str], Dict],
    ) -> None:
        old = records.pop(key, None)
        if not old:
            return
        old_nt, _old_generic, old_doi = self._ensure_identity_cache(old)
        owners = doi_index.get(old_doi)
        if owners:
            try:
                owners.remove(key)
            except ValueError:
                pass
            if not owners:
                del doi_index[old_doi]
        bucket = title_index.get(old_nt)
        if not bucket:
            return
        try:
            bucket.remove(key)
        except ValueError:
            return
        if not bucket:
            del title_index[old_nt]

    def _index_article(
        self,
        article: Dict,
        doi_index: Dict[str, List[Tuple[str, str]]],
        title_index: Dict[str, List[Tuple[str, str]]],
        records: Dict[Tuple[str, str], Dict],
    ) -> None:
        key = (article["article_id"], article.get("source") or "pubmed")
        records[key] = article
        nt, _generic, doi = self._ensure_identity_cache(article)
        if doi:
            owners = doi_index.setdefault(doi, [])
            if key not in owners:
                owners.append(key)
        if nt and key not in title_index.get(nt, ()):
            title_index.setdefault(nt, []).append(key)

    def _refresh_batch_index(
        self,
        cursor,
        table: str,
        key: Tuple[str, str],
        doi_index: Dict[str, List[Tuple[str, str]]],
        title_index: Dict[str, List[Tuple[str, str]]],
        records: Dict[Tuple[str, str], Dict],
    ) -> None:
        self._unindex_key(key, doi_index, title_index, records)
        cursor.execute(
            f"SELECT {', '.join(ARTICLE_COLUMNS)} FROM {table} "
            "WHERE article_id = ? AND source = ?",
            key,
        )
        row = cursor.fetchone()
        if row:
            self._index_article(
                _row_to_article(row), doi_index, title_index, records
            )

    def _merge_field_updates(
        self, existing: Dict, incoming: Dict, incoming_source: str
    ) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, Any]]:
        updates: Dict[str, Any] = {}
        filled: Dict[str, str] = {}
        conflicts: Dict[str, Any] = {}

        stored_journal = (existing.get("journal") or "").strip()
        incoming_journal = (incoming.get("journal") or "").strip()
        stored_placeholder = (not stored_journal) or _is_placeholder_journal(stored_journal)
        incoming_real = bool(incoming_journal) and not _is_placeholder_journal(
            incoming_journal
        )
        if stored_placeholder and incoming_real:
            updates["journal"] = incoming_journal
            filled["journal"] = incoming_source
        elif (
            incoming_real
            and stored_journal
            and not stored_placeholder
            and stored_journal != incoming_journal
        ):
            conflicts["journal"] = {
                "value": incoming_journal,
                "source": incoming_source,
            }

        for name in ("year", "authors", *_MERGE_COLUMNS):
            if name == "biblio":
                continue
            incoming_value = incoming.get(name)
            existing_value = existing.get(name)
            if name == "authors":
                incoming_value = self._author_list(incoming_value)
                existing_value = self._author_list(existing_value)
            if self._value_empty(incoming_value):
                continue
            if self._value_empty(existing_value):
                updates[name] = incoming_value
                filled[name] = incoming_source
            elif not self._field_equal(existing_value, incoming_value):
                conflicts[name] = {
                    "value": incoming_value,
                    "source": incoming_source,
                }

        existing_biblio = self._parse_biblio(existing.get("biblio"))
        incoming_biblio = self._parse_biblio(incoming.get("biblio"))
        if incoming_biblio:
            if not existing_biblio:
                updates["biblio"] = incoming_biblio
                for key, value in incoming_biblio.items():
                    if not self._value_empty(value):
                        filled[f"biblio.{key}"] = incoming_source
            else:
                merged_biblio = dict(existing_biblio)
                biblio_changed = False
                for key, value in incoming_biblio.items():
                    if self._value_empty(value):
                        continue
                    if self._value_empty(merged_biblio.get(key)):
                        merged_biblio[key] = value
                        filled[f"biblio.{key}"] = incoming_source
                        biblio_changed = True
                    elif merged_biblio.get(key) != value:
                        conflicts[f"biblio.{key}"] = {
                            "value": value,
                            "source": incoming_source,
                        }
                if biblio_changed:
                    updates["biblio"] = merged_biblio
        return updates, filled, conflicts

    def _merge_article_extra(
        self,
        cursor,
        article_id: str,
        source: str,
        extra: Optional[Dict],
        filled: Dict[str, str],
        conflicts: Dict[str, Any],
        *,
        staging: bool,
    ) -> bool:
        table = "staging_article_extra" if staging else "article_extra"
        row = cursor.execute(
            f"SELECT provenance, locations, provider_record, raw_status "
            f"FROM {table} WHERE article_id = ? AND source = ?",
            (article_id, source),
        ).fetchone()
        blob = status = None
        if row:
            try:
                provenance = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                provenance = {}
            try:
                locations = json.loads(row[1] or "[]")
            except json.JSONDecodeError:
                locations = []
            if not isinstance(provenance, dict):
                provenance = {}
            if not isinstance(locations, list):
                locations = []
            blob, status = row[2], row[3]
        else:
            provenance, locations = {}, []
            record = (extra or {}).get("provider_record")
            if isinstance(record, dict):
                blob, status = encode_provider_record(record)

        for field, src in filled.items():
            provenance[field] = src
        if conflicts:
            existing_conflicts = provenance.get("conflicts")
            if not isinstance(existing_conflicts, dict):
                existing_conflicts = {}
            for field, payload in conflicts.items():
                existing_conflicts[field] = self._dedupe_conflict_entries(
                    existing_conflicts.get(field), payload
                )
            provenance["conflicts"] = existing_conflicts

        incoming_locations = (extra or {}).get("locations") or []
        before_len = len(locations)
        locations = self._merge_locations(locations, incoming_locations)
        added_locations = len(locations) > before_len
        if (
            not filled
            and not conflicts
            and not incoming_locations
            and row is None
        ):
            return False
        cursor.execute(
            f"""
            INSERT INTO {table}
                (article_id, source, provenance, locations, provider_record, raw_status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_id, source) DO UPDATE SET
                provenance = excluded.provenance,
                locations = excluded.locations
            """,
            (
                article_id,
                source,
                json.dumps(provenance, ensure_ascii=False, separators=(",", ":")),
                json.dumps(locations, ensure_ascii=False, separators=(",", ":")),
                blob,
                status,
            ),
        )
        return added_locations

    @staticmethod
    def _conflict_entry(payload: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict) or "value" not in payload:
            return None
        return {"value": payload.get("value"), "source": payload.get("source")}

    @classmethod
    def _dedupe_conflict_entries(cls, existing: Any, incoming: Any) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        seen = set()

        def add(item: Any) -> None:
            entry = cls._conflict_entry(item)
            if entry is None:
                return
            marker = json.dumps(entry, sort_keys=True, default=str)
            if marker in seen:
                return
            seen.add(marker)
            entries.append(entry)

        if isinstance(existing, list):
            for item in existing:
                add(item)
        else:
            add(existing)
        if isinstance(incoming, list):
            for item in incoming:
                add(item)
        else:
            add(incoming)
        return entries

    def _merge_into(
        self,
        cursor,
        existing: Dict,
        incoming: Dict,
        extra: Optional[Dict],
        *,
        staging: bool,
        doi_index: Dict[str, List[Tuple[str, str]]],
    ) -> bool:
        """Fill empty fields on existing from incoming. Returns True if a field or location was added."""
        incoming_source = incoming.get("source") or "pubmed"
        updates, filled, conflicts = self._merge_field_updates(
            existing, incoming, incoming_source
        )
        if updates:
            assignments = []
            values: List[Any] = []
            for name, value in updates.items():
                assignments.append(f"{name} = ?")
                values.append(self._column_value({name: value}, name))
                existing[name] = value
            values.extend([existing["article_id"], existing["source"]])
            table = self.STAGING_TABLE if staging else "articles"
            cursor.execute(
                f"UPDATE {table} SET {', '.join(assignments)} "
                f"WHERE article_id = ? AND source = ?",
                values,
            )
            existing.pop("_cached_doi", None)
            doi = self._article_doi(existing)
            existing["_cached_doi"] = doi
            key = (existing["article_id"], existing["source"])
            if doi:
                owners = doi_index.setdefault(doi, [])
                if key not in owners:
                    owners.append(key)
        added_locations = self._merge_article_extra(
            cursor,
            existing["article_id"],
            existing["source"],
            extra,
            filled,
            conflicts,
            staging=staging,
        )
        return bool(filled) or added_locations

    def insert_articles(
        self, articles: List[Dict], dedupe: bool = True, *, staging: bool = False
    ) -> Dict:
        """
        Upsert articles into the database.

        Uses ON CONFLICT DO UPDATE (not REPLACE) so foreign-key children are
        not cascade-deleted when metadata is refreshed.

        When dedupe=True, an incoming row that is the same work as a stored
        row (or an earlier row in this batch) merges empty metadata into that
        row instead of inserting a second copy. Same (article_id, source)
        still upserts in place.

        staging=True writes replace-fetch rows into staging_articles (dedupe
        against staging only) so the live library stays intact until swap.

        Returns:
            dict with inserted, updated, skipped_duplicates, merged, dropped.
        """
        inserted = 0
        updated = 0
        skipped_duplicates = 0
        merged = 0
        dropped = 0
        stale_derived = 0
        table = self.STAGING_TABLE if staging else "articles"
        columns = ", ".join(ARTICLE_COLUMNS)
        placeholders = ", ".join("?" for _ in ARTICLE_COLUMNS)
        metadata_updates = ", ".join(
            f"{name} = COALESCE(excluded.{name}, {name})" for name in ARTICLE_COLUMNS[7:]
        )

        with self._writing():
            cursor = self.conn.cursor()
            doi_index: Dict[str, List[Tuple[str, str]]] = {}
            title_index: Dict[str, List[Tuple[str, str]]] = {}
            records: Dict[Tuple[str, str], Dict] = {}
            if dedupe:
                cursor.execute(f"SELECT {columns} FROM {table}")
                for row in cursor.fetchall():
                    self._index_article(
                        _row_to_article(row), doi_index, title_index, records
                    )

            for article in articles:
                try:
                    raw_extra = article.pop("_extra", None)
                    extra = raw_extra if isinstance(raw_extra, dict) else None
                    aid = article['article_id']
                    source = article.get('source', 'pubmed')
                    title = article.get('title', '')

                    cursor.execute(
                        f"SELECT title, abstract FROM {table} "
                        f"WHERE article_id = ? AND source = ?",
                        (aid, source),
                    )
                    prior = cursor.fetchone()
                    existed = prior is not None

                    if dedupe and not existed:
                        match = self._find_duplicate_key(
                            article, doi_index, title_index, records
                        )
                        if match is not None:
                            gained = self._merge_into(
                                cursor,
                                records[match],
                                article,
                                extra,
                                staging=staging,
                                doi_index=doi_index,
                            )
                            skipped_duplicates += 1
                            if gained:
                                merged += 1
                            continue

                    cursor.execute(f"""
                        INSERT INTO {table}
                        ({columns})
                        VALUES ({placeholders})
                        ON CONFLICT(article_id, source) DO UPDATE SET
                            title = excluded.title,
                            abstract = excluded.abstract,
                            year = excluded.year,
                            authors = excluded.authors,
                            journal = excluded.journal,
                            {metadata_updates}
                    """, (
                        aid,
                        source,
                        title,
                        article.get('abstract', ''),
                        article.get('year', ''),
                        json.dumps(article.get('authors', [])),
                        article.get('journal', ''),
                        *(self._column_value(article, name) for name in ARTICLE_COLUMNS[7:]),
                    ))
                    if extra:
                        self._write_article_extra(
                            cursor, aid, source, extra, staging=staging,
                        )
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
                    if dedupe:
                        self._refresh_batch_index(
                            cursor,
                            table,
                            (aid, source),
                            doi_index,
                            title_index,
                            records,
                        )
                except Exception as e:
                    dropped += 1
                    logger.warning("Error inserting article %s: %s", article.get('article_id'), e)
            self.conn.commit()
        logger.info(
            "Articles upsert: inserted=%d updated=%d skipped_dups=%d merged=%d "
            "dropped=%d stale_derived=%d",
            inserted, updated, skipped_duplicates, merged, dropped, stale_derived,
        )
        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_duplicates": skipped_duplicates,
            "merged": merged,
            "dropped": dropped,
            "stale_derived": stale_derived,
        }

    @staticmethod
    def _column_value(article: Dict, name: str):
        value = article.get(name)
        if name == "biblio" and isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if value else None
        if name == "authors" and isinstance(value, list):
            return json.dumps(value)
        return value

    def get_all_articles(self) -> List[Dict]:
        """Retrieve all articles from database"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(f"SELECT {', '.join(ARTICLE_COLUMNS)} FROM articles")
            rows = cursor.fetchall()

        return [_row_to_article(row) for row in rows]

    def get_article_by_id(self, article_id: str, source: str) -> Optional[Dict]:
        """Retrieve a specific article by article_id and source"""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                f"SELECT {', '.join(ARTICLE_COLUMNS)} FROM articles "
                "WHERE article_id = ? AND source = ?",
                (article_id, source)
            )
            row = cursor.fetchone()
        return _row_to_article(row) if row else None

    def insert_embeddings(self, embeddings: Dict, model_name: str):
        """
        Store embeddings for articles

        Args:
            embeddings: Dictionary mapping (article_id, source) tuples to embedding vectors
            model_name: Name of the embedding model used
        """
        with self._writing():
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
                f"SELECT {', '.join(ARTICLE_COLUMNS)} "
                "FROM articles WHERE article_id = ? COLLATE NOCASE LIMIT 1",
                (seed,),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    f"SELECT {', '.join(ARTICLE_COLUMNS)} "
                    "FROM articles WHERE article_id LIKE ? COLLATE NOCASE "
                    "OR title LIKE ? COLLATE NOCASE LIMIT 1",
                    (like, like),
                )
                row = cursor.fetchone()
        return _row_to_article(row) if row else None

    def get_library_export_rows(self, scope: str = "all") -> List[Dict]:
        """Articles with cluster + screening + note metadata for CSV export.

        scope: 'all' | 'included' | 'excluded' | 'starred'
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(f"""
                SELECT {', '.join(f'a.{name}' for name in ARTICLE_COLUMNS)},
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
            cluster_id, cluster_label, reason, note, star = row[len(ARTICLE_COLUMNS):]
            excluded = reason is not None
            starred = bool(star)
            if scope == "included" and excluded:
                continue
            if scope == "excluded" and not excluded:
                continue
            if scope == "starred" and not starred:
                continue
            out.append({
                **_row_to_article(row),
                "cluster_id": cluster_id,
                "cluster_label": cluster_label,
                "excluded": excluded,
                "exclusion_reason": reason or "",
                "note": note or "",
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
            with self._writing():
                cursor = self.conn.cursor()
                cursor.execute(
                    "DELETE FROM notes WHERE article_id = ? AND source = ?",
                    (article_id, source),
                )
                self.conn.commit()
            return {"article_id": article_id, "source": source, "note": "", "starred": False}
        with self._writing():
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
        with self._writing():
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
        with self._writing():
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
        with self._writing():
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
        with self._writing():
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

    def get_excluded_items(self, reason: Optional[str] = None) -> List[Dict]:
        """Excluded papers with their reason and enough of the article to show.

        ``reason`` narrows to one code (Simple Undo after Narrow it down asks
        for ``low_relevance``); ``None`` lists every reason for the Set aside
        list. Newest exclusions first inside a reason.
        """
        from app.content.screening_reasons import normalize_reason
        columns = ", ".join(
            f"NULL AS {name}" if name in {"abstract", "authors"}
            else f"{'s' if name in ARTICLE_COLUMNS[:2] else 'a'}.{name}"
            for name in ARTICLE_COLUMNS
        )
        sql = (
            f"SELECT {columns}, s.reason"
            " FROM screening s"
            " LEFT JOIN articles a ON a.article_id = s.article_id AND a.source = s.source"
        )
        params: tuple = ()
        if reason is not None:
            sql += " WHERE s.reason = ?"
            params = (normalize_reason(reason, default="manual"),)
        sql += " ORDER BY s.reason, s.created_at DESC, a.title"
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        items = []
        for row in rows:
            article = _row_to_article(row)
            article.pop("abstract")
            article.pop("authors")
            article["reason"] = row[len(ARTICLE_COLUMNS)]
            for name in ("title", "year", "journal"):
                article[name] = article[name] or ""
            items.append(article)
        return items

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
        with self._writing():
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
            cursor.execute(f"""
                SELECT {', '.join(f'a.{name}' for name in ARTICLE_COLUMNS)}, c.cluster_label,
                       s.article_id IS NOT NULL AS excluded
                FROM articles a
                JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
                LEFT JOIN screening s ON a.article_id = s.article_id AND a.source = s.source
                WHERE c.cluster_id = ?
            """, (cluster_id,))
            rows = cursor.fetchall()

        articles = []
        for row in rows:
            cluster_label, excluded = row[len(ARTICLE_COLUMNS):]
            articles.append({
                **_row_to_article(row),
                'cluster_label': cluster_label,
                'excluded': bool(excluded)
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

    def get_all_articles_with_clusters(
        self, columns: Tuple[str, ...] = ARTICLE_COLUMNS,
    ) -> Dict[Tuple[str, str], Dict]:
        """Retrieve all articles with their cluster info in one query (avoids O(N) calls).

        ``columns`` defaults to the full article projection. Search ranking
        passes ``SEARCH_ARTICLE_COLUMNS`` so it does not materialize metadata.
        """
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(f"""
                SELECT {', '.join(f'a.{name}' for name in columns)},
                       c.cluster_id, c.cluster_label
                FROM articles a
                LEFT JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
            """)
            rows = cursor.fetchall()

        result = {}
        for row in rows:
            cluster_id, cluster_label = row[len(columns):]
            key = (row[0], row[1])
            result[key] = {
                **_row_to_article(row, columns),
                'cluster_id': cluster_id,
                'cluster_label': cluster_label
            }
        return result

    def get_article_work_types(self) -> Dict[Tuple[str, str], Optional[str]]:
        """article_id, source, work_type only — used to filter before ranking."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT article_id, source, work_type FROM articles")
            rows = cursor.fetchall()
        return {(row[0], row[1]): row[2] for row in rows}

    def get_work_types_for_keys(
        self, keys: List[Tuple[str, str]],
    ) -> Dict[Tuple[str, str], Optional[str]]:
        """One batched work_type read for the ranked top-K keys."""
        if not keys:
            return {}
        placeholders = ",".join(["(?, ?)"] * len(keys))
        params: List[Any] = []
        for article_id, source in keys:
            params.extend([article_id, source])
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT article_id, source, work_type FROM articles "
                f"WHERE (article_id, source) IN ({placeholders})",
                params,
            )
            rows = cursor.fetchall()
        return {(row[0], row[1]): row[2] for row in rows}

    def get_article_access_fields(self) -> Dict[Tuple[str, str], Dict]:
        """oa_status, best_oa_url, and locations — used to filter before ranking."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT a.article_id, a.source, a.oa_status, a.best_oa_url, "
                "e.locations, e.provenance "
                "FROM articles a LEFT JOIN article_extra e "
                "ON a.article_id = e.article_id AND a.source = e.source"
            )
            rows = cursor.fetchall()
        return {
            (row[0], row[1]): {
                "source": row[1],
                "oa_status": row[2],
                "best_oa_url": row[3],
                "locations": row[4],
                "provenance": row[5],
            }
            for row in rows
        }

    def get_access_fields_for_keys(
        self, keys: List[Tuple[str, str]],
    ) -> Dict[Tuple[str, str], Dict]:
        """One batched access-field read for the ranked top-K keys."""
        if not keys:
            return {}
        placeholders = ",".join(["(?, ?)"] * len(keys))
        params: List[Any] = []
        for article_id, source in keys:
            params.extend([article_id, source])
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT a.article_id, a.source, a.oa_status, a.best_oa_url, "
                "e.locations, e.provenance "
                "FROM articles a LEFT JOIN article_extra e "
                "ON a.article_id = e.article_id AND a.source = e.source "
                f"WHERE (a.article_id, a.source) IN ({placeholders})",
                params,
            )
            rows = cursor.fetchall()
        return {
            (row[0], row[1]): {
                "source": row[1],
                "oa_status": row[2],
                "best_oa_url": row[3],
                "locations": row[4],
                "provenance": row[5],
            }
            for row in rows
        }

    def get_starred_copy_fields(
        self, keys: List[Tuple[str, str]],
    ) -> Dict[Tuple[str, str], Dict]:
        """One batched extra/OA read for starred keys only."""
        if not keys:
            return {}
        placeholders = ",".join(["(?, ?)"] * len(keys))
        params: List[Any] = []
        for article_id, source in keys:
            params.extend([article_id, source])
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT a.article_id, a.source, a.doi, a.oa_status, a.best_oa_url, "
                "a.host_name, e.locations, e.provenance "
                "FROM articles a "
                "INNER JOIN notes n "
                "ON a.article_id = n.article_id AND a.source = n.source "
                "AND n.starred = 1 "
                "LEFT JOIN article_extra e "
                "ON a.article_id = e.article_id AND a.source = e.source "
                f"WHERE (a.article_id, a.source) IN ({placeholders})",
                params,
            )
            rows = cursor.fetchall()
        return {
            (row[0], row[1]): {
                "article_id": row[0],
                "source": row[1],
                "doi": row[2],
                "oa_status": row[3],
                "best_oa_url": row[4],
                "host_name": row[5],
                "locations": row[6],
                "provenance": row[7],
            }
            for row in rows
        }

    def get_copy_fields_for_dois(self, dois: List[str]) -> List[Dict]:
        """OA and extra fields for every library row with one of these DOIs."""
        wanted = set()
        for raw in dois:
            normalized = normalize_doi(raw)
            if normalized:
                wanted.add(normalized)
        if not wanted:
            return []
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT a.article_id, a.source, a.doi, a.oa_status, a.best_oa_url, "
                "a.host_name, e.locations, e.provenance "
                "FROM articles a LEFT JOIN article_extra e "
                "ON a.article_id = e.article_id AND a.source = e.source "
                "WHERE a.doi IS NOT NULL AND TRIM(a.doi) != ''",
            )
            rows = cursor.fetchall()
        out: List[Dict] = []
        for row in rows:
            if normalize_doi(row[2]) not in wanted:
                continue
            out.append({
                "article_id": row[0],
                "source": row[1],
                "doi": row[2],
                "oa_status": row[3],
                "best_oa_url": row[4],
                "host_name": row[5],
                "locations": row[6],
                "provenance": row[7],
            })
        return out

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

            cursor.execute("SELECT work_type, COUNT(*) FROM articles GROUP BY work_type")
            work_type_rows = cursor.fetchall()

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

        work_type_counts: Dict[str, int] = {}
        for raw, n in work_type_rows:
            key = work_type_count_key(raw)
            work_type_counts[key] = work_type_counts.get(key, 0) + int(n)

        return {
            'total_articles': article_count,
            'articles_with_embeddings': embedding_count,
            'num_clusters': cluster_count,
            'excluded_articles': excluded_count,
            'sources': sources,
            'year_counts': year_counts,
            'work_type_counts': work_type_counts,
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
