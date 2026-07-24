"""
Share-a-library: optional copy codes that clone a library into another account.

v1 model is clone-only (not a live view of the teacher's DB). Join copies
articles + screening + key_points, and embeddings when the share allows it.
Notes, stars, and clusters are never copied.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.storage.database import ArticleDatabase
from app.storage.libraries import (
    NAME_MAX,
    create_library,
    delete_library,
    ensure_libraries,
    get_active_library_id,
    library_db_path,
    list_libraries,
    set_active_library,
)

logger = logging.getLogger(__name__)

# Human-typeable alphabet (no I/O/0/1).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
DEFAULT_EXPIRES_DAYS = 14
MAX_EXPIRES_DAYS = 365
MAX_MAX_USES = 10_000


def generate_share_code() -> str:
    """Return an unguessable XXXX-YYYY classroom code."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def normalize_share_code(code: str) -> str:
    cleaned = (code or "").strip().upper().replace(" ", "")
    if len(cleaned) == 8 and "-" not in cleaned:
        cleaned = f"{cleaned[:4]}-{cleaned[4:]}"
    return cleaned


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_share_usable(share: Dict) -> Tuple[bool, str]:
    """Return (ok, error_message) for redeem/preview eligibility."""
    if share.get("revoked_at"):
        return False, "This share code has been revoked."
    expires = _parse_iso(share.get("expires_at"))
    if expires is not None and datetime.now(timezone.utc) > expires:
        return False, "This share code has expired."
    max_uses = share.get("max_uses")
    if max_uses is not None and int(share.get("use_count") or 0) >= int(max_uses):
        return False, "This share code has reached its maximum number of uses."
    return True, ""


def library_exists(user_id: str, library_id: str) -> bool:
    meta = ensure_libraries(user_id)
    return any(L.get("id") == library_id for L in meta.get("libraries") or [])


def library_name(user_id: str, library_id: str) -> Optional[str]:
    meta = ensure_libraries(user_id)
    for L in meta.get("libraries") or []:
        if L.get("id") == library_id:
            return L.get("name")
    return None


def count_library_stats(user_id: str, library_id: str) -> Dict[str, int]:
    """Article / screening / embedding counts for preview (0 if empty/missing)."""
    path = library_db_path(user_id, library_id)
    if not path.is_file():
        return {"articles": 0, "screening": 0, "embeddings": 0, "key_points": 0}
    conn = sqlite3.connect(str(path))
    try:
        def _count(table: str) -> int:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return int(row[0] or 0) if row else 0
            except sqlite3.Error:
                return 0

        return {
            "articles": _count("articles"),
            "screening": _count("screening"),
            "embeddings": _count("embeddings"),
            "key_points": _count("key_points"),
        }
    finally:
        conn.close()


def _join_display_name(title: str, teacher_username: str) -> str:
    teacher = (teacher_username or "teacher").strip() or "teacher"
    title = (title or "Shared library").strip() or "Shared library"
    suffix = f" (from {teacher})"
    if len(title) + len(suffix) <= NAME_MAX:
        return title + suffix
    keep = max(8, NAME_MAX - len(suffix))
    return title[:keep].rstrip() + suffix


def create_library_with_unique_name(user_id: str, preferred: str) -> Dict:
    """create_library, appending (2), (3), … on name collision."""
    preferred = (preferred or "Shared library").strip() or "Shared library"
    if len(preferred) > NAME_MAX:
        preferred = preferred[:NAME_MAX].rstrip()
    try:
        return create_library(user_id, preferred)
    except ValueError as e:
        if "already exists" not in str(e).lower():
            raise
    for i in range(2, 100):
        suffix = f" ({i})"
        base = preferred
        if len(base) + len(suffix) > NAME_MAX:
            base = base[: NAME_MAX - len(suffix)].rstrip()
        try:
            return create_library(user_id, base + suffix)
        except ValueError as e:
            if "already exists" not in str(e).lower():
                raise
            continue
    raise ValueError("Could not allocate a unique library name.")


def clone_library_data(
    source_user_id: str,
    source_library_id: str,
    dest_user_id: str,
    dest_library_id: str,
    include_embeddings: bool = True,
) -> Dict[str, int]:
    """
    Copy articles (+ screening + key_points) into dest library DB.

    Strips notes and clusters. Embeddings copied only when include_embeddings.
    """
    src = library_db_path(source_user_id, source_library_id)
    dest = library_db_path(dest_user_id, dest_library_id)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if not src.is_file():
        # Empty source → leave empty dest (pipeline will create schema on open).
        return {"articles": 0, "embeddings": 0, "screening": 0, "key_points": 0}

    # Build the clone in a temp DB, sanitize it there, then atomically move it
    # into place. The sqlite backup API yields a consistent snapshot including
    # committed WAL frames (a wal_checkpoint can silently return busy), and
    # sanitize-then-VACUUM before publishing means the student's file never
    # contains the teacher's private notes/clusters, even transiently.
    tmp = dest.with_name(dest.name + ".cloning")
    for path in (tmp, dest, Path(str(dest) + "-wal"), Path(str(dest) + "-shm")):
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        try:
            tmp_conn = sqlite3.connect(str(tmp))
            try:
                src_conn.backup(tmp_conn)
                tmp_conn.execute("DELETE FROM notes")
                tmp_conn.execute("DELETE FROM clusters")
                if not include_embeddings:
                    tmp_conn.execute("DELETE FROM embeddings")
                tmp_conn.commit()
                # Compact so the deleted rows are not recoverable from the file.
                tmp_conn.execute("VACUUM")
            finally:
                tmp_conn.close()
        finally:
            src_conn.close()
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    db = ArticleDatabase(str(dest))
    try:
        with db._lock:

            def _count(table: str) -> int:
                row = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                return int(row[0] or 0) if row else 0

            return {
                "articles": _count("articles"),
                "embeddings": _count("embeddings"),
                "screening": _count("screening"),
                "key_points": _count("key_points"),
            }
    finally:
        db.close()


def join_share(
    user_db,
    student_user_id: str,
    student_username: str,
    code: str,
) -> Dict[str, Any]:
    """
    Validate code, clone into a new student library, record redemption.

    Raises ValueError with a user-facing message on expected failures.
    """
    code = normalize_share_code(code)
    if not code or len(code) < 9:
        raise ValueError("Enter a valid share code (for example ABCD-EFGH).")

    share = user_db.get_share_by_code(code)
    if not share:
        raise ValueError("Share code not found.")

    ok, err = is_share_usable(share)
    if not ok:
        raise ValueError(err)

    if share["owner_user_id"] == student_user_id:
        raise ValueError("You cannot join your own share. Students use this code.")

    if user_db.has_redeemed_share(share["id"], student_user_id):
        raise ValueError(
            "You already joined with this code. Switch to that library from Account."
        )

    owner_id = share["owner_user_id"]
    owner_lib = share["owner_library_id"]
    if not library_exists(owner_id, owner_lib):
        raise ValueError("The shared library is no longer available.")

    owner = user_db.get_by_id(owner_id)
    teacher = (owner or {}).get("username") or "teacher"
    title = share.get("title_snapshot") or library_name(owner_id, owner_lib) or "Shared library"
    preferred = _join_display_name(title, teacher)

    # Capture the pre-join active library so any rollback can restore it.
    prev_active = get_active_library_id(student_user_id)

    def _rollback_new_library(new_id: str) -> None:
        """Best-effort removal of the new library + restore of prev active."""
        try:
            # Only delete if we still have another library (create made ≥2).
            libs = list_libraries(student_user_id).get("libraries") or []
            if len(libs) > 1:
                delete_library(student_user_id, new_id)
            if any(L.get("id") == prev_active for L in
                   list_libraries(student_user_id).get("libraries") or []):
                set_active_library(student_user_id, prev_active)
        except Exception:
            logger.exception("Failed to roll back library after join error")

    # create_library enforces MAX_LIBRARIES.
    created = create_library_with_unique_name(student_user_id, preferred)
    new_lib = created["library"]
    new_id = new_lib["id"]

    # Prepare everything fallible *before* consuming the code: clone, set the
    # active library, and build the response. record_redemption commits last,
    # so a filesystem failure can't burn the student's code without a retry.
    try:
        counts = clone_library_data(
            owner_id,
            owner_lib,
            student_user_id,
            new_id,
            include_embeddings=bool(share.get("include_embeddings", True)),
        )
        set_active_library(student_user_id, new_id)
        libraries = list_libraries(student_user_id)["libraries"]
    except Exception:
        _rollback_new_library(new_id)
        raise

    try:
        user_db.record_redemption(
            share_id=share["id"],
            student_user_id=student_user_id,
            student_library_id=new_id,
        )
    except Exception:
        # Code was not consumed; remove the clone so a retry starts clean.
        _rollback_new_library(new_id)
        raise

    return {
        "library": new_lib,
        "active_id": new_id,
        "libraries": libraries,
        "counts": counts,
        "share_id": share["id"],
        "code": share["code"],
        "from_username": teacher,
    }


def preview_share(user_db, student_user_id: str, code: str) -> Dict[str, Any]:
    code = normalize_share_code(code)
    if not code or len(code) < 9:
        raise ValueError("Enter a valid share code (for example ABCD-EFGH).")

    share = user_db.get_share_by_code(code)
    if not share:
        raise ValueError("Share code not found.")

    ok, err = is_share_usable(share)
    owner = user_db.get_by_id(share["owner_user_id"])
    owner_name = (owner or {}).get("username") or "teacher"
    stats = {"articles": 0, "screening": 0, "embeddings": 0, "key_points": 0}
    lib_available = library_exists(share["owner_user_id"], share["owner_library_id"])
    if lib_available:
        stats = count_library_stats(share["owner_user_id"], share["owner_library_id"])

    already = user_db.has_redeemed_share(share["id"], student_user_id)
    can_join = ok and lib_available and not already and share["owner_user_id"] != student_user_id
    block_reason = None
    if not lib_available:
        block_reason = "The shared library is no longer available."
        can_join = False
    elif share["owner_user_id"] == student_user_id:
        block_reason = "This is your own share."
        can_join = False
    elif already:
        block_reason = "You already joined with this code."
        can_join = False
    elif not ok:
        block_reason = err
        can_join = False

    return {
        "code": share["code"],
        "title": share.get("title_snapshot") or "Shared library",
        "owner_username": owner_name,
        "article_count": stats["articles"],
        "excluded_count": stats["screening"],
        "embedding_count": stats["embeddings"],
        "include_embeddings": bool(share.get("include_embeddings", True)),
        "has_embeddings": stats["embeddings"] > 0,
        "expires_at": share.get("expires_at"),
        "max_uses": share.get("max_uses"),
        "use_count": int(share.get("use_count") or 0),
        "already_joined": already,
        "can_join": can_join,
        "block_reason": block_reason,
        "is_own": share["owner_user_id"] == student_user_id,
    }
