"""Restore and encryption-conversion safety (audit finding 20.4).

A restore that leaves the old ``-wal`` next to the restored file lets SQLite
replay stale writes onto it; a conversion that is not verified before it
replaces the original can destroy the only good copy. These tests build the
bad situation and check what the tools leave on disk.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sqlite3
import sys
import tarfile

import pytest

from app.storage import dbconn

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bk = _load("bk_restore", "backup.py")
enc = _load("enc_tool", "encrypt_databases.py")


def _rows(path: pathlib.Path, sql: str = "SELECT name FROM t ORDER BY name") -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute(sql)]
    finally:
        conn.close()


def _make_wal_db(path: pathlib.Path, names: list[str]) -> None:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?)", [(n,) for n in names])
    conn.commit()
    conn.close()


@pytest.fixture
def live(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(bk, "REPO", repo)
    monkeypatch.delenv("USERS_DB", raising=False)
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    monkeypatch.setenv("USER_DATA_DIR", str(repo / "user_data"))
    return repo


def test_restore_does_not_replay_a_leftover_wal(live, tmp_path):
    users = live / "users.db"
    _make_wal_db(users, ["alice"])
    archive = bk.create(tmp_path / "out", include_env=False)

    # Crash state: more committed rows that only exist in an uncheckpointed -wal.
    conn = sqlite3.connect(users)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("INSERT INTO t VALUES ('bob')")
    conn.execute("INSERT INTO t VALUES ('carol')")
    conn.commit()
    snap = tmp_path / "snap"
    snap.mkdir()
    for suffix in ("", "-wal"):
        shutil.copy2(str(users) + suffix, snap / f"users.db{suffix}")
    conn.close()
    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(str(users) + suffix).unlink(missing_ok=True)
    for suffix in ("", "-wal"):
        shutil.copy2(snap / f"users.db{suffix}", str(users) + suffix)
    (live / "users.db-shm").write_bytes(b"\x00" * 32768)

    # Precondition: left alone, SQLite would replay the WAL (the bug).
    probe = tmp_path / "probe"
    probe.mkdir()
    shutil.copy2(users, probe / "users.db")
    shutil.copy2(str(users) + "-wal", probe / "users.db-wal")
    assert _rows(probe / "users.db") == ["alice", "bob", "carol"]

    bk.restore(archive, include_env=False)

    assert _rows(users) == ["alice"]
    assert not (live / "users.db-wal").exists()
    assert not (live / "users.db-shm").exists()
    assert not list(live.glob(".*restoring*")), "temp file left behind"
    conn = sqlite3.connect(users)
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    conn.close()


def test_install_file_removes_every_sidecar_before_the_swap(tmp_path):
    src = tmp_path / "src.db"
    _make_wal_db(src, ["new"])
    dest = tmp_path / "live" / "users.db"
    dest.parent.mkdir()
    dest.write_bytes(b"old")
    for suffix in ("-wal", "-shm", "-journal"):
        pathlib.Path(str(dest) + suffix).write_bytes(b"stale")

    bk._install_file(src, dest)

    # Check sidecars first: merely opening the file would clean them up.
    assert [p.name for p in dest.parent.iterdir()] == ["users.db"]
    assert _rows(dest) == ["new"]


def _seed_live_with_library(live):
    users = live / "users.db"
    _make_wal_db(users, ["alice"])
    lib = live / "user_data" / "uid-1" / "libraries" / "lib-1"
    lib.mkdir(parents=True)
    _make_wal_db(lib / "articles.db", ["paper"])
    return users, lib / "articles.db"


def test_truncated_archive_fails_clearly_and_touches_nothing(live, tmp_path):
    users, lib_db = _seed_live_with_library(live)
    archive = bk.create(tmp_path / "out", include_env=False)
    # Change the live data so a wrongly applied restore would be visible.
    conn = sqlite3.connect(users)
    conn.execute("INSERT INTO t VALUES ('live-only')")
    conn.commit()
    conn.close()
    before = {p: p.read_bytes() for p in (users, lib_db)}

    bad = tmp_path / "truncated.tar.gz"
    bad.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    with pytest.raises(SystemExit, match="corrupt or truncated"):
        bk.restore(bad, include_env=False)

    assert {p: p.read_bytes() for p in (users, lib_db)} == before


def test_corrupt_member_fails_before_any_live_file_changes(live, tmp_path):
    users, lib_db = _seed_live_with_library(live)
    archive = bk.create(tmp_path / "out", include_env=False)
    extracted = tmp_path / "x"
    with tarfile.open(archive) as tar:
        tar.extractall(extracted, filter="data")
    # users.db stays good; only the library database is damaged.
    victim = next(extracted.rglob("articles.db"))
    victim.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(extracted / "litsieve", arcname="litsieve")

    conn = sqlite3.connect(users)
    conn.execute("INSERT INTO t VALUES ('live-only')")
    conn.commit()
    conn.close()
    before = {p: p.read_bytes() for p in (users, lib_db)}

    with pytest.raises(SystemExit, match="integrity check"):
        bk.restore(bad, include_env=False)

    assert {p: p.read_bytes() for p in (users, lib_db)} == before
    assert "live-only" in _rows(users)


# ---- tools/encrypt_databases.py -------------------------------------------


def test_clean_key_strips_like_dbconn(monkeypatch):
    monkeypatch.setenv(dbconn.ENV_KEY, "  k3y\n")
    assert enc.clean_key("  k3y\n") == dbconn.encryption_key() == "k3y"
    assert enc.clean_key(None) == ""


def test_find_databases_follows_users_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    (tmp_path / "users.db").write_bytes(b"")
    custom = tmp_path / "var" / "accounts.db"
    custom.parent.mkdir()
    custom.write_bytes(b"")
    monkeypatch.setenv("USERS_DB", str(custom))
    assert enc.find_databases() == [custom]
    monkeypatch.delenv("USERS_DB")
    assert enc.find_databases() == [pathlib.Path("users.db")]


@pytest.fixture
def encrypt_env(tmp_path, monkeypatch):
    pytest.importorskip("sqlcipher3", reason="sqlcipher3-binary not installed")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    acct = tmp_path / "var" / "accounts.db"
    acct.parent.mkdir()
    _make_wal_db(acct, ["alice", "bob"])
    (tmp_path / "users.db").write_bytes(b"decoy that must not be touched")
    monkeypatch.setenv("USERS_DB", str(acct))
    monkeypatch.setenv(dbconn.ENV_KEY, "  secret-key\n")
    return acct


def test_encrypt_uses_users_db_and_the_stripped_key(encrypt_env, monkeypatch, capsys):
    acct = encrypt_env
    monkeypatch.setattr(sys, "argv", ["encrypt_databases.py", "--apply"])
    assert enc.main() == 0

    assert dbconn.is_encrypted(str(acct))
    assert (acct.parent / "accounts.db.plaintext.bak").exists()
    assert (acct.parent.parent / "users.db").read_bytes() == b"decoy that must not be touched"
    # The app opens with the stripped env key: this only works if the tool did too.
    conn = dbconn.connect(str(acct))
    try:
        assert [r[0] for r in conn.execute("SELECT name FROM t ORDER BY name")] == ["alice", "bob"]
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert not list(acct.parent.glob("*.converting"))


def test_unverified_conversion_leaves_the_original(encrypt_env, monkeypatch):
    acct = encrypt_env
    before = acct.read_bytes()

    def boom(path, key):
        raise enc.ConversionError("simulated bad copy")

    monkeypatch.setattr(enc, "_snapshot", boom)
    monkeypatch.setattr(sys, "argv", ["encrypt_databases.py", "--apply"])
    assert enc.main() == 1

    assert not dbconn.is_encrypted(str(acct))
    assert _rows(acct) == ["alice", "bob"]
    assert not (acct.parent / "accounts.db.plaintext.bak").exists()
    assert not list(acct.parent.glob("*.converting"))
    assert before[:16] == b"SQLite format 3\x00"
