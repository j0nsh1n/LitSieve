from __future__ import annotations

import pathlib
import shutil

import pytest
from fastapi.testclient import TestClient

from app import core
from app.storage.user_db import AccountCapExceeded, UserDatabase

_CLOSED = "This host is not taking new accounts right now."


def test_total_account_cap_blocks_non_guest_users(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TOTAL_ACCOUNTS", "1")

    db = UserDatabase(db_path=str(tmp_path / "users.db"))
    try:
        db.create_user("alice", "hashed-pw")
        with pytest.raises(AccountCapExceeded, match="not taking new accounts"):
            db.create_user("bob", "hashed-pw-2")
    finally:
        db.conn.close()


def test_total_account_cap_allows_guest_users(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_TOTAL_ACCOUNTS", "1")

    db = UserDatabase(db_path=str(tmp_path / "users.db"))
    try:
        db.create_user("alice", "hashed-pw")
        guest = db.create_user("guest_tmp", "hashed-pw-guest", is_guest=True)
        assert guest["is_guest"] is True
    finally:
        db.conn.close()


@pytest.mark.parametrize("raw", [None, "", "0", "-3", "nope"])
def test_unset_or_zero_or_invalid_means_no_cap(tmp_path, monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv("MAX_TOTAL_ACCOUNTS", raising=False)
    else:
        monkeypatch.setenv("MAX_TOTAL_ACCOUNTS", raw)

    db = UserDatabase(db_path=str(tmp_path / f"users-{raw}.db"))
    try:
        db.create_user("alice", "hashed-pw")
        second = db.create_user("bob", "hashed-pw-2")
        assert second["username"] == "bob"
        assert db.registration_closed_reason() is None
    finally:
        db.conn.close()


# --- the user-facing path -----------------------------------------------------
# The tests above prove the storage layer refuses. They say nothing about what a
# student actually sees, which is the point of the feature: the cap has to
# surface as a rendered page, not a 500.


@pytest.fixture
def capped_app(tmp_path, monkeypatch):
    """App wired to a fresh accounts DB with room for exactly one real account."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAX_TOTAL_ACCOUNTS", "1")
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    monkeypatch.setenv("USERS_DB", str(tmp_path / "users.db"))

    import importlib

    main = importlib.import_module("app.main")
    previous = core.user_db
    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    yield main
    core.user_db.conn.close()
    core.user_db = previous


def _register(client, username):
    return client.post(
        "/register",
        data={
            "username": username,
            "password": "Str0ng-Pass-For-Tests",
            "password_confirm": "Str0ng-Pass-For-Tests",
        },
        follow_redirects=False,
    )


def test_registration_past_the_cap_renders_an_error_not_a_crash(capped_app):
    with TestClient(capped_app.app) as client:
        first = _register(client, "alice")
        assert first.status_code == 302, first.text

    with TestClient(capped_app.app) as client:
        second = _register(client, "bob")
        assert second.status_code == 403, second.text
        # A rendered page, not a stack trace or a bare JSON error.
        assert "<html" in second.text.lower()
        assert "auth-error" in second.text
        assert _CLOSED in second.text
        # And the account really was not created.
        assert core.user_db.get_by_username("bob") is None


def test_cap_does_not_lock_out_existing_accounts(capped_app):
    """Hitting the cap must close registration only, never login."""
    with TestClient(capped_app.app) as client:
        assert _register(client, "alice").status_code == 302

    with TestClient(capped_app.app) as client:
        assert _register(client, "bob").status_code == 403

    with TestClient(capped_app.app) as client:
        login = client.post(
            "/login",
            data={"username": "alice", "password": "Str0ng-Pass-For-Tests"},
            follow_redirects=False,
        )
        assert login.status_code == 302, login.text
        assert client.cookies.get("access_token")


def test_register_page_shows_cap_message_when_full(capped_app):
    with TestClient(capped_app.app) as client:
        assert _register(client, "alice").status_code == 302

    with TestClient(capped_app.app) as client:
        page = client.get("/register")
        assert page.status_code == 200, page.text
        assert "auth-error" in page.text
        assert _CLOSED in page.text


def test_guest_start_works_when_real_account_cap_is_full(capped_app):
    with TestClient(capped_app.app) as client:
        assert _register(client, "alice").status_code == 302

    with TestClient(capped_app.app) as client:
        started = client.get("/guest", follow_redirects=False)
        assert started.status_code in (302, 303), started.text
        assert started.headers.get("location") == "/search"
        assert client.cookies.get("access_token")
        assert core.user_db.account_counts()["guests"] >= 1
