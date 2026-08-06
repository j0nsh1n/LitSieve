"""Guest demo mode: sample corpus only; no multi-source fetch."""

from __future__ import annotations

from pathlib import Path

from conftest import route_paths
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def test_guest_route_exists():
    paths = route_paths(app)
    assert "/guest" in paths


def test_guest_username_reserved_for_registration():
    from app.auth import validate_new_username

    assert validate_new_username("guest_abc") is not None
    assert "reserved" in (validate_new_username("guest_abc") or "").lower()


def test_guest_start_loads_sample_and_blocks_fetch(tmp_path, monkeypatch):
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    client = TestClient(app)
    r = client.get("/guest", follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    assert r.headers.get("location") == "/data-management"
    assert client.cookies.get("access_token")
    assert client.cookies.get("csrf_token")

    # Guest session reaches the app shell.
    page = client.get("/data-management")
    assert page.status_code == 200
    assert b"data-guest" in page.content or b"Demo mode" in page.content

    # Sample papers present.
    stats = client.get("/api/statistics")
    assert stats.status_code == 200
    body = stats.json()
    assert body.get("total_articles", 0) >= 10

    # Multi-source fetch is forbidden.
    csrf = client.cookies.get("csrf_token")
    blocked = client.post(
        "/api/fetch-articles-multi",
        json={
            "query": "climate",
            "sources": ["pubmed"],
            "max_results": 10,
            "clear_first": True,
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert blocked.status_code == 403, blocked.text
    assert blocked.json().get("guest") is True

    # Sample reload still allowed.
    ok = client.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert ok.status_code == 200, ok.text


def test_guest_cta_on_public_pages():
    landing = _read("templates", "landing.html")
    login = _read("templates", "login.html")
    assert 'href="/guest"' in landing
    assert 'href="/guest"' in login
    assert "Try the demo" in landing or "demo" in landing.lower()


def test_expired_guests_are_purged(tmp_path, monkeypatch):
    """Guests older than GUEST_MAX_AGE_MINUTES lose their account and library data."""
    from app import core
    from app.storage.libraries import user_dir
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    user = db.create_user("guest_oldone", "hash", is_guest=True)
    uid = user["id"]
    # Backdate created_at past the demo window.
    with db._lock:
        db.conn.execute(
            "UPDATE users SET created_at = datetime('now', '-45 minutes') WHERE id = ?",
            (uid,),
        )
        db.conn.commit()
    udir = user_dir(uid)
    udir.mkdir(parents=True, exist_ok=True)
    (udir / "marker.txt").write_text("demo", encoding="utf-8")

    assert db.guest_is_expired(uid, 30) is True
    n = core.purge_expired_guests(30)
    assert n == 1
    assert db.get_by_id(uid) is None
    assert not udir.exists()


def test_fresh_guest_not_expired(tmp_path, monkeypatch):
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    user = db.create_user("guest_fresh", "hash", is_guest=True)
    assert db.guest_is_expired(user["id"], 30) is False
    assert core.purge_expired_guests(30) == 0
    assert db.get_by_id(user["id"]) is not None
