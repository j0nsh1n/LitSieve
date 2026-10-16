"""The Tickets tab: list by status, one thread, reply, status change."""

from __future__ import annotations

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.services import mailer
from app.storage import helpdesk


def _admin_client(tmp_path, monkeypatch, username="opadmin"):
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    client = TestClient(app)
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    monkeypatch.setenv("ADMIN_USERNAMES", username)
    return client, db


def _register(username):
    c = TestClient(app)
    r = c.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    return c


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _ticket(db, username, body, status=None):
    rec = db.get_by_username(username)
    t = helpdesk.create_ticket(
        db, student_id=rec["id"], student_username=rec["username"], body=body, context={},
    )
    if status:
        helpdesk.set_ticket_status(db, t["id"], status)
    return t["id"]


def test_page_has_the_tab_and_the_status_chips(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    html = client.get("/admin").text
    assert 'id="tab-tickets"' in html
    for status in (*helpdesk.TICKET_STATUSES, "all"):
        assert f'data-ticket-status="{status}"' in html
    assert "Reply to latest ticket" not in html


def test_list_filters_by_status_and_rejects_unknown(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    for i, status in enumerate(("open", "open", "waiting_on_student", "investigating", "resolved")):
        _register(f"stu{i}")
        _ticket(db, f"stu{i}", f"ticket {i}", status)
    counts = {"open": 2, "waiting_on_student": 1, "investigating": 1, "resolved": 1}
    for status, n in counts.items():
        r = client.get(f"/api/admin/tickets?status={status}")
        assert r.status_code == 200, r.text
        assert {t["status"] for t in r.json()["tickets"]} == {status}
        assert r.json()["total"] == n
    assert client.get("/api/admin/tickets?status=all").json()["total"] == 5
    assert client.get("/api/admin/tickets").json()["total"] == 5
    r = client.get("/api/admin/tickets?status=bogus")
    assert r.status_code == 400
    assert r.json()["detail"] == "Unknown ticket status filter."


def test_detail_is_one_thread_and_reply_moves_it_to_waiting(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("maria")
    _register("other")
    tid = _ticket(db, "maria", "Prepare hangs at 3 of 5 sources.")
    _ticket(db, "other", "private note from someone else")
    r = client.post(
        f"/api/admin/tickets/{tid}/reply",
        json={"reason": "answering", "body": "Europe PMC is slow; I restarted the fetch."},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["emailed"] is False
    detail = client.get(f"/api/admin/tickets/{tid}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["student_username"] == "maria"
    assert body["status"] == "waiting_on_student"
    assert [(x["author_role"], x["body"]) for x in body["replies"]] == [
        ("admin", "Europe PMC is slow; I restarted the fetch."),
    ]
    assert "private note" not in detail.text
    uid = db.get_by_username("maria")["id"]
    timeline = client.get(f"/api/admin/users/{uid}").json()["timeline"]
    assert timeline[0]["action"] == "ticket-reply"
    assert timeline[0]["reason"] == "answering"
    assert client.get("/api/admin/tickets/no-such-id").status_code == 404


def test_status_change_validates_and_logs(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("dan")
    tid = _ticket(db, "dan", "Cannot find export.")
    r = client.post(
        f"/api/admin/tickets/{tid}/status",
        json={"reason": "fixed by reset", "status": "resolved"},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["ticket"]["status"] == "resolved"
    uid = db.get_by_username("dan")["id"]
    row = client.get(f"/api/admin/users/{uid}").json()["timeline"][0]
    assert (row["action"], row["old_value"], row["new_value"]) == ("ticket-status", "open", "resolved")
    for bad in ("bogus", "all", ""):
        r = client.post(
            f"/api/admin/tickets/{tid}/status",
            json={"reason": "trying", "status": bad},
            headers=_csrf(client),
        )
        assert r.status_code == 400, bad
        assert r.json()["detail"] == "Unknown ticket status."
    assert helpdesk.get_ticket(db, tid)["status"] == "resolved"


def test_plain_user_is_refused_and_reason_is_required(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("stu")
    tid = _ticket(db, "stu", "Help.")
    plain = _register("plain")
    assert plain.get("/api/admin/tickets").status_code == 403
    assert plain.get(f"/api/admin/tickets/{tid}").status_code == 403
    assert plain.post(f"/api/admin/tickets/{tid}/reply", json={"reason": "hi", "body": "x"}, headers=_csrf(plain)).status_code == 403
    assert plain.post(f"/api/admin/tickets/{tid}/status", json={"reason": "hi", "status": "resolved"}, headers=_csrf(plain)).status_code == 403
    for path, body in ((f"/api/admin/tickets/{tid}/reply", {"body": "x"}), (f"/api/admin/tickets/{tid}/status", {"status": "resolved"})):
        r = client.post(path, json=body, headers=_csrf(client))
        assert r.status_code == 400, path
        assert "reason" in r.json()["detail"]
    assert helpdesk.get_ticket(db, tid)["status"] == "open"
    assert helpdesk.get_ticket(db, tid)["replies"] == []
