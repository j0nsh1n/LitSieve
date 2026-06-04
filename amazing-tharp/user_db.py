"""
User Database
Stores user accounts in users.db, separate from per-user article data.
"""

import sqlite3
import uuid
import threading
from typing import Optional, Dict


class UserDatabase:
    def __init__(self, db_path: str = "users.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id               TEXT PRIMARY KEY,
                username         TEXT UNIQUE NOT NULL COLLATE NOCASE,
                hashed_password  TEXT NOT NULL,
                created_at       TEXT DEFAULT (datetime('now'))
            )
        """)
        self.conn.commit()

    def create_user(self, username: str, hashed_password: str) -> Dict:
        user_id = str(uuid.uuid4())
        with self._lock:
            self.conn.execute(
                "INSERT INTO users (id, username, hashed_password) VALUES (?, ?, ?)",
                (user_id, username, hashed_password)
            )
            self.conn.commit()
        return {"id": user_id, "username": username}

    def get_by_username(self, username: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT id, username, hashed_password FROM users WHERE username = ? COLLATE NOCASE",
            (username,)
        ).fetchone()
        if row:
            return {"id": row[0], "username": row[1], "hashed_password": row[2]}
        return None

    def get_by_id(self, user_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if row:
            return {"id": row[0], "username": row[1]}
        return None
