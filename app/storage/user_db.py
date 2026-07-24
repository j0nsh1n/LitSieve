"""
User Database
Stores user accounts in users.db, separate from per-user article data.
"""

import hashlib
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple


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
        # Optional library copy codes: clone into another account (not live view).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS shares (
                id                 TEXT PRIMARY KEY,
                code               TEXT UNIQUE NOT NULL,
                owner_user_id      TEXT NOT NULL,
                owner_library_id   TEXT NOT NULL,
                title_snapshot     TEXT NOT NULL,
                include_embeddings INTEGER NOT NULL DEFAULT 1,
                created_at         TEXT NOT NULL,
                expires_at         TEXT,
                max_uses           INTEGER,
                use_count          INTEGER NOT NULL DEFAULT 0,
                revoked_at         TEXT
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shares_owner ON shares(owner_user_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shares_code ON shares(code)"
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS share_redemptions (
                share_id            TEXT NOT NULL,
                student_user_id     TEXT NOT NULL,
                student_library_id  TEXT NOT NULL,
                redeemed_at         TEXT NOT NULL,
                PRIMARY KEY (share_id, student_user_id),
                FOREIGN KEY (share_id) REFERENCES shares(id)
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_redemptions_student "
            "ON share_redemptions(student_user_id)"
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
            # Drop shares owned by this user and any of their redemptions.
            # Subquery instead of expanded placeholders: a long share history
            # would exceed SQLite's host-parameter limit and abort the delete.
            self.conn.execute(
                "DELETE FROM share_redemptions WHERE share_id IN "
                "(SELECT id FROM shares WHERE owner_user_id = ?)",
                (user_id,),
            )
            self.conn.execute(
                "DELETE FROM shares WHERE owner_user_id = ?", (user_id,)
            )
            self.conn.execute(
                "DELETE FROM share_redemptions WHERE student_user_id = ?",
                (user_id,),
            )
            cur = self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            self.conn.commit()
            return cur.rowcount > 0

    # --- Library copy codes (optional clone) ---

    @staticmethod
    def _share_row(row) -> Optional[Dict]:
        if not row:
            return None
        return {
            "id": row[0],
            "code": row[1],
            "owner_user_id": row[2],
            "owner_library_id": row[3],
            "title_snapshot": row[4],
            "include_embeddings": bool(row[5]),
            "created_at": row[6],
            "expires_at": row[7],
            "max_uses": row[8],
            "use_count": int(row[9] or 0),
            "revoked_at": row[10],
        }

    _SHARE_COLS = (
        "id, code, owner_user_id, owner_library_id, title_snapshot, "
        "include_embeddings, created_at, expires_at, max_uses, use_count, revoked_at"
    )

    def create_share(
        self,
        owner_user_id: str,
        owner_library_id: str,
        title_snapshot: str,
        code: str,
        *,
        include_embeddings: bool = True,
        expires_at: Optional[str] = None,
        max_uses: Optional[int] = None,
    ) -> Dict:
        share_id = str(uuid.uuid4())
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO shares ("
                    "id, code, owner_user_id, owner_library_id, title_snapshot, "
                    "include_embeddings, created_at, expires_at, max_uses, use_count, revoked_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)",
                    (
                        share_id,
                        code,
                        owner_user_id,
                        owner_library_id,
                        title_snapshot,
                        1 if include_embeddings else 0,
                        created,
                        expires_at,
                        max_uses,
                    ),
                )
                self.conn.commit()
            except sqlite3.IntegrityError as e:
                raise ValueError("Could not create share (code collision). Retry.") from e
        return {
            "id": share_id,
            "code": code,
            "owner_user_id": owner_user_id,
            "owner_library_id": owner_library_id,
            "title_snapshot": title_snapshot,
            "include_embeddings": bool(include_embeddings),
            "created_at": created,
            "expires_at": expires_at,
            "max_uses": max_uses,
            "use_count": 0,
            "revoked_at": None,
        }

    def get_share_by_code(self, code: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {self._SHARE_COLS} FROM shares WHERE code = ?",
                (code,),
            ).fetchone()
        return self._share_row(row)

    def get_share_by_id(self, share_id: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {self._SHARE_COLS} FROM shares WHERE id = ?",
                (share_id,),
            ).fetchone()
        return self._share_row(row)

    def list_shares_for_owner(self, owner_user_id: str) -> List[Dict]:
        with self._lock:
            rows = self.conn.execute(
                f"SELECT {self._SHARE_COLS} FROM shares "
                "WHERE owner_user_id = ? ORDER BY created_at DESC",
                (owner_user_id,),
            ).fetchall()
        return [self._share_row(r) for r in rows if r]

    def revoke_share(self, share_id: str, owner_user_id: str) -> bool:
        """Revoke a share if owned by owner_user_id. Returns True if revoked."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            cur = self.conn.execute(
                "UPDATE shares SET revoked_at = ? "
                "WHERE id = ? AND owner_user_id = ? AND revoked_at IS NULL",
                (now, share_id, owner_user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def has_redeemed_share(self, share_id: str, student_user_id: str) -> bool:
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM share_redemptions "
                "WHERE share_id = ? AND student_user_id = ?",
                (share_id, student_user_id),
            ).fetchone()
        return row is not None

    def record_redemption(
        self,
        share_id: str,
        student_user_id: str,
        student_library_id: str,
    ) -> None:
        """Record a successful join and increment use_count (atomic)."""
        redeemed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            # Re-check max_uses under lock to avoid over-redemption races.
            row = self.conn.execute(
                "SELECT max_uses, use_count, revoked_at, expires_at "
                "FROM shares WHERE id = ?",
                (share_id,),
            ).fetchone()
            if not row:
                raise ValueError("Library code not found.")
            max_uses, use_count, revoked_at, expires_at = (
                row[0],
                int(row[1] or 0),
                row[2],
                row[3],
            )
            if revoked_at:
                raise ValueError("This library code has been revoked.")
            if expires_at:
                exp = expires_at
                if exp.endswith("Z"):
                    exp = exp[:-1] + "+00:00"
                try:
                    exp_dt = datetime.fromisoformat(exp)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) > exp_dt:
                        raise ValueError("This library code has expired.")
                except ValueError as e:
                    if "expired" in str(e).lower():
                        raise
            if max_uses is not None and use_count >= int(max_uses):
                raise ValueError(
                    "This library code has reached its maximum number of uses."
                )
            try:
                self.conn.execute(
                    "INSERT INTO share_redemptions "
                    "(share_id, student_user_id, student_library_id, redeemed_at) "
                    "VALUES (?, ?, ?, ?)",
                    (share_id, student_user_id, student_library_id, redeemed_at),
                )
            except sqlite3.IntegrityError as e:
                # Close the failed write transaction; leaving it open keeps
                # the database locked until some later commit/rollback.
                self.conn.rollback()
                raise ValueError(
                    "You already joined with this code. "
                    "Switch to that library from Account."
                ) from e
            self.conn.execute(
                "UPDATE shares SET use_count = use_count + 1 WHERE id = ?",
                (share_id,),
            )
            self.conn.commit()


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
