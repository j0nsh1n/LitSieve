#!/usr/bin/env python3
"""Back up the accounts database and every user's papers.

Everything lives on one desktop: the accounts DB (real accounts) plus the
user-data tree (each account's libraries, embeddings, notes, screening
decisions). A dead disk loses all of it, and there is no second copy anywhere.

Two details that make this more than `cp -r`:

* **SQLite is copied through the online backup API**, not the filesystem. The
  databases run in WAL mode with a live server attached, so a plain copy can
  catch a torn write and produce an archive that restores to a corrupt file —
  the worst kind of backup, because it looks fine until you need it.
* **Every copy is integrity-checked before the archive is written.** An
  unverified backup is a guess.

The live layout follows `USERS_DB` and `USER_DATA_DIR` (same helpers the app
uses). Archives always use stable prefixes — `users.db` and `user_data/` —
so a restore can put them back at whatever those variables point to now.

Archives land *outside* the repo by default, so `git clean` or a bad deploy
cannot take the backups with it.

Contains real user data and (by default) `.env`, which holds SECRET_KEY —
losing that key makes stored AI keys undecryptable, so restoring without it is
only a partial restore. Archives are written 0600 for that reason. Treat a copy
moved off this machine as a secret: encrypt it.

Usage:
    tools/backup.py                 # create an archive, prune old ones
    tools/backup.py --list          # what exists now
    tools/backup.py --verify FILE   # integrity-check an existing archive
    tools/backup.py --restore FILE  # copy archive contents onto USERS_DB / USER_DATA_DIR
    tools/backup.py --no-env        # exclude .env from the archive (or skip it on restore)
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DEST = Path(os.getenv("BACKUP_DIR") or (Path.home() / "litsieve-backups"))
KEEP = int(os.getenv("BACKUP_KEEP", "14") or 14)

ARCHIVE_USERS = Path("users.db")
ARCHIVE_DATA = Path("user_data")
ARCHIVE_ENV = Path(".env")


def _log(msg: str) -> None:
    print(msg, flush=True)


def _ensure_app_path() -> None:
    root = str(REPO)
    if root not in sys.path:
        sys.path.insert(0, root)


def _resolve(path: Path) -> Path:
    """Absolute as-is; relative against the checkout this tool belongs to."""
    return path if path.is_absolute() else (REPO / path)


def _accounts_db() -> Path:
    _ensure_app_path()
    from app.storage.user_db import users_db_path

    return _resolve(Path(users_db_path())).resolve()


def _data_root() -> Path:
    _ensure_app_path()
    from app.storage.libraries import data_root

    return _resolve(data_root()).resolve()


def _archive_under_data(src: Path, root: Path) -> Path:
    return ARCHIVE_DATA / src.resolve().relative_to(root)


def _backup_items(include_env: bool) -> list[tuple[Path, Path]]:
    """(source file, path inside the archive under litsieve/)."""
    items: list[tuple[Path, Path]] = []
    accounts = _accounts_db()
    if accounts.is_file():
        items.append((accounts, ARCHIVE_USERS))

    root = _data_root()
    if root.is_dir():
        for src in sorted(root.rglob("*")):
            if not src.is_file():
                continue
            if src.suffix not in (".db", ".json"):
                continue
            try:
                rel = _archive_under_data(src, root)
            except ValueError:
                continue
            items.append((src, rel))

    if include_env:
        env = REPO / ".env"
        if env.is_file():
            items.append((env, ARCHIVE_ENV))
    return items


def _copy_db(src: Path, dest: Path) -> None:
    """Consistent copy via the SQLite online backup API.

    Goes through app.storage.dbconn so an encrypted (SQLCipher) source is
    opened with its key and the copy stays readable by the app.
    """
    _ensure_app_path()
    from app.storage import dbconn

    dest.parent.mkdir(parents=True, exist_ok=True)
    source = dbconn.connect(str(src), check_same_thread=True)
    try:
        target = dbconn.connect(str(dest), check_same_thread=True)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def _integrity_ok(path: Path) -> bool:
    try:
        _ensure_app_path()
        from app.storage import dbconn

        conn = dbconn.connect(str(path), check_same_thread=True)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row) and str(row[0]).lower() == "ok"
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def create(dest_dir: Path, include_env: bool = True) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_dir.mkdir(parents=True, exist_ok=True)
    archive = dest_dir / f"litsieve-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="litsieve-backup-") as tmp:
        staging = Path(tmp) / "litsieve"
        staging.mkdir(parents=True)

        items = _backup_items(include_env)
        if not items:
            raise SystemExit("backup: found no databases to back up — wrong directory?")

        for src, rel in items:
            out = staging / rel
            if src.suffix == ".db":
                _copy_db(src, out)
                if not _integrity_ok(out):
                    raise SystemExit(f"backup: integrity check FAILED for {rel} — aborting")
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
            _log(f"  ok  {rel}")

        with tarfile.open(archive, "w:gz") as tar:
            tar.add(staging, arcname="litsieve")

    os.chmod(archive, 0o600)
    _log(f"backup: wrote {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    return archive


def prune(dest_dir: Path, keep: int = KEEP) -> list[Path]:
    archives = sorted(dest_dir.glob("litsieve-*.tar.gz"))
    doomed = archives[:-keep] if keep > 0 and len(archives) > keep else []
    for path in doomed:
        path.unlink()
        _log(f"backup: pruned {path.name}")
    return doomed


def verify(archive: Path) -> bool:
    """Extract to a temp dir and integrity-check every database inside."""
    if not archive.exists():
        _log(f"verify: no such archive {archive}")
        return False
    with tempfile.TemporaryDirectory(prefix="litsieve-verify-") as tmp:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(tmp, filter="data")
        dbs = sorted(Path(tmp).rglob("*.db"))
        if not dbs:
            _log("verify: archive contains no databases")
            return False
        for db in dbs:
            if not _integrity_ok(db):
                _log(f"verify: FAILED {db.name}")
                return False
        _log(f"verify: {archive.name} OK ({len(dbs)} databases)")
        return True


def _extract_root(archive: Path, dest: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")
    root = dest / "litsieve"
    if root.is_dir():
        return root
    nested = list(dest.glob("*/litsieve"))
    if len(nested) == 1 and nested[0].is_dir():
        return nested[0]
    raise SystemExit("restore: archive is missing the litsieve/ prefix")


def restore(archive: Path, *, include_env: bool = True) -> None:
    """Copy archive contents onto the live USERS_DB / USER_DATA_DIR layout."""
    if not archive.exists():
        raise SystemExit(f"restore: no such archive {archive}")
    with tempfile.TemporaryDirectory(prefix="litsieve-restore-") as tmp:
        root = _extract_root(archive, Path(tmp))
        src_users = root / ARCHIVE_USERS
        if src_users.is_file():
            dest = _accounts_db()
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_users, dest)
            _log(f"  restored {ARCHIVE_USERS} -> {dest}")
        src_data = root / ARCHIVE_DATA
        if src_data.is_dir():
            dest_data = _data_root()
            dest_data.mkdir(parents=True, exist_ok=True)
            for src in src_data.rglob("*"):
                if not src.is_file():
                    continue
                out = dest_data / src.relative_to(src_data)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, out)
            _log(f"  restored {ARCHIVE_DATA}/ -> {dest_data}")
        if include_env:
            src_env = root / ARCHIVE_ENV
            if src_env.is_file():
                dest_env = REPO / ".env"
                shutil.copy2(src_env, dest_env)
                _log(f"  restored {ARCHIVE_ENV} -> {dest_env}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=str(DEFAULT_DEST), help="where archives go")
    ap.add_argument("--keep", type=int, default=KEEP, help="archives to retain")
    ap.add_argument("--no-env", action="store_true", help="exclude .env (and SECRET_KEY)")
    ap.add_argument("--list", action="store_true", help="list existing archives")
    ap.add_argument("--verify", metavar="FILE", help="integrity-check an archive")
    ap.add_argument("--restore", metavar="FILE", help="restore an archive onto USERS_DB / USER_DATA_DIR")
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()

    if args.verify:
        return 0 if verify(Path(args.verify).expanduser()) else 1

    if args.restore:
        restore(Path(args.restore).expanduser(), include_env=not args.no_env)
        return 0

    if args.list:
        archives = sorted(dest.glob("litsieve-*.tar.gz"))
        if not archives:
            _log(f"no archives in {dest}")
            return 0
        for a in archives:
            size = a.stat().st_size / 1e6
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(a.stat().st_mtime))
            _log(f"  {when}  {size:7.1f} MB  {a.name}")
        return 0

    archive = create(dest, include_env=not args.no_env)
    prune(dest, args.keep)
    return 0 if verify(archive) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        _log(f"backup: failed: {exc}")
        sys.exit(2)
