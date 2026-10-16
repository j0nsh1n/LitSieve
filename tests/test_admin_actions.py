"""The admin page's buttons, confirm rules and history paging come from ACTIONS."""

from __future__ import annotations

import pathlib
import re

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.routes.admin import ACTIONS, BANNER_CONFIRM, HISTORY_PAGE
from app.storage import helpdesk

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _admin_client(tmp_path, monkeypatch, username="opadmin"):
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
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


def test_page_buttons_are_the_registry(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    html = client.get("/admin").text
    buttons = re.findall(r'<button[^>]*data-action="([a-z-]+)"([^>]*)>', html)
    seen = {}
    for name, rest in buttons:
        seen.setdefault(name, set()).add('data-destructive="1"' in rest)
    assert set(seen) == {a.name for a in ACTIONS}
    for a in ACTIONS:
        assert seen[a.name] == {a.destructive}, a.name
    per_task = [a.name for a in ACTIONS if a.per_task]
    for name in per_task:
        tasks = re.findall(rf'data-action="{name}" data-task="([a-z]+)"', html)
        assert sorted(tasks) == ["embed", "fetch"], name
    assert "reset-mfa" not in html
    assert 'role="tablist"' in html


def test_script_forms_name_real_actions():
    js = (ROOT / "static" / "js" / "admin.js").read_text()
    table = js[js.index("const ACTION_FORMS = {"):js.index("function libraries(")]
    keys = re.findall(r"^ '?([a-z-]+)'?: \{", table, re.M)
    assert keys, "ACTION_FORMS has no entries"
    assert set(keys) <= {a.name for a in ACTIONS}, set(keys) - {a.name for a in ACTIONS}


def test_destructive_routes_need_the_username(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("stu")
    uid = db.get_by_username("stu")["id"]
    for a in ACTIONS:
        if a.per_task:
            body = {"reason": "testing the confirm rule", "task": "fetch"}
        else:
            body = {"reason": "testing the confirm rule"}
        r = client.post(f"/api/admin/users/{uid}/{a.name}", json=body, headers=_csrf(client))
        if a.destructive:
            assert r.status_code == 400, (a.name, r.text)
            assert r.json()["detail"] == "Type stu to confirm this action.", a.name
        else:
            assert r.json().get("detail") != "Type stu to confirm this action.", a.name
    r = client.post(f"/api/admin/users/{uid}/unlock", json={"reason": "no"}, headers=_csrf(client))
    assert r.status_code == 400
    assert "reason" in r.json()["detail"]
    r = client.post(f"/api/admin/users/{uid}/reset-mfa", json={"reason": "gone"}, headers=_csrf(client))
    assert r.status_code in (404, 405)


def test_guest_rule_comes_from_the_registry(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    guest = TestClient(app)
    r = guest.post("/guest", follow_redirects=False)
    assert r.status_code in (302, 303), r.text
    row = next(u for u in db.list_accounts() if u.get("is_guest"))
    uid = row["id"]
    a = next(x for x in ACTIONS if x.name == "disable")
    r = client.post(
        f"/api/admin/users/{uid}/disable",
        json={"reason": "testing", "confirm": row["username"], "message": "paused"},
        headers=_csrf(client),
    )
    assert r.status_code == 400
    assert r.json()["detail"] == a.guest_message


def test_history_pages_through_the_timeline(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("paged")
    uid = db.get_by_username("paged")["id"]
    admin_id = db.get_by_username("opadmin")["id"]
    for i in range(HISTORY_PAGE + 3):
        db.add_support_action(uid, admin_id, "opadmin", "unlock", reason=f"reason number {i}")
    detail = client.get(f"/api/admin/users/{uid}").json()
    assert len(detail["timeline"]) == HISTORY_PAGE
    page = client.get(f"/api/admin/users/{uid}/history?kind=timeline&offset={HISTORY_PAGE}").json()
    assert page["more"] is False
    assert len(page["items"]) == 3
    first_ids = {row["id"] for row in detail["timeline"]}
    assert first_ids.isdisjoint({row["id"] for row in page["items"]})
    bad = client.get(f"/api/admin/users/{uid}/history?kind=secrets")
    assert bad.status_code == 400


def test_banner_publish_and_take_down_need_the_word(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    r = client.post(
        "/api/admin/banner",
        json={"reason": "drafting", "body": "PubMed is slow this afternoon.", "status": "draft"},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    nid = r.json()["banner"]["id"]
    r = client.post(f"/api/admin/banner/{nid}/publish", json={"reason": "go live"}, headers=_csrf(client))
    assert r.status_code == 400
    assert r.json()["detail"] == f"Type {BANNER_CONFIRM} to confirm this action."
    r = client.post(
        f"/api/admin/banner/{nid}/publish",
        json={"reason": "go live", "confirm": BANNER_CONFIRM},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert helpdesk.published_banner(db)["id"] == nid
    r = client.post(f"/api/admin/banner/{nid}/disable", json={"reason": "over"}, headers=_csrf(client))
    assert r.status_code == 400
    r = client.post(
        f"/api/admin/banner/{nid}/disable",
        json={"reason": "over", "confirm": BANNER_CONFIRM},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert helpdesk.published_banner(db) is None


def _save_banner(client, text, **extra):
    r = client.post(
        "/api/admin/banner",
        json={"reason": "drafting", "body": text, **extra},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    return r.json()["banner"]


def _publish(client, nid):
    r = client.post(
        f"/api/admin/banner/{nid}/publish",
        json={"reason": "go live", "confirm": BANNER_CONFIRM},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text


def test_saving_a_draft_leaves_the_live_banner_up(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    live = _save_banner(client, "PubMed is slow this afternoon.")
    _publish(client, live["id"])
    draft = _save_banner(client, "PubMed is back.")
    assert draft["id"] != live["id"]
    assert draft["status"] == "draft"
    published = helpdesk.published_banner(db)
    assert published["id"] == live["id"]
    assert published["body"] == "PubMed is slow this afternoon."
    state = client.get("/api/admin/banner").json()
    assert state["published"]["body"] == "PubMed is slow this afternoon."
    assert state["draft"]["body"] == "PubMed is back."
    again = _save_banner(client, "PubMed is back to normal.")
    assert again["id"] == draft["id"]
    _publish(client, again["id"])
    assert helpdesk.published_banner(db)["body"] == "PubMed is back to normal."
    assert client.get("/api/admin/banner").json()["draft"] is None


def test_banner_status_changes_only_through_the_word(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    saved = _save_banner(client, "Maintenance tonight.", status="published")
    assert saved["status"] == "draft"
    assert helpdesk.published_banner(db) is None
    _publish(client, saved["id"])
    rev = saved["revisions"][0]["id"]
    r = client.post(
        f"/api/admin/banner/{saved['id']}/rollback",
        json={"reason": "undo", "revision_id": rev},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert helpdesk.published_banner(db)["id"] == saved["id"]
    r = client.post(
        f"/api/admin/banner/{saved['id']}/disable",
        json={"reason": "over", "confirm": BANNER_CONFIRM},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"/api/admin/banner/{saved['id']}/rollback",
        json={"reason": "bring it back", "revision_id": rev},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["banner"]["status"] == "draft"
    assert helpdesk.published_banner(db) is None


def test_admins_cannot_lock_admins_out(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    second = _register("second")
    monkeypatch.setenv("ADMIN_USERNAMES", "opadmin,second")
    me = db.get_by_username("opadmin")
    other = db.get_by_username("second")
    by_name = {a.name: a for a in ACTIONS}
    refused = (
        (me, "disable", by_name["disable"].admin_message, {"message": "paused"}),
        (me, "revoke-sessions", by_name["revoke-sessions"].self_message, {}),
        (me, "set-email", by_name["set-email"].admin_message, {"email": "me@example.org"}),
        (other, "disable", by_name["disable"].admin_message, {"message": "paused"}),
        (other, "set-email", by_name["set-email"].admin_message, {"email": "x@example.org"}),
    )
    for rec, name, message, extra in refused:
        assert message
        r = client.post(
            f"/api/admin/users/{rec['id']}/{name}",
            json={"reason": "testing", "confirm": rec["username"], **extra},
            headers=_csrf(client),
        )
        assert r.status_code == 400, (name, r.text)
        assert r.json()["detail"] == message
        detail = client.get(f"/api/admin/users/{rec['id']}").json()
        assert detail["refusals"][name] == message
    assert client.get("/api/admin/queue-counts").status_code == 200
    assert second.get("/api/libraries").status_code == 200
    r = client.post(
        f"/api/admin/users/{other['id']}/revoke-sessions",
        json={"reason": "stolen laptop", "confirm": "second"},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    student = _register("stu")
    assert student
    stu = db.get_by_username("stu")
    assert client.get(f"/api/admin/users/{stu['id']}").json()["refusals"] == {}


def test_retry_fetch_keeps_the_students_contact_email(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    _register("stu")
    uid = db.get_by_username("stu")["id"]
    last = {"query": "sleep", "sources": ["pubmed"], "max_results": 10,
            "clear_first": False, "email": "kid@school.org"}
    monkeypatch.setattr(core, "snapshot_jobs", lambda _uid: {"fetch": {"last_fetch": last}})
    started = {}

    def fake_start(user_id, task, fn, **kwargs):
        started.update(kwargs)
        return True

    monkeypatch.setattr(core, "start_user_job", fake_start)
    r = client.post(
        f"/api/admin/users/{uid}/retry-fetch",
        json={"reason": "source was down"},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert started["email"] == "kid@school.org"
