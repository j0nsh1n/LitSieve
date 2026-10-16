"""Audit 20.1, 20.2, 20.3 and 20.5: freed space, stored usage, clones, rollbacks."""

import os
from pathlib import Path

import pytest

from app.storage.database import ArticleDatabase

ROOT = Path(__file__).resolve().parents[1]


def _papers(n, source="pubmed", prefix="p"):
    filler = "Long abstract text about heart disease outcomes. " * 60
    return [
        {
            "article_id": f"{prefix}{i}", "source": source, "title": f"Paper {prefix}{i}",
            "abstract": filler + str(i), "year": "2024", "authors": ["A"], "journal": "J",
        }
        for i in range(n)
    ]


def _size(path):
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        if p.exists():
            total += p.stat().st_size
    return total


def test_start_over_gives_the_space_back(tmp_path):
    path = tmp_path / "lib.db"
    db = ArticleDatabase(str(path))
    try:
        db.insert_articles(_papers(400), dedupe=False)
        db.upsert_note("p0", "pubmed", starred=True)
        full = _size(path)
        result = db.keep_starred_and_noted()
        assert result["deleted"] == 399
        assert _size(path) < full / 4
    finally:
        db.close()


def test_clear_all_and_a_replace_fetch_give_the_space_back(tmp_path):
    path = tmp_path / "lib.db"
    db = ArticleDatabase(str(path))
    try:
        db.insert_articles(_papers(400), dedupe=False)
        full = _size(path)
        db.ensure_staging_articles()
        db.insert_articles(_papers(5, prefix="new"), dedupe=False, staging=True)
        assert db.replace_from_staging() == 5
        assert _size(path) < full / 4
        db.insert_articles(_papers(400, prefix="again"), dedupe=False)
        full = _size(path)
        db.clear_all()
        assert _size(path) < full / 4
    finally:
        db.close()


def test_a_failed_replace_leaves_no_swap_tables(tmp_path):
    db = ArticleDatabase(str(tmp_path / "lib.db"))
    try:
        db.insert_articles(_papers(3), dedupe=False)
        db.ensure_staging_articles()
        db.insert_articles(_papers(2, prefix="new"), dedupe=False, staging=True)
        # Break the last copy step so the swap fails after its first tables exist.
        with db._lock:
            db.conn.execute("DROP TABLE embeddings")
            db.conn.commit()
        with pytest.raises(Exception):
            db.replace_from_staging()
        names = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not [n for n in names if n.startswith("_swap_")]
        assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 3
    finally:
        db.close()


def test_a_failed_batch_does_not_stay_open_on_the_connection(tmp_path):
    db = ArticleDatabase(str(tmp_path / "lib.db"))
    try:
        db.insert_articles(_papers(1), dedupe=False)
        with pytest.raises(Exception):
            # The second key is not an article: the foreign key fails mid-batch.
            db.exclude_articles([("p0", "pubmed"), ("nope", "pubmed")], reason="manual")
        assert db.conn.in_transaction is False
        assert db.get_excluded_keys() == set()
    finally:
        db.close()


def test_a_share_clone_copies_only_the_allowed_tables(tmp_path, monkeypatch):
    from app.storage import shares
    from app.storage.libraries import library_db_path

    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    src = library_db_path("owner", "lib1")
    src.parent.mkdir(parents=True, exist_ok=True)
    db = ArticleDatabase(str(src))
    db.insert_articles(_papers(2), dedupe=False)
    db.upsert_note("p0", "pubmed", note="private")
    db.upsert_reader_explanation(
        "p0", "pubmed", "general_reader", "hash", "v1", {"summary": "owner's"}, {"ok": True},
    )
    with db._lock:
        db.conn.execute("CREATE TABLE _swap_keep_notes (article_id TEXT)")
        db.conn.execute("CREATE TABLE staging_articles (article_id TEXT)")
        db.conn.commit()
    db.close()

    shares.clone_library_data("owner", "lib1", "student", "lib2", include_embeddings=False)

    dest = ArticleDatabase(str(library_db_path("student", "lib2")))
    try:
        names = {r[0] for r in dest.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "_swap_keep_notes" not in names and "staging_articles" not in names
        assert dest.conn.execute("SELECT COUNT(*) FROM reader_explanations").fetchone()[0] == 0
        assert dest.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
        assert dest.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 2
    finally:
        dest.close()


def test_half_a_megabyte_is_a_cap_not_unlimited(monkeypatch):
    from app.storage import quota

    monkeypatch.setenv("MAX_USER_STORAGE_MB", "0.5")
    assert quota.limit_bytes() == 512 * 1024
    monkeypatch.setenv("MAX_USER_STORAGE_MB", "0")
    assert quota.limit_bytes() == 0


def test_the_storage_message_says_what_frees_space():
    text = (ROOT / "app" / "storage" / "quota.py").read_text()
    assert "screen out papers you do not need" not in text
    assert "use Start over to remove papers" in text


def test_stored_usage_follows_the_disk(tmp_path, monkeypatch):
    from app import core
    from app.storage.libraries import user_dir
    from app.storage.user_db import UserDatabase

    udb = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", udb)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    uid = udb.create_user("someone", "hash")["id"]
    d = user_dir(uid)
    d.mkdir(parents=True)
    (d / "blob.bin").write_bytes(b"x" * 70_000)
    assert core.refresh_all_storage_bytes() == 1
    assert udb.get_by_id(uid)["storage_bytes"] >= 70_000
    (d / "blob.bin").unlink()
    core.refresh_storage_bytes(uid)
    assert udb.get_by_id(uid)["storage_bytes"] == 0


def test_job_ends_refresh_the_stored_usage():
    core = (ROOT / "app" / "core.py").read_text()
    done = core[core.index("    def _on_done(fut):"):core.index("future.add_done_callback(_on_done)")]
    assert "refresh_storage_bytes(uid)" in done
    main = (ROOT / "app" / "main.py").read_text()
    assert "LITSIEVE_STORAGE_SWEEP_SECONDS" in main
    start_over = (ROOT / "app" / "routes" / "start_over.py").read_text()
    assert "await core.run_in_thread(p.db.keep_starred_and_noted)" in start_over
    assert "core.refresh_storage_bytes(uid)" in start_over


def test_a_guest_row_stays_until_its_files_are_gone(tmp_path, monkeypatch):
    import shutil

    from app import core
    from app.storage.libraries import user_dir
    from app.storage.user_db import UserDatabase

    udb = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", udb)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    uid = udb.create_user("guest_stuck", "hash", is_guest=True)["id"]
    d = user_dir(uid)
    d.mkdir(parents=True)
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)
    with pytest.raises(OSError):
        core.destroy_guest_account(uid)
    assert udb.get_by_id(uid) is not None
    assert os.path.isdir(d)
