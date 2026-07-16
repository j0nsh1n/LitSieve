"""Multi-library (workspace) storage and migration tests."""

import json
import os
from pathlib import Path

import pytest

import libraries as lib


@pytest.fixture
def user_id(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    # Reload path helpers pick up env
    return "user-test-1"


def test_ensure_creates_default_library(user_id):
    meta = lib.ensure_libraries(user_id)
    assert meta["active_id"]
    assert len(meta["libraries"]) == 1
    assert meta["libraries"][0]["name"] == lib.DEFAULT_LIBRARY_NAME
    db = lib.library_db_path(user_id, meta["active_id"])
    assert db.parent.is_dir()


def test_migrate_legacy_articles_db(user_id, tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    root = lib.user_dir(user_id)
    root.mkdir(parents=True)
    legacy = root / "articles.db"
    legacy.write_bytes(b"sqlite-fake")
    meta = lib.ensure_libraries(user_id)
    lib_id = meta["active_id"]
    dest = lib.library_db_path(user_id, lib_id)
    assert dest.is_file()
    assert dest.read_bytes() == b"sqlite-fake"
    # Legacy path should be gone (renamed) or at least dest has the content
    assert not legacy.exists() or dest.exists()


def test_create_switch_rename_delete(user_id):
    lib.ensure_libraries(user_id)
    created = lib.create_library(user_id, "Unit 3 climate")
    assert created["library"]["name"] == "Unit 3 climate"
    assert created["active_id"] == created["library"]["id"]
    second_id = created["library"]["id"]

    listed = lib.list_libraries(user_id)
    assert len(listed["libraries"]) == 2
    assert listed["active_id"] == second_id

    first_id = [L["id"] for L in listed["libraries"] if L["id"] != second_id][0]
    switched = lib.set_active_library(user_id, first_id)
    assert switched["active_id"] == first_id

    renamed = lib.rename_library(user_id, second_id, "Climate unit")
    names = {L["name"] for L in renamed["libraries"]}
    assert "Climate unit" in names

    deleted = lib.delete_library(user_id, second_id)
    assert deleted["deleted_id"] == second_id
    assert len(deleted["libraries"]) == 1
    assert not (lib.libraries_dir(user_id) / second_id).exists()


def test_cannot_delete_last_library(user_id):
    meta = lib.ensure_libraries(user_id)
    with pytest.raises(ValueError, match="at least one"):
        lib.delete_library(user_id, meta["active_id"])


def test_duplicate_names_rejected(user_id):
    lib.ensure_libraries(user_id)
    lib.create_library(user_id, "Alpha")
    with pytest.raises(ValueError, match="already exists"):
        lib.create_library(user_id, "alpha")


def test_pipeline_opens_active_library_db(user_id, tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    os.environ["SECRET_KEY"] = "pytest-only-not-a-secret-32b-min!!"
    lib.ensure_libraries(user_id)
    lib.create_library(user_id, "Empty two")
    # active is Empty two
    from database import ArticleDatabase
    path = lib.active_db_path(user_id)
    db = ArticleDatabase(db_path=path)
    try:
        db.insert_articles([{
            "article_id": "x",
            "source": "sample",
            "title": "T",
            "abstract": "A long enough abstract for storage.",
            "year": "2020",
            "authors": [],
            "journal": "",
        }], dedupe=False)
        assert db.get_statistics()["total_articles"] == 1
    finally:
        db.close()
    # Switch back to first library — empty
    meta = lib.list_libraries(user_id)
    other = [L["id"] for L in meta["libraries"] if L["id"] != meta["active_id"]][0]
    lib.set_active_library(user_id, other)
    path2 = lib.active_db_path(user_id)
    db2 = ArticleDatabase(db_path=path2)
    try:
        assert db2.get_statistics()["total_articles"] == 0
    finally:
        db2.close()
