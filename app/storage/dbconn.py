"""One place that opens SQLite connections, with optional at-rest encryption.

Encryption is **opt-in**: set ``DB_ENCRYPTION_KEY`` and every database (accounts
and every library) is opened through SQLCipher instead of plain sqlite3. Leave
it unset and behaviour is byte-for-byte what it was before — no new runtime
dependency is even imported.

What this protects: a stolen disk image, a copied ``user_data/`` folder, or a
backup that ends up somewhere it shouldn't. What it does **not** protect: a
compromised running app, which necessarily holds the key in memory.

Losing the key means losing the data — there is no recovery path. Convert
existing plaintext databases with ``tools/encrypt_databases.py`` before
switching it on.
"""

from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

ENV_KEY = "DB_ENCRYPTION_KEY"


class DatabaseKeyError(RuntimeError):
    """Encryption is configured but the database could not be opened with it."""


def encryption_key() -> str:
    """Configured key, or "" when at-rest encryption is off."""
    return (os.getenv(ENV_KEY) or "").strip()


def encryption_enabled() -> bool:
    return bool(encryption_key())


def _driver():
    """Return the DB-API module to use (sqlcipher3 only when keying)."""
    if not encryption_enabled():
        return sqlite3
    try:
        import sqlcipher3
    except ImportError as exc:  # pragma: no cover - depends on optional wheel
        raise DatabaseKeyError(
            f"{ENV_KEY} is set but sqlcipher3 is not installed. "
            "Install it with: pip install sqlcipher3-binary"
        ) from exc
    return sqlcipher3.dbapi2


def _quote(key: str) -> str:
    """Single-quote a key for PRAGMA (which takes no bound parameters)."""
    return "'" + key.replace("'", "''") + "'"


def connect(db_path: str, *, check_same_thread: bool = False, uri: bool = False):
    """Open ``db_path``, applying the encryption key first when configured.

    PRAGMA key must be the first statement on the connection, before anything
    touches the file — otherwise SQLCipher reports the file as "not a
    database".
    """
    driver = _driver()
    conn = driver.connect(db_path, check_same_thread=check_same_thread, uri=uri)
    if not encryption_enabled():
        return conn

    conn.execute(f"PRAGMA key = {_quote(encryption_key())}")
    try:
        # Forces SQLCipher to actually read the header and derive the key.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except Exception as exc:
        conn.close()
        raise DatabaseKeyError(
            f"Could not open {db_path} with {ENV_KEY}. Either the key is wrong, "
            "or this database is still unencrypted plaintext — convert it with "
            "tools/encrypt_databases.py before enabling encryption."
        ) from exc
    return conn


def is_encrypted(db_path: str) -> bool:
    """True when the file on disk is *not* a readable plaintext SQLite DB.

    A plain SQLite file starts with the ASCII header "SQLite format 3\\0";
    SQLCipher encrypts that header too, so its absence means the file is either
    encrypted or not a database at all.
    """
    try:
        with open(db_path, "rb") as fh:
            return fh.read(16) != b"SQLite format 3\x00"
    except OSError:
        return False
