"""
User Database
Stores user accounts in users.db, separate from per-user article data.
"""

import hashlib
import secrets
import sqlite3
import uuid
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Tuple


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
        # One-time password-reset codes (hashed). Classroom hosts can surface
        # the plaintext code when DEBUG/RESET_CODES_IN_RESPONSE is set.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                username     TEXT NOT NULL COLLATE NOCASE,
                token_hash   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (username, token_hash)
            )
        """)
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

    @staticmethod
    def _hash_reset_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_password_reset_token(
        self, username: str, ttl_minutes: int = 60
    ) -> Optional[str]:
        """Create a one-time reset code for username. Returns plaintext token or None."""
        user = self.get_by_username(username)
        if not user:
            return None
        token = secrets.token_urlsafe(24)
        token_hash = self._hash_reset_token(token)
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        uname = user["username"]
        with self._lock:
            # Invalidate prior unused tokens for this user.
            self.conn.execute(
                "UPDATE password_reset_tokens SET used = 1 "
                "WHERE username = ? COLLATE NOCASE AND used = 0",
                (uname,),
            )
            self.conn.execute(
                "INSERT INTO password_reset_tokens (username, token_hash, expires_at, used) "
                "VALUES (?, ?, ?, 0)",
                (uname, token_hash, expires),
            )
            self.conn.commit()
        return token

    def consume_password_reset_token(
        self, username: str, token: str, new_hashed_password: str
    ) -> Tuple[bool, str]:
        """Validate token and set password. Returns (ok, error_message)."""
        if not token or not username:
            return False, "Reset code and login are required."
        token_hash = self._hash_reset_token(token.strip())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            row = self.conn.execute(
                "SELECT username, expires_at, used FROM password_reset_tokens "
                "WHERE username = ? COLLATE NOCASE AND token_hash = ?",
                (username.strip(), token_hash),
            ).fetchone()
            if not row:
                return False, "Invalid or expired reset code."
            uname, expires_at, used = row[0], row[1], int(row[2] or 0)
            if used:
                return False, "This reset code was already used."
            if expires_at < now:
                return False, "This reset code has expired. Request a new one."
            cur = self.conn.execute(
                "UPDATE users SET hashed_password = ?, "
                "token_version = token_version + 1 "
                "WHERE username = ? COLLATE NOCASE",
                (new_hashed_password, uname),
            )
            if cur.rowcount == 0:
                return False, "Account not found."
            self.conn.execute(
                "UPDATE password_reset_tokens SET used = 1 "
                "WHERE username = ? COLLATE NOCASE AND token_hash = ?",
                (uname, token_hash),
            )
            self.conn.commit()
        return True, ""
