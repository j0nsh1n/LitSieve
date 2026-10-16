"""Phase 17: lockout, rate-limit keys, login CSRF, registration rules."""

from __future__ import annotations

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.storage.user_db import UserDatabase


def _db(tmp_path, monkeypatch) -> UserDatabase:
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    return db


def _register(username, client=None):
    c = client or TestClient(app)
    r = c.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    return c


def _wrong_logins(n, username="stu"):
    c = TestClient(app)
    for _ in range(n):
        c.post("/login", data={"username": username, "password": "wrong-password"}, follow_redirects=False)


def test_an_expired_lock_does_not_relock_on_the_next_mistake(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _register("stu")
    _wrong_logins(db.LOCKOUT_AFTER)
    assert db.is_locked(db.get_by_username("stu"))
    db.conn.execute("UPDATE users SET locked_until = '2000-01-01 00:00:00'")
    db.conn.commit()
    _wrong_logins(1)
    rec = db.get_by_username("stu")
    assert not db.is_locked(rec)
    assert rec["failed_logins"] == 1


def test_old_mistakes_do_not_count_toward_a_lock(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _register("stu")
    _wrong_logins(db.LOCKOUT_AFTER - 1)
    db.conn.execute(
        "UPDATE auth_events SET created_at = '2000-01-01 00:00:00' WHERE kind = 'login_fail'"
    )
    db.conn.commit()
    _wrong_logins(1)
    rec = db.get_by_username("stu")
    assert not db.is_locked(rec)
    assert rec["failed_logins"] == 1


def test_a_lock_keeps_sessions_that_are_already_signed_in(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    signed_in = _register("stu")
    _wrong_logins(db.LOCKOUT_AFTER)
    assert db.is_locked(db.get_by_username("stu"))
    assert signed_in.get("/api/libraries").status_code == 200
    r = TestClient(app).post(
        "/login", data={"username": "stu", "password": TEST_PASSWORD}, follow_redirects=False,
    )
    assert r.status_code == 400


def _request_with(token):
    from starlette.requests import Request

    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(b"cookie", f"access_token={token}".encode())],
        "client": ("203.0.113.9", 4000),
    })


def test_a_purged_guest_token_gets_no_private_rate_limit_bucket(tmp_path, monkeypatch):
    import jwt as pyjwt

    db = _db(tmp_path, monkeypatch)
    guest = TestClient(app)
    assert guest.post("/guest", follow_redirects=False).status_code in (302, 303)
    token = guest.cookies.get("access_token")
    claims = pyjwt.decode(token, options={"verify_signature": False})
    uid = claims["user_id"]
    from datetime import datetime, timezone
    lifetime = claims["exp"] - datetime.now(timezone.utc).timestamp()
    assert lifetime <= core.GUEST_MAX_AGE_MINUTES * 60 + 5
    assert core.rate_limit_key(_request_with(token)) == f"user:{uid}"
    core.destroy_guest_account(uid)
    assert db.get_by_id(uid) is None
    assert core.rate_limit_key(_request_with(token)) == "203.0.113.9"


def test_wrong_passwords_on_account_pages_count_toward_the_lock(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    c = _register("stu")
    headers = {"X-CSRF-Token": c.cookies.get("csrf_token") or ""}
    for _ in range(db.LOCKOUT_AFTER):
        r = c.post(
            "/api/change-password",
            json={"current_password": "wrong-password", "new_password": "another-pass-123", "new_password_confirm": "another-pass-123"},
            headers=headers,
        )
        assert r.status_code == 400
    rec = db.get_by_username("stu")
    assert db.is_locked(rec)
    kinds = [e["detail"] for e in db.list_auth_events(rec["id"], limit=20) if e["kind"] == "login_fail"]
    assert any(d.startswith("change-password") for d in kinds), kinds
    r = c.post(
        "/api/change-password",
        json={"current_password": TEST_PASSWORD, "new_password": "another-pass-123", "new_password_confirm": "another-pass-123"},
        headers=headers,
    )
    assert r.status_code == 400
    assert c.get("/api/libraries").status_code == 200


def test_delete_account_is_rate_limited(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    c = _register("stu")
    headers = {"X-CSRF-Token": c.cookies.get("csrf_token") or ""}
    codes = [
        c.post("/api/delete-account", json={"password": "wrong-password"}, headers=headers).status_code
        for _ in range(11)
    ]
    assert codes[-1] == 429, codes


def test_login_and_register_refuse_a_post_from_another_site(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _register("stu")
    form = {"username": "stu", "password": TEST_PASSWORD}
    for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://evil.example"}):
        c = TestClient(app)
        r = c.post("/login", data=form, headers=headers, follow_redirects=False)
        assert r.status_code == 403, headers
        assert not c.cookies.get("access_token")
        r = c.post(
            "/register",
            data={"username": "planted", "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
            headers=headers, follow_redirects=False,
        )
        assert r.status_code == 403
        assert db.get_by_username("planted") is None
    same = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    r = TestClient(app).post("/login", data=form, headers=same, follow_redirects=False)
    assert r.status_code == 302


def test_a_guest_can_register_and_the_demo_is_dropped(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    guest = TestClient(app)
    assert guest.post("/guest", follow_redirects=False).status_code in (302, 303)
    guest_id = next(u["id"] for u in db.list_accounts() if u.get("is_guest"))
    page = guest.get("/register", follow_redirects=False)
    assert page.status_code == 200
    _register("newstudent", client=guest)
    assert db.get_by_id(guest_id) is None
    assert guest.get("/api/libraries").status_code == 200
    me = db.get_by_username("newstudent")
    assert me and not me.get("is_guest")


def test_admin_names_cannot_be_registered(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    monkeypatch.setenv("ADMIN_USERNAMES", "boss")
    r = TestClient(app).post(
        "/register",
        data={"username": "Boss", "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "reserved" in r.text
    assert db.get_by_username("boss") is None


def test_an_unknown_username_costs_a_password_check_too(tmp_path, monkeypatch):
    from app.routes import auth as auth_routes

    _db(tmp_path, monkeypatch)
    calls = []
    real = auth_routes.verify_password_async

    async def counting(password, hashed):
        calls.append(hashed)
        return await real(password, hashed)

    monkeypatch.setattr(auth_routes, "verify_password_async", counting)
    r = TestClient(app).post(
        "/login", data={"username": "nobody", "password": "whatever-pass"}, follow_redirects=False,
    )
    assert r.status_code == 400
    assert len(calls) == 1


def test_reset_codes_show_only_with_their_own_flag(monkeypatch):
    from app.routes import auth as auth_routes

    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.delenv("RESET_CODES_IN_RESPONSE", raising=False)
    assert auth_routes._reset_codes_in_response() is False
    monkeypatch.setenv("RESET_CODES_IN_RESPONSE", "1")
    assert auth_routes._reset_codes_in_response() is True


def test_ops_unlock_has_no_fallback_secret(monkeypatch):
    import pytest

    from app.routes import ops

    monkeypatch.setenv("SECRET_KEY", "")
    with pytest.raises(RuntimeError):
        ops._reauth_secret()


def test_support_view_refusals_carry_the_security_headers(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    _register("needhelp")
    admin = _register("opadmin")
    monkeypatch.setenv("ADMIN_USERNAMES", "opadmin")
    uid = db.get_by_username("needhelp")["id"]
    csrf = {"X-CSRF-Token": admin.cookies.get("csrf_token") or ""}
    r = admin.post(
        f"/api/admin/users/{uid}/view",
        json={"reason": "reproduce", "password": TEST_PASSWORD}, headers=csrf,
    )
    assert r.status_code == 200, r.text
    blocked = admin.post(
        "/api/fetch-articles-multi",
        json={"sources": ["pubmed"], "query": "x", "max_results": 1, "wait": False},
        headers=csrf,
    )
    assert blocked.status_code == 403
    assert blocked.json().get("support_view") is True
    assert "content-security-policy" in blocked.headers
    redirect = admin.get("/admin", follow_redirects=False)
    assert redirect.status_code in (302, 303)
    assert "content-security-policy" in redirect.headers


def test_fetch_choices_are_stored_per_account(tmp_path, monkeypatch):
    import pathlib

    db = _db(tmp_path, monkeypatch)
    c = _register("stu")
    uid = db.get_by_username("stu")["id"]
    assert f'data-account="{uid}"' in c.get("/search").text
    js = (pathlib.Path(__file__).resolve().parent.parent / "static/js/common.js").read_text()
    assert "var FETCH_PREFS_KEY = 'lra_fetch_prefs_v2:' + " in js
    assert "dataset.account" in js
