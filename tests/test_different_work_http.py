"""HTTP contract for different-work suggestions."""

from __future__ import annotations

import os
import pathlib
import shutil

import numpy as np
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


def _register(client, username="diffuser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD,
              "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _uid(username="diffuser"):
    row = core.user_db.get_by_username(username)
    return row["id"]


def _paper(article_id, source, **kwargs):
    article = {
        "article_id": article_id,
        "source": source,
        "title": kwargs.pop("title", article_id),
        "abstract": kwargs.pop("abstract", "An abstract about zyptron."),
        "year": kwargs.pop("year", "2020"),
        "authors": [],
        "journal": "J",
    }
    article.update(kwargs)
    return article


def _vec(*values):
    return np.array(values, dtype=np.float32)


def _seed(username="diffuser"):
    uid = _uid(username)
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.insert_articles([
            _paper(
                "seed", "crossref", title="Closed seed",
                year="2008", work_type="journal-article", doi="10.1234/seed",
            ),
            _paper(
                "open-a", "openalex", title="Open zyptron review",
                year="2019", work_type="review-article", doi="10.1234/a",
                oa_status="gold", best_oa_url="https://example.org/a.pdf",
            ),
            _paper(
                "open-b", "doaj", title="Open zyptron notes",
                year="2018", doi="10.1234/b",
                oa_status="gold", best_oa_url="https://example.org/b.pdf",
            ),
            _paper("legacy", "pubmed", title="Old row", abstract="No extra."),
        ], dedupe=False)
        pipe.db.insert_embeddings(
            {
                ("seed", "crossref"): _vec(1.0, 0.0),
                ("open-a", "openalex"): _vec(0.95, 0.1),
                ("open-b", "doaj"): _vec(0.85, 0.2),
            },
            model_name="general",
        )
        pipe.db.upsert_note("seed", "crossref", starred=True)
        pipe.db.upsert_note("legacy", "pubmed", starred=True)
        pipe.embedding_engine.embed_query = (  # type: ignore[method-assign]
            lambda _t: _vec(1.0, 0.0)
        )
        pipe.invalidate_corpus_cache()
    finally:
        core.release_pipeline(uid)


def _post(client, headers, articles, **extra):
    return client.post(
        "/api/articles/different-work",
        json={"articles": articles, **extra},
        headers=headers,
    )


def test_different_work_require_auth(app_module):
    c = TestClient(app_module.app)
    r = c.post("/api/articles/different-work", json={"articles": [
        {"article_id": "1", "source": "pubmed"},
    ]})
    assert r.status_code == 401


def test_different_work_require_csrf(app_module):
    c = TestClient(app_module.app)
    _register(c)
    r = c.post("/api/articles/different-work", json={"articles": [
        {"article_id": "1", "source": "pubmed"},
    ]})
    assert r.status_code == 403


def test_starred_none_listed_returns_suggestions(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed()
    r = _post(c, headers, [
        {"article_id": "seed", "source": "crossref"},
    ])
    assert r.status_code == 200, r.text
    rows = r.json()["articles"]
    by_id = {row["article_id"]: row for row in rows}
    assert list(by_id) == ["seed"]
    suggestions = by_id["seed"]["suggestions"]
    assert suggestions
    assert suggestions[0]["url"] == "https://example.org/a.pdf"
    assert suggestions[0]["title"] == "Open zyptron review"
    assert "2019 vs 2008" in suggestions[0]["difference"]
    assert "review article vs journal article" in suggestions[0]["difference"]
    assert all("free" not in item["difference"].lower() for item in suggestions)
    assert all(item["url"].startswith("https://") for item in suggestions)


def test_unstarred_card_is_omitted(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed()
    uid = _uid()
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.upsert_note("seed", "crossref", starred=False)
    finally:
        core.release_pipeline(uid)
    r = _post(c, headers, [{"article_id": "seed", "source": "crossref"}])
    assert r.status_code == 200, r.text
    assert r.json()["articles"] == []


def test_foreign_library_is_400(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed()
    c2 = TestClient(app_module.app)
    _register(c2, "diffstranger")
    other_id = c2.get("/api/libraries").json()["active_id"]
    r = _post(
        c, headers,
        [{"article_id": "seed", "source": "crossref"}],
        library_id=other_id,
    )
    assert r.status_code == 400


def test_two_seeds_are_422(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    r = _post(c, headers, [
        {"article_id": "seed", "source": "crossref"},
        {"article_id": "open-a", "source": "openalex"},
    ])
    assert r.status_code == 422


def test_question_over_1000_chars_is_422(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    r = _post(
        c, headers,
        [{"article_id": "seed", "source": "crossref"}],
        query_text="x" * 1001,
    )
    assert r.status_code == 422


def test_filter_list_over_50_is_422(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    seed = [{"article_id": "seed", "source": "crossref"}]
    too_many = ["pubmed"] * 51
    r = _post(c, headers, seed, source_filter=too_many)
    assert r.status_code == 422
    r = _post(c, headers, seed, cluster_filter=list(range(51)))
    assert r.status_code == 422
    r = _post(c, headers, seed, work_type_filter=["journal-article"] * 51)
    assert r.status_code == 422


def test_search_payload_does_not_include_suggestions(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed()
    r = c.post("/api/search", json={"query_text": "zyptron", "top_k": 10},
               headers=headers)
    assert r.status_code == 200, r.text
    for row in r.json()["results"]:
        assert "suggestions" not in row
        assert "_extra" not in row
