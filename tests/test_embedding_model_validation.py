"""Embedding model names from request bodies must stay on an allow-list.

`EmbeddingEngine.MODELS.get(name, name)` falls through to treating an unknown
name as a HuggingFace repo path. That is a deliberate escape hatch, but it must
be an *operator* decision: driven by a request body it would let any logged-in
user make the server download arbitrary models onto its disk.
"""

from __future__ import annotations

import os

from conftest import TEST_PASSWORD

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pathlib
import re

import pytest

from app import core

for _dep in ("fastapi", "httpx", "sklearn", "jwt", "bcrypt", "multipart", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

from app.schemas import EmbeddingsRequest
from app.services.embeddings import EmbeddingEngine


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


def _register(client, username="modeluser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


# --- Schema level ----------------------------------------------------------

def test_catalog_names_are_accepted():
    for name in EmbeddingEngine.MODELS:
        assert EmbeddingsRequest(model=name).model == name


def test_default_is_valid():
    assert EmbeddingsRequest().model in EmbeddingEngine.MODELS


@pytest.mark.parametrize("bad", [
    "evil/backdoored-model",          # arbitrary HF repo
    "../../etc/passwd",               # path-ish
    "sentence-transformers/all-MiniLM-L6-v2",  # real path, but not a catalog *name*
    "",
])
def test_unknown_names_are_rejected(bad):
    with pytest.raises(Exception) as exc:
        EmbeddingsRequest(model=bad)
    assert "Unknown embedding model" in str(exc.value)


def test_operator_can_allow_extra_models(monkeypatch):
    """The escape hatch survives, but only via env (operator), not request body."""
    monkeypatch.setenv("EXTRA_EMBEDDING_MODELS", "mymodel=some-org/some-model")
    assert EmbeddingsRequest(model="mymodel").model == "mymodel"
    assert EmbeddingEngine.allowed_models()["mymodel"] == "some-org/some-model"


def test_extra_models_bare_path_form(monkeypatch):
    monkeypatch.setenv("EXTRA_EMBEDDING_MODELS", "some-org/some-model")
    allowed = EmbeddingEngine.allowed_models()
    assert allowed["some-org/some-model"] == "some-org/some-model"


def test_extra_models_ignores_blanks(monkeypatch):
    monkeypatch.setenv("EXTRA_EMBEDDING_MODELS", " , ,")
    assert EmbeddingEngine.allowed_models() == dict(EmbeddingEngine.MODELS)


# --- HTTP level ------------------------------------------------------------

def test_api_rejects_unknown_model(app_module):
    """A bogus model must be refused before any download/job starts."""
    c = TestClient(app_module.app)
    headers = _register(c, "modeluser1")
    r = c.post(
        "/api/create-embeddings",
        json={"model": "attacker/arbitrary-model", "wait": True},
        headers=headers,
    )
    assert r.status_code == 422, r.text
    assert "Unknown embedding model" in r.text


def test_api_still_requires_auth_before_validation(app_module):
    """Validation must not become an unauthenticated oracle."""
    c = TestClient(app_module.app)
    r = c.post("/api/create-embeddings", json={"model": "whatever"})
    assert r.status_code in (401, 403, 422), r.text


# --- Drift guard -----------------------------------------------------------

def test_ui_dropdown_matches_catalog():
    """Every model the UI offers must be accepted, or users hit a 422."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    html = (repo / "templates" / "data_management.html").read_text()
    block = re.search(
        r'id="embedding-model".*?</select>', html, re.S,
    )
    assert block, "embedding-model select not found; update this guard"
    offered = set(re.findall(r'value="([^"]+)"', block.group(0)))
    assert offered, "no options parsed from the embedding-model select"
    unknown = offered - set(EmbeddingEngine.allowed_models())
    assert not unknown, f"UI offers models the API will reject: {sorted(unknown)}"


def test_topic_recommendations_match_catalog():
    """The topic->model auto-selection must only recommend valid models."""
    repo = pathlib.Path(__file__).resolve().parent.parent
    js = (repo / "static" / "js" / "data_management.js").read_text()
    block = re.search(r"TOPIC_MODEL\s*=\s*\{(.*?)\}", js, re.S)
    assert block, "TOPIC_MODEL map not found; update this guard"
    recommended = set(re.findall(r":\s*'([a-z0-9_-]+)'", block.group(1)))
    assert recommended, "no models parsed from TOPIC_MODEL"
    unknown = recommended - set(EmbeddingEngine.allowed_models())
    assert not unknown, f"topic map recommends invalid models: {sorted(unknown)}"
