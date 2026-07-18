"""
HTTP integration tests for multi-library APIs (auth + CSRF + isolation).
"""

import os
import pathlib

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "plotly", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient


class _FakeFetcher:
    SOURCE_NAME = "pubmed"

    def __init__(self, email=None, **kwargs):
        self.email = email

    def search_and_fetch(self, query, max_results=200):
        return [{
            "article_id": f"fake-{query[:12].replace(' ', '-')}",
            "source": "pubmed",
            "title": f"Fake article about {query}",
            "abstract": "A canned abstract used for multi-library integration testing.",
            "year": "2024",
            "authors": ["Tester T"],
            "journal": "Journal of Testing",
        }]


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import shutil
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib
    import pipeline
    main = importlib.import_module("main")

    from user_db import UserDatabase
    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(main, "user_db", test_db)
    main._pipelines.clear()
    main._pipeline_refcounts.clear()
    main._all_progress.clear()
    # Clear shared in-memory rate-limit counters so suite order cannot 429 register.
    try:
        main.limiter.reset()
    except Exception:
        pass
    monkeypatch.setitem(pipeline.FETCHERS, "pubmed", _FakeFetcher)
    yield main
    test_db.conn.close()


def _register(client, username, password="tpw-fixture-0001"):
    resp = client.post(
        "/register",
        data={"username": username, "password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert client.cookies.get("access_token")
    assert client.cookies.get("csrf_token")


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _fetch(client, query="sleep"):
    return client.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": query,
            "max_results": 5,
            "email": None,
            "wait": True,
        },
        headers=_csrf(client),
    )


def test_libraries_crud_and_isolation(app_module):
    c = TestClient(app_module.app)
    _register(c, "libhttp")

    r = c.get("/api/libraries")
    assert r.status_code == 200
    data = r.json()
    assert len(data["libraries"]) == 1
    assert data["libraries"][0]["name"] == "My library"
    default_id = data["active_id"]

    assert _fetch(c, "sleep").status_code == 200
    default_count = c.get("/api/statistics").json()["total_articles"]
    assert default_count >= 1

    r = c.post("/api/libraries", json={"name": "Climate unit"}, headers=_csrf(c))
    assert r.status_code == 200
    body = r.json()
    climate_id = body["library"]["id"]
    assert body["active_id"] == climate_id
    assert c.get("/api/statistics").json()["total_articles"] == 0

    assert _fetch(c, "climate").status_code == 200
    climate_count = c.get("/api/statistics").json()["total_articles"]
    assert climate_count >= 1

    r = c.post(
        "/api/libraries/switch",
        json={"library_id": default_id},
        headers=_csrf(c),
    )
    assert r.status_code == 200
    assert r.json()["active_id"] == default_id
    assert c.get("/api/statistics").json()["total_articles"] == default_count

    r = c.post(
        "/api/libraries/switch",
        json={"library_id": climate_id},
        headers=_csrf(c),
    )
    assert r.status_code == 200
    assert c.get("/api/statistics").json()["total_articles"] == climate_count

    r = c.post("/api/libraries", json={"name": "climate unit"}, headers=_csrf(c))
    assert r.status_code == 400

    r = c.patch(
        f"/api/libraries/{climate_id}",
        json={"name": "Climate / earth"},
        headers=_csrf(c),
    )
    assert r.status_code == 200
    names = {L["name"] for L in r.json()["libraries"]}
    assert "Climate / earth" in names

    r = c.post(
        "/api/libraries/switch",
        json={"library_id": "not-real"},
        headers=_csrf(c),
    )
    assert r.status_code == 400

    r = c.post("/api/libraries", json={"name": "No CSRF"})
    assert r.status_code == 403

    r = c.delete(f"/api/libraries/{climate_id}", headers=_csrf(c))
    assert r.status_code == 200
    left = c.get("/api/libraries").json()
    assert len(left["libraries"]) == 1
    assert left["active_id"] == default_id
    assert c.get("/api/statistics").json()["total_articles"] == default_count

    r = c.delete(f"/api/libraries/{default_id}", headers=_csrf(c))
    assert r.status_code == 400


def test_max_libraries_enforced(app_module, monkeypatch):
    import libraries as lib
    monkeypatch.setattr(lib, "MAX_LIBRARIES", 3)

    c = TestClient(app_module.app)
    _register(c, "maxlib")
    # Default already counts as 1
    assert c.post(
        "/api/libraries", json={"name": "Two"}, headers=_csrf(c)
    ).status_code == 200
    assert c.post(
        "/api/libraries", json={"name": "Three"}, headers=_csrf(c)
    ).status_code == 200
    r = c.post("/api/libraries", json={"name": "Four"}, headers=_csrf(c))
    assert r.status_code == 400
    assert "At most" in r.json()["detail"]


def test_delete_library_while_in_use_conflicts(app_module):
    """Deleting a library with an active job/request must 409, not close the DB mid-write."""
    c = TestClient(app_module.app)
    _register(c, "libbusy")
    uid = app_module.user_db.get_by_username("libbusy")["id"]

    r = c.post("/api/libraries", json={"name": "Busy lib"}, headers=_csrf(c))
    assert r.status_code == 200, r.text
    lib_id = r.json()["library"]["id"]

    key = app_module.pipeline_cache_key(uid, lib_id)
    # Simulate an in-flight background job holding the pipeline reference.
    app_module._pipeline_refcounts[key] = 1
    try:
        r = c.delete(f"/api/libraries/{lib_id}", headers=_csrf(c))
        assert r.status_code == 409, r.text
        assert "in use" in r.json()["detail"]
        # Still listed: nothing was deleted.
        ids = [L["id"] for L in c.get("/api/libraries").json()["libraries"]]
        assert lib_id in ids
    finally:
        app_module._pipeline_refcounts.pop(key, None)

    # Once the reference is gone the delete succeeds.
    r = c.delete(f"/api/libraries/{lib_id}", headers=_csrf(c))
    assert r.status_code == 200, r.text
