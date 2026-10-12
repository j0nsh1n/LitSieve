"""Startup notice for the retired global AI settings file."""

import asyncio
import logging
from types import SimpleNamespace

import pytest


@pytest.fixture
def main_module(monkeypatch):
    from app import main

    # Keep the lifespan test focused on the notice, not UMAP's warm-up thread.
    monkeypatch.setattr(
        main.threading,
        "Thread",
        lambda **_kwargs: SimpleNamespace(start=lambda: None),
    )
    return main


def _start(main):
    async def run():
        async with main.lifespan(main.app):
            pass

    asyncio.run(run())


def _clear_ai_environment(monkeypatch):
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_startup_warns_for_legacy_global_file_without_reading_it(
    tmp_path, monkeypatch, caplog, main_module
):
    _clear_ai_environment(monkeypatch)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ai_settings.json").write_text("legacy-secret-marker", encoding="utf-8")
    monkeypatch.setenv("USER_DATA_DIR", str(data_dir))

    with caplog.at_level(logging.WARNING, logger="app.main"):
        _start(main_module)

    assert "Legacy global AI settings file exists" in caplog.text
    assert "ai_settings.json" in caplog.text
    assert "legacy-secret-marker" not in caplog.text


@pytest.mark.parametrize(
    "variable",
    ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_MODEL"),
)
def test_startup_does_not_warn_when_environment_configures_ai(
    tmp_path, monkeypatch, caplog, main_module, variable
):
    _clear_ai_environment(monkeypatch)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ai_settings.json").touch()
    monkeypatch.setenv("USER_DATA_DIR", str(data_dir))
    monkeypatch.setenv(variable, "configured-for-test")

    with caplog.at_level(logging.WARNING, logger="app.main"):
        _start(main_module)

    assert "Legacy global AI settings file exists" not in caplog.text


def test_startup_does_not_warn_when_legacy_file_is_absent(
    tmp_path, monkeypatch, caplog, main_module
):
    _clear_ai_environment(monkeypatch)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "empty-data"))

    with caplog.at_level(logging.WARNING, logger="app.main"):
        _start(main_module)

    assert "Legacy global AI settings file exists" not in caplog.text
