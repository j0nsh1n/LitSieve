"""Provider API keys are encrypted in ai_settings.json, not stored in the clear."""

from __future__ import annotations

import json

import pytest

from app.services import llm


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "ai_settings.json"
    monkeypatch.setattr(llm, "AI_SETTINGS_PATH", path)
    monkeypatch.setattr(llm, "_SETTINGS_CACHE", None)
    monkeypatch.setenv("SECRET_KEY", "unit-test-secret-key")
    return path


def test_api_key_is_encrypted_on_disk_but_plaintext_in_memory(settings_file):
    saved = llm.save_ai_settings({"openai_api_key": "sk-super-secret", "openai_model": "gpt-4o-mini"})
    # Caller still sees the usable value.
    assert saved["openai_api_key"] == "sk-super-secret"

    raw = settings_file.read_text(encoding="utf-8")
    assert "sk-super-secret" not in raw
    stored = json.loads(raw)
    assert stored["openai_api_key"].startswith(llm.ENC_PREFIX)
    # Non-secret fields stay readable.
    assert stored["openai_model"] == "gpt-4o-mini"

    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["openai_api_key"] == "sk-super-secret"


def test_legacy_plaintext_file_still_loads_and_upgrades_on_save(settings_file):
    settings_file.write_text(json.dumps({"anthropic_api_key": "legacy-plain"}), encoding="utf-8")
    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["anthropic_api_key"] == "legacy-plain"

    llm.save_ai_settings({"openai_model": "gpt-4o-mini"})
    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert stored["anthropic_api_key"].startswith(llm.ENC_PREFIX)


def test_rotated_secret_key_drops_the_value_instead_of_leaking_ciphertext(settings_file, monkeypatch):
    llm.save_ai_settings({"openai_api_key": "sk-old-key"})
    monkeypatch.setenv("SECRET_KEY", "a-completely-different-secret")
    llm._SETTINGS_CACHE = None
    loaded = llm.load_ai_settings()
    # Must not hand a ciphertext blob to a provider as if it were a key.
    assert "openai_api_key" not in loaded


def test_public_settings_never_expose_the_key(settings_file):
    llm.save_ai_settings({"openai_api_key": "sk-super-secret"})
    public = llm.public_ai_settings()
    assert "sk-super-secret" not in json.dumps(public)
    assert public["openai_api_key_set"] is True
