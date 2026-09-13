"""Per-account AI keys must not mix a student's base URL with the host key."""

from __future__ import annotations

import json
import os

from app.services import llm


def _prep(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret-key")
    for k in (
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL",
        "OLLAMA_MODEL", "OLLAMA_HOST", "OLLAMA_MODELS", "LLM_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(k, raising=False)
    llm._SETTINGS_CACHE = None


def test_save_does_not_copy_key_into_process_env(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch)
    llm.save_ai_settings({"openai_api_key": "sk-student"}, user_id="user-a")
    assert os.environ.get("OPENAI_API_KEY") is None


def test_host_key_ignores_student_base_url(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-host")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm.save_ai_settings(
        {"openai_base_url": "https://evil.example/v1"},
        user_id="user-a",
    )
    with llm.ai_for_user("user-a"):
        rt = llm.runtime_ai()
    assert rt["openai_api_key"] == "sk-host"
    assert "evil.example" not in rt["openai_base_url"]
    assert rt["openai_base_url"].rstrip("/").endswith("api.openai.com/v1")


def test_student_own_key_may_set_base_url(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-host")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    llm.save_ai_settings(
        {
            "openai_api_key": "sk-student",
            "openai_base_url": "https://openrouter.ai/api/v1",
        },
        user_id="user-a",
    )
    with llm.ai_for_user("user-a"):
        rt = llm.runtime_ai()
    assert rt["openai_api_key"] == "sk-student"
    assert "openrouter.ai" in rt["openai_base_url"]


def test_settings_files_are_per_account_under_user_data_dir(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch)
    llm.save_ai_settings({"openai_api_key": "sk-a", "openai_model": "model-a"}, user_id="user-a")
    llm.save_ai_settings({"openai_api_key": "sk-b", "openai_model": "model-b"}, user_id="user-b")
    path_a = tmp_path / "data" / "user-a" / "ai_settings.json"
    path_b = tmp_path / "data" / "user-b" / "ai_settings.json"
    assert path_a.is_file()
    assert path_b.is_file()
    assert "sk-a" not in path_a.read_text(encoding="utf-8")
    stored_a = json.loads(path_a.read_text(encoding="utf-8"))
    assert stored_a["openai_model"] == "model-a"
    with llm.ai_for_user("user-a"):
        assert llm.load_ai_settings(force=True)["openai_api_key"] == "sk-a"
        pub = llm.public_ai_settings()
    with llm.ai_for_user("user-b"):
        assert llm.load_ai_settings(force=True)["openai_api_key"] == "sk-b"
        pub_b = llm.public_ai_settings()
    assert pub["openai_model"] == "model-a"
    assert pub_b["openai_model"] == "model-b"
    assert pub["openai_api_key_set"] is True
    assert "sk-a" not in json.dumps(pub)


def test_public_settings_do_not_claim_the_host_key(tmp_path, monkeypatch):
    _prep(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-host-secret")
    with llm.ai_for_user("user-a"):
        pub = llm.public_ai_settings()
    assert pub["openai_api_key_set"] is False
    assert "sk-host" not in json.dumps(pub)
