"""The Host tab's read-only facts and the Site tab's copy history."""

from __future__ import annotations

import json

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app


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


def test_host_facts_come_from_the_backup_folder_state_file_and_disk(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "litsieve-20261001-120000.tar.gz").write_bytes(b"x" * 10)
    (backups / "litsieve-20261014-120420.tar.gz").write_bytes(b"y" * 2048)
    (backups / "notes.txt").write_text("ignored")
    monkeypatch.setenv("BACKUP_DIR", str(backups))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "watchdog_state.json").write_text(json.dumps({
        "healthy": True, "since": "2026-10-14 12:00:00", "last_alert": None,
        "checked_at": "2026-10-15 07:30:00", "summary": "app ok; tunnel ok",
    }))
    monkeypatch.delenv("LITSIEVE_LAYA_URL", raising=False)
    r = client.get("/api/admin/host")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["backup"]["name"] == "litsieve-20261014-120420.tar.gz"
    assert body["backup"]["size_bytes"] == 2048
    assert body["backup"]["age_hours"] < 1
    assert body["watchdog"] == {
        "healthy": True, "since": "2026-10-14 12:00:00",
        "checked_at": "2026-10-15 07:30:00", "summary": "app ok; tunnel ok",
    }
    assert body["disk"]["free_bytes"] > 0
    assert body["disk"]["total_bytes"] >= body["disk"]["free_bytes"]
    assert body["laya"] == {"state": "unset"}
    assert "control_allowed" in body["ai"]
    assert str(tmp_path) not in r.text


def test_host_facts_degrade_to_none_and_laya_down(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "missing"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LITSIEVE_LAYA_URL", "http://127.0.0.1:1")
    r = client.get("/api/admin/host")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["backup"] is None
    assert body["watchdog"] is None
    assert body["laya"] == {"state": "down"}


def test_host_facts_are_admin_only(tmp_path, monkeypatch):
    _admin_client(tmp_path, monkeypatch)
    plain = _register("plainuser")
    assert plain.get("/api/admin/host").status_code == 403
    assert TestClient(app).get("/api/admin/host").status_code == 401


def test_copy_history_rolls_back_to_an_earlier_revision(tmp_path, monkeypatch):
    client, db = _admin_client(tmp_path, monkeypatch)
    for text in ("First notice.", "Second notice."):
        r = client.post(
            "/api/admin/content/known_issues",
            json={"reason": "editing", "body": text},
            headers=_csrf(client),
        )
        assert r.status_code == 200, r.text
    item = client.get("/api/admin/content").json()["items"]["known_issues"]
    assert item["revision"] == 2
    assert [rev["body"] for rev in item["revisions"]] == ["Second notice.", "First notice."]
    first_id = item["revisions"][1]["id"]
    r = client.post(
        "/api/admin/content/known_issues/rollback",
        json={"reason": "second was wrong", "revision_id": first_id},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["item"]["body"] == "First notice."
    assert r.json()["item"]["revision"] == 3
    r = client.post(
        "/api/admin/content/known_issues/rollback",
        json={"reason": "typo", "revision_id": "no-such-revision"},
        headers=_csrf(client),
    )
    assert r.status_code == 404
    admin_id = db.get_by_username("opadmin")["id"]
    actions = [a["action"] for a in db.list_support_actions(admin_id, limit=5)]
    assert actions[0] == "content-rollback"


def test_page_has_the_history_list_and_the_study_aid_buttons(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    html = client.get("/admin").text
    for needle in ('id="content-revisions"', 'id="ollama-start"', 'id="ollama-stop"', 'id="host-backup"', 'id="host-ship"'):
        assert needle in html, needle


def test_laya_health_that_is_not_an_object_counts_as_up_but_not_loaded(monkeypatch):
    import requests

    from app.routes import admin

    class _Resp:
        ok = True

        def json(self):
            return ["unexpected", "shape"]

    monkeypatch.setenv("LITSIEVE_LAYA_URL", "http://127.0.0.1:7880")
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp())
    assert admin._laya_status() == {"state": "up", "loaded": False}


def test_watchdog_times_are_shown_as_utc_times(tmp_path, monkeypatch):
    client, _ = _admin_client(tmp_path, monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "watchdog_state.json").write_text(json.dumps({
        "healthy": True, "since": 1787123751.458334, "last_alert": None,
        "checked_at": 1792109262.0758734, "summary": "all checks passed",
    }))
    body = client.get("/api/admin/host").json()
    assert body["watchdog"]["checked_at"] == "2026-10-16 00:07:42"
    assert body["watchdog"]["since"] == "2026-08-19 07:15:51"


def test_a_sleeping_laya_worker_reads_as_waking_not_down(monkeypatch):
    import requests

    from app.routes import admin

    def slow(*_a, **_k):
        raise requests.exceptions.ReadTimeout("socket accepted, worker loading")

    monkeypatch.setenv("LITSIEVE_LAYA_URL", "http://127.0.0.1:7880")
    monkeypatch.setattr(requests, "get", slow)
    assert admin._laya_status() == {"state": "waking"}
