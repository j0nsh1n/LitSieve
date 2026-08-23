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
    saved = llm.save_ai_settings({
        "openai_api_key": "sk-super-secret",
        "openai_model": "gpt-4o-mini",
    })
    # Caller still sees the usable value.
    assert saved["openai_api_key"] == "sk-super-secret"

    raw = settings_file.read_text(encoding="utf-8")
    assert "sk-super-secret" not in raw
    stored = json.loads(raw)
    assert stored["openai_api_key"].startswith(llm.ENC_PREFIX_V2)
    # Non-secret fields stay readable.
    assert stored["openai_model"] == "gpt-4o-mini"

    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["openai_api_key"] == "sk-super-secret"


def test_encrypt_uses_fresh_nonce_each_time(settings_file):
    """AES-GCM is dynamic: same key material → different ciphertext each save."""
    llm.save_ai_settings({"openai_api_key": "sk-same-secret"})
    c1 = json.loads(settings_file.read_text(encoding="utf-8"))["openai_api_key"]
    llm._SETTINGS_CACHE = None
    # Force another encrypt of the same plaintext.
    llm.save_ai_settings({"openai_api_key": "sk-same-secret"})
    c2 = json.loads(settings_file.read_text(encoding="utf-8"))["openai_api_key"]
    assert c1.startswith(llm.ENC_PREFIX_V2)
    assert c2.startswith(llm.ENC_PREFIX_V2)
    assert c1 != c2


def test_ciphertext_cannot_be_swapped_across_fields(settings_file):
    """AAD binds ciphertext to the field name (openai vs anthropic)."""
    llm.save_ai_settings({"openai_api_key": "sk-only-for-openai"})
    blob = json.loads(settings_file.read_text(encoding="utf-8"))["openai_api_key"]
    # Plant the openai ciphertext under the anthropic field.
    settings_file.write_text(
        json.dumps({"anthropic_api_key": blob}),
        encoding="utf-8",
    )
    llm._SETTINGS_CACHE = None
    loaded = llm.load_ai_settings()
    assert "anthropic_api_key" not in loaded


def test_legacy_plaintext_file_still_loads_and_upgrades_on_save(settings_file):
    settings_file.write_text(
        json.dumps({"anthropic_api_key": "legacy-plain"}),
        encoding="utf-8",
    )
    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["anthropic_api_key"] == "legacy-plain"

    llm.save_ai_settings({"openai_model": "gpt-4o-mini"})
    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert stored["anthropic_api_key"].startswith(llm.ENC_PREFIX_V2)


def test_legacy_fernet_v1_still_loads_and_upgrades_on_save(settings_file):
    """enc:v1: Fernet blobs from older deploys keep working until next save."""
    f = llm._fernet()
    assert f is not None
    v1 = llm.ENC_PREFIX_V1 + f.encrypt(b"sk-from-fernet-era").decode("ascii")
    settings_file.write_text(json.dumps({"openai_api_key": v1}), encoding="utf-8")
    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["openai_api_key"] == "sk-from-fernet-era"

    llm.save_ai_settings({"openai_model": "gpt-4o-mini"})
    stored = json.loads(settings_file.read_text(encoding="utf-8"))
    assert stored["openai_api_key"].startswith(llm.ENC_PREFIX_V2)
    assert not stored["openai_api_key"].startswith(llm.ENC_PREFIX_V1)
    llm._SETTINGS_CACHE = None
    assert llm.load_ai_settings()["openai_api_key"] == "sk-from-fernet-era"


def test_rotated_secret_key_drops_the_value_instead_of_leaking_ciphertext(
    settings_file, monkeypatch,
):
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


def test_delete_library_rejects_traversal_ids():
    """rmtree path must be sanitised, not trusted from libraries.json."""
    import pytest

    from app.storage import libraries

    for bad in ("../../etc", "a/b", "..", ".", "", "x\x00y"):
        with pytest.raises(ValueError):
            libraries._safe_fs_id(bad, label="library id")
    # A real uuid still passes.
    assert libraries._safe_fs_id("0f8f0f1e-2b3c-4d5e-8f90-1a2b3c4d5e6f")


def test_sanitize_plain_is_linear_on_pathological_input():
    """<[^>]*> is quadratic on a long run of '<'; input must be pre-capped."""
    import time

    from app.storage import helpdesk

    payload = "<" * 200_000
    start = time.perf_counter()
    out = helpdesk.sanitize_plain(payload, limit=800)
    elapsed = time.perf_counter() - start
    assert len(out) <= 800
    # Pre-capped input finishes in milliseconds; the unbounded version took
    # seconds on the same string.
    assert elapsed < 1.0, f"sanitize_plain took {elapsed:.2f}s"


def test_server_error_takes_no_exception_argument():
    """Keeps py/stack-trace-exposure meaningful: no exception may flow into
    the response helper. logger.exception() captures the live exception, so
    passing it in only created a dataflow edge for the scanner to follow.
    """
    import inspect
    import pathlib
    import re

    from app.core import server_error

    assert not inspect.signature(server_error).parameters, (
        "server_error() must take no argument — see the CodeQL config note."
    )

    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"server_error\(\s*[^)\s]", line):
                offenders.append(f"{path.name}:{i}")
    assert not offenders, f"server_error() called with an argument: {offenders}"
