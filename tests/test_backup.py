"""Backups of the accounts DB and user libraries.

Everything lives on one desktop and there is no second copy. The failure mode
that matters is not "no backup ran" — it is a backup that exists and does not
restore, so these tests exercise the copy path and the verification, not just
that a file appeared.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sqlite3
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("bk", REPO / "tools" / "backup.py")
bk = importlib.util.module_from_spec(_spec)
sys.modules["bk"] = bk
_spec.loader.exec_module(bk)


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A miniature repo layout: users.db + one library + json + .env."""
    monkeypatch.setattr(bk, "REPO", tmp_path)

    users = sqlite3.connect(tmp_path / "users.db")
    users.execute("CREATE TABLE users (id TEXT, username TEXT)")
    users.execute("INSERT INTO users VALUES ('1', 'alice')")
    users.commit(); users.close()

    lib = tmp_path / "user_data" / "uid-1" / "libraries" / "lib-1"
    lib.mkdir(parents=True)
    art = sqlite3.connect(lib / "articles.db")
    art.execute("CREATE TABLE articles (article_id TEXT, title TEXT)")
    art.execute("INSERT INTO articles VALUES ('a1', 'A paper')")
    art.commit(); art.close()

    (tmp_path / "user_data" / "uid-1" / "libraries.json").write_text('{"libraries": []}')
    (tmp_path / ".env").write_text("SECRET_KEY=not-a-real-key\n")
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    return tmp_path


def test_archive_contains_every_database(fake_repo, tmp_path):
    dest = tmp_path / "out"
    archive = bk.create(dest)
    assert archive.exists()
    import tarfile
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert any(n.endswith("users.db") for n in names)
    assert any(n.endswith("articles.db") for n in names)
    assert any(n.endswith("libraries.json") for n in names)


def test_restored_database_is_readable_and_complete(fake_repo, tmp_path):
    """The point of a backup: the data comes back."""
    import tarfile
    archive = bk.create(tmp_path / "out")
    restore = tmp_path / "restore"
    with tarfile.open(archive) as tar:
        tar.extractall(restore, filter="data")

    users = next(restore.rglob("users.db"))
    conn = sqlite3.connect(users)
    rows = conn.execute("SELECT username FROM users").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["alice"]

    arts = next(restore.rglob("articles.db"))
    conn = sqlite3.connect(arts)
    n = conn.execute("SELECT count(*) FROM articles").fetchone()[0]
    conn.close()
    assert n == 1


def test_verify_accepts_a_good_archive(fake_repo, tmp_path):
    assert bk.verify(bk.create(tmp_path / "out")) is True


def test_verify_rejects_a_corrupt_archive(fake_repo, tmp_path):
    """A backup that cannot restore must fail loudly, not pass quietly."""
    import tarfile
    archive = bk.create(tmp_path / "out")
    staging = tmp_path / "tamper" / "litsieve"
    staging.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(tmp_path / "tamper_src", filter="data")
    src = next((tmp_path / "tamper_src").rglob("users.db"))
    (staging / "users.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    for extra in (tmp_path / "tamper_src").rglob("articles.db"):
        (staging / "articles.db").write_bytes(extra.read_bytes())
    bad = tmp_path / "bad.tar.gz"
    with tarfile.open(bad, "w:gz") as tar:
        tar.add(staging, arcname="litsieve")
    assert src.exists()
    assert bk.verify(bad) is False


def test_env_is_included_by_default_and_excludable(fake_repo, tmp_path):
    """SECRET_KEY is needed for a full restore, but must be opt-out-able."""
    import tarfile
    with tarfile.open(bk.create(tmp_path / "a")) as tar:
        assert any(n.endswith(".env") for n in tar.getnames())
    with tarfile.open(bk.create(tmp_path / "b", include_env=False)) as tar:
        assert not any(n.endswith(".env") for n in tar.getnames())


def test_archive_is_not_world_readable(fake_repo, tmp_path):
    """It contains every user's data and the app's secret key."""
    archive = bk.create(tmp_path / "out")
    assert archive.stat().st_mode & 0o077 == 0, "archive must be 0600"


def test_prune_keeps_the_newest(fake_repo, tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    made = []
    for i in range(5):
        p = dest / f"litsieve-2026010{i}-000000.tar.gz"
        p.write_bytes(b"x")
        made.append(p)
    bk.prune(dest, keep=2)
    left = sorted(p.name for p in dest.glob("litsieve-*.tar.gz"))
    assert left == [made[-2].name, made[-1].name]


def test_refuses_when_there_is_nothing_to_back_up(tmp_path, monkeypatch):
    """An empty archive would look like a successful backup of nothing."""
    monkeypatch.setattr(bk, "REPO", tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    with pytest.raises(SystemExit):
        bk.create(tmp_path / "out")


def test_units_exist_and_are_scheduled():
    for name in ("litsieve-backup.service", "litsieve-backup.timer"):
        assert (REPO / "deploy" / name).exists(), f"missing {name}"
    timer = (REPO / "deploy" / "litsieve-backup.timer").read_text()
    assert "OnCalendar=" in timer
    assert "Persistent=true" in timer, "a missed day must catch up, not vanish"


def _seed_accounts(path: pathlib.Path, username: str = "alice") -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE users (id TEXT, username TEXT)")
    conn.execute("INSERT INTO users VALUES ('1', ?)", (username,))
    conn.commit()
    conn.close()


def _seed_library(root: pathlib.Path, title: str = "A paper") -> None:
    lib = root / "uid-1" / "libraries" / "lib-1"
    lib.mkdir(parents=True)
    conn = sqlite3.connect(lib / "articles.db")
    conn.execute("CREATE TABLE articles (article_id TEXT, title TEXT)")
    conn.execute("INSERT INTO articles VALUES ('a1', ?)", (title,))
    conn.commit()
    conn.close()
    (root / "uid-1" / "libraries.json").write_text('{"libraries": []}')


def _archive_names(archive: pathlib.Path) -> list[str]:
    import tarfile
    with tarfile.open(archive) as tar:
        return tar.getnames()


def test_custom_accounts_db_is_in_the_archive(tmp_path, monkeypatch):
    """USERS_DB is the live accounts file; a hardcoded users.db misses it."""
    monkeypatch.setattr(bk, "REPO", tmp_path)
    accounts = tmp_path / "var" / "accounts.db"
    accounts.parent.mkdir()
    _seed_accounts(accounts, "custom-alice")
    monkeypatch.setenv("USERS_DB", str(accounts))
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "empty_data"))

    archive = bk.create(tmp_path / "out")
    names = _archive_names(archive)
    assert any(n.endswith("users.db") for n in names)
    assert not any(n.endswith("accounts.db") for n in names), names

    import tarfile
    restore_dir = tmp_path / "extracted"
    with tarfile.open(archive) as tar:
        tar.extractall(restore_dir, filter="data")
    conn = sqlite3.connect(next(restore_dir.rglob("users.db")))
    rows = conn.execute("SELECT username FROM users").fetchall()
    conn.close()
    assert [r[0] for r in rows] == ["custom-alice"]


def test_external_data_root_does_not_abort(tmp_path, monkeypatch):
    """USER_DATA_DIR may live outside the checkout; relative_to(REPO) used to crash."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    outside = tmp_path / "outside" / "papers"
    monkeypatch.setattr(bk, "REPO", checkout)
    monkeypatch.delenv("USERS_DB", raising=False)
    monkeypatch.setenv("USER_DATA_DIR", str(outside))
    _seed_library(outside, "External paper")

    archive = bk.create(tmp_path / "out")
    names = _archive_names(archive)
    assert any("user_data/" in n and n.endswith("articles.db") for n in names)
    assert not any("outside" in n for n in names), names

    import tarfile
    restore_dir = tmp_path / "extracted"
    with tarfile.open(archive) as tar:
        tar.extractall(restore_dir, filter="data")
    conn = sqlite3.connect(next(restore_dir.rglob("articles.db")))
    title = conn.execute("SELECT title FROM articles").fetchone()[0]
    conn.close()
    assert title == "External paper"


def test_restore_honours_custom_live_paths(tmp_path, monkeypatch):
    """A complete restore lands on the current USERS_DB / USER_DATA_DIR, not repo defaults."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    src_accounts = tmp_path / "src" / "live-accounts.db"
    src_data = tmp_path / "src" / "live-data"
    src_accounts.parent.mkdir()
    _seed_accounts(src_accounts, "restore-me")
    _seed_library(src_data, "Restore paper")

    monkeypatch.setattr(bk, "REPO", checkout)
    monkeypatch.setenv("USERS_DB", str(src_accounts))
    monkeypatch.setenv("USER_DATA_DIR", str(src_data))
    archive = bk.create(tmp_path / "out")

    dest_accounts = tmp_path / "dest" / "other-accounts.db"
    dest_data = tmp_path / "dest" / "other-data"
    monkeypatch.setenv("USERS_DB", str(dest_accounts))
    monkeypatch.setenv("USER_DATA_DIR", str(dest_data))
    bk.restore(archive, include_env=False)

    conn = sqlite3.connect(dest_accounts)
    users = [r[0] for r in conn.execute("SELECT username FROM users")]
    conn.close()
    assert users == ["restore-me"]
    conn = sqlite3.connect(dest_data / "uid-1" / "libraries" / "lib-1" / "articles.db")
    title = conn.execute("SELECT title FROM articles").fetchone()[0]
    conn.close()
    assert title == "Restore paper"
    assert not dest_accounts.with_name("users.db").exists()


def test_relative_data_root_outside_checkout(tmp_path, monkeypatch):
    """A relative USER_DATA_DIR that resolves outside the repo must still archive."""
    checkout = tmp_path / "repo"
    checkout.mkdir()
    outside = tmp_path / "papers"
    _seed_library(outside, "Relative paper")
    monkeypatch.setattr(bk, "REPO", checkout)
    monkeypatch.delenv("USERS_DB", raising=False)
    monkeypatch.setenv("USER_DATA_DIR", os.path.relpath(outside, checkout))

    archive = bk.create(tmp_path / "out")
    names = _archive_names(archive)
    assert any(n.endswith("articles.db") for n in names)

    dest = tmp_path / "restored-data"
    monkeypatch.setenv("USER_DATA_DIR", str(dest))
    bk.restore(archive, include_env=False)
    conn = sqlite3.connect(dest / "uid-1" / "libraries" / "lib-1" / "articles.db")
    title = conn.execute("SELECT title FROM articles").fetchone()[0]
    conn.close()
    assert title == "Relative paper"
