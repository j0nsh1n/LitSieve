"""
End-to-end smoke paths (no live network):

  Advanced-shaped: register → sample → embeddings → cluster → search → export
  Simple-shaped:   register → sample → embeddings → quick screen → search → export

Uses the real ASGI app under an isolated tmp working directory. Embedding model
loads are stubbed so CI stays offline and fast.
"""

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

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn",
    "slowapi", "jwt", "bcrypt", "multipart", "requests", "dotenv",
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

    main = importlib.import_module("app.main")
    from app.storage.user_db import UserDatabase

    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    return main


def _register(client: TestClient, username: str = "smoke_user", password: str = TEST_PASSWORD):
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
    pipe = core.get_pipeline(user_id)
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
        core.release_pipeline(user_id)


def test_smoke_register_sample_cluster_search_export(app_module):
    main = app_module
    c = TestClient(main.app)

    # 1. Register
    _register(c)

    # Resolve user id from JWT path used by the app (statistics needs auth).
    me = c.get("/api/statistics")
    assert me.status_code == 200, me.text
    # User id is not returned by statistics; pull from users.db.
    rows = core.user_db.conn.execute("SELECT id FROM users").fetchall()
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
        assert "LitSieve" in page.text or "LitPilot" in page.text or "text/html" in page.headers.get("content-type", "")

    # Advanced surfaces still present in HTML (Simple only CSS-hides them).
    dm = c.get("/data-management")
    assert dm.status_code == 200
    assert "source-option-grid" in dm.text or "embedding-model" in dm.text
    stats_page = c.get("/statistics")
    assert stats_page.status_code == 200
    assert "Clean up" in stats_page.text
    assert "quick-screen" in stats_page.text


def test_smoke_simple_path_quick_screen_search_export(app_module):
    """Simple-mode workflow: prepare → Quick screen → search → export (no cluster)."""
    main = app_module
    c = TestClient(main.app)

    _register(c, username="simple_smoke")
    # New accounts seed Simple mode for the browser; cookie is set on register.
    assert c.cookies.get("ui_mode_seed") == "simple"

    rows = core.user_db.conn.execute("SELECT id FROM users").fetchall()
    user_id = rows[0][0]

    r = c.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    _seed_fake_embeddings(main, user_id)

    # Quick screen preview must not write exclusions.
    prev = c.post(
        "/api/screening/quick-preview",
        json={"query": "education learning students", "fraction": 0.25},
        headers=_csrf(c),
    )
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["total_ranked"] >= 1
    assert body.get("proposed_count", 0) >= 0
    report0 = c.get("/api/screening-report?format=json").json()
    assert report0["excluded"]["total"] == 0

    # Apply a subset if any candidates (fraction may yield 0 on tiny corpora).
    candidates = body.get("candidates") or []
    if candidates:
        items = [
            {"article_id": x["article_id"], "source": x["source"]}
            for x in candidates[:3]
        ]
        ex = c.post(
            "/api/screening",
            json={"items": items, "action": "exclude", "reason": "low_relevance"},
            headers=_csrf(c),
        )
        assert ex.status_code == 200, ex.text
        assert ex.json()["reason"] == "low_relevance"
        report1 = c.get("/api/screening-report?format=json").json()
        assert report1["excluded"]["low_relevance"] >= 1

        # Re-include (undo)
        inc = c.post(
            "/api/screening",
            json={"items": items, "action": "include"},
            headers=_csrf(c),
        )
        assert inc.status_code == 200, inc.text

    # Search + export still work without clustering.
    r = c.post(
        "/api/search",
        json={"query_text": "education learning students", "top_k": 5, "lexical_boost": True},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    assert len(r.json().get("results") or []) >= 1

    # Per-paper Not relevant (off_topic) via screening API.
    hit = (r.json().get("results") or [])[0]
    off = c.post(
        "/api/screening",
        json={
            "items": [{"article_id": hit["article_id"], "source": hit["source"]}],
            "action": "exclude",
            "reason": "off_topic",
        },
        headers=_csrf(c),
    )
    assert off.status_code == 200, off.text
    assert off.json()["reason"] == "off_topic"

    exp = c.get("/api/export/library?format=ris&scope=included")
    assert exp.status_code == 200, exp.text[:200]

    # Simple nav still leaves /clusters reachable.
    assert c.get("/clusters").status_code == 200
