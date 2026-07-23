"""
Integration test: per-user account isolation through the real ASGI app.

Drives register -> authenticated fetch -> statistics for two separate accounts
to prove each user only ever sees their own articles. Heavy work is stubbed:

  * A fake fetcher returns one canned article, so there is NO network I/O.
  * Embeddings/search are intentionally not exercised here (fetch + statistics
    don't need them), so no embedding models are downloaded.

The app is run against an isolated working directory so users.db and the
per-user ``user_data/<uid>/`` trees are created under tmp_path, never the repo.
"""

import os
import pathlib

# Must be set BEFORE the app is imported:
#   SECRET_KEY  -> lets auth.py mint/verify tokens
#   DEBUG=true  -> auth cookies are NOT marked "Secure", so the plain-http test
#                  client will actually store and resend them (otherwise login
#                  silently loops, exactly like local http://localhost).
os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest

# Skip the whole module cleanly if the app's runtime deps aren't installed.
for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient


class _FakeFetcher:
    """Stand-in fetcher returning one canned article with no network access."""

    SOURCE_NAME = "pubmed"

    def __init__(self, email=None, **kwargs):
        self.email = email

    def search_and_fetch(self, query, max_results=200):
        return [{
            "article_id": "fake-1",
            "source": "pubmed",
            "title": f"Fake article about {query}",
            "abstract": "A canned abstract used for integration testing.",
            "year": "2024",
            "authors": ["Tester T"],
            "journal": "Journal of Testing",
        }]


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    # The app mounts static/ and renders templates/ by path relative to the CWD.
    # Copy both into the tmp working dir so StaticFiles mounts and template
    # rendering (e.g. the login error page) work, while users.db / user_data stay
    # isolated under tmp.
    import shutil
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)

    import importlib

    from app.services import pipeline
    main = importlib.import_module("app.main")

    # Fresh account DB + cleared per-user caches for a clean slate every run.
    from app.storage.user_db import UserDatabase
    main.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    main._pipelines.clear()
    main._pipeline_refcounts.clear()
    main._all_progress.clear()

    # Canned fetcher so /api/fetch-articles-multi does zero network I/O.
    monkeypatch.setitem(pipeline.FETCHERS, "pubmed", _FakeFetcher)

    return main


def _register(client, username, password="tpw-fixture-0001"):
    resp = client.post(
        "/register",
        data={"username": username, "password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    # Both auth cookies should now be in the client's jar.
    assert client.cookies.get("access_token")
    assert client.cookies.get("csrf_token")


def _fetch(client, query="diabetes", wait=True):
    # State-changing endpoint: send the CSRF header matching the cookie.
    # wait=True keeps the historical synchronous response shape for assertions.
    csrf = client.cookies.get("csrf_token")
    return client.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": query,
            "max_results": 5,
            "email": None,
            "wait": wait,
        },
        headers={"X-CSRF-Token": csrf},
    )


def test_per_user_account_isolation(app_module):
    main = app_module
    alice = TestClient(main.app)
    bob = TestClient(main.app)

    _register(alice, "alice")
    _register(bob, "bob")

    # Alice fetches an article into her own database.
    r = _fetch(alice)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_fetched"] == 1
    assert body["by_source"]["pubmed"] == 1
    assert body["errors"] == {}

    # Alice sees her article; Bob (separate account) sees nothing.
    alice_stats = alice.get("/api/statistics").json()
    bob_stats = bob.get("/api/statistics").json()
    assert alice_stats["total_articles"] == 1
    assert bob_stats["total_articles"] == 0


def test_unauthenticated_requests_are_rejected(app_module):
    main = app_module
    anon = TestClient(main.app)

    # API rejects with 401...
    assert anon.get("/api/statistics").status_code == 401

    # ...and protected pages redirect to /login instead of rendering.
    resp = anon.get("/data-management", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login")


def test_csrf_required_for_state_change(app_module):
    main = app_module
    alice = TestClient(main.app)
    _register(alice, "alice")

    # Same request as _fetch but WITHOUT the X-CSRF-Token header must be refused.
    resp = alice.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "x",
            "max_results": 5,
            "email": None,
            "wait": True,
        },
    )
    assert resp.status_code == 403


def test_login_after_register(app_module):
    main = app_module
    c = TestClient(main.app)
    _register(c, "carol")

    # Simulate a fresh browser, then log back in with the same credentials.
    c.cookies.clear()
    resp = c.post(
        "/login",
        data={"username": "carol", "password": "tpw-fixture-0001"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert c.cookies.get("access_token")
    # The restored session can read its own (empty) statistics.
    assert c.get("/api/statistics").json()["total_articles"] == 0


def test_delete_account_flow(app_module):
    main = app_module
    c = TestClient(main.app)
    _register(c, "erin")

    uid = main.user_db.get_by_username("erin")["id"]

    # Touch an authed endpoint so the per-user data directory gets created.
    assert c.get("/api/statistics").status_code == 200
    assert os.path.isdir(os.path.join("user_data", uid))

    csrf = c.cookies.get("csrf_token")

    # Wrong password must NOT delete the account.
    r = c.post("/api/delete-account", json={"password": "WRONG-password"},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 400
    assert main.user_db.get_by_username("erin") is not None

    # Missing CSRF header must be refused.
    r = c.post("/api/delete-account", json={"password": "tpw-fixture-0001"})
    assert r.status_code == 403

    # Correct password deletes the account, its data dir, and clears the session.
    r = c.post("/api/delete-account", json={"password": "tpw-fixture-0001"},
               headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200
    assert main.user_db.get_by_username("erin") is None
    assert not os.path.isdir(os.path.join("user_data", uid))

    # The credentials no longer work.
    c.cookies.clear()
    r = c.post("/login", data={"username": "erin", "password": "tpw-fixture-0001"},
               follow_redirects=False)
    assert r.status_code == 400


def test_wrong_password_is_rejected(app_module):
    main = app_module
    c = TestClient(main.app)
    _register(c, "dave")
    c.cookies.clear()

    resp = c.post(
        "/login",
        data={"username": "dave", "password": "WRONG-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert not c.cookies.get("access_token")


def test_change_password_revokes_other_sessions(app_module):
    main = app_module
    first = TestClient(main.app)
    second = TestClient(main.app)
    _register(first, "pwchanger")

    # Second client logs in with the same credentials (separate session cookies).
    r = second.post(
        "/login",
        data={"username": "pwchanger", "password": "tpw-fixture-0001"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert second.get("/api/statistics").status_code == 200
    assert first.get("/api/statistics").status_code == 200

    csrf = first.cookies.get("csrf_token")
    r = first.post(
        "/api/change-password",
        json={
            "current_password": "tpw-fixture-0001",
            "new_password": "tpw-fixture-0002",
            "new_password_confirm": "tpw-fixture-0002",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200, r.text

    # First client got a fresh token and still works; second is revoked.
    assert first.get("/api/statistics").status_code == 200
    assert second.get("/api/statistics").status_code == 401

    # New password works; old does not.
    second.cookies.clear()
    assert second.post(
        "/login",
        data={"username": "pwchanger", "password": "tpw-fixture-0001"},
        follow_redirects=False,
    ).status_code == 400
    assert second.post(
        "/login",
        data={"username": "pwchanger", "password": "tpw-fixture-0002"},
        follow_redirects=False,
    ).status_code == 302

    # bcrypt 72-byte limit: 100-char password rejected.
    csrf = first.cookies.get("csrf_token")
    r = first.post(
        "/api/change-password",
        json={
            "current_password": "tpw-fixture-0002",
            "new_password": "x" * 100,
            "new_password_confirm": "x" * 100,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 400


def test_fetch_async_job_and_conflict(app_module):
    """POST without wait → 202; poll progress for result; active slot → 409."""
    import time

    main = app_module
    c = TestClient(main.app)
    _register(c, "jobuser")
    csrf = c.cookies.get("csrf_token")
    uid = main.user_db.get_by_username("jobuser")["id"]

    # Force an in-flight job so the next start is rejected (deterministic under TestClient).
    with main._progress_lock:
        main._ensure_progress(uid)["fetch"].update(
            {"active": True, "done": 0, "total": 1, "result": None, "error": None}
        )

    r_conflict = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "blocked",
            "max_results": 5,
            "email": None,
            "wait": False,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r_conflict.status_code == 409
    assert "already running" in r_conflict.json()["detail"].lower()

    with main._progress_lock:
        main._ensure_progress(uid)["fetch"]["active"] = False

    r = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "async",
            "max_results": 5,
            "email": None,
            "wait": False,
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "started"

    result = None
    err = None
    deadline = time.time() + 5
    while time.time() < deadline:
        prog = c.get("/api/progress").json()
        fetch = prog.get("fetch") or {}
        if not fetch.get("active"):
            result = fetch.get("result")
            err = fetch.get("error")
            break
        time.sleep(0.05)

    assert result is not None, f"job never completed (error={err!r})"
    assert result.get("total_fetched") == 1
    # Pipeline refcount released after job done callback.
    assert main._pipeline_refcounts.get(uid, 0) == 0

