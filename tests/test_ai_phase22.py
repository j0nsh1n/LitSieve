"""Audit 22.1-22.6: account AI status, Ollama model, URL and timeout checks, gate."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_integration_accounts import _register, app_module  # noqa: F401

from app.services import llm

ROOT = Path(__file__).resolve().parents[1]


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_settings_status_is_computed_for_the_account():
    src = (ROOT / "app" / "routes" / "ai.py").read_text()
    get = src[src.index("async def api_ai_settings_get"):src.index('@router.post("/api/ai/settings")')]
    with_block = get[get.index("with ai_for_user("):get.index("# Ollama start/stop")]
    assert "status_detail = ai_status()" in with_block


def test_choosing_an_installed_model_never_touches_the_environment(monkeypatch):
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(llm, "list_ollama_models", lambda *a, **k: ["qwen2.5:3b"])
    monkeypatch.setattr(llm, "_INSTALLED_OLLAMA_DEFAULT", None)
    with llm.ai_for_user(None):
        assert llm._ensure_ollama_model_env() == "qwen2.5:3b"
    assert "OLLAMA_MODEL" not in os.environ


def test_the_settings_payload_has_no_server_path():
    src = (ROOT / "app" / "services" / "llm.py").read_text()
    payload = src[src.index("def public_ai_settings("):src.index("def ollama_control_allowed(")]
    assert "settings_path" not in payload


@pytest.mark.parametrize("url", [
    "http://api.example.com/v1",          # not https
    "https://127.0.0.1/v1",               # loopback
    "https://10.0.0.5/v1",                # private
    "https://192.168.12.1:8443/v1",       # private, with port
    "https://169.254.169.254/latest",     # link-local metadata
    "https://[::1]/v1",                   # IPv6 loopback
])
def test_local_and_private_base_urls_are_refused(url, monkeypatch):
    monkeypatch.delenv("AI_ALLOW_PRIVATE_BASE_URL", raising=False)
    assert llm.base_url_problem(url)


def test_a_public_address_is_allowed_and_the_host_can_allow_private(monkeypatch):
    monkeypatch.delenv("AI_ALLOW_PRIVATE_BASE_URL", raising=False)
    assert llm.base_url_problem("https://1.1.1.1/v1") is None
    monkeypatch.setenv("AI_ALLOW_PRIVATE_BASE_URL", "true")
    assert llm.base_url_problem("https://10.0.0.5/v1") is None


def test_the_timeout_is_held_between_five_seconds_and_five_minutes(monkeypatch):
    for saved, used in (("1", 5.0), ("100000", 300.0), ("60", 60.0), ("nan", 120.0)):
        monkeypatch.setattr(llm, "runtime_ai", lambda saved=saved: {"llm_timeout_seconds": saved})
        assert llm._timeout() == used


def test_saving_a_private_url_or_a_wild_timeout_is_refused(app_module, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_SETTINGS_WRITE", "true")
    client = TestClient(app_module.app)
    _register(client, "aisave")
    r = client.post("/api/ai/settings", json={"openai_base_url": "https://127.0.0.1/v1"}, headers=_csrf(client))
    assert r.status_code == 400
    r = client.post("/api/ai/settings", json={"llm_timeout_seconds": "9999"}, headers=_csrf(client))
    assert r.status_code == 400
    assert "between 5 and 300" in r.json()["detail"]


def test_hidden_ai_buttons_also_switch_the_routes_off(app_module, monkeypatch):
    monkeypatch.setenv("HIDE_AI_BUTTONS", "true")
    client = TestClient(app_module.app)
    _register(client, "aioff")
    for path, body in (
        ("/api/ai/refine-article", {"article_id": "1", "source": "pubmed"}),
        ("/api/ai/ask-article", {"article_id": "1", "source": "pubmed", "question": "What?"}),
        ("/api/reader/explain", {"article_id": "1", "source": "pubmed"}),
    ):
        r = client.post(path, json=body, headers=_csrf(client))
        assert r.status_code == 403, (path, r.text)
        assert "turned off" in r.json()["detail"]
