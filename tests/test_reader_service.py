"""Reader Mode generation + orchestration (providers mocked, no network)."""

from app.services import llm as llm_service
from app.services.llm import LLMError, LLMUnavailable, ReaderExplanation
from app.services.reader_mode import (
    FALLBACK_WHAT_IT_DOES_NOT_SHOW,
    _inject_app_copy,
    facts_block,
)


def _clear_providers(monkeypatch):
    for k in (
        "OLLAMA_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "LLM_PROVIDER", "OPENAI_BASE_URL", "OPENAI_MODEL", "LLM_MODEL",
        "OLLAMA_MODELS", "OLLAMA_HOST",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm_service, "_SETTINGS_CACHE", {})
    monkeypatch.setattr(llm_service, "load_ai_settings", lambda force=False: {})


def _sample(**overrides):
    data = dict(
        plain_summary="Students slept about 43 minutes longer.",
        question_asked="Does a later start increase sleep?",
        who_was_studied="Teenagers at secondary schools.",
        what_was_found="Sleep rose by 43 minutes on average.",
        what_it_does_not_show="Not reported in the abstract.",
        stated_limitations="Not reported in the abstract.",
        glossary=[{"term": "cohort", "definition": "A group followed over time."}],
        not_reported_fields=["stated_limitations"],
    )
    data.update(overrides)
    return ReaderExplanation(**data)


def test_malformed_json_maps_to_llm_error(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    def boom(system, prompt, schema):
        raise LLMError("Model output was not valid JSON.")

    monkeypatch.setattr(llm_service, "_structured_call", boom)
    try:
        llm_service.generate_reader_explanation(
            "Sleep",
            "n = 40 teenagers were followed for two school years after a later start.",
        )
        assert False, "expected LLMError"
    except LLMError as exc:
        assert "json" in str(exc).lower()


def test_provider_timeout_maps_to_unavailable(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    def boom(system, prompt, schema):
        raise LLMUnavailable("timed out contacting provider")

    monkeypatch.setattr(llm_service, "_structured_call", boom)
    try:
        llm_service.generate_reader_explanation(
            "Sleep",
            "n = 40 teenagers were followed for two school years after a later start.",
        )
        assert False, "expected LLMUnavailable"
    except LLMUnavailable:
        pass


def test_schema_violation_rejected(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")

    def boom(system, prompt, schema):
        raise LLMError("Output did not match the requested schema.")

    monkeypatch.setattr(llm_service, "_structured_call", boom)
    try:
        llm_service.generate_reader_explanation(
            "Sleep",
            "n = 40 teenagers were followed for two school years after a later start.",
        )
        assert False, "expected LLMError"
    except LLMError as exc:
        assert "schema" in str(exc).lower()


def test_prompt_omits_low_confidence_study_type():
    block = facts_block(
        "A review of school sleep programmes",
        "We discuss studies of adolescent sleep. The evidence remains mixed.",
    )
    assert "Study type" not in block


def test_prompt_contains_no_user_identity(monkeypatch):
    _clear_providers(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    captured = {}

    def fake(system, prompt, schema):
        captured["system"] = system
        captured["prompt"] = prompt
        return _sample()

    monkeypatch.setattr(llm_service, "_structured_call", fake)
    llm_service.generate_reader_explanation(
        "Sleep study",
        "n = 40 teenagers were followed for two school years after a later start.",
        audience="high_school",
        source="pubmed",
        article_id="34567890",
        facts_block=facts_block(
            "Sleep study",
            "n = 40 teenagers were followed for two school years after a later start.",
        ),
    )
    blob = captured["system"] + "\n" + captured["prompt"]
    for needle in ("user_id", "user@", "library name", "email", "password"):
        assert needle not in blob.lower()
    assert "grades 8-10" in captured["system"]


def test_empty_what_it_does_not_show_becomes_app_copy():
    injected = _inject_app_copy({
        "plain_summary": "Students slept longer.",
        "question_asked": "Does a later start help?",
        "who_was_studied": "Teenagers.",
        "what_was_found": "Sleep rose.",
        "what_it_does_not_show": "",
        "stated_limitations": "",
        "glossary": [],
        "not_reported_fields": [],
    })
    assert injected["what_it_does_not_show"] == FALLBACK_WHAT_IT_DOES_NOT_SHOW
    assert injected["stated_limitations"] == "Not reported in the abstract."
    assert "stated_limitations" in injected["not_reported_fields"]


def test_short_abstract_raises_friendly_error():
    try:
        llm_service.generate_reader_explanation("T", "Too short.")
        assert False, "expected LLMError"
    except LLMError as exc:
        assert "too short to explain" in str(exc)
