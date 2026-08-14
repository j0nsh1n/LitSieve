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
    assert "function resetSearchAndNarrowingForStartOver" in tools
    start_over = tools[
        tools.index("async function simpleToolsStartOver") : tools.index(
            "function wireSimpleToolsStrip"
        )
    ]
    assert "/api/start-over" in start_over
    assert "openSiteConfirm" in start_over
    assert "resolveSimpleFetchModeBeforeRequest" not in start_over
    assert "resetSearchAndNarrowingForStartOver" in start_over
    reset_fn = tools[
        tools.index("async function resetSearchAndNarrowingForStartOver") : tools.index(
            "async function simpleToolsStartOver"
        )
    ]
    assert "low_relevance" in reset_fn
    assert "clearSearchWorkspace" in reset_fn
    assert "setSimpleScreenSkipped(false)" in reset_fn
    assert "_resetAfterStartOver" in reset_fn
    dm = _read("static", "js", "data_management.js")
    assert "_resetAfterStartOver" in dm
    search_js = _read("static", "js", "search.js")
    assert "function clearSearchWorkspace" in search_js
    assert "SEARCH_SESSION_KEY" in search_js
    assert "clearSearchWorkspace()" in search_js
    clear_fn = search_js[
        search_js.index("function clearSearchWorkspace") : search_js.index(
            "async function restoreSearchSession"
        )
    ]
    assert "displayFilterState.starred = false" in clear_fn
    assert "displayFilterState.noted = false" in clear_fn
    assert "displayFilterState.recent = false" in clear_fn
    assert "function _simpleScreenEnsureQuery" in tools
    assert "startOverReset" in dm
    assert "_resetAfterStartOver = false" in dm
    # Collect / start-over must not auto-restore the last query.
    boot = search_js[
        search_js.index("loadSearchEmptyState()") : search_js.index("refreshStarredCount")
    ]
    assert "wantsSimpleCollectView" in boot
    assert "clearSearchWorkspace()" in boot
    css = _read("static", "css", "style.css")
    simple_hide = css[
        css.find('html[data-mode="simple"] .result-row-ids') : css.find(
            "html[data-mode=\"simple\"] body.simple-collecting"
        )
    ]
    assert ".key-points" not in simple_hide
    assert ".ai-actions" not in simple_hide


def test_simple_search_asks_count_and_year_range():
    """Simple Search pops a form for how many + year range; Advanced keeps the rail."""
    search_js = _read("static", "js", "search.js")
    common = _read("static", "js", "common.js")
    assert "function promptSimpleSearchScope" in search_js
    assert "function openSiteForm" in common
    assert "mode === 'form'" in common or "mode: 'form'" in common
    do_search = search_js[search_js.index("async function doSearch") : search_js.index("async function doStarredSearch")]
    assert "promptSimpleSearchScope" in do_search
    assert "fromRestore" in do_search
    assert "How many papers" in search_js
    assert "year_min" in search_js[search_js.index("function promptSimpleSearchScope") :]
    assert "year_max" in search_js[search_js.index("function promptSimpleSearchScope") :]


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


def test_start_over_api_keeps_starred_and_drops_unmarked(tmp_path, monkeypatch):
    """POST /api/start-over is option B: starred/noted stay, unmarked go."""
    from app import core
    from app.core import get_pipeline, release_pipeline
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": "startover1",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    csrf = client.cookies.get("csrf_token")
    loaded = client.post(
        "/api/load-sample-corpus",
        json={"clear_first": True},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert loaded.status_code == 200, loaded.text

    rec = db.get_by_username("startover1")
    pipe = get_pipeline(rec["id"])
    try:
        arts = pipe.db.get_all_articles()
        assert len(arts) >= 3
        a, b, c = arts[0], arts[1], arts[2]
        pipe.db.upsert_note(a["article_id"], a["source"], starred=True)
        pipe.db.upsert_note(b["article_id"], b["source"], note="keep me")
        before = pipe.db.get_statistics()["total_articles"]
    finally:
        release_pipeline(rec["id"])

    out = client.post(
        "/api/start-over",
        json={},
        headers={"X-CSRF-Token": csrf or ""},
    )
    assert out.status_code == 200, out.text
    body = out.json()
    assert body.get("status") == "success"
    assert body.get("remaining") == 2
    assert body.get("deleted") == before - 2

    pipe = get_pipeline(rec["id"])
    try:
        ids = {(x["article_id"], x["source"]) for x in pipe.db.get_all_articles()}
        assert ids == {
            (a["article_id"], a["source"]),
            (b["article_id"], b["source"]),
        }
        assert (c["article_id"], c["source"]) not in ids
    finally:
        release_pipeline(rec["id"])
