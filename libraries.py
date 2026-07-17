"""
Multi-library (workspace) support for per-user paper collections.

Each library is an isolated articles.db under:
  user_data/<user_id>/libraries/<library_id>/articles.db

Metadata + active selection live in:
  user_data/<user_id>/libraries.json

Legacy single-file layouts (user_data/<user_id>/articles.db) are migrated on
first access into a library named "My library".
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()

DEFAULT_LIBRARY_NAME = "My library"
MAX_LIBRARIES = 20
NAME_MIN = 1
NAME_MAX = 64
_NAME_CLEAN = re.compile(r"\s+")


def data_root() -> Path:
    return Path(os.getenv("USER_DATA_DIR", "user_data"))


def user_dir(user_id: str) -> Path:
    return data_root() / user_id


def libraries_dir(user_id: str) -> Path:
    return user_dir(user_id) / "libraries"


def meta_path(user_id: str) -> Path:
    return user_dir(user_id) / "libraries.json"


def library_db_path(user_id: str, library_id: str) -> Path:
    return libraries_dir(user_id) / library_id / "articles.db"


def pipeline_cache_key(user_id: str, library_id: str) -> str:
    return f"{user_id}:{library_id}"


def _normalize_name(name: str) -> str:
    cleaned = _NAME_CLEAN.sub(" ", (name or "").strip())
    if len(cleaned) < NAME_MIN or len(cleaned) > NAME_MAX:
        raise ValueError(f"Library name must be {NAME_MIN}–{NAME_MAX} characters.")
    return cleaned


def _empty_meta(library_id: str, name: str = DEFAULT_LIBRARY_NAME) -> Dict:
    return {
        "active_id": library_id,
        "libraries": [
            {
                "id": library_id,
                "name": name,
                "created_at": _now_iso(),
            }
        ],
    }


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_meta_unlocked(user_id: str) -> Optional[Dict]:
    path = meta_path(user_id)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "libraries" not in data:
            return None
        return data
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Corrupt libraries.json for %s: %s", user_id, e)
        return None


def _write_meta_unlocked(user_id: str, meta: Dict) -> None:
    root = user_dir(user_id)
    root.mkdir(parents=True, exist_ok=True)
    path = meta_path(user_id)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def _migrate_legacy_unlocked(user_id: str) -> Dict:
    """Create default library; move legacy articles.db if present."""
    lib_id = str(uuid.uuid4())
    dest_dir = libraries_dir(user_id) / lib_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    legacy = user_dir(user_id) / "articles.db"
    dest_db = dest_dir / "articles.db"
    if legacy.is_file() and not dest_db.exists():
        try:
            legacy.rename(dest_db)
            logger.info("Migrated legacy articles.db for %s → library %s", user_id, lib_id)
            # Move WAL/SHM sidecars if present
            for suffix in ("-wal", "-shm"):
                side = Path(str(legacy) + suffix)
                if side.is_file():
                    side.rename(Path(str(dest_db) + suffix))
        except OSError as e:
            logger.exception("Failed to migrate legacy db for %s: %s", user_id, e)
            # Fall back to copy so we never lose data
            try:
                shutil.copy2(legacy, dest_db)
            except OSError:
                pass
    meta = _empty_meta(lib_id, DEFAULT_LIBRARY_NAME)
    _write_meta_unlocked(user_id, meta)
    return meta


def ensure_libraries(user_id: str) -> Dict:
    """Return libraries meta, migrating legacy layout if needed."""
    if not user_id:
        raise ValueError("user_id required")
    with _lock:
        meta = _read_meta_unlocked(user_id)
        if meta is None:
            user_dir(user_id).mkdir(parents=True, exist_ok=True)
            meta = _migrate_legacy_unlocked(user_id)
        # Ensure active library exists on disk
        active = meta.get("active_id")
        libs = {L["id"]: L for L in meta.get("libraries") or [] if L.get("id")}
        if not libs:
            meta = _migrate_legacy_unlocked(user_id)
            libs = {L["id"]: L for L in meta["libraries"]}
            active = meta["active_id"]
        if active not in libs:
            active = next(iter(libs))
            meta["active_id"] = active
            _write_meta_unlocked(user_id, meta)
        library_db_path(user_id, active).parent.mkdir(parents=True, exist_ok=True)
        return meta


def list_libraries(user_id: str) -> Dict:
    meta = ensure_libraries(user_id)
    return {
        "active_id": meta["active_id"],
        "libraries": list(meta.get("libraries") or []),
    }


def get_active_library_id(user_id: str) -> str:
    return ensure_libraries(user_id)["active_id"]


def set_active_library(user_id: str, library_id: str) -> Dict:
    with _lock:
        meta = _read_meta_unlocked(user_id) or _migrate_legacy_unlocked(user_id)
        ids = {L["id"] for L in meta.get("libraries") or []}
        if library_id not in ids:
            raise ValueError("Library not found.")
        meta["active_id"] = library_id
        _write_meta_unlocked(user_id, meta)
        library_db_path(user_id, library_id).parent.mkdir(parents=True, exist_ok=True)
        return {
            "active_id": meta["active_id"],
            "libraries": list(meta.get("libraries") or []),
        }


def create_library(user_id: str, name: str) -> Dict:
    name = _normalize_name(name)
    with _lock:
        meta = _read_meta_unlocked(user_id) or _migrate_legacy_unlocked(user_id)
        libs = list(meta.get("libraries") or [])
        if len(libs) >= MAX_LIBRARIES:
            raise ValueError(f"At most {MAX_LIBRARIES} libraries per account.")
        # Unique name (case-insensitive)
        lower = name.lower()
        if any((L.get("name") or "").lower() == lower for L in libs):
            raise ValueError("A library with that name already exists.")
        lib_id = str(uuid.uuid4())
        (libraries_dir(user_id) / lib_id).mkdir(parents=True, exist_ok=True)
        entry = {"id": lib_id, "name": name, "created_at": _now_iso()}
        libs.append(entry)
        meta["libraries"] = libs
        # New library becomes active so the user lands in an empty workspace.
        meta["active_id"] = lib_id
        _write_meta_unlocked(user_id, meta)
        return {"library": entry, "active_id": lib_id, "libraries": libs}


def rename_library(user_id: str, library_id: str, name: str) -> Dict:
    name = _normalize_name(name)
    with _lock:
        meta = _read_meta_unlocked(user_id) or _migrate_legacy_unlocked(user_id)
        libs = list(meta.get("libraries") or [])
        found = None
        for L in libs:
            if L.get("id") == library_id:
                found = L
                break
        if not found:
            raise ValueError("Library not found.")
        lower = name.lower()
        if any(
            L.get("id") != library_id and (L.get("name") or "").lower() == lower
            for L in libs
        ):
            raise ValueError("A library with that name already exists.")
        found["name"] = name
        meta["libraries"] = libs
        _write_meta_unlocked(user_id, meta)
        return {"library": found, "active_id": meta["active_id"], "libraries": libs}


def delete_library(user_id: str, library_id: str) -> Dict:
    with _lock:
        meta = _read_meta_unlocked(user_id) or _migrate_legacy_unlocked(user_id)
        libs = list(meta.get("libraries") or [])
        if len(libs) <= 1:
            raise ValueError("You must keep at least one library.")
        if not any(L.get("id") == library_id for L in libs):
            raise ValueError("Library not found.")
        libs = [L for L in libs if L.get("id") != library_id]
        meta["libraries"] = libs
        if meta.get("active_id") == library_id:
            meta["active_id"] = libs[0]["id"]
        _write_meta_unlocked(user_id, meta)
        # Remove on-disk data
        lib_path = libraries_dir(user_id) / library_id
        if lib_path.is_dir():
            try:
                shutil.rmtree(lib_path)
            except OSError:
                logger.exception("Failed to remove library dir %s", lib_path)
        return {
            "active_id": meta["active_id"],
            "libraries": libs,
            "deleted_id": library_id,
        }


def active_db_path(user_id: str) -> str:
    """Filesystem path to the active library's articles.db (str for pipeline)."""
    lib_id = get_active_library_id(user_id)
    path = library_db_path(user_id, lib_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)
