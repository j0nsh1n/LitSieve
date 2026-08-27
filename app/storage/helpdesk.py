"""Helpdesk extras on the accounts DB: view-as, tickets, banners, site copy.

Uses the same UserDatabase connection/lock. Not a second database.
"""

from __future__ import annotations

import json
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

SUPPORT_VIEW_MINUTES = 15
SUPPORT_VIEW_MAX_MINUTES = 30
TICKET_STATUSES = ("open", "waiting_on_student", "investigating", "resolved")
CONTENT_KEYS = ("support_links", "help_text", "topic_presets", "known_issues")
BANNER_STATUSES = ("draft", "published", "disabled")
_VISIT_PATH_MAX = 200
_BODY_MAX = 4000
_NOTICE_MAX = 800


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_tables(db) -> None:
    conn = db.conn
    extra = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "disabled_until" not in extra:
        conn.execute("ALTER TABLE users ADD COLUMN disabled_until TEXT")
    if "disabled_message" not in extra:
        conn.execute("ALTER TABLE users ADD COLUMN disabled_message TEXT")
    if "disabled_at" not in extra:
        conn.execute("ALTER TABLE users ADD COLUMN disabled_at TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_views (
            id                TEXT PRIMARY KEY,
            token_hash        TEXT UNIQUE NOT NULL,
            admin_id          TEXT NOT NULL,
            admin_username    TEXT NOT NULL,
            student_id        TEXT NOT NULL,
            student_username  TEXT NOT NULL,
            reason            TEXT NOT NULL,
            ui_mode           TEXT,
            started_at        TEXT NOT NULL,
            expires_at        TEXT NOT NULL,
            ended_at          TEXT,
            end_reason        TEXT,
            ip                TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_views_student "
        "ON support_views(student_id, started_at)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_view_visits (
            id          TEXT PRIMARY KEY,
            view_id     TEXT NOT NULL,
            method      TEXT NOT NULL,
            path        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_view_visits "
        "ON support_view_visits(view_id, created_at)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id                 TEXT PRIMARY KEY,
            student_id         TEXT NOT NULL,
            student_username   TEXT NOT NULL,
            status             TEXT NOT NULL,
            body               TEXT NOT NULL,
            context_json       TEXT NOT NULL,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_tickets_status "
        "ON support_tickets(status, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_support_tickets_student "
        "ON support_tickets(student_id, created_at)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS support_ticket_replies (
            id               TEXT PRIMARY KEY,
            ticket_id        TEXT NOT NULL,
            author_id        TEXT NOT NULL,
            author_username  TEXT NOT NULL,
            author_role      TEXT NOT NULL,
            body             TEXT NOT NULL,
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ticket_replies "
        "ON support_ticket_replies(ticket_id, created_at)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_notices (
            id            TEXT PRIMARY KEY,
            status        TEXT NOT NULL,
            body          TEXT NOT NULL,
            expires_at    TEXT,
            created_by    TEXT NOT NULL,
            updated_by    TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            published_at  TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_notice_revisions (
            id          TEXT PRIMARY KEY,
            notice_id   TEXT NOT NULL,
            action      TEXT NOT NULL,
            status      TEXT NOT NULL,
            body        TEXT NOT NULL,
            expires_at  TEXT,
            actor       TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notice_revisions "
        "ON site_notice_revisions(notice_id, created_at)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_content (
            key          TEXT PRIMARY KEY,
            body         TEXT NOT NULL,
            updated_by   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            revision     INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_content_revisions (
            id          TEXT PRIMARY KEY,
            key         TEXT NOT NULL,
            body        TEXT NOT NULL,
            actor       TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_revisions "
        "ON site_content_revisions(key, created_at)"
    )
    conn.commit()


def is_disabled(rec: Optional[dict], *, now: Optional[str] = None) -> bool:
    if not rec:
        return False
    until = rec.get("disabled_until")
    if not until:
        return False
    return str(until) > (now or _now())


def set_disabled(db, user_id: str, *, until: str, message: str) -> bool:
    with db._lock:
        cur = db.conn.execute(
            "UPDATE users SET disabled_until = ?, disabled_message = ?, "
            "disabled_at = ? WHERE id = ?",
            (until, message, _now(), user_id),
        )
        db.conn.commit()
        return cur.rowcount > 0


def clear_disabled(db, user_id: str) -> bool:
    with db._lock:
        cur = db.conn.execute(
            "UPDATE users SET disabled_until = NULL, disabled_message = NULL, "
            "disabled_at = NULL WHERE id = ?",
            (user_id,),
        )
        db.conn.commit()
        return cur.rowcount > 0


def create_support_view(
    db,
    *,
    admin_id: str,
    admin_username: str,
    student_id: str,
    student_username: str,
    reason: str,
    ui_mode: str = "",
    minutes: int = SUPPORT_VIEW_MINUTES,
    ip: str = "",
) -> Dict[str, Any]:
    minutes = max(5, min(int(minutes or SUPPORT_VIEW_MINUTES), SUPPORT_VIEW_MAX_MINUTES))
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=minutes)
    view_id = str(uuid.uuid4())
    started = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_s = expires.strftime("%Y-%m-%d %H:%M:%S")
    mode = (ui_mode or "").strip().lower()
    if mode not in ("simple", "advanced"):
        mode = "simple"
    with db._lock:
        db.conn.execute(
            "UPDATE support_views SET ended_at = ?, end_reason = 'superseded' "
            "WHERE admin_id = ? AND ended_at IS NULL",
            (started, admin_id),
        )
        db.conn.execute(
            "INSERT INTO support_views "
            "(id, token_hash, admin_id, admin_username, student_id, "
            "student_username, reason, ui_mode, started_at, expires_at, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                view_id, _hash(token), admin_id, admin_username, student_id,
                student_username, reason.strip(), mode, started, expires_s, ip,
            ),
        )
        db.conn.commit()
    return {
        "id": view_id,
        "token": token,
        "started_at": started,
        "expires_at": expires_s,
        "minutes": minutes,
        "ui_mode": mode,
        "student_username": student_username,
        "admin_username": admin_username,
        "reason": reason.strip(),
    }


def get_support_view_by_token(db, token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    with db._lock:
        row = db.conn.execute(
            "SELECT id, admin_id, admin_username, student_id, student_username, "
            "reason, ui_mode, started_at, expires_at, ended_at, end_reason "
            "FROM support_views WHERE token_hash = ?",
            (_hash(token.strip()),),
        ).fetchone()
    if not row:
        return None
    rec = {
        "id": row[0],
        "admin_id": row[1],
        "admin_username": row[2],
        "student_id": row[3],
        "student_username": row[4],
        "reason": row[5],
        "ui_mode": row[6],
        "started_at": row[7],
        "expires_at": row[8],
        "ended_at": row[9],
        "end_reason": row[10],
    }
    now = _now()
    if rec["ended_at"]:
        return None
    if rec["expires_at"] <= now:
        end_support_view(db, rec["id"], reason="expired")
        return None
    return rec


def end_support_view(db, view_id: str, *, reason: str = "exit") -> bool:
    with db._lock:
        cur = db.conn.execute(
            "UPDATE support_views SET ended_at = ?, end_reason = ? "
            "WHERE id = ? AND ended_at IS NULL",
            (_now(), reason, view_id),
        )
        db.conn.commit()
        return cur.rowcount > 0


def log_support_visit(db, view_id: str, method: str, path: str) -> None:
    clean = (path or "/")[:_VISIT_PATH_MAX]
    if "?" in clean:
        clean = clean.split("?", 1)[0]
    with db._lock:
        db.conn.execute(
            "INSERT INTO support_view_visits "
            "(id, view_id, method, path, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), view_id, (method or "GET")[:8], clean, _now()),
        )
        db.conn.commit()


def list_support_visits(db, view_id: str, *, limit: int = 100) -> List[Dict]:
    limit = max(1, min(int(limit), 200))
    with db._lock:
        rows = db.conn.execute(
            "SELECT method, path, created_at FROM support_view_visits "
            "WHERE view_id = ? ORDER BY created_at DESC LIMIT ?",
            (view_id, limit),
        ).fetchall()
    return [{"method": r[0], "path": r[1], "created_at": r[2]} for r in rows]


def list_support_views_for_student(db, student_id: str, *, limit: int = 10) -> List[Dict]:
    limit = max(1, min(int(limit), 25))
    with db._lock:
        rows = db.conn.execute(
            "SELECT id, admin_username, reason, started_at, expires_at, "
            "ended_at, end_reason FROM support_views "
            "WHERE student_id = ? ORDER BY started_at DESC LIMIT ?",
            (student_id, limit),
        ).fetchall()
    return [
        {
            "id": r[0],
            "admin_username": r[1],
            "reason": r[2],
            "started_at": r[3],
            "expires_at": r[4],
            "ended_at": r[5],
            "end_reason": r[6],
        }
        for r in rows
    ]


# --- Tickets -----------------------------------------------------------------

_SAFE_CONTEXT_KEYS = frozenset({
    "route", "ui_mode", "app_version", "user_agent", "library_count",
    "article_count", "embedding_count", "quota_used_mb", "quota_limit_mb",
    "job_fetch", "job_embed", "last_error",
})


def sanitize_ticket_context(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in _SAFE_CONTEXT_KEYS:
        if key not in raw:
            continue
        val = raw[key]
        if isinstance(val, (int, float, bool)):
            out[key] = val
        elif val is None:
            continue
        else:
            text = str(val).strip()
            if key == "user_agent":
                text = text[:160]
            elif key == "last_error":
                text = text.split("\n")[0][:240]
            else:
                text = text[:120]
            if text:
                out[key] = text
    return out


def create_ticket(db, *, student_id: str, student_username: str, body: str, context: dict) -> Dict:
    text = (body or "").strip()
    if not text:
        raise ValueError("Write a short message about what is stuck.")
    if len(text) > _BODY_MAX:
        raise ValueError("Message is too long.")
    now = _now()
    ticket_id = str(uuid.uuid4())
    ctx = sanitize_ticket_context(context)
    with db._lock:
        db.conn.execute(
            "INSERT INTO support_tickets "
            "(id, student_id, student_username, status, body, context_json, "
            "created_at, updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?)",
            (ticket_id, student_id, student_username, text, json.dumps(ctx), now, now),
        )
        db.conn.commit()
    return {
        "id": ticket_id,
        "student_id": student_id,
        "student_username": student_username,
        "status": "open",
        "body": text,
        "context": ctx,
        "created_at": now,
        "updated_at": now,
        "replies": [],
    }


def _ticket_summary(row) -> Dict:
    ctx = {}
    try:
        ctx = json.loads(row[5] or "{}")
    except (TypeError, ValueError):
        ctx = {}
    return {
        "id": row[0],
        "student_id": row[1],
        "student_username": row[2],
        "status": row[3],
        "body": row[4],
        "context": sanitize_ticket_context(ctx),
        "created_at": row[6],
        "updated_at": row[7],
    }


def get_ticket(db, ticket_id: str) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT id, student_id, student_username, status, body, context_json, "
            "created_at, updated_at FROM support_tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        replies = []
        if row:
            replies = db.conn.execute(
                "SELECT id, author_username, author_role, body, created_at "
                "FROM support_ticket_replies WHERE ticket_id = ? "
                "ORDER BY created_at ASC LIMIT 50",
                (ticket_id,),
            ).fetchall()
    if not row:
        return None
    rec = _ticket_summary(row)
    rec["replies"] = [
        {
            "id": r[0],
            "author_username": r[1],
            "author_role": r[2],
            "body": r[3],
            "created_at": r[4],
        }
        for r in replies
    ]
    return rec


def list_tickets(db, *, status: str = "", student_id: str = "", limit: int = 25) -> List[Dict]:
    limit = max(1, min(int(limit), 25))
    sql = (
        "SELECT id, student_id, student_username, status, body, context_json, "
        "created_at, updated_at FROM support_tickets"
    )
    args: list = []
    where = []
    if status and status in TICKET_STATUSES:
        where.append("status = ?")
        args.append(status)
    if student_id:
        where.append("student_id = ?")
        args.append(student_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    with db._lock:
        rows = db.conn.execute(sql, args).fetchall()
    return [_ticket_summary(r) for r in rows]


def set_ticket_status(db, ticket_id: str, status: str) -> Optional[Dict]:
    if status not in TICKET_STATUSES:
        raise ValueError("Unknown ticket status.")
    with db._lock:
        db.conn.execute(
            "UPDATE support_tickets SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), ticket_id),
        )
        db.conn.commit()
    return get_ticket(db, ticket_id)


def add_ticket_reply(
    db, ticket_id: str, *, author_id: str, author_username: str, author_role: str, body: str
) -> Dict:
    text = (body or "").strip()
    if not text:
        raise ValueError("Reply cannot be empty.")
    if len(text) > _BODY_MAX:
        raise ValueError("Reply is too long.")
    now = _now()
    reply_id = str(uuid.uuid4())
    with db._lock:
        db.conn.execute(
            "INSERT INTO support_ticket_replies "
            "(id, ticket_id, author_id, author_username, author_role, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (reply_id, ticket_id, author_id, author_username, author_role, text, now),
        )
        db.conn.execute(
            "UPDATE support_tickets SET updated_at = ? WHERE id = ?",
            (now, ticket_id),
        )
        db.conn.commit()
    return {
        "id": reply_id,
        "author_username": author_username,
        "author_role": author_role,
        "body": text,
        "created_at": now,
    }


# --- Banner / content --------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]*>")


def sanitize_plain(text: str, *, limit: int = _NOTICE_MAX) -> str:
    # Bound the input before the regex: <[^>]*> is quadratic on a long run of
    # unclosed '<'. The result is truncated to `limit` anyway, so capping the
    # input at a multiple of it changes no accepted output.
    raw = (text or "")[: max(limit, 1) * 4]
    cleaned = _TAG_RE.sub("", raw)
    cleaned = cleaned.replace("\x00", "").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[:limit]
    return cleaned


def _valid_link(url: str) -> bool:
    raw = (url or "").strip()
    if raw.startswith("/") and not raw.startswith("//"):
        return ".." not in raw
    parsed = urlparse(raw)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_content(key: str, body: str) -> str:
    if key not in CONTENT_KEYS:
        raise ValueError("Unknown content key.")
    if key in ("help_text", "known_issues"):
        text = sanitize_plain(body, limit=2000)
        if not text:
            raise ValueError("Text cannot be empty.")
        return text
    try:
        data = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise ValueError("Body must be JSON.") from exc
    if key == "support_links":
        items = data if isinstance(data, list) else data.get("links")
        if not isinstance(items, list):
            raise ValueError("support_links must be a list of {label, url}.")
        clean = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            label = sanitize_plain(str(item.get("label") or ""), limit=80)
            url = str(item.get("url") or "").strip()
            if not label or not _valid_link(url):
                raise ValueError("Each link needs a label and an https or / path.")
            clean.append({"label": label, "url": url})
        return json.dumps(clean)
    # topic_presets
    items = data if isinstance(data, list) else data.get("presets")
    if not isinstance(items, list):
        raise ValueError("topic_presets must be a list of {id, label}.")
    clean = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        pid = sanitize_plain(str(item.get("id") or ""), limit=40)
        label = sanitize_plain(str(item.get("label") or ""), limit=80)
        if not re.fullmatch(r"[a-z0-9_-]{1,40}", pid or ""):
            raise ValueError("Preset id must be short letters, numbers, _ or -.")
        if not label:
            raise ValueError("Each preset needs a label.")
        clean.append({"id": pid, "label": label})
    return json.dumps(clean)


def save_notice_revision(db, notice_id: str, *, action: str, status: str, body: str, expires_at: Optional[str], actor: str) -> None:
    with db._lock:
        db.conn.execute(
            "INSERT INTO site_notice_revisions "
            "(id, notice_id, action, status, body, expires_at, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), notice_id, action, status, body, expires_at or "", actor, _now()),
        )
        db.conn.commit()


def upsert_banner(db, *, body: str, expires_at: Optional[str], actor: str, status: str = "draft") -> Dict:
    text = sanitize_plain(body, limit=_NOTICE_MAX)
    if not text:
        raise ValueError("Banner text cannot be empty.")
    if status not in BANNER_STATUSES:
        raise ValueError("Unknown banner status.")
    now = _now()
    existing = published_banner(db, include_draft=True)
    if existing:
        notice_id = existing["id"]
        with db._lock:
            db.conn.execute(
                "UPDATE site_notices SET status = ?, body = ?, expires_at = ?, "
                "updated_by = ?, updated_at = ? WHERE id = ?",
                (status, text, expires_at, actor, now, notice_id),
            )
            db.conn.commit()
    else:
        notice_id = str(uuid.uuid4())
        with db._lock:
            db.conn.execute(
                "INSERT INTO site_notices "
                "(id, status, body, expires_at, created_by, updated_by, "
                "created_at, updated_at, published_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    notice_id, status, text, expires_at, actor, actor, now, now,
                    now if status == "published" else None,
                ),
            )
            db.conn.commit()
    save_notice_revision(
        db, notice_id, action="save", status=status, body=text,
        expires_at=expires_at, actor=actor,
    )
    return get_banner(db, notice_id) or {}


def publish_banner(db, notice_id: str, *, actor: str) -> Optional[Dict]:
    rec = get_banner(db, notice_id)
    if not rec:
        return None
    now = _now()
    with db._lock:
        db.conn.execute(
            "UPDATE site_notices SET status = 'disabled', updated_at = ?, updated_by = ? "
            "WHERE status = 'published' AND id != ?",
            (now, actor, notice_id),
        )
        db.conn.execute(
            "UPDATE site_notices SET status = 'published', published_at = ?, "
            "updated_at = ?, updated_by = ? WHERE id = ?",
            (now, now, actor, notice_id),
        )
        db.conn.commit()
    save_notice_revision(
        db, notice_id, action="publish", status="published",
        body=rec["body"], expires_at=rec.get("expires_at"), actor=actor,
    )
    return get_banner(db, notice_id)


def disable_banner(db, notice_id: str, *, actor: str) -> Optional[Dict]:
    rec = get_banner(db, notice_id)
    if not rec:
        return None
    now = _now()
    with db._lock:
        db.conn.execute(
            "UPDATE site_notices SET status = 'disabled', updated_at = ?, updated_by = ? "
            "WHERE id = ?",
            (now, actor, notice_id),
        )
        db.conn.commit()
    save_notice_revision(
        db, notice_id, action="disable", status="disabled",
        body=rec["body"], expires_at=rec.get("expires_at"), actor=actor,
    )
    return get_banner(db, notice_id)


def rollback_banner(db, notice_id: str, revision_id: str, *, actor: str) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT body, status, expires_at FROM site_notice_revisions "
            "WHERE id = ? AND notice_id = ?",
            (revision_id, notice_id),
        ).fetchone()
    if not row:
        return None
    body, status, expires_at = row[0], row[1], row[2] or None
    if status not in BANNER_STATUSES:
        status = "draft"
    now = _now()
    with db._lock:
        db.conn.execute(
            "UPDATE site_notices SET body = ?, status = ?, expires_at = ?, "
            "updated_at = ?, updated_by = ? WHERE id = ?",
            (body, status, expires_at, now, actor, notice_id),
        )
        db.conn.commit()
    save_notice_revision(
        db, notice_id, action="rollback", status=status, body=body,
        expires_at=expires_at, actor=actor,
    )
    return get_banner(db, notice_id)


def get_banner(db, notice_id: str) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT id, status, body, expires_at, created_by, updated_by, "
            "created_at, updated_at, published_at FROM site_notices WHERE id = ?",
            (notice_id,),
        ).fetchone()
        revs = db.conn.execute(
            "SELECT id, action, status, body, expires_at, actor, created_at "
            "FROM site_notice_revisions WHERE notice_id = ? "
            "ORDER BY created_at DESC LIMIT 25",
            (notice_id,),
        ).fetchall() if row else []
    if not row:
        return None
    return {
        "id": row[0],
        "status": row[1],
        "body": row[2],
        "expires_at": row[3],
        "created_by": row[4],
        "updated_by": row[5],
        "created_at": row[6],
        "updated_at": row[7],
        "published_at": row[8],
        "revisions": [
            {
                "id": r[0],
                "action": r[1],
                "status": r[2],
                "body": r[3],
                "expires_at": r[4],
                "actor": r[5],
                "created_at": r[6],
            }
            for r in revs
        ],
    }


def latest_banner(db) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT id FROM site_notices ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return get_banner(db, row[0]) if row else None


def published_banner(db, *, include_draft: bool = False) -> Optional[Dict]:
    now = _now()
    with db._lock:
        if include_draft:
            row = db.conn.execute(
                "SELECT id FROM site_notices ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
        else:
            row = db.conn.execute(
                "SELECT id FROM site_notices WHERE status = 'published' "
                "AND (expires_at IS NULL OR expires_at = '' OR expires_at > ?) "
                "ORDER BY published_at DESC LIMIT 1",
                (now,),
            ).fetchone()
    return get_banner(db, row[0]) if row else None


def get_site_content(db, key: str) -> Optional[Dict]:
    if key not in CONTENT_KEYS:
        return None
    with db._lock:
        row = db.conn.execute(
            "SELECT key, body, updated_by, updated_at, revision FROM site_content "
            "WHERE key = ?",
            (key,),
        ).fetchone()
        revs = db.conn.execute(
            "SELECT id, body, actor, created_at FROM site_content_revisions "
            "WHERE key = ? ORDER BY created_at DESC LIMIT 20",
            (key,),
        ).fetchall() if row else []
    if not row:
        return {"key": key, "body": "", "updated_by": "", "updated_at": "", "revision": 0, "revisions": []}
    return {
        "key": row[0],
        "body": row[1],
        "updated_by": row[2],
        "updated_at": row[3],
        "revision": row[4],
        "revisions": [
            {"id": r[0], "body": r[1], "actor": r[2], "created_at": r[3]}
            for r in revs
        ],
    }


def set_site_content(db, key: str, body: str, *, actor: str) -> Dict:
    clean = validate_content(key, body)
    now = _now()
    with db._lock:
        existing = db.conn.execute(
            "SELECT revision FROM site_content WHERE key = ?", (key,)
        ).fetchone()
        rev = int(existing[0] or 0) + 1 if existing else 1
        db.conn.execute(
            "INSERT INTO site_content (key, body, updated_by, updated_at, revision) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET body = excluded.body, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at, "
            "revision = excluded.revision",
            (key, clean, actor, now, rev),
        )
        db.conn.execute(
            "INSERT INTO site_content_revisions (id, key, body, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), key, clean, actor, now),
        )
        db.conn.commit()
    return get_site_content(db, key) or {}


def rollback_site_content(db, key: str, revision_id: str, *, actor: str) -> Optional[Dict]:
    with db._lock:
        row = db.conn.execute(
            "SELECT body FROM site_content_revisions WHERE id = ? AND key = ?",
            (revision_id, key),
        ).fetchone()
    if not row:
        return None
    return set_site_content(db, key, row[0], actor=actor)


def public_site_content(db) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in CONTENT_KEYS:
        rec = get_site_content(db, key)
        body = (rec or {}).get("body") or ""
        if key in ("support_links", "topic_presets"):
            try:
                out[key] = json.loads(body) if body else []
            except (TypeError, ValueError):
                out[key] = []
        else:
            out[key] = body
    return out
