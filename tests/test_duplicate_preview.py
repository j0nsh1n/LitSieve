"""Duplicate preview proposes the exact automatic plan without screening writes."""

from collections import OrderedDict

import numpy as np
import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.user_db import UserDatabase


def _article(index, abstract="A complete abstract"):
    return {
        "article_id": str(index), "source": "pubmed", "title": f"Title {index}",
        "abstract": abstract, "year": "2024", "authors": [], "journal": "Fixture",
    }


def test_preview_is_complete_read_only_and_matches_auto_resolve(tmp_path):
    pipe = LiteratureSearchPipeline(str(tmp_path / "articles.db"))
    try:
        rows = [_article(i) for i in range(53)]
        rows[-1]["abstract"] = "Longest complete abstract " * 20
        pipe.db.insert_articles([*rows, _article("unrelated")], dedupe=False)
        pipe.db.insert_embeddings({(str(i), "pubmed"): np.ones(4, dtype=np.float32) for i in range(53)}, model_name="general")
        pipe.db.exclude_articles([("unrelated", "pubmed")], reason="off_topic")
        preview = pipe.preview_duplicate_resolution()
        assert preview["groups"] == 1
        assert preview["excluded"] == 52
        candidates = preview["candidates"]
        assert len(candidates) == 52  # Every loser, beyond the old 50-pair display cap.
        assert all(item["keeper"]["article_id"] == "52" for item in candidates)
        assert {item["article_id"] for item in candidates} == {str(i) for i in range(52)}
        assert pipe.db.get_excluded_keys() == {("unrelated", "pubmed")}
        assert pipe.resolve_duplicates() == {"groups": 1, "excluded": 52}
        assert pipe.db.get_excluded_keys() == {("unrelated", "pubmed"), *((str(i), "pubmed") for i in range(52))}
        assert pipe.preview_duplicate_resolution()["candidates"] == []
    finally:
        pipe.close()


@pytest.fixture
def client_with_library(tmp_path, monkeypatch):
    from app.main import app

    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setattr(core, "_pipelines", OrderedDict())
    monkeypatch.setattr(core, "_pipeline_refcounts", {})
    monkeypatch.setattr(core, "_all_progress", OrderedDict())
    client = TestClient(app)
    response = client.post("/register", data={
        "username": "preview-fixture", "password": TEST_PASSWORD,
        "password_confirm": TEST_PASSWORD,
    }, follow_redirects=False)
    assert response.status_code == 302
    uid = db.get_by_username("preview-fixture")["id"]
    lib_id = client.get("/api/libraries").json()["active_id"]
    yield client, uid, lib_id
    for pipe in core._pipelines.values():
        pipe.close()
    db.conn.close()


def test_http_preview_uses_page_library_and_apply_is_separate(client_with_library):
    client, uid, library_id = client_with_library
    pipe = core.get_pipeline(uid, library_id)
    try:
        pipe.db.insert_articles([_article(1), _article(2, "Longer abstract " * 20)], dedupe=False)
        pipe.db.insert_embeddings({("1", "pubmed"): np.ones(4, dtype=np.float32), ("2", "pubmed"): np.ones(4, dtype=np.float32)}, model_name="general")
    finally:
        core.release_pipeline(uid, library_id)
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    other = client.post("/api/libraries", json={"name": "Other"}, headers=headers).json()["library"]["id"]
    assert other != library_id
    response = client.post("/api/resolve-duplicates", json={"preview": True, "library_id": library_id}, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert [item["article_id"] for item in result["candidates"]] == ["1"]
    assert client.get("/api/screening/excluded", params={"library_id": library_id}).json()["items"] == []
    assert client.get("/api/statistics", params={"library_id": library_id}).json()["total_articles"] == 2
    assert client.get("/api/statistics").json()["total_articles"] == 0
    assert client.post("/api/coverage", json={"library_id": library_id, "topics": []}).json()["total_articles"] == 2
    assert client.post("/api/screening", json={"library_id": library_id, "action": "exclude", "reason": "duplicate", "items": [{"article_id": "1", "source": "pubmed"}]}, headers=headers).status_code == 200
    excluded = client.get("/api/screening/excluded", params={"library_id": library_id}).json()["items"]
    assert [(item["article_id"], item["reason"]) for item in excluded] == [("1", "duplicate")]


@pytest.mark.parametrize("path,method", [
    ("/api/resolve-duplicates", "post"), ("/api/coverage", "post"),
    ("/api/statistics", "get"), ("/api/screening/excluded", "get"),
])
def test_collection_tools_reject_foreign_library(client_with_library, path, method):
    client, _uid, _library_id = client_with_library
    headers = {"X-CSRF-Token": client.cookies.get("csrf_token")}
    foreign = "00000000-0000-0000-0000-000000000000"
    response = (client.post(path, json={"library_id": foreign, "preview": True}, headers=headers)
                if method == "post" else client.get(path, params={"library_id": foreign}))
    assert response.status_code == 400


def test_duplicate_preview_still_requires_auth_and_csrf(client_with_library):
    client, _uid, lib_id = client_with_library
    assert client.post("/api/resolve-duplicates", json={"library_id": lib_id, "preview": True}).status_code == 403
    client.cookies.clear()
    assert client.post("/api/resolve-duplicates", json={"preview": True}).status_code == 401
