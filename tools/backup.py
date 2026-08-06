#!/usr/bin/env python3
"""Back up the accounts database and every user's papers.

Everything lives on one desktop: `users.db` (real accounts) plus `user_data/`
(each account's libraries, embeddings, notes, screening decisions). A dead disk
loses all of it, and there is no second copy anywhere.

Two details that make this more than `cp -r`:

* **SQLite is copied through the online backup API**, not the filesystem. The
  databases run in WAL mode with a live server attached, so a plain copy can
  catch a torn write and produce an archive that restores to a corrupt file —
  the worst kind of backup, because it looks fine until you need it.
* **Every copy is integrity-checked before the archive is written.** An
  unverified backup is a guess.

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
    tools/backup.py --no-env        # exclude .env from the archive
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


def _log(msg: str) -> None:
    print(msg, flush=True)


def _sqlite_files() -> list[Path]:
    """Every SQLite database that matters, relative paths under the repo."""
    found: list[Path] = []
    users = REPO / "users.db"
    if users.exists():
        found.append(users)
    data = Path(os.getenv("USER_DATA_DIR") or (REPO / "user_data"))
    if data.exists():
        found.extend(sorted(data.rglob("*.db")))
    return found


def _plain_files(include_env: bool) -> list[Path]:
    """Non-SQLite files worth keeping (library metadata, AI settings, .env)."""
    found: list[Path] = []
    data = Path(os.getenv("USER_DATA_DIR") or (REPO / "user_data"))
    if data.exists():
        found.extend(sorted(data.rglob("*.json")))
    if include_env:
        env = REPO / ".env"
        if env.exists():
            found.append(env)
    return found


def _copy_db(src: Path, dest: Path) -> None:
    """Consistent copy via the SQLite online backup API.

    Goes through app.storage.dbconn so an encrypted (SQLCipher) source is
    opened with its key and the copy stays readable by the app.
    """
    sys.path.insert(0, str(REPO))
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
        sys.path.insert(0, str(REPO))
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

        dbs = _sqlite_files()
        if not dbs:
            raise SystemExit("backup: found no databases to back up — wrong directory?")

        for src in dbs:
            rel = src.relative_to(REPO)
            out = staging / rel
            _copy_db(src, out)
            if not _integrity_ok(out):
                raise SystemExit(f"backup: integrity check FAILED for {rel} — aborting")
            _log(f"  ok  {rel}")

        for src in _plain_files(include_env):
            rel = src.relative_to(REPO)
            out = staging / rel
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dest", default=str(DEFAULT_DEST), help="where archives go")
    ap.add_argument("--keep", type=int, default=KEEP, help="archives to retain")
    ap.add_argument("--no-env", action="store_true", help="exclude .env (and SECRET_KEY)")
    ap.add_argument("--list", action="store_true", help="list existing archives")
    ap.add_argument("--verify", metavar="FILE", help="integrity-check an archive")
    args = ap.parse_args()

    dest = Path(args.dest).expanduser()

    if args.verify:
        return 0 if verify(Path(args.verify).expanduser()) else 1

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
