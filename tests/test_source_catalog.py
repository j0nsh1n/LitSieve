"""Phase R4: source catalog alignment (tips, topics, fetchers, URLs)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.content.source_catalog import (
    SOURCE_CATALOG,
    SOURCE_PRIORITY,
    TOPIC_PACKS,
    TOPIC_SOURCE_HINTS,
    public_catalog,
    student_tip,
)
from app.main import app
from app.services.citations import SOURCE_URL
from app.services.pipeline import FETCHERS
from app.utils import coverage_suggestions


def test_catalog_matches_fetchers():
    assert set(SOURCE_CATALOG.keys()) == set(FETCHERS.keys())


def test_catalog_matches_citation_urls():
    # sample is demo-only; not a fetcher.
    assert set(SOURCE_CATALOG.keys()) <= set(SOURCE_URL.keys()) | {"sample"}
    for sid in SOURCE_CATALOG:
        assert sid in SOURCE_URL, f"citations.SOURCE_URL missing {sid}"


def test_every_source_has_student_tip():
    for sid, meta in SOURCE_CATALOG.items():
        tip = student_tip(sid)
        assert tip and len(tip) > 20, f"missing tip for {sid}"
        assert meta.get("good_for"), f"missing good_for for {sid}"
        assert meta.get("misses"), f"missing misses for {sid}"
        assert meta.get("name")
        assert meta.get("desc")


def test_topic_hints_only_use_known_sources():
    known = set(SOURCE_CATALOG)
    for tid, srcs in TOPIC_SOURCE_HINTS.items():
        assert srcs, f"empty topic {tid}"
        for s in srcs:
            assert s in known, f"topic {tid} references unknown source {s}"


def test_packs_align_with_catalog():
    known = set(SOURCE_CATALOG)
    for pack in TOPIC_PACKS:
        assert pack.get("topics")
        for s in pack.get("sources") or []:
            assert s in known, f"pack {pack['id']} unknown source {s}"
        for t in pack.get("topics") or []:
            assert t in TOPIC_SOURCE_HINTS, f"pack {pack['id']} unknown topic {t}"


def test_priority_matches_catalog():
    for sid, meta in SOURCE_CATALOG.items():
        assert SOURCE_PRIORITY[sid] == int(meta["priority"])


def test_public_catalog_api():
    client = TestClient(app)
    r = client.get("/api/sources")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(SOURCE_CATALOG)
    assert len(body["sources"]) == len(SOURCE_CATALOG)
    assert body["topics"]
    assert body["packs"]
    # Every listed source has a tip for the UI.
    for s in body["sources"]:
        assert s["tip"]
        assert s["id"] in SOURCE_CATALOG


def test_public_catalog_helper_shape():
    cat = public_catalog()
    assert "note" in cat
    assert any(p["id"] == "pack_climate" for p in cat["packs"])


def test_coverage_includes_student_tip():
    tips = coverage_suggestions({"openalex": 1}, ["education"])
    assert tips
    eric = next(t for t in tips if t["source"] == "eric")
    assert "tip" in eric
    assert "education" in eric["tip"].lower() or "ERIC" in eric["reason"] or "education" in eric["reason"].lower()
    assert eric.get("name") == "ERIC"
