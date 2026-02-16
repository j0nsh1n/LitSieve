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
    
    def create_tables(self):
        """Create database tables if they don't exist"""
        cursor = self.conn.cursor()
        
        # Articles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                pmid TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                year TEXT,
                authors TEXT,
                journal TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Embeddings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                pmid TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pmid) REFERENCES articles (pmid)
            )
        """)
        
        # Clusters table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clusters (
                pmid TEXT PRIMARY KEY,
                cluster_id INTEGER,
                cluster_label TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (pmid) REFERENCES articles (pmid)
            )
        """)
        
        self.conn.commit()
    
    def insert_articles(self, articles: List[Dict]):
        """
        Insert articles into database
        
        Args:
            articles: List of article dictionaries
        """
        cursor = self.conn.cursor()
        
        for article in articles:
            try:
                cursor.execute("""
                    INSERT OR REPLACE INTO articles 
                    (pmid, title, abstract, year, authors, journal)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    article['pmid'],
                    article['title'],
                    article['abstract'],
                    article['year'],
                    json.dumps(article['authors']),
                    article['journal']
                ))
            except Exception as e:
                print(f"Error inserting article {article.get('pmid')}: {e}")
        
        self.conn.commit()
        print(f"Inserted {len(articles)} articles")
    
    def get_all_articles(self) -> List[Dict]:
        """Retrieve all articles from database"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM articles")
        
        articles = []
        for row in cursor.fetchall():
            articles.append({
                'pmid': row[0],
                'title': row[1],
                'abstract': row[2],
                'year': row[3],
                'authors': json.loads(row[4]) if row[4] else [],
                'journal': row[5]
            })
        
        return articles
    
    def get_article_by_pmid(self, pmid: str) -> Optional[Dict]:
        """Retrieve a specific article by PMID"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE pmid = ?", (pmid,))
        
        row = cursor.fetchone()
        if row:
            return {
                'pmid': row[0],
                'title': row[1],
                'abstract': row[2],
                'year': row[3],
                'authors': json.loads(row[4]) if row[4] else [],
                'journal': row[5]
            }
        return None
    
    def insert_embeddings(self, embeddings: Dict[str, np.ndarray], model_name: str):
        """
        Store embeddings for articles
        
        Args:
            embeddings: Dictionary mapping PMIDs to embedding vectors
            model_name: Name of the embedding model used
        """
        cursor = self.conn.cursor()
        
        for pmid, embedding in embeddings.items():
            # Convert numpy array to bytes
            embedding_bytes = pickle.dumps(embedding)
            
            cursor.execute("""
                INSERT OR REPLACE INTO embeddings 
                (pmid, embedding, model_name)
                VALUES (?, ?, ?)
            """, (pmid, embedding_bytes, model_name))
        
        self.conn.commit()
        print(f"Inserted embeddings for {len(embeddings)} articles")
    
    def get_all_embeddings(self) -> Tuple[List[str], np.ndarray]:
        """
        Retrieve all embeddings
        
        Returns:
            Tuple of (list of PMIDs, numpy array of embeddings)
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT pmid, embedding FROM embeddings")
        
        pmids = []
        embeddings = []
        
        for row in cursor.fetchall():
            pmids.append(row[0])
            # Convert bytes back to numpy array
            embedding = pickle.loads(row[1])
            embeddings.append(embedding)
        
        if embeddings:
            return pmids, np.array(embeddings)
        return [], np.array([])
    
    def insert_clusters(self, cluster_assignments: Dict[str, Tuple[int, str]]):
        """
        Store cluster assignments
        
        Args:
            cluster_assignments: Dict mapping PMIDs to (cluster_id, cluster_label)
        """
        cursor = self.conn.cursor()
        
        for pmid, (cluster_id, label) in cluster_assignments.items():
            cursor.execute("""
                INSERT OR REPLACE INTO clusters 
                (pmid, cluster_id, cluster_label)
                VALUES (?, ?, ?)
            """, (pmid, cluster_id, label))
        
        self.conn.commit()
        print(f"Inserted cluster assignments for {len(cluster_assignments)} articles")
    
    def get_articles_by_cluster(self, cluster_id: int) -> List[Dict]:
        """Get all articles in a specific cluster"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT a.*, c.cluster_label
            FROM articles a
            JOIN clusters c ON a.pmid = c.pmid
            WHERE c.cluster_id = ?
        """, (cluster_id,))
        
        articles = []
        for row in cursor.fetchall():
            articles.append({
                'pmid': row[0],
                'title': row[1],
                'abstract': row[2],
                'year': row[3],
                'authors': json.loads(row[4]) if row[4] else [],
                'journal': row[5],
                'cluster_label': row[7]
            })
        
        return articles
    
    def get_statistics(self) -> Dict:
        """Get database statistics"""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM articles")
        article_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM embeddings")
        embedding_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT cluster_id) FROM clusters")
        cluster_count = cursor.fetchone()[0]
        
        return {
            'total_articles': article_count,
            'articles_with_embeddings': embedding_count,
            'num_clusters': cluster_count
        }
    
    def close(self):
        """Close database connection"""
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Example usage
if __name__ == "__main__":
    # Create database and load articles from JSON
    with ArticleDatabase() as db:
        # Load articles from JSON file
        with open("pubmed_articles.json", "r") as f:
            articles = json.load(f)
        
        # Insert into database
        db.insert_articles(articles)
        
        # Get statistics
        stats = db.get_statistics()
        print(f"Database statistics: {stats}")
