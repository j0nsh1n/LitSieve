"""Operator change-and-ship pipeline: jail, denylist, validate, deploy, audit."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app.main import app


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, shell=False)
    _git(path, "config", "user.email", "ops@test.example")
    _git(path, "config", "user.name", "ops")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    (path / "app").mkdir()
    (path / "app" / "ok.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")


def _ops_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    staging = tmp_path / "staging"
    health = tmp_path / "health"
    _init_repo(repo)
    health.write_text("ok\n", encoding="utf-8")
    monkeypatch.setenv("LITSIEVE_REPO", str(repo))
    monkeypatch.setenv("LITSIEVE_LIVE", str(repo))
    monkeypatch.setenv("LITSIEVE_STAGING", str(staging))
    monkeypatch.setenv("LITSIEVE_SKIP_RESTART", "1")
    # These tests assert on the deploy's own verdict, so they need the blocking
    # path. The detached path is covered separately below; leaving it on here
    # would only ever assert that a dispatch receipt came back.
    monkeypatch.setenv("LITSIEVE_DEPLOY_DETACHED", "0")
    monkeypatch.setenv("LITSIEVE_HEALTH_MODE", "file")
    monkeypatch.setenv("LITSIEVE_HEALTH_FILE", str(health))
    return repo, staging, health


def _ops_client(tmp_path, monkeypatch, username="opadmin"):
    from app import core
    from app.storage.user_db import UserDatabase

    _ops_env(tmp_path, monkeypatch)
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
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


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


def _reauth(client) -> None:
    r = client.post(
        "/api/ops/reauth",
        json={"password": TEST_PASSWORD},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text


def test_ops_page_is_ide_workbench(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    page = client.get("/ops")
    assert page.status_code == 200, page.text
    html = page.text
    for needle in (
        "ops-ide",
        "ops-activity",
        "ops-sidebar",
        "ops-statusbar",
        "ops-editor",
        "ops-ttl",
        "ops-reauth",
        "ops-lock",
        "ops.js?v=",
    ):
        assert needle in html, needle


def test_non_operator_gets_403_on_every_ops_endpoint(tmp_path, monkeypatch):
    from app import core
    from app.storage.user_db import UserDatabase

    _ops_env(tmp_path, monkeypatch)
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
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
    assert r.status_code in (302, 303)
    headers = _csrf(client)
    page = client.get("/ops", follow_redirects=False)
    assert page.status_code in (302, 303)
    for method, path in (
        ("GET", "/api/ops/files"),
        ("GET", "/api/ops/file?path=README.md"),
        ("GET", "/api/ops/diff"),
        ("GET", "/api/ops/status"),
        ("GET", "/api/ops/audit"),
        ("POST", "/api/ops/file"),
        ("POST", "/api/ops/validate"),
        ("POST", "/api/ops/commit"),
        ("POST", "/api/ops/deploy"),
        ("POST", "/api/ops/rollback"),
        ("POST", "/api/ops/revert-last"),
        ("POST", "/api/ops/reauth"),
        ("POST", "/api/ops/lock"),
        ("POST", "/api/ops/grok"),
    ):
        if method == "GET":
            out = client.get(path)
        else:
            out = client.post(path, json={"path": "README.md", "content": "x"}, headers=headers)
        assert out.status_code == 403, path


def test_path_escape_and_denylist_rejected(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    files = client.get("/api/ops/files")
    assert files.status_code == 200, files.text
    names = files.json()["files"]
    assert "README.md" in names
    assert not any(n.startswith(".env") or n.startswith(".git") or "user_data" in n for n in names)

    for bad in ("../etc/passwd", "/etc/passwd", "..\\windows", ".env", "secrets/cloudflared.token", "user_data/x.py"):
        out = client.get("/api/ops/file", params={"path": bad})
        assert out.status_code == 400, bad

    staging = Path(tmp_path / "staging")
    (staging / ".env").write_text("SECRET_KEY=nope\n", encoding="utf-8")
    (staging / "secrets").mkdir(exist_ok=True)
    (staging / "secrets" / "token").write_text("t\n", encoding="utf-8")
    env_read = client.get("/api/ops/file", params={"path": ".env"})
    assert env_read.status_code == 400
    secret_read = client.get("/api/ops/file", params={"path": "secrets/token"})
    assert secret_read.status_code == 400

    _reauth(client)
    env_write = client.post(
        "/api/ops/file",
        json={"path": ".env", "content": "SECRET_KEY=x\n"},
        headers=_csrf(client),
    )
    assert env_write.status_code == 400
    abs_write = client.post(
        "/api/ops/file",
        json={"path": "/tmp/evil.py", "content": "x = 1\n"},
        headers=_csrf(client),
    )
    assert abs_write.status_code == 400

    target = tmp_path / "outside.txt"
    target.write_text("secret-outside\n", encoding="utf-8")
    link = staging / "escape.py"
    link.symlink_to(target)
    escaped = client.get("/api/ops/file", params={"path": "escape.py"})
    assert escaped.status_code == 400


def test_binary_and_oversize_writes_rejected(tmp_path, monkeypatch):
    client, db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    binary = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "ok\x00nope"},
        headers=_csrf(client),
    )
    assert binary.status_code == 400
    huge = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "a" * (512 * 1024 + 8)},
        headers=_csrf(client),
    )
    assert huge.status_code == 400
    rows = [e["action"] for e in client.get("/api/ops/audit").json()["entries"]]
    assert "save_file" in rows


def test_validation_failure_blocks_commit_and_deploy(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    bad = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "def (\n"},
        headers=_csrf(client),
    )
    assert bad.status_code == 200, bad.text
    val = client.post("/api/ops/validate", json={}, headers=_csrf(client))
    assert val.status_code == 400
    commit = client.post(
        "/api/ops/commit",
        json={"message": "broken syntax"},
        headers=_csrf(client),
    )
    assert commit.status_code == 400
    assert "validate" in commit.json()["detail"].lower()
    deploy = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY"},
        headers=_csrf(client),
    )
    assert deploy.status_code == 400


def test_deploy_health_fail_rolls_back_and_audits(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    live = Path(tmp_path / "repo")
    before = subprocess.check_output(["git", "-C", str(live), "rev-parse", "HEAD"], text=True).strip()
    save = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "VALUE = 2\n"},
        headers=_csrf(client),
    )
    assert save.status_code == 200, save.text
    val = client.post("/api/ops/validate", json={}, headers=_csrf(client))
    assert val.status_code == 200, val.text
    commit = client.post(
        "/api/ops/commit",
        json={"message": "bump value"},
        headers=_csrf(client),
    )
    assert commit.status_code == 200, commit.text
    health = Path(tmp_path / "health")
    health.write_text("fail\n", encoding="utf-8")
    deploy = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY", "sha": commit.json()["sha"]},
        headers=_csrf(client),
    )
    assert deploy.status_code == 400, deploy.text
    assert deploy.json().get("rolled_back") is True
    after = subprocess.check_output(["git", "-C", str(live), "rev-parse", "HEAD"], text=True).strip()
    assert after == before
    audit = client.get("/api/ops/audit").json()["entries"]
    actions = [e["action"] for e in audit]
    assert "save_file" in actions
    assert "validate" in actions
    assert "commit" in actions
    assert "deploy" in actions
    assert any(e["action"] == "deploy" and e["result"] == "fail" for e in audit)


def test_save_requires_reauth_and_writes_audit(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    missing = client.post(
        "/api/ops/file",
        json={"path": "README.md", "content": "hello again\n"},
        headers=_csrf(client),
    )
    assert missing.status_code == 403
    assert missing.json().get("reauth") is True
    _reauth(client)
    ok = client.post(
        "/api/ops/file",
        json={"path": "README.md", "content": "hello again\n"},
        headers=_csrf(client),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json().get("after_hash")
    audit = client.get("/api/ops/audit").json()["entries"]
    assert audit[0]["action"] == "save_file"
    assert audit[0]["result"] == "ok"
    assert audit[0]["path"] == "README.md"


def test_unlock_hold_keeps_session_open_while_grok_busy(tmp_path, monkeypatch):
    from app.routes import ops as ops_mod

    ops_mod._unlock_holds.clear()
    client, db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    uid = db.get_by_username("opadmin")["id"]
    ops_mod._begin_unlock_hold(uid, "ask_grok", remaining=90, timeout=180)
    client.cookies.set("ops_reauth", "expired:1:dead")
    st = client.get("/api/ops/status").json()
    assert st["reauth"] is True
    assert st["unlock_hold"] == "ask_grok"
    assert st["reauth_until"] > 0
    saved = client.post(
        "/api/ops/file",
        json={"path": "README.md", "content": "still open\n"},
        headers=_csrf(client),
    )
    assert saved.status_code == 200, saved.text
    locked = client.post("/api/ops/lock", json={}, headers=_csrf(client))
    assert locked.status_code == 200, locked.text
    st2 = client.get("/api/ops/status").json()
    assert st2["reauth"] is False
    assert not st2.get("unlock_hold")
    blocked = client.post(
        "/api/ops/file",
        json={"path": "README.md", "content": "x\n"},
        headers=_csrf(client),
    )
    assert blocked.status_code == 403
    assert blocked.json().get("reauth") is True


def test_ask_grok_pauses_unlock_clock_until_finished(tmp_path, monkeypatch):
    from app.routes import ops as ops_mod

    ops_mod._unlock_holds.clear()
    stub = tmp_path / "grok"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('grok 0.0-test')\n"
        "    sys.exit(0)\n"
        "print('held the lock')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("GROK_BIN", str(stub))
    client, _db = _ops_client(tmp_path, monkeypatch)
    opened = client.post(
        "/api/ops/reauth",
        json={"password": TEST_PASSWORD, "minutes": 5},
        headers=_csrf(client),
    )
    assert opened.status_code == 200, opened.text
    seen = {}
    real = ops_mod.run_action

    def wrap(action, argv=None, **kwargs):
        if action == "ask_grok":
            assert ops_mod._unlock_holds, "hold should start before Grok runs"
            uid = next(iter(ops_mod._unlock_holds))
            seen["hold"] = dict(ops_mod._unlock_holds[uid])
        return real(action, argv, **kwargs)

    monkeypatch.setattr(ops_mod, "run_action", wrap)
    asked = client.post(
        "/api/ops/grok",
        json={"prompt": "summarize the staging tree", "path": "README.md"},
        headers=_csrf(client),
    )
    assert asked.status_code == 200, asked.text
    assert seen.get("hold", {}).get("action") == "ask_grok"
    assert seen["hold"]["remaining"] >= 60
    assert not ops_mod._unlock_holds
    set_cookie = asked.headers.get("set-cookie") or ""
    assert "ops_reauth=" in set_cookie.lower()
    st = client.get("/api/ops/status").json()
    assert st["reauth"] is True
    assert not st.get("unlock_hold")
    assert st["reauth_until"] > 0


def test_ops_lock_and_custom_unlock_duration(tmp_path, monkeypatch):
    client, _db = _ops_client(tmp_path, monkeypatch)
    bad = client.post(
        "/api/ops/reauth",
        json={"password": TEST_PASSWORD, "minutes": 99999},
        headers=_csrf(client),
    )
    assert bad.status_code == 400
    opened = client.post(
        "/api/ops/reauth",
        json={"password": TEST_PASSWORD, "minutes": 30},
        headers=_csrf(client),
    )
    assert opened.status_code == 200, opened.text
    assert opened.json()["ttl"] == 30 * 60
    st = client.get("/api/ops/status").json()
    assert st["reauth"] is True
    assert st["reauth_until"] > 0
    locked = client.post("/api/ops/lock", json={}, headers=_csrf(client))
    assert locked.status_code == 200, locked.text
    st2 = client.get("/api/ops/status").json()
    assert st2["reauth"] is False
    blocked = client.post(
        "/api/ops/file",
        json={"path": "README.md", "content": "x\n"},
        headers=_csrf(client),
    )
    assert blocked.status_code == 403
    assert blocked.json().get("reauth") is True


def test_grok_status_and_ask_requires_reauth(tmp_path, monkeypatch):
    stub = tmp_path / "grok"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--version' in sys.argv:\n"
        "    print('grok 0.0-test')\n"
        "    sys.exit(0)\n"
        "print('reviewed staging')\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("GROK_BIN", str(stub))
    client, _db = _ops_client(tmp_path, monkeypatch)
    status = client.get("/api/ops/status")
    assert status.status_code == 200, status.text
    grok = status.json().get("grok") or {}
    assert grok.get("available") is True
    assert grok.get("connected") is True
    locked = client.post(
        "/api/ops/grok",
        json={"prompt": "explain README.md"},
        headers=_csrf(client),
    )
    assert locked.status_code == 403
    _reauth(client)
    empty = client.post("/api/ops/grok", json={"prompt": ""}, headers=_csrf(client))
    assert empty.status_code == 400
    asked = client.post(
        "/api/ops/grok",
        json={"prompt": "summarize the staging tree", "path": "README.md"},
        headers=_csrf(client),
    )
    assert asked.status_code == 200, asked.text
    assert "reviewed" in (asked.json().get("text") or "").lower()
    actions = [e["action"] for e in client.get("/api/ops/audit").json()["entries"]]
    assert "ask_grok" in actions


def test_new_operator_code_has_no_shell_true():
    root = Path(__file__).resolve().parent.parent
    hits = []
    for path in list((root / "app" / "operator").glob("*.py")) + list((root / "tools" / "operator").glob("*.py")) + [root / "app" / "routes" / "ops.py"]:
        text = path.read_text(encoding="utf-8")
        stripped = re.sub(r'""".*?"""', "", text, flags=re.S)
        stripped = re.sub(r"#.*", "", stripped)
        if re.search(r"shell\s*=\s*True", stripped):
            hits.append(str(path))
    assert hits == []


def test_deploy_refuses_when_live_has_uncommitted_tracked_changes(tmp_path, monkeypatch):
    """Deploy resets the live checkout hard; uncommitted tracked work must block it."""
    client, _db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    live = Path(tmp_path / "repo")

    save = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "VALUE = 3\n"},
        headers=_csrf(client),
    )
    assert save.status_code == 200, save.text
    val = client.post("/api/ops/validate", json={}, headers=_csrf(client))
    assert val.status_code == 200, val.text
    commit = client.post(
        "/api/ops/commit", json={"message": "bump value"}, headers=_csrf(client)
    )
    assert commit.status_code == 200, commit.text
    sha = commit.json()["sha"]

    # Uncommitted edit to a TRACKED file in the live checkout.
    tracked = live / "app" / "ok.py"
    tracked.write_text("VALUE = 999  # unsaved work\n", encoding="utf-8")
    before = subprocess.check_output(
        ["git", "-C", str(live), "rev-parse", "HEAD"], text=True
    ).strip()

    deploy = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY", "sha": sha},
        headers=_csrf(client),
    )
    assert deploy.status_code == 400, deploy.text
    body = deploy.json()
    assert "uncommitted" in (body.get("detail") or "").lower(), body
    assert body.get("dirty_live"), body

    # The edit survived and the live HEAD did not move.
    assert tracked.read_text(encoding="utf-8") == "VALUE = 999  # unsaved work\n"
    after = subprocess.check_output(
        ["git", "-C", str(live), "rev-parse", "HEAD"], text=True
    ).strip()
    assert after == before


def test_deploy_ignores_untracked_files_in_live(tmp_path, monkeypatch):
    """Untracked files survive `git reset --hard`, so they must not block deploy."""
    client, _db = _ops_client(tmp_path, monkeypatch)
    _reauth(client)
    live = Path(tmp_path / "repo")
    (live / "scratch_notes.md").write_text("untracked\n", encoding="utf-8")

    save = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "VALUE = 4\n"},
        headers=_csrf(client),
    )
    assert save.status_code == 200, save.text
    val = client.post("/api/ops/validate", json={}, headers=_csrf(client))
    assert val.status_code == 200, val.text
    commit = client.post(
        "/api/ops/commit", json={"message": "bump value"}, headers=_csrf(client)
    )
    assert commit.status_code == 200, commit.text

    deploy = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY", "sha": commit.json()["sha"]},
        headers=_csrf(client),
    )
    assert deploy.status_code == 200, deploy.text
    assert (live / "scratch_notes.md").exists()


# --- A04: deploy state survives the process that writes it -------------------

def test_deploy_state_records_previous_sha_before_touching_the_checkout(tmp_path, monkeypatch):
    """The one fact a recovery cannot reconstruct must be on disk first.

    A04: _restart_service() can kill this process mid-deploy. If previous_sha
    only ever lived in a local variable, a bad deploy would be unrecoverable
    without reading the reflog. Assert ordering, not just presence: the record
    must exist while the checkout is still at the OLD revision.
    """
    from app.operator import actions, deploy_state

    repo, _staging, _health = _ops_env(tmp_path, monkeypatch)
    monkeypatch.setenv("LITSIEVE_DEPLOY_STATE", str(tmp_path / "deploy-state.json"))
    before = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    seen = {}
    real_reset = actions.gitutil.reset_hard

    def _spy(root, sha):
        # Called before the checkout moves; capture what recovery would find.
        seen["record"] = deploy_state.read()
        seen["head_at_reset"] = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        return real_reset(root, sha)

    monkeypatch.setattr(actions.gitutil, "reset_hard", _spy)
    actions._do_deploy(before)

    record = seen.get("record")
    assert record, "no deploy state existed when the checkout was about to move"
    assert record["previous_sha"] == before
    assert seen["head_at_reset"] == before, "state was written after the reset, too late"


def test_interrupted_deploy_is_distinguishable_from_no_deploy(tmp_path, monkeypatch):
    """A killed deploy must not look like an idle system."""
    from app.operator import deploy_state

    monkeypatch.setenv("LITSIEVE_DEPLOY_STATE", str(tmp_path / "deploy-state.json"))
    assert deploy_state.interrupted() is None

    deploy_state.begin(sha="a" * 40, previous_sha="b" * 40, actor_username="op")
    deploy_state.write(phase=deploy_state.PHASE_RESTARTING)
    stuck = deploy_state.interrupted()
    assert stuck is not None, "a deploy killed mid-restart reported nothing in flight"
    assert stuck["previous_sha"] == "b" * 40

    deploy_state.finish(result="ok")
    assert deploy_state.interrupted() is None


def test_deploy_state_write_is_atomic_and_survives_corruption(tmp_path, monkeypatch):
    """A damaged record must not take the deploy down with it."""
    from app.operator import deploy_state

    path = tmp_path / "deploy-state.json"
    monkeypatch.setenv("LITSIEVE_DEPLOY_STATE", str(path))
    deploy_state.begin(sha="c" * 40, previous_sha="d" * 40)
    assert deploy_state.read()["previous_sha"] == "d" * 40

    path.write_text("{ truncated", encoding="utf-8")
    assert deploy_state.read() is None
    assert deploy_state.interrupted() is None
    # and it recovers: a fresh begin() overwrites the damaged file
    deploy_state.begin(sha="e" * 40, previous_sha="f" * 40)
    assert deploy_state.read()["previous_sha"] == "f" * 40
    assert not list(path.parent.glob(".deploy-state-*.tmp")), "temp file left behind"


# --- A04: the detached path, which is what production actually runs ----------
# _ops_env pins LITSIEVE_DEPLOY_DETACHED=0 so the older tests can assert on a
# deploy verdict. These drive the path that runs when systemd-run exists.


def _fake_systemd_run(tmp_path, monkeypatch, *, rc=0):
    """Put a recording stub named systemd-run at the front of PATH."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "systemd-run.log"
    stub = bindir / "systemd-run"
    stub.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" >> "{log}"\n'
        f"exit {rc}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ.get('PATH', '')}")
    return log


def test_deploy_dispatches_into_its_own_unit_and_returns_immediately(tmp_path, monkeypatch):
    """A04: the request must not wait for a deploy that will kill the server.

    The restart inside the deploy tears down this worker's control group, so a
    synchronous response could never arrive. Assert the handoff, and assert the
    unit is transient and carries the actor.
    """
    client, _db = _ops_client(tmp_path, monkeypatch)
    monkeypatch.delenv("LITSIEVE_DEPLOY_DETACHED", raising=False)
    log = _fake_systemd_run(tmp_path, monkeypatch)
    _reauth(client)

    save = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "VALUE = 3\n"},
        headers=_csrf(client),
    )
    assert save.status_code == 200, save.text
    assert client.post("/api/ops/validate", json={}, headers=_csrf(client)).status_code == 200
    commit = client.post(
        "/api/ops/commit", json={"message": "bump"}, headers=_csrf(client)
    )
    assert commit.status_code == 200, commit.text
    sha = commit.json()["sha"]

    resp = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY", "sha": sha},
        headers=_csrf(client),
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body.get("dispatched") is True
    assert body.get("unit", "").startswith("litsieve-deploy-")

    args = log.read_text(encoding="utf-8")
    assert "--user" in args
    assert "--collect" in args, "unit must be transient, or a failed deploy blocks the next one"
    assert "LITSIEVE_DEPLOY_ACTOR=opadmin" in args, "deploy cannot write its audit row without the actor"
    # The handoff must not carry the coupling that caused A04 in the first place.
    assert "litsieve-uvicorn.service" not in args


def test_deploy_refuses_to_start_on_top_of_an_interrupted_one(tmp_path, monkeypatch):
    """A stuck record means the live checkout is at an unknown revision."""
    from app.operator import deploy_state

    client, _db = _ops_client(tmp_path, monkeypatch)
    monkeypatch.delenv("LITSIEVE_DEPLOY_DETACHED", raising=False)
    monkeypatch.setenv("LITSIEVE_DEPLOY_STATE", str(tmp_path / "deploy-state.json"))
    _fake_systemd_run(tmp_path, monkeypatch)
    _reauth(client)

    save = client.post(
        "/api/ops/file",
        json={"path": "app/ok.py", "content": "VALUE = 4\n"},
        headers=_csrf(client),
    )
    assert save.status_code == 200
    assert client.post("/api/ops/validate", json={}, headers=_csrf(client)).status_code == 200
    commit = client.post(
        "/api/ops/commit", json={"message": "bump again"}, headers=_csrf(client)
    )
    assert commit.status_code == 200

    deploy_state.begin(sha="f" * 40, previous_sha="e" * 40, actor_username="opadmin")
    deploy_state.write(phase=deploy_state.PHASE_RESTARTING)

    resp = client.post(
        "/api/ops/deploy",
        json={"confirm": "DEPLOY", "sha": commit.json()["sha"]},
        headers=_csrf(client),
    )
    assert resp.status_code == 409, resp.text
    assert "in flight" in resp.json().get("detail", "")


def test_deploy_state_endpoint_reports_progress_and_requires_operator(tmp_path, monkeypatch):
    from app.operator import deploy_state

    client, _db = _ops_client(tmp_path, monkeypatch)
    monkeypatch.setenv("LITSIEVE_DEPLOY_STATE", str(tmp_path / "deploy-state.json"))

    idle = client.get("/api/ops/deploy-state")
    assert idle.status_code == 200, idle.text
    assert idle.json()["in_flight"] is False

    deploy_state.begin(sha="a" * 40, previous_sha="b" * 40, actor_username="opadmin")
    deploy_state.write(phase=deploy_state.PHASE_HEALTH)
    busy = client.get("/api/ops/deploy-state").json()
    assert busy["in_flight"] is True
    assert busy["phase"] == deploy_state.PHASE_HEALTH
    assert busy["record"]["previous_sha"] == "b" * 40

    deploy_state.finish(result="ok")
    done = client.get("/api/ops/deploy-state").json()
    assert done["in_flight"] is False
    assert done["record"]["result"] == "ok"


# --- A05: operator work must not stall the single web worker ------------------


def test_operator_action_does_not_block_the_event_loop(tmp_path, monkeypatch):
    """A05: ops routes await blocking work instead of running it inline.

    The host runs one uvicorn worker. `validate` can occupy 240 s and other
    actions 180 s; run inline, nothing else — including /health — is served for
    that whole window. The audit reproduced this with a 200 ms stub and a 10 ms
    timer that fired late.

    Asserted the same way, against the route rather than the helper: a timer
    scheduled while a slow action runs must still fire near its own deadline.
    """
    import asyncio
    import time

    from app.routes import ops as ops_mod

    slow = 0.4

    def _slow_action(action, argv=None, **kwargs):
        time.sleep(slow)
        return {"ok": True, "empty": False, "staging_sha": "0" * 40}

    monkeypatch.setattr(ops_mod, "run_action", _slow_action)

    async def _drive():
        loop = asyncio.get_running_loop()
        fired_at = {}
        start = loop.time()

        def _tick():
            fired_at["t"] = loop.time() - start

        loop.call_later(0.02, _tick)
        # The route helper is what production awaits; call it the same way.
        await ops_mod.run_in_thread(ops_mod.run_action, "diff")
        return fired_at.get("t"), loop.time() - start

    tick, total = asyncio.run(_drive())
    assert total >= slow, "the slow action did not actually run"
    assert tick is not None, "the timer never fired"
    # Blocked, this lands at ~slow. Awaited, it lands near its own 20 ms deadline.
    assert tick < slow / 2, (
        f"timer fired {tick:.3f}s into a {slow:.1f}s action — the event loop was blocked"
    )


def test_ops_routes_never_call_run_action_inline():
    """Contract: a future route must not reintroduce the stall.

    Greps rather than exercises, because the failure is a missing `await` that
    no single test would notice — the route still works, it just freezes
    everything else while it does.
    """
    import re

    src = (Path(__file__).resolve().parent.parent / "app" / "routes" / "ops.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    bare = [
        m.start()
        for m in re.finditer(r"(?<!run_in_thread\()(?<!, )\brun_action\(", code)
        if "import" not in code[max(0, m.start() - 60):m.start()]
    ]
    assert not bare, (
        f"{len(bare)} call(s) to run_action() outside run_in_thread in ops.py; "
        "wrap them or the single worker stalls for the action's duration"
    )
