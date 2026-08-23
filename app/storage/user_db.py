"""
User Database
Stores user accounts in users.db (override with USERS_DB), separate from
per-user article data.
"""

import hashlib
import os
import secrets
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.storage import dbconn

DEFAULT_USERS_DB = "users.db"


def users_db_path() -> str:
    """Accounts DB location: ``USERS_DB`` env, else ``users.db`` in the cwd.

    Configurable so a dev server can be pointed at a throwaway accounts file.
    Without this, running the reload server from the repo opens the *live*
    accounts database — a local experiment could change a real password or
    delete a real account. Pairs with ``USER_DATA_DIR`` (paper libraries) and
    ``LOG_FILE``; see run_dev.sh, which sets all three.
    """
    return (os.getenv("USERS_DB") or "").strip() or DEFAULT_USERS_DB


class UserDatabase:
    def __init__(self, db_path: Optional[str] = None):
        db_path = db_path or users_db_path()
        self.conn = dbconn.connect(db_path, check_same_thread=False)
        self.db_path = db_path
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
        # Optional recovery email. Separate from `username` on purpose: the
        # login handle is not an email, and an address only counts once its
        # owner has clicked the verification link (email_verified = 1).
        if "email" not in cols:
            self.conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "email_verified" not in cols:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"
            )
        # Guest demo accounts: sample corpus only; no real multi-source fetch.
        if "is_guest" not in cols:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0"
            )
        # One *verified* address per account, and no two accounts may verify the
        # same address (unverified duplicates are allowed — anyone can type any
        # address, only clicking the link proves control).
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_verified_email "
            "ON users(email) WHERE email IS NOT NULL AND email_verified = 1"
        )
        # One-time email-verification links (hashed, same shape as reset codes).
        # `email` is stored on the token so a pending change is only applied to
        # the address that was actually confirmed.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                username     TEXT NOT NULL COLLATE NOCASE,
                email        TEXT NOT NULL COLLATE NOCASE,
                token_hash   TEXT NOT NULL,
                expires_at   TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (username, token_hash)
            )
        """)
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
        # Helpdesk support: access state + last-seen (no MFA/class/grades in this schema).
        extra = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "locked_until" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
        if "failed_logins" not in extra:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN failed_logins INTEGER NOT NULL DEFAULT 0"
            )
        if "last_login_at" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
        if "last_seen_at" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN last_seen_at TEXT")
        if "password_changed_at" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")
        if "storage_bytes" not in extra:
            self.conn.execute(
                "ALTER TABLE users ADD COLUMN storage_bytes INTEGER NOT NULL DEFAULT 0"
            )
        if "quota_limit_mb" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN quota_limit_mb INTEGER")
        if "quota_limit_until" not in extra:
            self.conn.execute("ALTER TABLE users ADD COLUMN quota_limit_until TEXT")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS support_notes (
                id              TEXT PRIMARY KEY,
                student_id      TEXT NOT NULL,
                admin_id        TEXT NOT NULL,
                admin_username  TEXT NOT NULL,
                body            TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_notes_student "
            "ON support_notes(student_id, created_at)"
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS support_actions (
                id              TEXT PRIMARY KEY,
                student_id      TEXT NOT NULL,
                admin_id        TEXT NOT NULL,
                admin_username  TEXT NOT NULL,
                action          TEXT NOT NULL,
                reason          TEXT NOT NULL,
                old_value       TEXT,
                new_value       TEXT,
                ip              TEXT,
                created_at      TEXT NOT NULL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_support_actions_student "
            "ON support_actions(student_id, created_at)"
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_events (
                id          TEXT PRIMARY KEY,
                user_id     TEXT,
                username    TEXT,
                kind        TEXT NOT NULL,
                ip          TEXT,
                detail      TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_events_user "
            "ON auth_events(user_id, created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_events_kind_time "
            "ON auth_events(kind, created_at)"
        )
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS one_time_logins (
                token_hash  TEXT PRIMARY KEY,
                user_id     TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                used        INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
        """)
        from app.storage.helpdesk import ensure_tables
        from app.storage.ops_audit import ensure_tables as ensure_ops_tables
        ensure_tables(self)
        ensure_ops_tables(self)
        self.conn.commit()

    def create_user(
        self, username: str, hashed_password: str, *, is_guest: bool = False
    ) -> Dict:
        """Create a user. Raises ValueError if the username is already taken.

        The UNIQUE constraint is the source of truth: relying on a prior
        get_by_username() check alone would leave a race window where two
        concurrent registrations both pass the check and one hits IntegrityError.
        """
        user_id = str(uuid.uuid4())
        guest = 1 if is_guest else 0
        with self._lock:
            try:
                self.conn.execute(
                    "INSERT INTO users (id, username, hashed_password, token_version, is_guest) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (user_id, username, hashed_password, guest),
                )
                self.conn.commit()
            except dbconn.integrity_errors() as e:
                # Driver-agnostic: sqlcipher3 has its own IntegrityError, so
                # naming sqlite3's would stop catching this the moment
                # DB_ENCRYPTION_KEY is set, turning a taken username into a 500.
                raise ValueError(f"Username already taken: {username}") from e
        return {
            "id": user_id,
            "username": username,
            "token_version": 0,
            "is_guest": bool(guest),
        }

    _USER_COLS = (
        "id, username, hashed_password, token_version, email, email_verified, "
        "COALESCE(is_guest, 0), created_at, locked_until, "
        "COALESCE(failed_logins, 0), last_login_at, last_seen_at, "
        "password_changed_at, COALESCE(storage_bytes, 0), "
        "quota_limit_mb, quota_limit_until, "
        "disabled_until, disabled_message, disabled_at"
    )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _row_to_user(self, row) -> Optional[Dict]:
        if not row:
            return None
        return {
            "id": row[0],
            "username": row[1],
            "hashed_password": row[2],
            "token_version": int(row[3] or 0),
            "email": row[4],
            "email_verified": bool(row[5]),
            "is_guest": bool(row[6]),
            "created_at": row[7],
            "locked_until": row[8],
            "failed_logins": int(row[9] or 0),
            "last_login_at": row[10],
            "last_seen_at": row[11],
            "password_changed_at": row[12],
            "storage_bytes": int(row[13] or 0),
            "quota_limit_mb": int(row[14]) if row[14] is not None else None,
            "quota_limit_until": row[15],
            "disabled_until": row[16],
            "disabled_message": row[17],
            "disabled_at": row[18],
        }

    def get_by_username(self, username: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE username = ? COLLATE NOCASE",
                (username,),
            ).fetchone()
        return self._row_to_user(row)

    def get_by_id(self, user_id: str) -> Optional[Dict]:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {self._USER_COLS} FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row)

    def list_accounts(self) -> List[Dict]:
        """Deprecated helper: prefer search_accounts (bounded). No password hashes."""
        return self.search_accounts("", limit=25)

    def account_counts(self) -> Dict[str, int]:
        """Aggregates only — no usernames. For the operator admin overview."""
        now = self._utc_now()
        with self._lock:
            total = int(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            guests = int(self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE COALESCE(is_guest, 0) = 1"
            ).fetchone()[0])
            locked = int(self.conn.execute(
                "SELECT COUNT(*) FROM users "
                "WHERE locked_until IS NOT NULL AND locked_until > ?",
                (now,),
            ).fetchone()[0])
            unverified = int(self.conn.execute(
                "SELECT COUNT(*) FROM users "
                "WHERE email IS NOT NULL AND TRIM(email) != '' "
                "AND COALESCE(email_verified, 0) = 0 "
                "AND COALESCE(is_guest, 0) = 0"
            ).fetchone()[0])
        return {
            "accounts": total - guests,
            "guests": guests,
            "locked": locked,
            "unverified": unverified,
        }

    def search_accounts(self, query: str, *, limit: int = 25) -> List[Dict]:
        """Exact id/username/email first, then prefix, then contains. Capped."""
        q = (query or "").strip()
        limit = max(1, min(int(limit), 25))
        seen: set = set()
        out: List[Dict] = []

        def _add(rows) -> None:
            for row in rows:
                rec = self._row_to_user(row)
                if not rec or rec["id"] in seen:
                    continue
                seen.add(rec["id"])
                out.append(rec)
                if len(out) >= limit:
                    return

        with self._lock:
            if q:
                _add(self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE id = ? OR username = ? COLLATE NOCASE "
                    "OR email = ? COLLATE NOCASE",
                    (q, q, q),
                ).fetchall())
                if len(out) < limit:
                    like = f"{q}%"
                    _add(self.conn.execute(
                        f"SELECT {self._USER_COLS} FROM users "
                        "WHERE username LIKE ? COLLATE NOCASE "
                        "OR email LIKE ? COLLATE NOCASE "
                        "ORDER BY username LIMIT ?",
                        (like, like, limit),
                    ).fetchall())
                if len(out) < limit and len(q) >= 2:
                    like = f"%{q}%"
                    _add(self.conn.execute(
                        f"SELECT {self._USER_COLS} FROM users "
                        "WHERE username LIKE ? COLLATE NOCASE "
                        "OR email LIKE ? COLLATE NOCASE "
                        "ORDER BY username LIMIT ?",
                        (like, like, limit),
                    ).fetchall())
            else:
                _add(self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall())
        return out[:limit]

    def queue_accounts(self, kind: str, *, limit: int = 25) -> List[Dict]:
        """Small support queues. kind: locked | unverified | quota | errors."""
        limit = max(1, min(int(limit), 25))
        now = self._utc_now()
        with self._lock:
            if kind == "locked":
                rows = self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE locked_until IS NOT NULL AND locked_until > ? "
                    "ORDER BY locked_until DESC LIMIT ?",
                    (now, limit),
                ).fetchall()
            elif kind == "unverified":
                rows = self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE email IS NOT NULL AND TRIM(email) != '' "
                    "AND COALESCE(email_verified, 0) = 0 "
                    "AND COALESCE(is_guest, 0) = 0 "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif kind == "quota":
                rows = self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE COALESCE(storage_bytes, 0) > 0 "
                    "ORDER BY storage_bytes DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif kind == "disabled":
                rows = self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE disabled_until IS NOT NULL AND disabled_until > ? "
                    "ORDER BY disabled_until DESC LIMIT ?",
                    (now, limit),
                ).fetchall()
            elif kind == "errors":
                hour_ago = (
                    datetime.now(timezone.utc) - timedelta(hours=1)
                ).strftime("%Y-%m-%d %H:%M:%S")
                rows = self.conn.execute(
                    f"SELECT {self._USER_COLS} FROM users "
                    "WHERE id IN ("
                    "  SELECT user_id FROM auth_events "
                    "  WHERE kind IN ('login_fail', 'lockout') "
                    "  AND created_at >= ? AND user_id IS NOT NULL "
                    "  GROUP BY user_id HAVING COUNT(*) >= 3"
                    ") ORDER BY last_seen_at DESC LIMIT ?",
                    (hour_ago, limit),
                ).fetchall()
            else:
                rows = []
        found = []
        for r in rows:
            rec = self._row_to_user(r)
            if rec:
                found.append(rec)
        return found

    def list_expired_guest_ids(self, max_age_minutes: int = 30) -> list:
        """Guest account ids older than max_age_minutes (SQLite UTC datetime)."""
        minutes = max(1, int(max_age_minutes))
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM users "
                "WHERE COALESCE(is_guest, 0) = 1 "
                "AND created_at < datetime('now', ?)",
                (f"-{minutes} minutes",),
            ).fetchall()
        return [row[0] for row in rows if row and row[0]]

    def guest_is_expired(self, user_id: str, max_age_minutes: int = 30) -> bool:
        """True if this guest account is past max_age_minutes (non-guests → False)."""
        minutes = max(1, int(max_age_minutes))
        with self._lock:
            row = self.conn.execute(
                "SELECT 1 FROM users "
                "WHERE id = ? AND COALESCE(is_guest, 0) = 1 "
                "AND created_at < datetime('now', ?)",
                (user_id, f"-{minutes} minutes"),
            ).fetchone()
        return row is not None

    def update_password(self, user_id: str, hashed_password: str) -> bool:
        """Set password hash and bump token_version so other sessions die."""
        now = self._utc_now()
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET hashed_password = ?, "
                "token_version = token_version + 1, password_changed_at = ? "
                "WHERE id = ?",
                (hashed_password, now, user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    LOCKOUT_AFTER = 8
    LOCKOUT_MINUTES = 15
    LAST_SEEN_THROTTLE_SEC = 300

    def is_locked(self, user: Optional[Dict]) -> bool:
        if not user:
            return False
        until = user.get("locked_until")
        if not until:
            return False
        return str(until) > self._utc_now()

    def is_disabled(self, user: Optional[Dict]) -> bool:
        from app.storage.helpdesk import is_disabled
        return is_disabled(user, now=self._utc_now())

    def record_login_failure(self, username: str, ip: str = "") -> Dict:
        """Increment fail count; lock after LOCKOUT_AFTER. Returns {locked, user_id}."""
        user = self.get_by_username(username)
        uid = user["id"] if user else None
        uname = (user["username"] if user else username) or username
        locked = False
        if user:
            now = self._utc_now()
            fails = int(user.get("failed_logins") or 0) + 1
            until = None
            if fails >= self.LOCKOUT_AFTER:
                until = (
                    datetime.now(timezone.utc)
                    + timedelta(minutes=self.LOCKOUT_MINUTES)
                ).strftime("%Y-%m-%d %H:%M:%S")
                locked = True
            with self._lock:
                self.conn.execute(
                    "UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                    (fails, until, uid),
                )
                self.conn.commit()
            self.record_auth_event(uid, uname, "login_fail", ip, f"fails={fails}")
            if locked:
                self.record_auth_event(uid, uname, "lockout", ip, f"until={until}")
        else:
            self.record_auth_event(None, uname, "login_fail", ip, "unknown_user")
        return {"locked": locked, "user_id": uid}

    def record_login_success(self, user_id: str, ip: str = "") -> None:
        now = self._utc_now()
        with self._lock:
            self.conn.execute(
                "UPDATE users SET failed_logins = 0, locked_until = NULL, "
                "last_login_at = ?, last_seen_at = ? WHERE id = ?",
                (now, now, user_id),
            )
            self.conn.commit()
        user = self.get_by_id(user_id)
        if user:
            self.record_auth_event(user_id, user["username"], "login_ok", ip, "")

    def touch_last_seen(self, user_id: str) -> None:
        """Write last_seen at most once per LAST_SEEN_THROTTLE_SEC."""
        now = datetime.now(timezone.utc)
        user = self.get_by_id(user_id)
        if not user:
            return
        prev = user.get("last_seen_at")
        if prev:
            try:
                prev_dt = datetime.strptime(str(prev)[:19], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                if (now - prev_dt).total_seconds() < self.LAST_SEEN_THROTTLE_SEC:
                    return
            except ValueError:
                pass
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute(
                "UPDATE users SET last_seen_at = ? WHERE id = ?",
                (stamp, user_id),
            )
            self.conn.commit()

    def unlock_account(self, user_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET locked_until = NULL, failed_logins = 0 WHERE id = ?",
                (user_id,),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def bump_sessions(self, user_id: str) -> bool:
        """Invalidate all JWTs for this account."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET token_version = token_version + 1 WHERE id = ?",
                (user_id,),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def set_storage_bytes(self, user_id: str, used: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE users SET storage_bytes = ? WHERE id = ?",
                (int(used or 0), user_id),
            )
            self.conn.commit()

    def set_quota_override(
        self, user_id: str, limit_mb: int, until: str
    ) -> bool:
        """Time-boxed per-account cap. ``until`` is UTC ``YYYY-MM-DD HH:MM:SS``."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET quota_limit_mb = ?, quota_limit_until = ? "
                "WHERE id = ?",
                (int(limit_mb), until, user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def clear_quota_override(self, user_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "UPDATE users SET quota_limit_mb = NULL, quota_limit_until = NULL "
                "WHERE id = ?",
                (user_id,),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def record_auth_event(
        self,
        user_id: Optional[str],
        username: str,
        kind: str,
        ip: str = "",
        detail: str = "",
    ) -> None:
        now = self._utc_now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO auth_events "
                "(id, user_id, username, kind, ip, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, username or "", kind, ip or "", detail or "", now),
            )
            self.conn.commit()

    def list_auth_events(self, user_id: str, *, limit: int = 20) -> List[Dict]:
        limit = max(1, min(int(limit), 50))
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, kind, ip, detail, created_at FROM auth_events "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "kind": r[1],
                "ip": r[2],
                "detail": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def add_support_note(
        self, student_id: str, admin_id: str, admin_username: str, body: str
    ) -> Dict:
        note_id = str(uuid.uuid4())
        now = self._utc_now()
        text = (body or "").strip()
        if not text:
            raise ValueError("Note cannot be empty.")
        if len(text) > 2000:
            raise ValueError("Note is too long (max 2000 characters).")
        with self._lock:
            self.conn.execute(
                "INSERT INTO support_notes "
                "(id, student_id, admin_id, admin_username, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, student_id, admin_id, admin_username, text, now),
            )
            self.conn.commit()
        return {
            "id": note_id,
            "student_id": student_id,
            "admin_id": admin_id,
            "admin_username": admin_username,
            "body": text,
            "created_at": now,
        }

    def list_support_notes(self, student_id: str, *, limit: int = 50) -> List[Dict]:
        limit = max(1, min(int(limit), 50))
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, admin_id, admin_username, body, created_at "
                "FROM support_notes WHERE student_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (student_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "admin_id": r[1],
                "admin_username": r[2],
                "body": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def add_support_action(
        self,
        student_id: str,
        admin_id: str,
        admin_username: str,
        action: str,
        reason: str,
        *,
        old_value: str = "",
        new_value: str = "",
        ip: str = "",
    ) -> Dict:
        act_id = str(uuid.uuid4())
        now = self._utc_now()
        with self._lock:
            self.conn.execute(
                "INSERT INTO support_actions "
                "(id, student_id, admin_id, admin_username, action, reason, "
                "old_value, new_value, ip, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    act_id, student_id, admin_id, admin_username, action,
                    (reason or "").strip(), old_value or "", new_value or "",
                    ip or "", now,
                ),
            )
            self.conn.commit()
        return {
            "id": act_id,
            "action": action,
            "reason": (reason or "").strip(),
            "old_value": old_value or "",
            "new_value": new_value or "",
            "admin_username": admin_username,
            "ip": ip or "",
            "created_at": now,
        }

    def list_support_actions(self, student_id: str, *, limit: int = 50) -> List[Dict]:
        limit = max(1, min(int(limit), 50))
        with self._lock:
            rows = self.conn.execute(
                "SELECT id, admin_username, action, reason, old_value, new_value, ip, created_at "
                "FROM support_actions WHERE student_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (student_id, limit),
            ).fetchall()
        return [
            {
                "id": r[0],
                "admin_username": r[1],
                "action": r[2],
                "reason": r[3],
                "old_value": r[4],
                "new_value": r[5],
                "ip": r[6],
                "created_at": r[7],
            }
            for r in rows
        ]

    def create_one_time_login(self, user_id: str, ttl_minutes: int = 15) -> Optional[str]:
        user = self.get_by_id(user_id)
        if not user or user.get("is_guest"):
            return None
        token = secrets.token_urlsafe(24)
        token_hash = self._hash_reset_token(token)
        now = self._utc_now()
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self.conn.execute(
                "UPDATE one_time_logins SET used = 1 "
                "WHERE user_id = ? AND used = 0",
                (user_id,),
            )
            self.conn.execute(
                "INSERT INTO one_time_logins "
                "(token_hash, user_id, expires_at, used, created_at) "
                "VALUES (?, ?, ?, 0, ?)",
                (token_hash, user_id, expires, now),
            )
            self.conn.commit()
        return token

    def consume_one_time_login(self, token: str) -> Optional[Dict]:
        if not token:
            return None
        token_hash = self._hash_reset_token(token.strip())
        now = self._utc_now()
        with self._lock:
            row = self.conn.execute(
                "SELECT user_id, expires_at, used FROM one_time_logins "
                "WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row or int(row[2] or 0) or str(row[1]) < now:
                return None
            self.conn.execute(
                "UPDATE one_time_logins SET used = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            self.conn.commit()
        return self.get_by_id(row[0])

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
            except dbconn.integrity_errors() as e:
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
            except dbconn.integrity_errors() as e:
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
                "token_version = token_version + 1, password_changed_at = ? "
                "WHERE username = ? COLLATE NOCASE",
                (new_hashed_password, now, uname),
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

    # --- Optional recovery email -------------------------------------------
    # Design: `username` stays the login handle. An address is only usable
    # (i.e. can receive a password-reset link) once the person clicking the
    # verification link proves they control it.

    @staticmethod
    def normalize_email(raw: str) -> str:
        return (raw or "").strip().lower()

    def start_email_verification(
        self, username: str, email: str, ttl_minutes: int = 60
    ) -> Optional[str]:
        """Store a pending (unverified) address + return a one-time token.

        Returns None if the account does not exist. Raises ValueError when the
        address is already verified on another account.
        """
        user = self.get_by_username(username)
        if not user:
            return None
        email = self.normalize_email(email)
        uname = user["username"]

        token = secrets.token_urlsafe(24)
        token_hash = self._hash_reset_token(token)
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            taken = self.conn.execute(
                "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE "
                "AND email_verified = 1 AND username <> ? COLLATE NOCASE",
                (email, uname),
            ).fetchone()
            if taken:
                raise ValueError("That email is already verified on another account.")
            # Storing the pending address unverified: harmless (it grants
            # nothing) and lets the UI show "check your inbox".
            self.conn.execute(
                "UPDATE users SET email = ?, email_verified = 0 "
                "WHERE username = ? COLLATE NOCASE",
                (email, uname),
            )
            self.conn.execute(
                "UPDATE email_verification_tokens SET used = 1 "
                "WHERE username = ? COLLATE NOCASE AND used = 0",
                (uname,),
            )
            self.conn.execute(
                "INSERT INTO email_verification_tokens "
                "(username, email, token_hash, expires_at, used) VALUES (?, ?, ?, ?, 0)",
                (uname, email, token_hash, expires),
            )
            self.conn.commit()
        return token

    def confirm_email_verification(self, token: str) -> Tuple[bool, str, Optional[str]]:
        """Consume a verification token. Returns (ok, error, username)."""
        if not token:
            return False, "Verification link is missing its code.", None
        token_hash = self._hash_reset_token(token.strip())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            row = self.conn.execute(
                "SELECT username, email, expires_at, used FROM email_verification_tokens "
                "WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if not row:
                return False, "That verification link is not valid.", None
            uname, email, expires_at, used = row[0], row[1], row[2], int(row[3] or 0)
            if used:
                return False, "That verification link was already used.", None
            if expires_at < now:
                return False, "That verification link has expired. Send a new one.", None
            taken = self.conn.execute(
                "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE "
                "AND email_verified = 1 AND username <> ? COLLATE NOCASE",
                (email, uname),
            ).fetchone()
            if taken:
                return False, "That email is already verified on another account.", None
            # Only verify if the pending address still matches the token: if the
            # user changed their mind and entered a different address, an old
            # link must not silently verify the wrong one.
            cur = self.conn.execute(
                "UPDATE users SET email_verified = 1 "
                "WHERE username = ? COLLATE NOCASE AND email = ? COLLATE NOCASE",
                (uname, email),
            )
            if cur.rowcount == 0:
                return False, "That address is no longer pending on this account.", None
            self.conn.execute(
                "UPDATE email_verification_tokens SET used = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            self.conn.commit()
        return True, "", uname

    def clear_email(self, user_id: str) -> bool:
        """Remove the address and any pending verification links."""
        with self._lock:
            user = self.conn.execute(
                "SELECT username FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if not user:
                return False
            self.conn.execute(
                "UPDATE users SET email = NULL, email_verified = 0 WHERE id = ?",
                (user_id,),
            )
            self.conn.execute(
                "UPDATE email_verification_tokens SET used = 1 "
                "WHERE username = ? COLLATE NOCASE AND used = 0",
                (user[0],),
            )
            self.conn.commit()
        return True

    def get_by_verified_email(self, email: str) -> Optional[Dict]:
        """Look up an account by a **verified** address (reset-by-email).

        Unverified addresses are ignored on purpose: anyone can type anyone
        else's address, so only a confirmed one may identify an account.
        """
        email = self.normalize_email(email)
        if not email:
            return None
        with self._lock:
            row = self.conn.execute(
                "SELECT username FROM users "
                "WHERE email = ? COLLATE NOCASE AND email_verified = 1",
                (email,),
            ).fetchone()
        return self.get_by_username(row[0]) if row else None

    def get_verified_email(self, username: str) -> Optional[str]:
        """Verified address for this login, or None. Used for reset delivery."""
        user = self.get_by_username(username)
        if user and user.get("email") and user.get("email_verified"):
            return user["email"]
        return None
