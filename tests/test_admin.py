"""Helpdesk console: ADMIN_USERNAMES gate, lookup, unlock, note, logs."""

from __future__ import annotations

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app.main import app


def _admin_client(tmp_path, monkeypatch, username="opadmin"):
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setenv("ADMIN_USERNAMES", username)

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": username,
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    return client, db


def _register(username: str):
    c = TestClient(app)
    r = c.post(
        "/register",
        data={
            "username": username,
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    return c


def test_helpdesk_page_and_search_requires_admin(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    page = client.get("/admin")
    assert page.status_code == 200
    assert b"Find a student" in page.content
    assert b"admin.js" in page.content

    _register("needhelp")
    found = client.get("/api/admin/search?q=needhelp")
    assert found.status_code == 200, found.text
    names = [u["username"] for u in found.json()["users"]]
    assert "needhelp" in names
    assert all("hashed_password" not in u for u in found.json()["users"])
    assert found.json()["users"][0]["username"] == "needhelp"

    roster = client.get("/api/admin/search?q=")
    assert roster.status_code == 200
    assert len(roster.json()["users"]) <= 25


def test_helpdesk_forbidden_for_plain_user(tmp_path, monkeypatch):
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setenv("ADMIN_USERNAMES", "someoneelse")

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": "student1",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    page = client.get("/admin", follow_redirects=False)
    assert page.status_code in (302, 303)
    assert page.headers.get("location") == "/account"
    api = client.get("/api/admin/search?q=student1")
    assert api.status_code == 403
    assert api.json().get("admin") is True


def test_helpdesk_unlock_note_and_timeline(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]

    for _ in range(8):
        db.record_login_failure("needhelp", "test")
    assert db.is_locked(db.get_by_username("needhelp"))

    missing = client.post(
        f"/api/admin/users/{uid}/unlock",
        json={},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert missing.status_code == 400

    out = client.post(
        f"/api/admin/users/{uid}/unlock",
        json={"reason": "too many failed sign-ins in class"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    assert db.is_locked(db.get_by_username("needhelp")) is False

    note = client.post(
        f"/api/admin/users/{uid}/note",
        json={"body": "Unlocked after class lockout."},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert note.status_code == 200, note.text

    detail = client.get(f"/api/admin/users/{uid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["locked"] is False
    assert any(n["body"] == "Unlocked after class lockout." for n in body["support_notes"])
    actions = [a["action"] for a in body["timeline"]]
    assert "unlock" in actions
    assert "note" in actions
    assert "hashed_password" not in body


def test_helpdesk_send_reset_emails_not_shown(tmp_path, monkeypatch):
    sent = []

    def fake_send(to, username, code):
        sent.append((to, username, code))

    from app.services import mailer
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_password_reset", fake_send)

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    db.conn.execute(
        "UPDATE users SET email = ?, email_verified = 1 WHERE id = ?",
        ("need@school.edu", rec["id"]),
    )
    db.conn.commit()

    no_confirm = client.post(
        f"/api/admin/users/{rec['id']}/send-reset",
        json={"reason": "forgot password"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert no_confirm.status_code == 400

    out = client.post(
        f"/api/admin/users/{rec['id']}/send-reset",
        json={"reason": "forgot password at desk", "confirm": "needhelp"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    assert out.json().get("reset_code") is None
    assert out.json().get("emailed_to") == "need@school.edu"
    assert sent and sent[0][0] == "need@school.edu"
    assert sent[0][2]


def test_helpdesk_no_roster_dump_or_promote(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    for i in range(6):
        _register(f"stu{i}")
    listed = client.get("/api/admin/search?q=")
    assert listed.status_code == 200
    assert listed.json()["total"] <= 25
    rec = db.get_by_username("stu0")
    packet = client.get(f"/api/admin/users/{rec['id']}/packet")
    assert packet.status_code == 200
    text = packet.text
    assert "stu0" in text
    assert "hashed_password" not in text
    assert "stu5" not in text


def test_helpdesk_queue_locked(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    _register("lockedkid")
    for _ in range(8):
        db.record_login_failure("lockedkid", "test")
    q = client.get("/api/admin/queue?filter=locked")
    assert q.status_code == 200
    names = [u["username"] for u in q.json()["users"]]
    assert "lockedkid" in names
