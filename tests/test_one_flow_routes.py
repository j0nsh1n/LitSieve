"""HTTP coverage for the single Search flow and its legacy redirects."""

from __future__ import annotations

import json

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.main import app
from app.routes.auth import _safe_next_url
from app.services.embeddings import EmbeddingEngine
from app.storage.user_db import UserDatabase


def _client(tmp_path, monkeypatch) -> tuple[TestClient, UserDatabase]:
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    return TestClient(app), db


def _register(client: TestClient, username: str) -> None:
    response = client.post(
        "/register",
        data={
            "username": username,
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "/search?pickLook=1"


def test_former_pages_permanently_redirect_before_auth(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    for old_path in ("/data-management?collect=1", "/statistics?report=1", "/clusters?tab=2"):
        response = client.get(old_path, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/search"


def test_former_pages_redirect_signed_in_users_to_search(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _register(client, "oneflowstudent")
    client.cookies.set("ui_mode", "advanced")
    for old_path in ("/data-management", "/statistics", "/clusters"):
        response = client.get(old_path, follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/search"


def test_login_defaults_to_search_and_preserves_safe_next(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert _safe_next_url(None) == "/search"
    assert _safe_next_url("https://example.test") == "/search"
    assert _safe_next_url("//example.test") == "/search"
    assert _safe_next_url("/account") == "/account"

    login = client.get("/login")
    assert login.status_code == 200
    assert 'name="next"' not in login.text

    _register(client, "nextstudent")
    default_login = TestClient(app).post(
        "/login",
        data={"username": "nextstudent", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert default_login.status_code == 302
    assert default_login.headers["location"] == "/search"

    safe_login = TestClient(app).post(
        "/login",
        data={"username": "nextstudent", "password": TEST_PASSWORD, "next": "/account"},
        follow_redirects=False,
    )
    assert safe_login.status_code == 302
    assert safe_login.headers["location"] == "/account"

    unsafe_login = TestClient(app).post(
        "/login",
        data={"username": "nextstudent", "password": TEST_PASSWORD, "next": "https://example.test"},
        follow_redirects=False,
    )
    assert unsafe_login.status_code == 302
    assert unsafe_login.headers["location"] == "/search"


def test_registration_and_guest_do_not_seed_mode_cookie(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    _register(client, "cookiecheck")
    response = client.post(
        "/register",
        data={
            "username": "cookiecheck2",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "ui_mode_seed" not in response.cookies
    assert response.cookies.get("ui_look_prompt") == "1"

    from app.routes import auth

    class _GuestDb:
        def clear_all(self):
            pass

        def insert_articles(self, articles, dedupe=False):
            pass

    class _GuestPipeline:
        db = _GuestDb()

        def invalidate_corpus_cache(self):
            pass

    monkeypatch.setattr(auth, "get_pipeline", lambda _uid: _GuestPipeline())
    monkeypatch.setattr(auth, "release_pipeline", lambda _uid: None)
    monkeypatch.setattr(auth, "_start_guest_prepare", lambda _uid: None)
    guest_client = TestClient(app)
    guest = guest_client.get("/guest", follow_redirects=False)
    assert guest.status_code == 302
    assert guest.headers["location"] == "/search"
    assert "ui_mode_seed" not in guest.cookies


def test_search_nav_keeps_workspace_controls_admin_links_and_model_catalog(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ADMIN_USERNAMES", "catalogadmin")
    client, _ = _client(tmp_path, monkeypatch)
    _register(client, "catalogadmin")
    response = client.get("/search")
    assert response.status_code == 200
    html = response.text

    nav = html.split('<nav class="navbar app-shell"', 1)[1].split("</nav>", 1)[0]
    assert nav.count('href="/search"') == 1
    assert ">Search</a>" in nav
    assert 'href="/account"' in nav
    assert 'href="/admin"' in nav
    assert 'href="/ops"' in nav
    assert 'id="nav-library-select"' in html
    assert 'id="theme-toggle"' in html
    assert 'id="mode-toggle"' not in nav
    assert "Simple" not in nav
    assert "Advanced" not in nav
    assert "data-step-simple" not in nav
    assert "data-step-advanced" not in nav

    catalog = html.split('id="embedding-model-catalog" data-models=\'')[1].split("'", 1)[0]
    assert json.loads(catalog) == [
        {"value": name, "label": f"{name} ({path})"}
        for name, path in EmbeddingEngine.allowed_models().items()
    ]
