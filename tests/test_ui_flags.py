"""Phase R2 classroom UI flags and plain-language study types."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.content.ui_flags import get_ui_flags
from app.main import app
from app.services.study_type import (
    STUDY_TYPE_LABELS,
    STUDY_TYPE_MEANINGS,
    classify_study_type,
)


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
