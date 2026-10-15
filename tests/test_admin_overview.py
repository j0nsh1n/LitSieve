"""The Overview queues and cross-account activity feed stay read-only."""

from __future__ import annotations

import re
from collections import OrderedDict

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.routes.admin import _QUEUE_KINDS
from app.storage import helpdesk


def _admin_client(tmp_path, monkeypatch, username="opadmin"):
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setenv("ADMIN_USERNAMES", username)
    client = TestClient(app)
    response = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text
    return client, db


def _register(username):
    client = TestClient(app)
    response = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text
    return client


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_queue_counts_match_seeded_queue_state(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    monkeypatch.setattr(core, "_all_progress", OrderedDict())
    _register("lockedstudent")
    _register("unverifiedstudent")
    _register("disabledstudent")
    _register("ticketstudent")

    locked = db.get_by_username("lockedstudent")
    unverified = db.get_by_username("unverifiedstudent")
    disabled = db.get_by_username("disabledstudent")
    ticket = db.get_by_username("ticketstudent")
    future = "2999-01-01 00:00:00"
    with db._lock:
        db.conn.execute("UPDATE users SET locked_until = ? WHERE id = ?", (future, locked["id"]))
        db.conn.execute(
            "UPDATE users SET email = ?, email_verified = 0 WHERE id = ?",
            ("student@example.test", unverified["id"]),
        )
        db.conn.commit()
    assert helpdesk.set_disabled(db, disabled["id"], until=future, message="test")
    helpdesk.create_ticket(
        db, student_id=ticket["id"], student_username=ticket["username"],
        body="A test ticket", context={},
    )

    response = client.get("/api/admin/queue-counts")
    assert response.status_code == 200, response.text
    counts = response.json()["counts"]
    assert set(counts) == _QUEUE_KINDS
    assert counts == {
        "locked": 1, "unverified": 1, "quota": 0, "errors": 0,
        "jobs": 0, "jobs-active": 0, "jobs-stalled": 0, "jobs-failed": 0,
        "disabled": 1, "tickets": 1,
    }


def test_activity_is_cross_account_newest_first_and_excludes_private_fields(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("studentone")
    _register("studenttwo")
    admin_id = db.get_by_username("opadmin")["id"]
    one = db.get_by_username("studentone")
    two = db.get_by_username("studenttwo")
    rows = []
    for user, action in ((one, "unlock"), (two, "disable"), (one, "quota-bump"), (two, "ticket-reply")):
        rows.append(db.add_support_action(
            user["id"], admin_id, "opadmin", action, f"reason for {action}",
            new_value="safe value",
        ))
    times = ("2026-10-15 10:00:00", "2026-10-15 10:01:00", "2026-10-15 10:02:00", "2026-10-15 10:03:00")
    with db._lock:
        for row, timestamp in zip(rows, times):
            db.conn.execute("UPDATE support_actions SET created_at = ? WHERE id = ?", (timestamp, row["id"]))
        db.conn.commit()

    response = client.get("/api/admin/activity?limit=99")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["action"] for item in items] == ["ticket-reply", "quota-bump", "disable", "unlock"]
    assert [item["student_username"] for item in items] == ["studenttwo", "studentone", "studenttwo", "studentone"]
    assert items[0]["created_at"] == times[-1]
    assert set(items[0]) == {
        "id", "created_at", "admin_username", "action", "reason", "new_value",
        "student_id", "student_username",
    }
    assert "hashed_password" not in items[0]
    assert "email" not in items[0]
    assert len(client.get("/api/admin/activity?limit=0").json()["items"]) == 1


def test_overview_routes_require_admin(tmp_path, monkeypatch):
    admin, _ = _admin_client(tmp_path, monkeypatch)
    plain = _register("plainstudent")
    anonymous = TestClient(app)
    for path in ("/api/admin/queue-counts", "/api/admin/activity"):
        assert admin.get(path).status_code == 200
        assert plain.get(path).status_code == 403
        assert anonymous.get(path).status_code == 401


def test_overview_template_has_every_queue_and_activity_card(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    html = client.get("/admin").text
    tile_kinds = set(re.findall(r'data-count="([a-z-]+)"', html))
    assert tile_kinds == _QUEUE_KINDS
    assert 'id="admin-recent-activity"' in html
    assert 'id="admin-activity-list"' in html
    assert 'href="#tickets/open"' in html
    assert 'admin.js?v=20261015b' in html
