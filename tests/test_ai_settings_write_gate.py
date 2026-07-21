"""HTTP tests for AI_ALLOW_SETTINGS_WRITE gate on settings / ollama control."""

import os
import pathlib

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest

for _dep in (
    "fastapi", "httpx", "Bio", "sklearn", "plotly", "tqdm",
    "slowapi", "jwt", "passlib", "multipart", "requests", "dotenv",
):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import shutil

    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib

    main = importlib.import_module("main")
    from user_db import UserDatabase

    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(main, "user_db", test_db)
    main._pipelines.clear()
    main._pipeline_refcounts.clear()
    main._all_progress.clear()
    try:
        main.limiter.reset()
    except Exception:
        pass
    yield main
    test_db.conn.close()


def _register(client, username="writegate_user", password="tpw-fixture-0001"):
    resp = client.post(
        "/register",
        data={"username": username, "password": password, "password_confirm": password},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    assert client.cookies.get("access_token")
    assert client.cookies.get("csrf_token")


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_settings_get_reports_write_allowed_true(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "true")
    c = TestClient(app_module.app)
    _register(c)
    r = c.get("/api/ai/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["settings_write_allowed"] is True


def test_settings_get_reports_write_allowed_false(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "false")
    c = TestClient(app_module.app)
    _register(c)
    r = c.get("/api/ai/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["settings_write_allowed"] is False


def test_settings_post_forbidden_when_write_disabled(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "false")
    c = TestClient(app_module.app)
    _register(c)
    r = c.post(
        "/api/ai/settings",
        json={"openai_model": "gpt-4o-mini"},
        headers=_csrf(c),
    )
    assert r.status_code == 403
    assert "AI_ALLOW_SETTINGS_WRITE" in r.json().get("detail", "")


def test_settings_post_ok_when_write_enabled(app_module, monkeypatch, tmp_path):
    import llm_service

    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "true")
    settings_path = tmp_path / "user_data" / "ai_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(llm_service, "AI_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(llm_service, "_SETTINGS_CACHE", None)

    c = TestClient(app_module.app)
    _register(c)
    r = c.post(
        "/api/ai/settings",
        json={"openai_model": "gpt-4o-mini", "llm_provider": "openai"},
        headers=_csrf(c),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "success"
    assert body["settings"]["openai_model"] == "gpt-4o-mini"


def test_ollama_start_forbidden_when_write_disabled(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "false")
    c = TestClient(app_module.app)
    _register(c)
    r = c.post("/api/ai/ollama/start", headers=_csrf(c))
    assert r.status_code == 403
    assert "disabled" in r.json().get("detail", "").lower()


def test_ollama_stop_forbidden_when_write_disabled(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "false")
    c = TestClient(app_module.app)
    _register(c)
    r = c.post("/api/ai/ollama/stop", headers=_csrf(c))
    assert r.status_code == 403
    assert "disabled" in r.json().get("detail", "").lower()
