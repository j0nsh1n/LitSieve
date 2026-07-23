#!/usr/bin/env python3
"""Convert the app's SQLite databases between plaintext and SQLCipher.

Enabling DB_ENCRYPTION_KEY does not convert anything on its own — the app will
refuse to open plaintext files once a key is set. Run this first.

    # see what would happen (default: nothing is written)
    python tools/encrypt_databases.py --key "$DB_ENCRYPTION_KEY"

    # actually convert, keeping .plaintext.bak copies
    python tools/encrypt_databases.py --key "$DB_ENCRYPTION_KEY" --apply

    # go back to plaintext (e.g. you are about to rotate the key)
    python tools/encrypt_databases.py --key "$DB_ENCRYPTION_KEY" --decrypt --apply

Stop the server first: converting a database that is being written to can
lose the in-flight writes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.storage.dbconn import is_encrypted  # noqa: E402

BACKUP_SUFFIX = ".plaintext.bak"


def data_root() -> Path:
    return Path(os.getenv("USER_DATA_DIR", "user_data"))


def find_databases() -> list[Path]:
    """users.db plus every per-library articles.db."""
    found = []
    users = Path("users.db")
    if users.is_file():
        found.append(users)
    root = data_root()
    if root.is_dir():
        found.extend(sorted(root.glob("*/libraries/*/articles.db")))
        # Pre-v4.0 single-library layout, in case it was never migrated.
        found.extend(sorted(root.glob("*/articles.db")))
    return found


def _quote(key: str) -> str:
    return "'" + key.replace("'", "''") + "'"


def convert(path: Path, key: str, *, decrypt: bool) -> None:
    """Rewrite ``path`` via sqlcipher_export(), keeping a backup."""
    import sqlcipher3

    tmp = path.with_name(path.name + ".converting")
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    for stale in (tmp,):
        stale.unlink(missing_ok=True)

    conn = sqlcipher3.dbapi2.connect(str(path))
    try:
        if decrypt:
            # Source is encrypted; destination gets an empty key.
            conn.execute(f"PRAGMA key = {_quote(key)}")
            conn.execute(f"ATTACH DATABASE '{tmp}' AS target KEY ''")
        else:
            # Source is plaintext (no key); destination gets the key.
            conn.execute(f"ATTACH DATABASE '{tmp}' AS target KEY {_quote(key)}")
        # Flush any WAL content into the file we are about to copy from.
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("SELECT sqlcipher_export('target')")
        conn.execute("DETACH DATABASE target")
    finally:
        conn.close()

    shutil.copy2(path, backup)
    os.replace(tmp, path)
    # WAL/SHM sidecars belong to the old file; they are rebuilt on next open.
    for suffix in ("-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default=os.getenv("DB_ENCRYPTION_KEY", ""),
                    help="encryption key (defaults to $DB_ENCRYPTION_KEY)")
    ap.add_argument("--decrypt", action="store_true",
                    help="convert encrypted databases back to plaintext")
    ap.add_argument("--apply", action="store_true",
                    help="actually write changes (default is a dry run)")
    args = ap.parse_args()

    if not args.key:
        print("No key given. Pass --key or set DB_ENCRYPTION_KEY.", file=sys.stderr)
        return 2

    databases = find_databases()
    if not databases:
        print("No databases found. Run this from the repo root.")
        return 1

    want_encrypted = not args.decrypt
    todo, skip = [], []
    for path in databases:
        already = is_encrypted(str(path))
        (skip if already == want_encrypted else todo).append(path)

    verb = "decrypt" if args.decrypt else "encrypt"
    for path in skip:
        print(f"  skip     {path}  (already {'encrypted' if want_encrypted else 'plaintext'})")
    for path in todo:
        print(f"  {verb:8s} {path}")

    if not todo:
        print("\nNothing to do.")
        return 0
    if not args.apply:
        print(f"\nDry run — {len(todo)} database(s) would be {verb}ed. Re-run with --apply.")
        return 0

    print()
    for path in todo:
        convert(path, args.key, decrypt=args.decrypt)
        print(f"  done     {path}  (backup: {path.name}{BACKUP_SUFFIX})")

    print(
        f"\n{len(todo)} database(s) {verb}ed."
        f"\nBackups kept as *{BACKUP_SUFFIX} — delete them once you have verified"
        "\nthe app starts and your data is intact. They are plaintext copies."
        if not args.decrypt else
        f"\n{len(todo)} database(s) {verb}ed."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
