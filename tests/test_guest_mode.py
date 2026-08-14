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
    assert r.headers.get("location") == "/search"
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


def test_guest_end_demo_is_guarded_and_tappable():
    """End demo is a secondary 44px control, not an inline link next to Register."""
    base = _read("templates", "base.html")
    assert 'class="guest-banner-actions"' in base or "guest-banner-actions" in base
    assert "guest-banner-register" in base
    assert "guest-banner-logout" in base
    assert 'href="/register"' in base
    assert 'href="/logout"' in base
    css = _read("static", "css", "style.css")
    assert ".guest-banner-actions" in css
    assert ".guest-banner-actions .btn" in css
    common = _read("static", "js", "common.js")
    start = common.index("querySelector('.guest-banner-logout')")
    handler = common[start : start + 700]
    assert "addEventListener('click'" in handler
    assert "preventDefault" in handler
    assert "openSiteConfirm" in handler
    assert "End this demo?" in handler
    assert "window.location.href" in handler


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


def test_guest_start_never_replaces_a_signed_in_session(tmp_path, monkeypatch):
    """POST /guest must not hijack a real account's session.

    /guest deliberately takes no CSRF token — a logged-out visitor has no
    csrf cookie yet, so requiring one would make the demo unreachable. That
    leaves a cross-site POST able to reach it, so the protection has to be the
    "already signed in" short-circuit in _start_guest_session: an existing
    session is redirected to the app instead of being swapped for a guest one.
    Without it, any page on the internet could quietly sign a student out of
    their own account and out of their saved libraries.
    """
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    client = TestClient(app)
    reg = client.post(
        "/register",
        data={
            "username": "realstudent",
            "password": "tpw-fixture-0001",
            "password_confirm": "tpw-fixture-0001",
        },
        follow_redirects=False,
    )
    assert reg.status_code == 302, reg.text
    token_before = client.cookies.get("access_token")
    assert token_before

    for call in (
        lambda: client.post("/guest", follow_redirects=False),
        lambda: client.get("/guest", follow_redirects=False),
    ):
        resp = call()
        assert resp.status_code in (302, 303), resp.text
        assert resp.headers.get("location") == "/data-management" or resp.headers.get("location") == "/search"
        # Session untouched: same token, and still the real account.
        assert client.cookies.get("access_token") == token_before
        who = client.get("/api/statistics")
        assert who.status_code == 200

    # No guest account was created as a side effect.
    rows = db.conn.execute(
        "SELECT username FROM users WHERE username LIKE 'guest_%'"
    ).fetchall()
    assert rows == [], f"signed-in request created a guest account: {rows}"
