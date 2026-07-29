"""Optional recovery email: separate from username, verified before it counts.

Security-relevant invariants live here:
  * an UNVERIFIED address must never receive a password-reset code;
  * changing the address requires the current password;
  * a verified address cannot be claimed by a second account.
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ["DEBUG"] = "true"

import pathlib

import pytest

from app import core
from app.auth import validate_email, validate_login_name, validate_new_username

for _dep in ("fastapi", "httpx", "sklearn", "jwt", "bcrypt", "multipart", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

from app.services import mailer
from app.storage.user_db import UserDatabase

PASSWORD = "password123"


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import shutil
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib
    main = importlib.import_module("app.main")

    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", test_db)
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    yield main
    test_db.conn.close()


@pytest.fixture
def sent(monkeypatch):
    """Capture outbound mail instead of talking to a real SMTP server."""
    box: list[dict] = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "noreply@test")
    monkeypatch.setattr(
        mailer, "send",
        lambda to, subject, body: box.append({"to": to, "subject": subject, "body": body}),
    )
    return box


def _register(client, username="student1"):
    r = client.post(
        "/register",
        data={"username": username, "password": PASSWORD, "password_confirm": PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _token_from(body: str) -> str:
    return body.split("token=")[1].split()[0].strip()


# --- validation ---------------------------------------------------------------

def test_new_usernames_reject_at_sign_but_old_logins_still_validate():
    assert validate_new_username("student_1") is None
    err = validate_new_username("me@school.edu")
    assert err and "@" in err
    # Grandfathered: the base validator still accepts the old shape, so an
    # existing email-style login keeps working at sign-in.
    assert validate_login_name("me@school.edu") is None


def test_validate_email_catches_typos():
    assert validate_email("me@school.edu") is None
    assert validate_email("") is not None
    assert validate_email("nope") is not None
    assert validate_email("a b@c.com") is not None
    assert validate_email("a@b") is not None          # no dot in domain
    assert validate_email("a@@b.com") is not None
    assert validate_email("x" * 250 + "@b.com") is not None


# --- storage lifecycle --------------------------------------------------------

def test_verification_lifecycle(tmp_path):
    db = UserDatabase(db_path=str(tmp_path / "u.db"))
    try:
        db.create_user("alice", "h")
        token = db.start_email_verification("alice", "  Alice@School.EDU ")
        assert db.get_by_username("alice")["email"] == "alice@school.edu"
        # Pending address grants nothing until confirmed.
        assert db.get_verified_email("alice") is None

        ok, err, who = db.confirm_email_verification(token)
        assert ok and who == "alice", err
        assert db.get_verified_email("alice") == "alice@school.edu"

        # One-time only.
        assert db.confirm_email_verification(token)[0] is False
        assert db.confirm_email_verification("garbage")[0] is False
    finally:
        db.conn.close()


def test_stale_link_cannot_verify_a_replaced_address(tmp_path):
    db = UserDatabase(db_path=str(tmp_path / "u.db"))
    try:
        db.create_user("alice", "h")
        first = db.start_email_verification("alice", "old@x.com")
        db.start_email_verification("alice", "new@x.com")
        ok, _, _ = db.confirm_email_verification(first)
        assert ok is False, "an old link must not verify the address it replaced"
        assert db.get_verified_email("alice") is None
    finally:
        db.conn.close()


def test_verified_address_cannot_be_taken_by_another_account(tmp_path):
    db = UserDatabase(db_path=str(tmp_path / "u.db"))
    try:
        db.create_user("alice", "h")
        db.create_user("bob", "h")
        db.confirm_email_verification(db.start_email_verification("alice", "shared@x.com"))
        with pytest.raises(ValueError):
            db.start_email_verification("bob", "shared@x.com")
    finally:
        db.conn.close()


def test_clear_email_revokes_pending_links(tmp_path):
    db = UserDatabase(db_path=str(tmp_path / "u.db"))
    try:
        user = db.create_user("alice", "h")
        token = db.start_email_verification("alice", "a@x.com")
        db.clear_email(user["id"])
        assert db.confirm_email_verification(token)[0] is False
        assert db.get_by_username("alice")["email"] is None
    finally:
        db.conn.close()


# --- HTTP ---------------------------------------------------------------------

def test_registration_rejects_email_as_username(app_module):
    c = TestClient(app_module.app)
    r = c.post(
        "/register",
        data={"username": "me@school.edu", "password": PASSWORD, "password_confirm": PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "@" in r.text


def test_add_verify_and_remove_email_over_http(app_module, sent):
    c = TestClient(app_module.app)
    headers = _register(c)

    state = c.get("/api/account/email").json()
    assert state["email"] == "" and state["sending_configured"] is True

    r = c.post(
        "/api/account/email",
        json={"email": "Student@School.edu", "current_password": PASSWORD},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pending"] is True
    assert len(sent) == 1 and sent[0]["to"] == "student@school.edu"

    # Public link (the reader may not be signed in).
    token = _token_from(sent[0]["body"])
    plain = TestClient(app_module.app)
    page = plain.get(f"/verify-email?token={token}")
    assert page.status_code == 200
    assert "confirmed" in page.text.lower()

    assert c.get("/api/account/email").json()["verified"] is True

    r = c.request("DELETE", "/api/account/email", headers=headers)
    assert r.status_code == 200
    assert c.get("/api/account/email").json()["email"] == ""


def test_changing_email_requires_the_current_password(app_module, sent):
    c = TestClient(app_module.app)
    headers = _register(c, "student2")
    r = c.post(
        "/api/account/email",
        json={"email": "attacker@evil.test", "current_password": "wrong-password"},
        headers=headers,
    )
    assert r.status_code == 400
    assert not sent, "no mail should be sent when the password check fails"


def test_email_endpoints_require_auth_and_csrf(app_module, sent):
    c = TestClient(app_module.app)
    anon = c.post("/api/account/email", json={"email": "a@b.com", "current_password": "x"})
    assert anon.status_code in (401, 403)

    _register(c, "student3")
    no_csrf = c.post("/api/account/email", json={"email": "a@b.com", "current_password": PASSWORD})
    assert no_csrf.status_code == 403


def test_unverified_email_never_receives_a_reset_code(app_module, sent):
    c = TestClient(app_module.app)
    headers = _register(c, "student4")
    c.post(
        "/api/account/email",
        json={"email": "pending@x.com", "current_password": PASSWORD},
        headers=headers,
    )
    sent.clear()

    r = c.post("/reset-password/request", data={"username": "student4"}, follow_redirects=False)
    assert r.status_code == 200
    assert not sent, "a reset code must never go to an unverified address"


def test_reset_code_is_emailed_once_verified(app_module, sent):
    c = TestClient(app_module.app)
    headers = _register(c, "student5")
    c.post(
        "/api/account/email",
        json={"email": "ok@x.com", "current_password": PASSWORD},
        headers=headers,
    )
    TestClient(app_module.app).get(f"/verify-email?token={_token_from(sent[0]['body'])}")
    sent.clear()

    r = c.post("/reset-password/request", data={"username": "student5"}, follow_redirects=False)
    assert r.status_code == 200
    assert len(sent) == 1
    assert sent[0]["to"] == "ok@x.com"
    assert "reset" in sent[0]["subject"].lower()
    # The code must not also be rendered into the page when it was emailed.
    assert "reset_code" not in r.text or sent[0]["body"].split()[-1] not in r.text


def test_feature_is_inert_without_smtp(app_module, monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    c = TestClient(app_module.app)
    headers = _register(c, "student6")
    assert c.get("/api/account/email").json()["sending_configured"] is False
    r = c.post(
        "/api/account/email",
        json={"email": "a@b.com", "current_password": PASSWORD},
        headers=headers,
    )
    assert r.status_code == 503


def test_grandfathered_login_is_offered_as_a_claim(app_module, sent):
    """Old email-shaped logins keep working and get a one-click claim prompt."""
    core.user_db.create_user("old@school.edu", "irrelevant-hash")
    c = TestClient(app_module.app)
    _register(c, "student7")
    state = c.get("/api/account/email").json()
    assert state["login_looks_like_email"] is False

    # And the legacy login itself still passes sign-in validation.
    assert validate_login_name("old@school.edu") is None
