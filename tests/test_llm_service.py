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
    assert "not configured" in st["detail"].lower() or "No AI" in st["detail"]


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
    monkeypatch.setattr(llm_service, "ollama_running", lambda force=False: True)
    ok, msg = llm_service.start_ollama()
    assert ok is True
    assert "already running" in msg.lower()


def test_start_ollama_disabled(monkeypatch):
    monkeypatch.setenv("AI_ALLOW_OLLAMA_CONTROL", "false")
    ok, msg = llm_service.start_ollama()
    assert ok is False
    assert "disabled" in msg.lower()


def test_builtin_ephemeral_starts_and_stops(monkeypatch):
    """Refine lifecycle: start → work → stop when we own the process."""
    _clear_providers(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("AI_ALLOW_OLLAMA_CONTROL", "true")
    state = {"running": False, "starts": 0, "stops": 0}

    def fake_running(force=False):
        return state["running"]

    def fake_start():
        state["starts"] += 1
        state["running"] = True
        return True, "started"

    def fake_stop():
        state["stops"] += 1
        state["running"] = False
        return True, "stopped"

    monkeypatch.setattr(llm_service, "ollama_running", fake_running)
    monkeypatch.setattr(llm_service, "start_ollama", fake_start)
    monkeypatch.setattr(llm_service, "stop_ollama", fake_stop)
    monkeypatch.setattr(llm_service, "_builtin_hold_count", 0)
    monkeypatch.setattr(llm_service, "_builtin_started_by_app", False)

    out = llm_service.run_with_ephemeral_builtin(lambda: "ok")
    assert out == "ok"
    assert state["starts"] == 1
    assert state["stops"] == 1
    assert state["running"] is False


def test_builtin_concurrent_ops_share_one_start(monkeypatch):
    """Two overlapping Refine/Ask holds share one start; stop only after both release."""
    _clear_providers(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("AI_ALLOW_OLLAMA_CONTROL", "true")
    state = {"running": False, "stops": 0}

    monkeypatch.setattr(llm_service, "ollama_running", lambda force=False: state["running"])
    monkeypatch.setattr(
        llm_service, "start_ollama",
        lambda: (state.update(running=True) or True, "started"),
    )
    monkeypatch.setattr(
        llm_service, "stop_ollama",
        lambda: (state.update(running=False, stops=state["stops"] + 1) or True, "stopped"),
    )
    import llm_service as ls
    ls._builtin_hold_count = 0
    ls._builtin_started_by_app = False

    ok, _ = ls.ensure_builtin_service()
    assert ok is True
    assert state["running"] is True
    ok2, _ = ls.ensure_builtin_service()
    assert ok2 is True
    ls.release_builtin_service()
    assert state["running"] is True
    ls.release_builtin_service()
    assert state["running"] is False
    assert state["stops"] == 1


def test_study_aid_mode_built_in_vs_api(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert llm_service.study_aid_mode() == "built_in"
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert llm_service.study_aid_mode() == "api_key"


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
        source="pubmed",
        article_id="demo-1",
    )
    assert out["method"] == "rules+llm"
    assert "summary" in out and len(out["summary"]) > 10
    assert len(out["key_points"]) == 3


def test_refine_prompt_includes_selected_paper_context(monkeypatch):
    """System + user prompts must frame the selected paper as sole evidence."""
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    captured = {}

    def fake_call(system, prompt, schema_model):
        captured["system"] = system
        captured["prompt"] = prompt
        return schema_model(
            summary="Summary grounded in the abstract only.",
            limitations="Abstract only.",
            key_points=["Point one", "Point two", "Point three"],
        )

    monkeypatch.setattr(llm_service, "_structured_call", fake_call)
    abstract = (
        "In this randomized trial of 200 adults with condition X, "
        "drug Y improved the primary endpoint versus placebo over 12 weeks."
    )
    llm_service.refine_article(
        title="Trial of Y",
        abstract=abstract,
        source="pubmed",
        article_id="123",
    )
    assert "selected" in captured["system"].lower() or "library" in captured["system"].lower()
    assert "abstract" in captured["system"].lower()
    assert "Trial of Y" in captured["prompt"]
    assert "source=pubmed" in captured["prompt"]
    assert "id=123" in captured["prompt"]
    assert abstract[:40] in captured["prompt"]


def test_ask_article_mocked(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    captured = {}

    def fake_call(system, prompt, schema_model):
        captured["system"] = system
        captured["prompt"] = prompt
        return schema_model(
            answer="The trial enrolled 200 adults.",
            quotes=["200 adults"],
        )

    monkeypatch.setattr(llm_service, "_structured_call", fake_call)
    out = llm_service.ask_article(
        question="How many people were enrolled?",
        title="Trial",
        abstract="In this randomized trial of 200 adults, drug Y improved outcomes versus placebo.",
        source="pubmed",
        article_id="99",
    )
    assert "200" in out["answer"]
    assert out["quotes"]
    assert "STUDENT QUESTION" in captured["prompt"]
    assert "source=pubmed" in captured["prompt"]
    assert "selected" in captured["system"].lower() or "library" in captured["system"].lower()


def test_refine_rejects_short_abstract(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "x")
    with pytest.raises(llm_service.LLMError):
        llm_service.refine_article(title="T", abstract="Too short.")


def test_ollama_down_raises_unavailable(monkeypatch):
    """R5: Ollama stopped → LLMUnavailable (HTTP 503 path), not a generic 400."""
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setattr(llm_service, "ollama_running", lambda force=False: False)
    with pytest.raises(llm_service.LLMUnavailable) as ei:
        llm_service.refine_article(
            title="A trial of Y for adults with condition X",
            abstract=(
                "In this randomized trial of 200 adults with condition X, "
                "drug Y improved the primary endpoint versus placebo over 12 weeks."
            ),
        )
    assert "not running" in str(ei.value).lower() or "study aid" in str(ei.value).lower()


def test_connection_failure_classifier():
    """R5: transport failures map to LLMUnavailable → clear HTTP 503."""
    assert llm_service._is_connection_failure(ConnectionError("Connection refused"))
    assert llm_service._is_connection_failure(TimeoutError("timed out"))
    assert not llm_service._is_connection_failure(ValueError("bad json"))


def test_extract_json_object_fenced():
    raw = '```json\n{"answer": "yes", "quotes": []}\n```'
    cleaned = llm_service._extract_json_object(raw)
    assert cleaned.startswith("{")
