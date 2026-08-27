"""Admin console: ADMIN_USERNAMES gate, overview, lookup, unlock, note, logs."""

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
    assert b"Admin" in page.content
    assert b"This host" in page.content
    assert b"Find a student" not in page.content
    assert b"admin.js" in page.content
    snap = client.get("/api/admin/overview")
    assert snap.status_code == 200, snap.text
    body = snap.json()
    assert "counts" in body
    assert "users" not in body
    assert body["counts"]["accounts"] >= 1
    assert "smtp" in body
    assert "ai" in body

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
    ov = client.get("/api/admin/overview")
    assert ov.status_code == 200
    assert "users" not in ov.json()
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


def test_admin_rejects_path_user_id(tmp_path, monkeypatch):
    client, _db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    for raw in ("../etc/passwd", "not-a-uuid", "abcd"):
        r = client.get(f"/api/admin/users/{raw}")
        assert r.status_code == 404, raw


def test_helpdesk_queue_locked(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    _register("lockedkid")
    for _ in range(8):
        db.record_login_failure("lockedkid", "test")
    q = client.get("/api/admin/queue?filter=locked")
    assert q.status_code == 200
    names = [u["username"] for u in q.json()["users"]]
    assert "lockedkid" in names


def test_admin_new_tools_forbidden_for_plain_user(tmp_path, monkeypatch):
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
    rec = db.get_by_username("student1")
    uid = rec["id"]
    csrf = client.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf or ""}
    for path in (
        f"/api/admin/users/{uid}/set-email",
        f"/api/admin/users/{uid}/clear-job",
        f"/api/admin/users/{uid}/retry-embed",
        f"/api/admin/users/{uid}/quota-bump",
        f"/api/admin/users/{uid}/delete-library",
    ):
        out = client.post(path, json={"reason": "please help this student"}, headers=headers)
        assert out.status_code == 403, path
        assert out.json().get("admin") is True


def test_admin_new_tools_uuid_only(tmp_path, monkeypatch):
    client, _db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    headers = {"X-CSRF-Token": csrf or ""}
    body = {"reason": "desk help for stuck student", "confirm": "x"}
    for raw in ("../etc/passwd", "not-a-uuid", "abcd"):
        for suffix in ("set-email", "clear-job", "retry-embed", "quota-bump", "delete-library"):
            r = client.post(f"/api/admin/users/{raw}/{suffix}", json=body, headers=headers)
            assert r.status_code == 404, (raw, suffix)


def test_admin_set_email_does_not_auto_verify(tmp_path, monkeypatch):
    sent = []

    def fake_send(to, username, token):
        sent.append((to, username, token))

    from app.services import mailer
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    monkeypatch.setattr(mailer, "send_verification", fake_send)

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]

    guest = db.create_user("guest_tmp", "hash", is_guest=True)
    guest_out = client.post(
        f"/api/admin/users/{guest['id']}/set-email",
        json={"reason": "fix guest mail", "confirm": "guest_tmp", "email": "g@school.edu"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert guest_out.status_code == 400
    assert "register" in guest_out.json()["detail"].lower()

    monkeypatch.setattr(mailer, "is_configured", lambda: False)
    off = client.post(
        f"/api/admin/users/{uid}/set-email",
        json={"reason": "typo on signup form", "confirm": "needhelp", "email": "need@school.edu"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert off.status_code == 503
    assert off.json().get("smtp_configured") is False
    monkeypatch.setattr(mailer, "is_configured", lambda: True)

    out = client.post(
        f"/api/admin/users/{uid}/set-email",
        json={"reason": "typo on signup form", "confirm": "needhelp", "email": "need@school.edu"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body.get("email_verified") is False
    assert body.get("token") is None
    assert "verification" not in body
    assert sent and sent[0][0] == "need@school.edu"
    fresh = db.get_by_id(uid)
    assert fresh["email"] == "need@school.edu"
    assert fresh["email_verified"] is False


def test_admin_quota_bump_expires(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.storage import quota

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]
    default_mb = quota.mb(quota.limit_bytes())

    until = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    out = client.post(
        f"/api/admin/users/{uid}/quota-bump",
        json={
            "reason": "mid-term project overflow",
            "confirm": "needhelp",
            "limit_mb": 800,
            "until": until,
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    report = out.json()["quota"]
    assert report["quota_override_active"] is True
    assert report["limit_mb"] == 800
    assert report["default_limit_mb"] == default_mb

    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.set_quota_override(uid, 800, past)
    expired = quota.usage_report(uid)
    assert expired["quota_override_active"] is False
    assert expired["limit_mb"] == default_mb
    assert quota.account_limit_bytes(uid) == quota.limit_bytes()


def test_admin_delete_library_is_one_library(tmp_path, monkeypatch):
    from app.storage.libraries import create_library, list_libraries

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]
    create_library(uid, "Scratch")
    before = list_libraries(uid)
    assert len(before["libraries"]) == 2
    scratch = next(L for L in before["libraries"] if L["name"] == "Scratch")
    keep = next(L for L in before["libraries"] if L["name"] != "Scratch")

    missing_name = client.post(
        f"/api/admin/users/{uid}/delete-library",
        json={
            "reason": "duplicate collection from class",
            "confirm": "needhelp",
            "library_id": scratch["id"],
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert missing_name.status_code == 400

    out = client.post(
        f"/api/admin/users/{uid}/delete-library",
        json={
            "reason": "duplicate collection from class",
            "confirm": "needhelp",
            "library_id": scratch["id"],
            "library_name": "Scratch",
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    after = list_libraries(uid)
    names = [L["name"] for L in after["libraries"]]
    assert "Scratch" not in names
    assert keep["name"] in names
    assert len(after["libraries"]) == 1
    actions = [a["action"] for a in db.list_support_actions(uid)]
    assert "delete-library" in actions


def test_admin_job_clear_and_retry_logged(tmp_path, monkeypatch):
    from app import core

    started = []

    def fake_start(uid, task, fn, /, **kwargs):
        started.append({"uid": uid, "task": task, "fn": getattr(fn, "__name__", ""), "kwargs": kwargs})
        return True

    monkeypatch.setattr(core, "start_user_job", fake_start)

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]

    with core._progress_lock:
        core._ensure_progress(uid)["fetch"].update(
            {"active": True, "error": "worker gone", "message": "stuck"}
        )
        core._ensure_progress(uid)["embed"].update(
            {"active": False, "error": "boom", "result": {"status": "error"}}
        )

    q = client.get("/api/admin/queue?filter=jobs")
    assert q.status_code == 200, q.text
    names = [u["username"] for u in q.json()["users"]]
    assert "needhelp" in names

    detail = client.get(f"/api/admin/users/{uid}")
    assert detail.status_code == 200
    jobs = detail.json()["jobs"]
    assert jobs["fetch"]["state"] == "stalled"
    assert jobs["fetch"]["can_clear"] is True
    assert jobs["embed"]["state"] == "failed"

    clear = client.post(
        f"/api/admin/users/{uid}/clear-job",
        json={"reason": "slot still running after crash", "confirm": "needhelp", "task": "fetch"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert clear.status_code == 200, clear.text
    assert clear.json()["status"] == "cleared"

    retry = client.post(
        f"/api/admin/users/{uid}/retry-embed",
        json={"reason": "prepare never finished after fetch"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert retry.status_code == 200, retry.text
    assert started and started[0]["uid"] == uid
    assert started[0]["task"] == "embed"
    assert started[0]["kwargs"].get("only_missing") is True
    assert started[0]["uid"] != db.get_by_username("opadmin")["id"]

    actions = [a["action"] for a in db.list_support_actions(uid)]
    assert "clear-job" in actions
    assert "retry-embed" in actions


def test_support_view_read_only_and_expiry(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]

    denied = TestClient(app)
    denied.post(
        "/register",
        data={"username": "plain", "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    r = denied.post(
        f"/api/admin/users/{uid}/view",
        json={"reason": "reproduce search bug", "password": TEST_PASSWORD},
        headers={"X-CSRF-Token": denied.cookies.get("csrf_token") or ""},
    )
    assert r.status_code == 403

    started = client.post(
        f"/api/admin/users/{uid}/view",
        json={"reason": "reproduce search bug", "password": TEST_PASSWORD, "ui_mode": "simple"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert started.status_code == 200, started.text
    assert started.json().get("token") is None
    assert client.cookies.get("support_view")
    actions = [a["action"] for a in db.list_support_actions(uid)]
    assert "support-view-start" in actions

    admin_page = client.get("/admin", follow_redirects=False)
    assert admin_page.status_code in (302, 303)
    overview = client.get("/api/admin/overview")
    assert overview.status_code == 403
    assert overview.json().get("support_view") is True

    mutate = client.post(
        "/api/fetch-articles-multi",
        json={"sources": ["pubmed"], "query": "x", "max_results": 1, "wait": False},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token") or ""},
    )
    assert mutate.status_code == 403
    assert mutate.json().get("support_view") is True

    search_ok = client.post(
        "/api/search",
        json={"query": "test", "top_k": 5},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token") or ""},
    )
    assert search_ok.status_code != 403 or search_ok.json().get("support_view") is not True

    me = client.get("/search", follow_redirects=False)
    assert me.status_code == 200
    assert b"Read-only student view" in me.content
    assert b"needhelp" in me.content

    db.conn.execute("UPDATE support_views SET expires_at = '2000-01-01 00:00:00'")
    db.conn.commit()
    after = client.get("/api/admin/overview")
    assert after.status_code == 200

    client.cookies.delete("support_view")
    fresh = client.post(
        f"/api/admin/users/{uid}/view",
        json={"reason": "second look at search", "password": TEST_PASSWORD},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token") or ""},
    )
    assert fresh.status_code == 200
    ended = client.post(
        "/api/support-view/exit",
        json={},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token") or ""},
    )
    assert ended.status_code == 200
    back = client.get("/admin")
    assert back.status_code == 200


def test_soft_disable_expires(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    student = _register("needhelp")
    rec = db.get_by_username("needhelp")
    uid = rec["id"]
    until = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    out = client.post(
        f"/api/admin/users/{uid}/disable",
        json={
            "reason": "policy review this week",
            "confirm": "needhelp",
            "message": "Your teacher paused this account for a review.",
            "until": until,
        },
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    blocked = student.post(
        "/login",
        data={"username": "needhelp", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert blocked.status_code == 400
    assert "paused" in blocked.text.lower()

    past = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    db.conn.execute("UPDATE users SET disabled_until = ? WHERE id = ?", (past, uid))
    db.conn.commit()
    student.cookies.clear()
    ok = student.post(
        "/login",
        data={"username": "needhelp", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert ok.status_code in (302, 303)

    enable = client.post(
        f"/api/admin/users/{uid}/enable",
        json={"reason": "review finished today"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert enable.status_code == 200
    actions = [a["action"] for a in db.list_support_actions(uid)]
    assert "disable" in actions
    assert "enable" in actions


def test_ticket_privacy_and_banner_rollback(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch, username="opadmin")
    csrf = client.cookies.get("csrf_token")
    student = _register("needhelp")
    rec = db.get_by_username("needhelp")

    created = student.post(
        "/api/tickets",
        json={
            "body": "Prepare never finishes on Search.",
            "context": {
                "route": "/search",
                "ui_mode": "simple",
                "title": "Secret paper title",
                "query": "full research question about a student",
                "user_agent": "TestBrowser/1.0",
            },
        },
        headers={"X-CSRF-Token": student.cookies.get("csrf_token") or ""},
    )
    assert created.status_code == 200, created.text
    ctx = created.json()["ticket"]["context"]
    assert "title" not in ctx
    assert "query" not in ctx
    assert ctx.get("route") == "/search"
    assert "Secret" not in created.text

    guest_client = TestClient(app)
    guest_client.post("/guest", follow_redirects=False)
    guest_ticket = guest_client.post(
        "/api/tickets",
        json={"body": "help"},
        headers={"X-CSRF-Token": guest_client.cookies.get("csrf_token") or ""},
    )
    assert guest_ticket.status_code in (400, 401, 403)

    draft = client.post(
        "/api/admin/banner",
        json={"reason": "draft the outage note", "body": "First banner text", "status": "draft"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert draft.status_code == 200, draft.text
    notice_id = draft.json()["banner"]["id"]
    first_rev = draft.json()["banner"]["revisions"][0]["id"]
    second = client.post(
        "/api/admin/banner",
        json={"reason": "update the outage note", "body": "Second banner text", "status": "draft"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert second.status_code == 200
    rolled = client.post(
        f"/api/admin/banner/{notice_id}/rollback",
        json={"reason": "first wording was clearer", "revision_id": first_rev},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["banner"]["body"] == "First banner text"

    bad_html = client.post(
        "/api/admin/banner",
        json={"reason": "try inject", "body": "<script>alert(1)</script>Hello", "status": "draft"},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert bad_html.status_code == 200
    assert "<script>" not in bad_html.json()["banner"]["body"]
