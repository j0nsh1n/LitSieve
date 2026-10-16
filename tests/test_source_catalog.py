"""Source catalog alignment (tips, topics, fetchers, URLs)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_integration_accounts import _register, app_module  # noqa: F401

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


def test_eligible_for_coverage_excludes_preprints_and_unkeyed():
    from app.content.source_catalog import eligible_for_coverage_suggestion

    assert eligible_for_coverage_suggestion("pubmed") is True
    assert eligible_for_coverage_suggestion("medrxiv") is False
    assert eligible_for_coverage_suggestion("biorxiv") is False
    assert eligible_for_coverage_suggestion("arxiv") is False
    assert eligible_for_coverage_suggestion("clinicaltrials") is False
    assert eligible_for_coverage_suggestion("zenodo") is False


def test_every_topic_has_a_line_icon():
    """Each topic ships inner SVG markup for a 24x24 stroke icon, emoji kept as fallback."""
    from app.content.source_catalog import TOPIC_META, list_topics_for_api

    for tid, meta in TOPIC_META.items():
        assert meta.get("icon_svg", "").startswith(("<path", "<circle", "<rect")), tid
        assert meta.get("icon"), tid
    api = {t["id"]: t for t in list_topics_for_api()}
    assert set(api) == set(TOPIC_META)
    for tid, meta in TOPIC_META.items():
        assert api[tid]["icon_svg"] == meta["icon_svg"]


def test_dblp_is_retired_but_still_named():
    from app.content import source_catalog as sc

    assert "dblp" in sc.RETIRED_SOURCES
    assert "dblp" not in sc.SOURCE_CATALOG
    assert "dblp" not in sc.TOPIC_SOURCE_HINTS.get("cs", [])
    assert all("dblp" not in pack["sources"] for pack in sc.TOPIC_PACKS)
    assert all(s["id"] != "dblp" for s in sc.list_sources_for_api())
    assert sc.eligible_for_coverage_suggestion("dblp") is False
    assert sc.drop_retired_sources(["dblp", "pubmed"]) == ["pubmed"]
    # Papers already stored under the old source still show a readable name.
    assert sc.source_display_name("dblp") == "DBLP"


def _post_fetch(client, sources):
    return client.post(
        "/api/fetch-articles-multi",
        json={"sources": sources, "query": "diabetes", "max_results": 5, "wait": True},
        headers={"X-CSRF-Token": client.cookies.get("csrf_token")},
    )


def test_fetch_request_listing_dblp_runs_the_other_sources(app_module):
    main = app_module
    client = TestClient(main.app)
    _register(client, "oldprefs")

    r = _post_fetch(client, ["dblp", "pubmed"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["by_source"] == {"pubmed": 1}
    assert body["errors"] == {}


def test_fetch_request_with_only_dblp_is_a_plain_400(app_module):
    main = app_module
    client = TestClient(main.app)
    _register(client, "onlydblp")

    r = _post_fetch(client, ["dblp"])
    assert r.status_code == 400, r.text
    assert "at least one" in r.json()["detail"]
