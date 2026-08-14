"""Simple one-page: collect + search on /search; Simple /data-management redirects."""

from __future__ import annotations

from pathlib import Path

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def test_search_includes_collect_and_simple_tools():
    html = _read("templates", "search.html")
    assert 'include "partials/collect_ui.html"' in html
    assert 'include "partials/simple_screening_card.html"' in html
    assert "simple_tools.js" in html
    assert "data_management.js" in html
    assert 'id="search-collect"' in html
    collect = _read("templates", "partials", "collect_ui.html")
    assert 'id="fetch-form"' in collect
    assert 'id="topic-grid"' in collect
    assert "simple-tools-reprepare-btn" in _read(
        "templates", "partials", "simple_screening_card.html"
    )
    assert "simple-tools-startover-btn" in _read(
        "templates", "partials", "simple_screening_card.html"
    )
    tools = _read("static", "js", "simple_tools.js")
    assert "function simpleToolsStartOver" in tools
    assert "function simpleToolsReprepare" in tools
    assert "function syncSimpleOnePageState" in tools
    assert "function wantsSimpleCollectView" in tools
    assert "/search?collect=1" in tools
    assert "function openSimpleScreenModal" in tools
    assert "function openSimpleSourceReport" in tools


def test_collect_query_on_data_management_redirects_to_search(tmp_path, monkeypatch):
    """Simple ?collect=1 on Get papers lands on Search collect, not DM."""
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    client = TestClient(app)
    client.cookies.set("ui_mode", "simple")
    r = client.post(
        "/register",
        data={
            "username": "onepage1",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    client.cookies.set("ui_mode", "simple")
    bounced = client.get("/data-management?collect=1", follow_redirects=False)
    assert bounced.status_code in (302, 303), bounced.text
    assert bounced.headers.get("location") == "/search?collect=1"

    page = client.get("/search?collect=1", follow_redirects=False)
    assert page.status_code == 200
    assert b"fetch-form" in page.content
    assert b"search-collect" in page.content


def test_simple_data_management_always_redirects_to_search(tmp_path, monkeypatch):
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": "onepage2",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    client.cookies.set("ui_mode", "simple")

    csrf = client.cookies.get("csrf_token")
    loaded = client.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert loaded.status_code == 200, loaded.text

    import numpy as np

    from app.core import get_pipeline, release_pipeline

    rec = db.get_by_username("onepage2")
    pipe = get_pipeline(rec["id"])
    try:
        arts = pipe.db.get_all_articles()
        assert arts
        key = (arts[0]["article_id"], arts[0]["source"])
        pipe.db.insert_embeddings({key: np.zeros(8, dtype=np.float32)}, "general")
    finally:
        release_pipeline(rec["id"])

    bounced = client.get("/data-management", follow_redirects=False)
    assert bounced.status_code in (302, 303), bounced.text
    assert bounced.headers.get("location") == "/search"

    empty_user = TestClient(app)
    empty_user.post(
        "/register",
        data={
            "username": "onepage3",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    empty_user.cookies.set("ui_mode", "simple")
    empty_bounce = empty_user.get("/data-management", follow_redirects=False)
    assert empty_bounce.status_code in (302, 303)
    assert empty_bounce.headers.get("location") == "/search"
    empty_search = empty_user.get("/search", follow_redirects=False)
    assert empty_search.status_code == 200
    assert b"fetch-form" in empty_search.content

    adv = TestClient(app)
    adv.post(
        "/register",
        data={
            "username": "onepage4",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    adv.cookies.set("ui_mode", "advanced")
    csrf = adv.cookies.get("csrf_token")
    adv.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers={"X-CSRF-Token": csrf or ""},
    )
    stay_adv = adv.get("/data-management", follow_redirects=False)
    assert stay_adv.status_code == 200
    assert b"fetch-form" in stay_adv.content


def test_simple_collect_url_stays_on_search():
    """One-page Simple: collect is /search?collect=1 (Start over), not a second nav step."""
    tools = _read("static", "js", "simple_tools.js")
    assert "/search?collect=1" in tools
    base = _read("templates", "base.html")
    assert 'data-href-simple="/search?collect=1"' in base


def test_simple_css_hides_leftover_collect():
    css = _read("static", "css", "style.css")
    assert 'html[data-mode="simple"] #search-collect.has-papers #collect-topics-card' in css
    assert 'html[data-mode="simple"] #search-collect.has-papers #fetch-form' in css
    assert 'html:not([data-mode="simple"]) #search-collect' in css
    js = _read("static", "js", "simple_tools.js")
    assert "has-papers" in js
    assert "simple-collecting" in js
