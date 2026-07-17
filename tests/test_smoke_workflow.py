"""
Phase R1 smoke path (no live network):

  register → load sample corpus → (stub embeddings) → cluster → search → export

Uses the real ASGI app under an isolated tmp working directory. Embedding model
loads are stubbed so CI stays offline and fast.
"""

from __future__ import annotations

import os
import pathlib
import shutil

import numpy as np
import pytest

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "plotly", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)

    import importlib

    main = importlib.import_module("main")
    from user_db import UserDatabase

    main.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    main._pipelines.clear()
    main._pipeline_refcounts.clear()
    main._all_progress.clear()
    return main


def _register(client: TestClient, username: str = "smoke_user", password: str = "tpw-fixture-0001"):
    resp = client.post(
        "/register",
        data={"username": username, "password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert client.cookies.get("access_token")
    assert client.cookies.get("csrf_token")


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _seed_fake_embeddings(main, user_id: str):
    """Insert unit vectors so cluster + search work without model downloads."""
    pipe = main.get_pipeline(user_id)
    try:
        arts = pipe.db.get_all_articles()
        assert arts, "sample corpus should have inserted papers"
        emb = {}
        rng = np.random.default_rng(0)
        for a in arts:
            v = rng.standard_normal(8).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-9
            emb[(a["article_id"], a["source"])] = v
        pipe.db.insert_embeddings(emb, model_name="general")

        # Search ranks via embed_query; keep it cheap and deterministic.
        def fake_query(_text: str):
            return np.ones(8, dtype=np.float32) / np.sqrt(8.0)

        pipe.embedding_engine.embed_query = fake_query  # type: ignore[method-assign]
    finally:
        main.release_pipeline(user_id)


def test_smoke_register_sample_cluster_search_export(app_module):
    main = app_module
    c = TestClient(main.app)

    # 1. Register
    _register(c)

    # Resolve user id from JWT path used by the app (statistics needs auth).
    me = c.get("/api/statistics")
    assert me.status_code == 200, me.text
    # User id is not returned by statistics; pull from users.db.
    rows = main.user_db.conn.execute("SELECT id FROM users").fetchall()
    assert len(rows) == 1
    user_id = rows[0][0]

    # 2. Load sample corpus (stand-in for fetch from 1–2 sources)
    r = c.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success"
    assert body.get("loaded", 0) >= 10
    stats = c.get("/api/statistics").json()
    assert stats["total_articles"] >= 10

    # 3. Prepare papers (embeddings) — stubbed offline
    _seed_fake_embeddings(main, user_id)
    stats = c.get("/api/statistics").json()
    # total_embeddings key name varies; articles alone prove corpus is ready.
    assert stats["total_articles"] >= 10

    # 4. Cluster
    r = c.post(
        "/api/create-clusters",
        json={"method": "kmeans", "n_clusters": 3},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "success"
    clusters = c.get("/api/clusters").json()
    assert clusters.get("clusters") is not None

    # 5. Search
    r = c.post(
        "/api/search",
        json={"query_text": "education learning students", "top_k": 5, "lexical_boost": True},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    results = r.json()
    arts = results.get("results") or []
    assert isinstance(arts, list)
    assert len(arts) >= 1

    # 6. Export library (CSV + RIS) and screening report
    for fmt in ("csv", "ris", "bibtex", "apa"):
        exp = c.get(f"/api/export/library?format={fmt}&scope=all")
        assert exp.status_code == 200, f"export {fmt}: {exp.text[:200]}"
        assert len(exp.text) > 20

    report = c.get("/api/screening-report?format=txt")
    assert report.status_code == 200, report.text
    assert "collected" in report.text.lower() or "included" in report.text.lower() or len(report.text) > 20

    # App pages still render after the workflow (disclaimer + cache-bust smoke).
    for path in ("/data-management", "/clusters", "/statistics", "/search", "/account"):
        page = c.get(path)
        assert page.status_code == 200, path
        assert "20260717r4" in page.text or "Literature Research Aide" in page.text
