"""Classroom UI flags and plain-language study types."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app.content.ui_flags import get_ui_flags
from app.main import app
from app.services.study_type import (
    STUDY_TYPE_LABELS,
    STUDY_TYPE_MEANINGS,
    classify_study_type,
)

REPO = Path(__file__).resolve().parents[1]


def _clear_host_ai(monkeypatch):
    for key in (
        "HIDE_AI_BUTTONS",
        "OLLAMA_MODEL",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_MODEL",
        "LLM_PROVIDER",
        "LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_study_type_labels_are_plain_language():
    r = classify_study_type(
        title="A meta-analysis of classroom interventions",
        abstract="We conducted a meta-analysis of 40 studies.",
    )
    assert r["study_type"] == "synthesis"
    assert "Likely" in r["study_type_label"] or "review" in r["study_type_label"].lower()
    assert r["study_type_meaning"]
    assert "formal" in r["study_type_label_formal"].lower() or "/" in r["study_type_label_formal"]
    # Every known type has a meaning line.
    for tid in STUDY_TYPE_LABELS:
        assert tid in STUDY_TYPE_MEANINGS


def test_ui_flags_default_show_features(monkeypatch):
    monkeypatch.delenv("HIDE_STUDY_TYPE_TAGS", raising=False)
    monkeypatch.delenv("HIDE_AI_BUTTONS", raising=False)
    flags = get_ui_flags()
    assert flags["show_study_type_tags"] is True
    assert flags["show_ai_buttons"] is True


def test_ui_flags_hide_via_env(monkeypatch):
    monkeypatch.setenv("HIDE_STUDY_TYPE_TAGS", "true")
    monkeypatch.setenv("HIDE_AI_BUTTONS", "1")
    flags = get_ui_flags()
    assert flags["show_study_type_tags"] is False
    assert flags["show_ai_buttons"] is False


def test_api_ui_flags_public():
    client = TestClient(app)
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    body = r.json()
    assert "show_study_type_tags" in body
    assert "show_ai_buttons" in body


def test_api_ui_flags_respect_env(monkeypatch):
    monkeypatch.setenv("HIDE_STUDY_TYPE_TAGS", "yes")
    monkeypatch.setenv("HIDE_AI_BUTTONS", "on")
    # get_ui_flags reads env at call time; endpoint uses it live.
    client = TestClient(app)
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    assert r.json()["show_study_type_tags"] is False
    assert r.json()["show_ai_buttons"] is False


def test_attach_skipped_when_hidden(monkeypatch):
    monkeypatch.setenv("HIDE_STUDY_TYPE_TAGS", "true")
    from app.services.enrich import attach_study_types as _attach_study_types

    arts = [
        {
            "title": "A systematic review of tutoring",
            "abstract": "This systematic review synthesizes 12 RCTs of tutoring.",
        }
    ]
    _attach_study_types(arts)
    assert "study_type" not in arts[0]


def test_attach_runs_when_visible(monkeypatch):
    monkeypatch.delenv("HIDE_STUDY_TYPE_TAGS", raising=False)
    monkeypatch.setenv("HIDE_STUDY_TYPE_TAGS", "false")
    from app.services.enrich import attach_study_types as _attach_study_types

    arts = [
        {
            "title": "A systematic review of tutoring",
            "abstract": "This systematic review synthesizes 12 RCTs of tutoring.",
        }
    ]
    _attach_study_types(arts)
    assert arts[0]["study_type"] == "synthesis"
    assert arts[0]["study_type_meaning"]


@pytest.fixture
def signed_in_no_ai(tmp_path, monkeypatch):
    """Signed-in student, no host model, no saved key, isolated accounts DB."""
    from app import core
    from app.services import llm
    from app.storage.user_db import UserDatabase

    _clear_host_ai(monkeypatch)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    db = UserDatabase(str(tmp_path / "users.db"))
    previous = core.user_db
    core.user_db = db
    llm._SETTINGS_CACHE = {}
    client = TestClient(app)
    created = client.post(
        "/register",
        data={
            "username": "flaguser",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert created.status_code == 302, created.text
    yield client, db
    db.conn.close()
    core.user_db = previous
    llm._SETTINGS_CACHE = {}


def test_signed_out_ui_flags_keep_env_shape(monkeypatch):
    _clear_host_ai(monkeypatch)
    client = TestClient(app)
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    body = r.json()
    assert "show_study_type_tags" in body
    assert "show_ai_buttons" in body
    assert body["show_ai_buttons"] is True


def test_signed_in_without_key_or_host_model_hides_ai_buttons(signed_in_no_ai):
    client, _db = signed_in_no_ai
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    assert r.json()["show_ai_buttons"] is False


def test_signed_in_with_saved_key_shows_ai_buttons(signed_in_no_ai):
    from app.services import llm

    client, db = signed_in_no_ai
    rec = db.get_by_username("flaguser")
    assert rec is not None
    llm.save_ai_settings({"openai_api_key": "sk-student-test"}, user_id=rec["id"])
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    assert r.json()["show_ai_buttons"] is True


def test_signed_in_with_ollama_model_shows_ai_buttons(signed_in_no_ai, monkeypatch):
    client, _db = signed_in_no_ai
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    assert r.json()["show_ai_buttons"] is True


def test_hide_ai_buttons_env_forces_false(signed_in_no_ai, monkeypatch):
    from app.services import llm

    client, db = signed_in_no_ai
    rec = db.get_by_username("flaguser")
    assert rec is not None
    llm.save_ai_settings({"openai_api_key": "sk-student-test"}, user_id=rec["id"])
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    monkeypatch.setenv("HIDE_AI_BUTTONS", "true")
    r = client.get("/api/ui-flags")
    assert r.status_code == 200
    assert r.json()["show_ai_buttons"] is False


def test_account_ai_card_stays_visible_when_ai_unavailable(signed_in_no_ai):
    client, _db = signed_in_no_ai
    page = client.get("/account")
    assert page.status_code == 200, page.text
    html = page.text
    assert 'id="ai-settings-section"' in html
    assert 'id="ai-unavailable-note"' in html
    assert "not available right now" in html


def test_common_js_does_not_hide_account_ai_card():
    js = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "aiSec.hidden = true" not in js
    assert "ai-unavailable-note" in js


def test_account_js_keeps_ai_card_visible():
    js = (REPO / "static" / "js" / "account.js").read_text(encoding="utf-8")
    assert "aiSection.hidden = true" not in js
    assert "ai-unavailable-note" in js
