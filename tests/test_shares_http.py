"""HTTP integration tests for share create / preview / join / revoke."""

import os
import pathlib

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest

from app import core

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn",
    "slowapi", "jwt", "bcrypt", "multipart", "requests", "dotenv",
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
            "abstract": "A canned abstract used for share-library integration testing.",
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

    from app.services import pipeline
    main = importlib.import_module("app.main")

    from app.storage.user_db import UserDatabase
    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", test_db)
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
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


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _client_for(app_module, username):
    c = TestClient(app_module.app)
    _register(c, username)
    return c


def test_share_create_preview_join_revoke(app_module):
    teacher = _client_for(app_module, "shareteach")
    student = _client_for(app_module, "sharestud")

    # Seed teacher library via fetch
    r = teacher.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "sleep",
            "max_results": 5,
            "email": None,
            "wait": True,
        },
        headers=_csrf(teacher),
    )
    assert r.status_code == 200, r.text
    t_count = teacher.get("/api/statistics").json()["total_articles"]
    assert t_count >= 1

    # CSRF required
    r = teacher.post("/api/shares", json={"expires_days": 14})
    assert r.status_code == 403

    r = teacher.post(
        "/api/shares",
        json={"expires_days": 14, "include_embeddings": True, "max_uses": 10},
        headers=_csrf(teacher),
    )
    assert r.status_code == 200, r.text
    share = r.json()["share"]
    code = share["code"]
    assert "-" in code
    assert share["join_path"] == f"/join?code={code}"

    listed = teacher.get("/api/shares").json()["shares"]
    assert any(s["code"] == code for s in listed)

    # Preview as student
    prev = student.get(f"/api/shares/preview?code={code}")
    assert prev.status_code == 200, prev.text
    body = prev.json()
    assert body["can_join"] is True
    assert body["article_count"] == t_count
    assert body["owner_username"] == "shareteach"

    # Join
    r = student.post(
        "/api/shares/join",
        json={"code": code},
        headers=_csrf(student),
    )
    assert r.status_code == 200, r.text
    joined = r.json()
    assert joined["counts"]["articles"] == t_count
    assert joined["library"]["name"]
    assert student.get("/api/statistics").json()["total_articles"] == t_count

    # Re-join blocked
    r = student.post(
        "/api/shares/join",
        json={"code": code},
        headers=_csrf(student),
    )
    assert r.status_code == 400
    assert "already" in r.json()["detail"].lower()

    # Teacher corpus unchanged after student activity (isolation)
    assert teacher.get("/api/statistics").json()["total_articles"] == t_count

    # Revoke
    r = teacher.delete(f"/api/shares/{share['id']}", headers=_csrf(teacher))
    assert r.status_code == 200

    other = _client_for(app_module, "sharestud2")
    r = other.post(
        "/api/shares/join",
        json={"code": code},
        headers=_csrf(other),
    )
    assert r.status_code == 400
    assert "revoked" in r.json()["detail"].lower()


def test_join_page_requires_auth(app_module):
    c = TestClient(app_module.app)
    r = c.get("/join?code=ABCD-EFGH", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers.get("location", "")
    assert "next=" in r.headers.get("location", "")


def test_cannot_share_others_library_id(app_module):
    teacher = _client_for(app_module, "ownlib")
    other = _client_for(app_module, "otherlib")
    other_lib = other.get("/api/libraries").json()["active_id"]
    r = teacher.post(
        "/api/shares",
        json={"library_id": other_lib, "expires_days": 7},
        headers=_csrf(teacher),
    )
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()
