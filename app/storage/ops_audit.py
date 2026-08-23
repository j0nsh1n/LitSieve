"""Immutable operator audit + deploy history on the accounts DB."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_tables(db) -> None:
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_audit (
            id              TEXT PRIMARY KEY,
            actor_id        TEXT,
            actor_username  TEXT NOT NULL,
            action          TEXT NOT NULL,
            path            TEXT,
            before_hash     TEXT,
            after_hash      TEXT,
            sha             TEXT,
            previous_sha    TEXT,
            message         TEXT,
            result          TEXT NOT NULL,
            detail          TEXT,
            ip              TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_operator_audit_time "
        "ON operator_audit(created_at)"
    )
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_deploys (
            id              TEXT PRIMARY KEY,
            sha             TEXT NOT NULL,
            previous_sha    TEXT,
            actor_username  TEXT NOT NULL,
            result          TEXT NOT NULL,
            detail          TEXT,
            created_at      TEXT NOT NULL
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_operator_deploys_time "
        "ON operator_deploys(created_at)"
    )
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS operator_state (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        )
    """)
    db.conn.commit()


def add(
    db,
    *,
    actor_id: str = "",
    actor_username: str,
    action: str,
    result: str,
    path: str = "",
    before_hash: str = "",
    after_hash: str = "",
    sha: str = "",
    previous_sha: str = "",
    message: str = "",
    detail: str = "",
    ip: str = "",
) -> Dict:
    row_id = str(uuid.uuid4())
    now = _now()
    with db._lock:
        db.conn.execute(
            "INSERT INTO operator_audit "
            "(id, actor_id, actor_username, action, path, before_hash, "
            "after_hash, sha, previous_sha, message, result, detail, ip, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id, actor_id or "", actor_username, action, path or "",
                before_hash or "", after_hash or "", sha or "", previous_sha or "",
                message or "", result, (detail or "")[:2000], ip or "", now,
            ),
        )
        db.conn.commit()
    return {"id": row_id, "action": action, "result": result, "created_at": now}


def list_audit(db, *, limit: int = 50) -> List[Dict]:
    limit = max(1, min(int(limit), 100))
    with db._lock:
        rows = db.conn.execute(
            "SELECT id, actor_username, action, path, sha, previous_sha, "
            "message, result, detail, ip, created_at "
            "FROM operator_audit ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "actor_username": r[1],
            "action": r[2],
            "path": r[3],
            "sha": r[4],
            "previous_sha": r[5],
            "message": r[6],
            "result": r[7],
            "detail": r[8],
            "ip": r[9],
            "created_at": r[10],
        }
        for r in rows
    ]


def add_deploy(
    db, *, sha: str, previous_sha: str, actor_username: str, result: str, detail: str = ""
) -> Dict:
    row_id = str(uuid.uuid4())
    now = _now()
    with db._lock:
        db.conn.execute(
            "INSERT INTO operator_deploys "
            "(id, sha, previous_sha, actor_username, result, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, sha, previous_sha or "", actor_username, result, detail[:500], now),
        )
        db.conn.commit()
    return {"id": row_id, "sha": sha, "previous_sha": previous_sha, "result": result, "created_at": now}


def list_deploys(db, *, limit: int = 25) -> List[Dict]:
    limit = max(1, min(int(limit), 50))
    with db._lock:
        rows = db.conn.execute(
            "SELECT id, sha, previous_sha, actor_username, result, detail, created_at "
            "FROM operator_deploys ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r[0],
            "sha": r[1],
            "previous_sha": r[2],
            "actor_username": r[3],
            "result": r[4],
            "detail": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def set_state(db, key: str, value: str) -> None:
    with db._lock:
        db.conn.execute(
            "INSERT INTO operator_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        db.conn.commit()


def get_state(db, key: str) -> str:
    with db._lock:
        row = db.conn.execute(
            "SELECT value FROM operator_state WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else ""


def last_good_deploy(db) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT id, sha, previous_sha, actor_username, result, detail, created_at "
            "FROM operator_deploys WHERE result = 'ok' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "sha": row[1],
        "previous_sha": row[2],
        "actor_username": row[3],
        "result": row[4],
        "detail": row[5],
        "created_at": row[6],
    }
