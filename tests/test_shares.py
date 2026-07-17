"""Unit tests for share codes and library clone (no HTTP)."""

import numpy as np
import pytest

import libraries as lib
import shares as shares_mod
from database import ArticleDatabase
from user_db import UserDatabase


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    udb = UserDatabase(db_path=str(tmp_path / "users.db"))
    teacher = udb.create_user("teacher", "hash")
    student = udb.create_user("student", "hash")
    lib.ensure_libraries(teacher["id"])
    lib.ensure_libraries(student["id"])
    return {
        "udb": udb,
        "teacher": teacher,
        "student": student,
        "tmp": tmp_path,
    }


def _seed_library(user_id: str, library_id: str, *, with_emb=True, exclude=True):
    path = lib.library_db_path(user_id, library_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = ArticleDatabase(str(path))
    try:
        db.insert_articles([
            {
                "article_id": "a1",
                "source": "pubmed",
                "title": "Sleep study",
                "abstract": "About sleep hygiene and adolescents in classroom settings.",
                "year": "2023",
                "authors": ["A Author"],
                "journal": "Sleep J",
            },
            {
                "article_id": "a2",
                "source": "pubmed",
                "title": "Junk paper",
                "abstract": "Off topic abstract for exclusion testing purposes only.",
                "year": "2020",
                "authors": ["B Author"],
                "journal": "Misc",
            },
        ])
        if exclude:
            db.exclude_articles([("a2", "pubmed")], reason="off_topic")
        with db._lock:
            db.conn.execute(
                "INSERT OR REPLACE INTO key_points (article_id, source, bullets) "
                "VALUES (?, ?, ?)",
                ("a1", "pubmed", '["Point one"]'),
            )
            db.conn.execute(
                "INSERT OR REPLACE INTO notes (article_id, source, note, starred) "
                "VALUES (?, ?, ?, 1)",
                ("a1", "pubmed", "Teacher private note"),
            )
            db.conn.commit()
        if with_emb:
            emb = {
                ("a1", "pubmed"): np.ones(8, dtype=np.float32),
                ("a2", "pubmed"): np.zeros(8, dtype=np.float32),
            }
            db.insert_embeddings(emb, model_name="test-model")
    finally:
        db.close()


def test_generate_share_code_format():
    code = shares_mod.generate_share_code()
    assert len(code) == 9
    assert code[4] == "-"
    assert code == code.upper()
    # Alphabet excludes ambiguous I/O/0/1
    for ch in code.replace("-", ""):
        assert ch in shares_mod._CODE_ALPHABET


def test_normalize_share_code():
    assert shares_mod.normalize_share_code("abcd efgh") == "ABCD-EFGH"
    assert shares_mod.normalize_share_code("abcdefgh") == "ABCD-EFGH"
    assert shares_mod.normalize_share_code("ABCD-EFGH") == "ABCD-EFGH"


def test_clone_copies_screening_not_notes(user_data):
    teacher = user_data["teacher"]
    student = user_data["student"]
    t_meta = lib.list_libraries(teacher["id"])
    t_lib = t_meta["active_id"]
    _seed_library(teacher["id"], t_lib)

    created = lib.create_library(student["id"], "Copy")
    s_lib = created["library"]["id"]
    counts = shares_mod.clone_library_data(
        teacher["id"], t_lib, student["id"], s_lib, include_embeddings=True
    )
    assert counts["articles"] == 2
    assert counts["screening"] == 1
    assert counts["embeddings"] == 2
    assert counts["key_points"] == 1

    db = ArticleDatabase(str(lib.library_db_path(student["id"], s_lib)))
    try:
        with db._lock:
            notes = db.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            clusters = db.conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
            screening = db.conn.execute(
                "SELECT article_id, reason FROM screening"
            ).fetchall()
            kp = db.conn.execute(
                "SELECT bullets FROM key_points WHERE article_id='a1'"
            ).fetchone()
        assert notes == 0
        assert clusters == 0
        assert screening == [("a2", "off_topic")]
        assert kp and "Point one" in kp[0]
    finally:
        db.close()


def test_clone_can_skip_embeddings(user_data):
    teacher = user_data["teacher"]
    student = user_data["student"]
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    _seed_library(teacher["id"], t_lib)
    s_lib = lib.create_library(student["id"], "No emb")["library"]["id"]
    counts = shares_mod.clone_library_data(
        teacher["id"], t_lib, student["id"], s_lib, include_embeddings=False
    )
    assert counts["articles"] == 2
    assert counts["embeddings"] == 0


def test_join_share_happy_path(user_data):
    udb = user_data["udb"]
    teacher = user_data["teacher"]
    student = user_data["student"]
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    _seed_library(teacher["id"], t_lib)

    code = shares_mod.generate_share_code()
    share = udb.create_share(
        owner_user_id=teacher["id"],
        owner_library_id=t_lib,
        title_snapshot="Unit 3 Sleep",
        code=code,
        include_embeddings=True,
        expires_at=None,
        max_uses=40,
    )
    result = shares_mod.join_share(
        udb, student["id"], student["username"], code
    )
    assert result["counts"]["articles"] == 2
    assert result["counts"]["screening"] == 1
    assert "Unit 3 Sleep" in result["library"]["name"]
    assert "teacher" in result["library"]["name"].lower()
    assert result["active_id"] == result["library"]["id"]
    assert udb.get_share_by_id(share["id"])["use_count"] == 1

    # Re-join blocked
    with pytest.raises(ValueError, match="already joined"):
        shares_mod.join_share(udb, student["id"], student["username"], code)


def test_join_own_share_blocked(user_data):
    udb = user_data["udb"]
    teacher = user_data["teacher"]
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    code = shares_mod.generate_share_code()
    udb.create_share(
        owner_user_id=teacher["id"],
        owner_library_id=t_lib,
        title_snapshot="Mine",
        code=code,
    )
    with pytest.raises(ValueError, match="own share"):
        shares_mod.join_share(udb, teacher["id"], teacher["username"], code)


def test_revoke_blocks_join(user_data):
    udb = user_data["udb"]
    teacher = user_data["teacher"]
    student = user_data["student"]
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    code = shares_mod.generate_share_code()
    share = udb.create_share(
        owner_user_id=teacher["id"],
        owner_library_id=t_lib,
        title_snapshot="Revoke me",
        code=code,
    )
    assert udb.revoke_share(share["id"], teacher["id"])
    with pytest.raises(ValueError, match="revoked"):
        shares_mod.join_share(udb, student["id"], student["username"], code)


def test_max_uses_enforced(user_data):
    udb = user_data["udb"]
    teacher = user_data["teacher"]
    student = user_data["student"]
    other = udb.create_user("student2", "hash")
    lib.ensure_libraries(other["id"])
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    _seed_library(teacher["id"], t_lib, with_emb=False)
    code = shares_mod.generate_share_code()
    udb.create_share(
        owner_user_id=teacher["id"],
        owner_library_id=t_lib,
        title_snapshot="One seat",
        code=code,
        max_uses=1,
    )
    shares_mod.join_share(udb, student["id"], student["username"], code)
    with pytest.raises(ValueError, match="maximum"):
        shares_mod.join_share(udb, other["id"], other["username"], code)


def test_preview_share(user_data):
    udb = user_data["udb"]
    teacher = user_data["teacher"]
    student = user_data["student"]
    t_lib = lib.list_libraries(teacher["id"])["active_id"]
    _seed_library(teacher["id"], t_lib)
    code = shares_mod.generate_share_code()
    udb.create_share(
        owner_user_id=teacher["id"],
        owner_library_id=t_lib,
        title_snapshot="Unit 3 Sleep",
        code=code,
        include_embeddings=True,
    )
    preview = shares_mod.preview_share(udb, student["id"], code)
    assert preview["can_join"] is True
    assert preview["article_count"] == 2
    assert preview["excluded_count"] == 1
    assert preview["owner_username"] == "teacher"
    assert preview["has_embeddings"] is True
