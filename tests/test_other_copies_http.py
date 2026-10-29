"""HTTP contract for other listed copies of a starred paper."""

from __future__ import annotations

import os
import pathlib
import shutil

import pytest
from conftest import TEST_PASSWORD

from app import core

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

for _dep in ("fastapi", "httpx", "Bio", "sklearn", "slowapi", "jwt",
             "bcrypt", "multipart", "requests", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib
    main = importlib.import_module("app.main")
    from app.storage.user_db import UserDatabase

    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    return main


def _register(client, username="copyuser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD,
              "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _uid(username="copyuser"):
    row = core.user_db.get_by_username(username)
    return row["id"]


def _paper(article_id, source, **kwargs):
    article = {
        "article_id": article_id,
        "source": source,
        "title": kwargs.pop("title", "Closed paper"),
        "abstract": kwargs.pop("abstract", "An abstract about copies."),
        "year": "2020",
        "authors": [],
        "journal": "J",
    }
    article.update(kwargs)
    return article


def _seed_closed(username="copyuser"):
    uid = _uid(username)
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.insert_articles([
            _paper(
                "10.1234/closed", "crossref",
                doi="10.1234/closed",
                oa_status=None,
                _extra={"locations": [
                    {
                        "url": "https://api.elsevier.com/content/article/doi/10",
                        "kind": "text-mining",
                        "via": "crossref",
                    },
                    {
                        "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
                        "host": "PubMed Central",
                        "via": "openalex",
                    },
                ]},
            ),
            _paper(
                "W-peer", "openalex",
                doi="10.1234/closed",
                oa_status="gold",
                best_oa_url="https://zenodo.org/record/9/files/a.pdf",
                host_name="Zenodo",
                _extra={"locations": [{
                    "url": "https://zenodo.org/record/9/files/a.pdf",
                    "host": "Zenodo",
                    "via": "zenodo",
                }]},
            ),
            _paper("legacy", "pubmed", title="Old row", abstract="No extra."),
        ], dedupe=False)
        pipe.db.upsert_note("10.1234/closed", "crossref", starred=True)
        pipe.db.upsert_note("legacy", "pubmed", starred=True)
    finally:
        core.release_pipeline(uid)


def _post_copies(client, headers, articles, **extra):
    return client.post(
        "/api/articles/other-copies",
        json={"articles": articles, **extra},
        headers=headers,
    )


def test_other_copies_require_auth(app_module):
    c = TestClient(app_module.app)
    r = c.post("/api/articles/other-copies", json={"articles": [
        {"article_id": "1", "source": "pubmed"},
    ]})
    assert r.status_code == 401


def test_other_copies_require_csrf(app_module):
    c = TestClient(app_module.app)
    _register(c)
    r = c.post("/api/articles/other-copies", json={"articles": [
        {"article_id": "1", "source": "pubmed"},
    ]})
    assert r.status_code == 403


def test_peer_doi_matches_after_normalize(app_module):
    c = TestClient(app_module.app)
    headers = _register(c, "doicase")
    uid = _uid("doicase")
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.insert_articles([
            _paper(
                "10.1234/abc", "crossref",
                doi="10.1234/abc",
                oa_status=None,
            ),
            _paper(
                "W-peer", "openalex",
                doi="https://doi.org/10.1234/ABC",
                oa_status="gold",
                best_oa_url="https://zenodo.org/record/9/files/a.pdf",
                host_name="Zenodo",
                _extra={"locations": [{
                    "url": "https://zenodo.org/record/9/files/a.pdf",
                    "host": "Zenodo",
                    "via": "zenodo",
                }]},
            ),
            _paper(
                "other-doi", "pubmed",
                doi="10.9999/unrelated",
                oa_status="gold",
                best_oa_url="https://example.org/unrelated.pdf",
                host_name="Other",
            ),
        ], dedupe=False)
        pipe.db.upsert_note("10.1234/abc", "crossref", starred=True)
        stored = pipe.db.conn.execute(
            "SELECT doi FROM articles WHERE article_id = ? AND source = ?",
            ("W-peer", "openalex"),
        ).fetchone()
        assert stored[0] == "https://doi.org/10.1234/ABC"
    finally:
        core.release_pipeline(uid)
    r = _post_copies(c, headers, [
        {"article_id": "10.1234/abc", "source": "crossref"},
    ])
    assert r.status_code == 200, r.text
    rows = r.json()["articles"]
    assert len(rows) == 1
    copies = rows[0]["copies"]
    urls = [item["url"] for item in copies]
    assert "https://zenodo.org/record/9/files/a.pdf" in urls
    assert "https://example.org/unrelated.pdf" not in urls
    zenodo = next(item for item in copies if "zenodo" in item["url"])
    assert zenodo["where"] == "Zenodo"
    assert zenodo["open_listed"] is True


def test_starred_none_listed_returns_other_copies(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_closed()
    r = _post_copies(c, headers, [
        {"article_id": "10.1234/closed", "source": "crossref"},
        {"article_id": "W-peer", "source": "openalex"},
        {"article_id": "legacy", "source": "pubmed"},
    ])
    assert r.status_code == 200, r.text
    rows = r.json()["articles"]
    by_id = {row["article_id"]: row for row in rows}
    assert "W-peer" not in by_id
    assert "legacy" not in by_id
    copies = by_id["10.1234/closed"]["copies"]
    urls = [item["url"] for item in copies]
    assert "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/" in urls
    assert "https://zenodo.org/record/9/files/a.pdf" in urls
    assert "https://api.elsevier.com/content/article/doi/10" not in urls
    pmc = next(item for item in copies if "PMC1" in item["url"])
    assert pmc["where"] == "PubMed Central"
    zenodo = next(item for item in copies if "zenodo" in item["url"])
    assert zenodo["where"] == "Zenodo"
    assert zenodo["open_listed"] is True


def test_unstarred_card_is_omitted(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_closed()
    uid = _uid()
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.upsert_note("10.1234/closed", "crossref", starred=False)
    finally:
        core.release_pipeline(uid)
    r = _post_copies(c, headers, [
        {"article_id": "10.1234/closed", "source": "crossref"},
    ])
    assert r.status_code == 200, r.text
    assert r.json()["articles"] == []


def test_foreign_library_is_400(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_closed()
    c2 = TestClient(app_module.app)
    _register(c2, "copystranger")
    other_id = c2.get("/api/libraries").json()["active_id"]
    r = _post_copies(
        c, headers,
        [{"article_id": "10.1234/closed", "source": "crossref"}],
        library_id=other_id,
    )
    assert r.status_code == 400


def test_search_payload_does_not_include_other_copies(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed_closed()
    uid = _uid()
    pipe = core.get_pipeline(uid)
    try:
        import numpy as np
        arts = pipe.db.get_all_articles()
        emb = {}
        for a in arts:
            v = np.ones(8, dtype=np.float32)
            v /= float(np.linalg.norm(v) or 1)
            emb[(a["article_id"], a["source"])] = v
        pipe.db.insert_embeddings(emb, model_name="general")
        pipe.embedding_engine.embed_query = (  # type: ignore[method-assign]
            lambda _t: np.ones(8, dtype=np.float32) / (8.0 ** 0.5)
        )
    finally:
        core.release_pipeline(uid)
    r = c.post("/api/search", json={"query_text": "copies", "top_k": 10},
               headers=headers)
    assert r.status_code == 200, r.text
    for row in r.json()["results"]:
        assert "copies" not in row
        assert "_extra" not in row
