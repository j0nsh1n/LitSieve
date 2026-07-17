"""Unit tests for optional AI helpers (no network; providers mocked)."""

import pytest

import llm_service


def _clear_providers(monkeypatch):
    for k in (
        "OLLAMA_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "LLM_PROVIDER", "OPENAI_BASE_URL", "OPENAI_MODEL", "LLM_MODEL",
        "OLLAMA_MODELS", "OLLAMA_HOST",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm_service, "_SETTINGS_CACHE", {})
    monkeypatch.setattr(llm_service, "load_ai_settings", lambda force=False: {})


def test_provider_none_when_unconfigured(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert llm_service.provider() is None
    assert llm_service.is_configured() is False
    st = llm_service.status()
    assert st["provider"] is None
    assert "No AI configured" in st["detail"]


def test_provider_prefers_ollama_in_auto(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert llm_service.provider() == "ollama"


def test_provider_openai_before_anthropic_in_auto(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert llm_service.provider() == "openai"


def test_provider_force_anthropic(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert llm_service.provider() == "anthropic"


def test_save_and_load_ai_settings(tmp_path, monkeypatch):
    for k in (
        "OLLAMA_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "LLM_PROVIDER", "OPENAI_BASE_URL", "OPENAI_MODEL", "LLM_MODEL",
        "OLLAMA_MODELS", "OLLAMA_HOST",
    ):
        monkeypatch.delenv(k, raising=False)
    path = tmp_path / "ai_settings.json"
    monkeypatch.setattr(llm_service, "AI_SETTINGS_PATH", path)
    monkeypatch.setattr(llm_service, "_SETTINGS_CACHE", None)
    saved = llm_service.save_ai_settings({
        "llm_provider": "openai",
        "openai_api_key": "sk-secret-test",
        "openai_model": "gpt-4o-mini",
        "ollama_models_dir": "/var/mnt/games/LLM_Models",
    })
    assert saved["openai_api_key"] == "sk-secret-test"
    assert path.is_file()
    monkeypatch.setattr(llm_service, "_SETTINGS_CACHE", None)
    loaded = llm_service.load_ai_settings(force=True)
    assert loaded["openai_model"] == "gpt-4o-mini"
    pub = llm_service.public_ai_settings()
    assert pub["openai_api_key_set"] is True
    assert "sk-secret-test" not in (pub.get("openai_api_key_masked") or "")


def test_start_ollama_already_running(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_OLLAMA_CONTROL", "true")
    monkeypatch.setattr(llm_service, "ollama_running", lambda: True)
    ok, msg = llm_service.start_ollama()
    assert ok is True
    assert "already running" in msg.lower()


def test_start_ollama_disabled(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_OLLAMA_CONTROL", "false")
    ok, msg = llm_service.start_ollama()
    assert ok is False
    assert "disabled" in msg.lower()


def test_refine_article_mocked(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    def fake_call(system, prompt, schema_model):
        return schema_model(
            summary="A short faithful summary of the trial findings.",
            limitations="Abstract only; long-term outcomes not reported.",
            key_points=["Adults with condition X", "Drug Y vs placebo", "Primary endpoint improved"],
        )

    monkeypatch.setattr(llm_service, "_structured_call", fake_call)
    out = llm_service.refine_article(
        title="A randomized trial of Y",
        abstract="In this randomized trial of 200 adults, drug Y improved outcomes versus placebo.",
        existing_key_points=["Drug Y"],
    )
    assert out["method"] == "rules+llm"
    assert "summary" in out and len(out["summary"]) > 10
    assert len(out["key_points"]) == 3


def test_ask_article_mocked(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")

    def fake_call(system, prompt, schema_model):
        return schema_model(
            answer="The trial enrolled 200 adults.",
            quotes=["200 adults"],
        )

    monkeypatch.setattr(llm_service, "_structured_call", fake_call)
    out = llm_service.ask_article(
        question="How many people were enrolled?",
        title="Trial",
        abstract="In this randomized trial of 200 adults, drug Y improved outcomes versus placebo.",
    )
    assert "200" in out["answer"]
    assert out["quotes"]


def test_refine_rejects_short_abstract(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "x")
    with pytest.raises(llm_service.LLMError):
        llm_service.refine_article(title="T", abstract="Too short.")


def test_extract_json_object_fenced():
    raw = '```json\n{"answer": "yes", "quotes": []}\n```'
    cleaned = llm_service._extract_json_object(raw)
    assert cleaned.startswith("{")
