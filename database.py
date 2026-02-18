"""
Database Module
Handles storage and retrieval of articles and embeddings
"""

import sqlite3
import json
import numpy as np
from typing import List, Dict, Optional, Tuple
import pickle


class ArticleDatabase:
    """SQLite database for storing articles and their embeddings"""

    def __init__(self, db_path: str = "articles.db"):
        """Initialize database connection"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
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

        # Embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                embedding BLOB NOT NULL,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

        if 'pmid' in columns and 'source' not in columns:
            print("Migrating database schema from pmid to article_id+source...")
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
            print("Schema migration complete.")

    def insert_articles(self, articles: List[Dict]):
        """
        Insert articles into database

        Args:
            articles: List of article dictionaries with 'article_id' and 'source' keys
        """
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
                    article['title'],
                    article['abstract'],
                    article['year'],
                    json.dumps(article['authors']),
                    article['journal']
                ))
            except Exception as e:
                print(f"Error inserting article {article.get('article_id')}: {e}")

        self.conn.commit()
        print(f"Inserted {len(articles)} articles")

    def get_all_articles(self) -> List[Dict]:
        """Retrieve all articles from database"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT article_id, source, title, abstract, year, authors, journal FROM articles")

        articles = []
        for row in cursor.fetchall():
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
        cursor = self.conn.cursor()

        for key, embedding in embeddings.items():
            article_id, source = key
            embedding_bytes = pickle.dumps(embedding)

            cursor.execute("""
                INSERT OR REPLACE INTO embeddings
                (article_id, source, embedding, model_name)
                VALUES (?, ?, ?, ?)
            """, (article_id, source, embedding_bytes, model_name))

        self.conn.commit()
        print(f"Inserted embeddings for {len(embeddings)} articles")

    def get_all_embeddings(self) -> Tuple[List[Tuple[str, str]], np.ndarray]:
        """
        Retrieve all embeddings

        Returns:
            Tuple of (list of (article_id, source) tuples, numpy array of embeddings)
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT article_id, source, embedding FROM embeddings")

        ids = []
        embeddings = []

        for row in cursor.fetchall():
            ids.append((row[0], row[1]))
            embedding = pickle.loads(row[2])
            embeddings.append(embedding)

        if embeddings:
            return ids, np.array(embeddings)
        return [], np.array([])

    def insert_clusters(self, cluster_assignments: Dict):
        """
        Store cluster assignments

        Args:
            cluster_assignments: Dict mapping (article_id, source) tuples to (cluster_id, cluster_label)
        """
        cursor = self.conn.cursor()

        for key, (cluster_id, label) in cluster_assignments.items():
            article_id, source = key
            cursor.execute("""
                INSERT OR REPLACE INTO clusters
                (article_id, source, cluster_id, cluster_label)
                VALUES (?, ?, ?, ?)
            """, (article_id, source, cluster_id, label))

        self.conn.commit()
        print(f"Inserted cluster assignments for {len(cluster_assignments)} articles")

    def get_articles_by_cluster(self, cluster_id: int) -> List[Dict]:
        """Get all articles in a specific cluster"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT a.article_id, a.source, a.title, a.abstract, a.year, a.authors, a.journal, c.cluster_label
            FROM articles a
            JOIN clusters c ON a.article_id = c.article_id AND a.source = c.source
            WHERE c.cluster_id = ?
        """, (cluster_id,))

        articles = []
        for row in cursor.fetchall():
            articles.append({
                'article_id': row[0],
                'source': row[1],
                'title': row[2],
                'abstract': row[3],
                'year': row[4],
                'authors': json.loads(row[5]) if row[5] else [],
                'journal': row[6],
                'cluster_label': row[7]
            })

        return articles

    def get_all_clusters(self) -> List[Dict]:
        """Get summary of all clusters with article counts"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT cluster_id, cluster_label, COUNT(*) as article_count
            FROM clusters
            GROUP BY cluster_id, cluster_label
            ORDER BY cluster_id
        """)
        return [
            {'cluster_id': row[0], 'cluster_label': row[1], 'article_count': row[2]}
            for row in cursor.fetchall()
        ]

    def get_cluster_for_article(self, article_id: str, source: str) -> Optional[Dict]:
        """Return cluster info for a specific article"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT cluster_id, cluster_label FROM clusters WHERE article_id = ? AND source = ?",
            (article_id, source)
        )
        row = cursor.fetchone()
        if row:
            return {'cluster_id': row[0], 'cluster_label': row[1]}
        return None

    def get_statistics(self) -> Dict:
        """Get database statistics"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM articles")
        article_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM embeddings")
        embedding_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(DISTINCT cluster_id) FROM clusters")
        cluster_count = cursor.fetchone()[0]

        # Source breakdown
        cursor.execute("SELECT source, COUNT(*) FROM articles GROUP BY source")
        sources = {row[0]: row[1] for row in cursor.fetchall()}

        return {
            'total_articles': article_count,
            'articles_with_embeddings': embedding_count,
            'num_clusters': cluster_count,
            'sources': sources
        }

    def close(self):
        """Close database connection"""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
