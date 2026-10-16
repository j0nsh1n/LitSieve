"""
Error sentences a student sees are the app's own, unchanged by the route.

Pins the messages that reach the client for the common caught errors, so the
route helper that stops exception text leaking cannot also change the copy.
"""

from __future__ import annotations

import os

from conftest import TEST_PASSWORD

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pathlib

import pytest

from app import core
from app.storage import quota

for _dep in ("fastapi", "httpx", "sklearn", "jwt", "bcrypt", "multipart", "dotenv"):
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
    main = importlib.import_module("app.main")

    from app.storage.user_db import UserDatabase
    test_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", test_db)
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    yield main
    test_db.conn.close()


def _register(client, username="sentences"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_library_not_found_sentence(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    r = c.post("/api/libraries/switch", json={"library_id": "no-such-library"}, headers=headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Library not found."


def test_duplicate_library_name_sentence(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    r = c.post("/api/libraries", json={"name": "My library"}, headers=headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "A library with that name already exists."


def test_bad_share_code_sentence(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    r = c.post("/api/shares/join", json={"code": "ZZZZ-ZZZZ"}, headers=headers)
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "Library code not found."


def test_storage_limit_sentence_carries_the_numbers(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c)
    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 3 * 1024 * 1024)
    monkeypatch.setenv(quota.ENV_KEY, "2")
    r = c.post(
        "/api/fetch-articles-multi",
        json={"sources": ["pubmed"], "query": "x", "max_results": 5, "wait": True, "clear_first": False},
        headers=headers,
    )
    assert r.status_code == 507, r.text
    assert r.json()["detail"] == (
        "Storage limit reached (3.0 MB of 2.0 MB). "
        "Delete a library you no longer need, or use Start over to remove papers "
        "that are not starred or noted, then try again."
    )


def test_sentence_for_passes_app_sentences_and_hides_the_rest():
    from app.errors import FALLBACK, UserError, sentence_for
    from app.services.llm import LLMError, LLMUnavailable

    assert sentence_for(UserError("Library not found.")) == "Library not found."
    assert sentence_for(LLMError("Ollama request failed.")) == "Ollama request failed."
    assert sentence_for(LLMUnavailable("OPENAI_API_KEY is not set.")) == "OPENAI_API_KEY is not set."
    assert sentence_for(quota.QuotaExceeded(3 * 1024 * 1024, 2 * 1024 * 1024)).startswith(
        "Storage limit reached (3.0 MB of 2.0 MB)."
    )
    assert sentence_for(ValueError("unable to open database file /srv/users.db")) == FALLBACK
    assert sentence_for(RuntimeError("Library not found."), "Nope.") == "Library not found."



def test_routes_never_echo_an_exception():
    """A route's detail comes from app.errors, never from the exception object."""
    import re

    routes = pathlib.Path(__file__).resolve().parent.parent / "app" / "routes"
    offenders = []
    for path in sorted(routes.glob("*.py")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r'"detail":\s*(str|repr)\((e|exc|err|error)\b', line):
                offenders.append(f"{path.name}:{n}: {line.strip()}")
    assert offenders == [], "\n".join(offenders)
