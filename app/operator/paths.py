"""Path jail and denylist for the operator staging worktree."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

MAX_FILE_BYTES = 512 * 1024

DENY_DIR_NAMES = frozenset({
    ".git", "secrets", "user_data", "venv", ".venv", "backups",
    "__pycache__", "dev_data", "node_modules",
})
DENY_EXACT_NAMES = frozenset({
    ".env", ".env.local", ".secret_key", "mailersend-smtp.txt",
})
DENY_SUFFIXES = (
    ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3",
    ".pem", ".key", ".pfx", ".p12", ".crt", ".pyc",
)
DENY_NAME_RE = re.compile(
    r"(secret|credential|\.token$|smtp.*secret|smtp.*credential)",
    re.IGNORECASE,
)
TEXT_SUFFIXES = frozenset({
    ".py", ".md", ".txt", ".html", ".htm", ".css", ".js", ".json", ".toml",
    ".yml", ".yaml", ".ini", ".cfg", ".svg", ".sh", ".service", ".timer",
    ".example", ".sql", ".csv", ".xml", ".rst", ".in", ".conf", ".gitignore",
    ".gitattributes",
})
TEXT_BASENAMES = frozenset({
    "Dockerfile", "Makefile", "LICENSE", "CHANGELOG", "README", "NOTICE",
    "AUTHORS", "CONTRIBUTING", "CODEOWNERS",
})


class PathJailError(ValueError):
    """Path is outside the staging root or is denylisted."""


def code_root() -> Path:
    """Directory of the running application (scripts live here)."""
    return Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    raw = (os.getenv("LITSIEVE_REPO") or "").strip()
    if raw:
        return Path(raw).resolve()
    return code_root()


def staging_root() -> Path:
    raw = (os.getenv("LITSIEVE_STAGING") or "").strip()
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".local" / "share" / "litsieve" / "staging").resolve()


def live_root() -> Path:
    raw = (os.getenv("LITSIEVE_LIVE") or "").strip()
    if raw:
        return Path(raw).resolve()
    return repo_root()


def is_denied_name(name: str) -> bool:
    lower = name.lower()
    if name in DENY_DIR_NAMES or name in DENY_EXACT_NAMES:
        return True
    if name.startswith(".env") and name != ".env.example":
        return True
    if lower.endswith(DENY_SUFFIXES):
        return True
    if DENY_NAME_RE.search(name):
        return True
    return False


def is_denied_rel(rel: str) -> bool:
    parts = Path(rel).parts
    if any(is_denied_name(part) for part in parts):
        return True
    return False


def looks_text_name(rel: str) -> bool:
    path = Path(rel)
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    if path.name in TEXT_BASENAMES:
        return True
    if path.suffix == "" and path.name.upper() in TEXT_BASENAMES:
        return True
    return False


def jail(root: Path, rel: str) -> Path:
    """Resolve rel under root. Rejects absolute paths, .., and symlink escapes."""
    raw = (rel or "").strip()
    if not raw or raw.startswith(("/", "\\")) or ":" in raw[:4]:
        raise PathJailError("Path must be relative to the staging tree.")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise PathJailError("Path must stay inside the staging tree.")
    if any(part in ("", ".") for part in candidate.parts if part == ""):
        raise PathJailError("Path is not allowed.")
    if is_denied_rel(raw):
        raise PathJailError("That path is not readable or writable from Ops.")
    root_res = root.resolve()
    full = (root_res / candidate).resolve()
    try:
        common = os.path.commonpath([str(root_res), str(full)])
    except ValueError as exc:
        raise PathJailError("Path must stay inside the staging tree.") from exc
    if common != str(root_res):
        raise PathJailError("Path must stay inside the staging tree.")
    return full


def rel_from(root: Path, full: Path) -> str:
    return str(full.resolve().relative_to(root.resolve())).replace("\\", "/")


def is_binary_bytes(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def read_text_capped(path: Path, *, limit: int = MAX_FILE_BYTES) -> str:
    data = path.read_bytes()
    if len(data) > limit:
        raise PathJailError(f"File is larger than {limit} bytes.")
    if is_binary_bytes(data):
        raise PathJailError("Only UTF-8 text files can be opened.")
    return data.decode("utf-8")


def encode_text(content: str) -> bytes:
    if content is None:
        raise PathJailError("Missing file content.")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise PathJailError(f"File is larger than {MAX_FILE_BYTES} bytes.")
    if b"\x00" in data:
        raise PathJailError("Binary writes are not allowed.")
    return data


def walk_text_files(root: Path, *, cap: int = 1500) -> list:
    root_res = root.resolve()
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_res, followlinks=False):
        dirnames[:] = [d for d in dirnames if not is_denied_name(d) and d != ".git"]
        rel_dir = os.path.relpath(dirpath, root_res)
        if rel_dir != "." and is_denied_rel(rel_dir):
            dirnames[:] = []
            continue
        for name in filenames:
            if is_denied_name(name):
                continue
            rel = name if rel_dir == "." else f"{rel_dir}/{name}".replace("\\", "/")
            if is_denied_rel(rel) or not looks_text_name(rel):
                continue
            try:
                jail(root_res, rel)
            except PathJailError:
                continue
            out.append(rel)
            if len(out) >= cap:
                out.sort()
                return out
    out.sort()
    return out


def optional_rel(rel: Optional[str]) -> str:
    return (rel or "").strip()
