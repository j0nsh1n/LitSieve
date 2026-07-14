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
        # WAL + busy_timeout: same rationale as ArticleDatabase (concurrent access).
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
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
        # token_version: bumped on password change so old JWTs are rejected.
        cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "token_version" not in cols:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0"
            )
        self.conn.commit()

    def create_user(self, username: str, hashed_password: str) -> Dict:
        """Create a user. Raises ValueError if the username is already taken.

        The UNIQUE constraint is the source of truth: relying on a prior
        get_by_username() check alone would leave a race window where two
        concurrent registrations both pass the check and one hits IntegrityError.
        """
        user_id = str(uuid.uuid4())
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO users (id, username, hashed_password, token_version) "
                    "VALUES (?, ?, ?, 0)",
                    (user_id, username, hashed_password),
                )
                self.conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Username already taken: {username}") from e
        return {"id": user_id, "username": username, "token_version": 0}

    def get_by_username(self, username: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, username, hashed_password, token_version "
                "FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "hashed_password": row[2],
                "token_version": int(row[3] or 0),
            }
        return None

    def get_by_id(self, user_id: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, username, hashed_password, token_version FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row:
            return {
                "id": row[0],
                "username": row[1],
                "hashed_password": row[2],
                "token_version": int(row[3] or 0),
            }
        return None

    def update_password(self, user_id: str, hashed_password: str) -> bool:
        """Set password hash and bump token_version so other sessions die."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET hashed_password = ?, "
                "token_version = token_version + 1 WHERE id = ?",
                (hashed_password, user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def delete_user(self, user_id: str) -> bool:
        """Delete a user account. Returns True if a row was removed."""
        with self._lock:
            cur = self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.conn.commit()
            return cur.rowcount > 0
