"""HTTP contract for the search endpoints.

`test_search_quality.py` covers the ranking *pipeline*; nothing covered the
routes themselves, which left app/routes/search.py at 33% line coverage even
though search is the product's main feature. What was untested: auth gating,
request validation, error mapping (400 vs 500), and the response shapes the
frontend actually reads.

Embeddings are stubbed with unit vectors so this runs offline and fast.
"""

from __future__ import annotations

from conftest import TEST_PASSWORD
import os
import pathlib
import shutil

import numpy as np
import pytest

from app import core

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

for _dep in ("fastapi", "httpx", "Bio", "sklearn", "slowapi", "jwt",
             "bcrypt", "multipart", "requests", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

SEARCH_POSTS = ("/api/search", "/api/search/seed", "/api/search/starred")


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    import importlib
    main = importlib.import_module("app.main")
    from app.storage.user_db import UserDatabase

    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    try:
        core.limiter.reset()
    except Exception:
        pass
    return main


def _register(client, username="searchuser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD,
              "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _uid(username="searchuser"):
    row = core.user_db.get_by_username(username)
    return row["id"]


def _seed(main, client, headers, username="searchuser"):
    """Load the sample corpus and give every paper a deterministic vector."""
    r = client.post("/api/load-sample-corpus", json={"clear_first": True},
                    headers=headers)
    assert r.status_code == 200, r.text

    uid = _uid(username)
    pipe = core.get_pipeline(uid)
    try:
        arts = pipe.db.get_all_articles()
        assert arts, "sample corpus should have inserted papers"
        rng = np.random.default_rng(0)
        emb = {}
        for a in arts:
            v = rng.standard_normal(8).astype(np.float32)
            v /= np.linalg.norm(v) + 1e-9
            emb[(a["article_id"], a["source"])] = v
        pipe.db.insert_embeddings(emb, model_name="general")
        pipe.embedding_engine.embed_query = (  # type: ignore[method-assign]
            lambda _t: np.ones(8, dtype=np.float32) / np.sqrt(8.0)
        )
    finally:
        core.release_pipeline(uid)
    return arts


# --- Auth gating -----------------------------------------------------------

@pytest.mark.parametrize("path", SEARCH_POSTS)
def test_search_endpoints_require_auth(app_module, path):
    c = TestClient(app_module.app)
    r = c.post(path, json={"query_text": "x", "seed": "x"})
    assert r.status_code == 401, f"{path}: {r.status_code} {r.text}"


def test_notes_endpoints_require_auth(app_module):
    c = TestClient(app_module.app)
    assert c.post("/api/notes", json={"article_id": "1", "source": "pubmed"}
                  ).status_code == 401
    assert c.get("/api/notes", params={"article_id": "1", "source": "pubmed"}
                 ).status_code == 401


# --- Happy paths -----------------------------------------------------------

def test_search_returns_ranked_results(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    r = c.post("/api/search", json={"query_text": "health", "top_k": 5},
               headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == len(body["results"])
    assert 0 < len(body["results"]) <= 5
    first = body["results"][0]
    for field in ("article_id", "source", "title"):
        assert field in first, f"missing {field} in result: {sorted(first)}"


def test_search_respects_top_k(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    small = c.post("/api/search", json={"query_text": "health", "top_k": 2},
                   headers=headers).json()
    assert len(small["results"]) <= 2


def test_seed_search_by_title_fragment(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    arts = _seed(app_module, c, headers)

    fragment = arts[0]["title"][:18]
    r = c.post("/api/search/seed", json={"seed": fragment, "top_k": 5},
               headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "seed" in body and body["total"] == len(body["results"])


def test_seed_search_unknown_seed_is_400_not_500(app_module):
    """A miss is user error; it must not surface as a server fault."""
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    r = c.post("/api/search/seed",
               json={"seed": "no-such-paper-anywhere-xyzzy", "top_k": 5},
               headers=headers)
    assert r.status_code == 400, f"{r.status_code}: {r.text}"
    assert "detail" in r.json()


def test_starred_search_with_no_stars_is_400(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    r = c.post("/api/search/starred", json={"top_k": 5}, headers=headers)
    assert r.status_code == 400, f"{r.status_code}: {r.text}"


def test_starred_search_after_starring(app_module):
    """Starred papers stay in their own results (regression from 4.3.1)."""
    c = TestClient(app_module.app)
    headers = _register(c)
    arts = _seed(app_module, c, headers)

    target = arts[0]
    r = c.post("/api/notes", json={
        "article_id": target["article_id"], "source": target["source"],
        "starred": True,
    }, headers=headers)
    assert r.status_code == 200, r.text

    r = c.post("/api/search/starred", json={"top_k": 10}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["seed_count"] >= 1
    returned = {(x["article_id"], x["source"]) for x in body["results"]}
    assert (target["article_id"], target["source"]) in returned, (
        "starred paper must remain in its own result list"
    )


# --- Notes -----------------------------------------------------------------

def test_note_roundtrip(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    arts = _seed(app_module, c, headers)
    a = arts[0]

    r = c.post("/api/notes", json={
        "article_id": a["article_id"], "source": a["source"],
        "note": "read this one first", "starred": True,
    }, headers=headers)
    assert r.status_code == 200, r.text

    r = c.get("/api/notes", params={"article_id": a["article_id"],
                                    "source": a["source"]}, headers=headers)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got.get("note") == "read this one first"
    assert got.get("starred") in (True, 1)


def test_note_write_requires_csrf(app_module):
    """Notes mutate state, so a bare cross-site POST must be refused."""
    c = TestClient(app_module.app)
    _register(c)          # cookies set, but send no X-CSRF-Token
    r = c.post("/api/notes", json={"article_id": "1", "source": "pubmed",
                                   "note": "x"})
    assert r.status_code == 403, f"{r.status_code}: {r.text}"


def test_get_note_requires_both_identifiers(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    assert c.get("/api/notes", params={"article_id": "1"},
                 headers=headers).status_code == 400
    assert c.get("/api/notes", params={"source": "pubmed"},
                 headers=headers).status_code == 400


def test_note_for_unknown_article_does_not_500(app_module):
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    r = c.get("/api/notes", params={"article_id": "not-real",
                                    "source": "pubmed"}, headers=headers)
    assert r.status_code == 200, r.text


# --- Isolation -------------------------------------------------------------

def test_notes_do_not_leak_between_accounts(app_module):
    """Private notes are per-account; libraries must not bleed."""
    c1 = TestClient(app_module.app)
    h1 = _register(c1, "noteowner")
    arts = _seed(app_module, c1, h1, username="noteowner")
    a = arts[0]
    c1.post("/api/notes", json={"article_id": a["article_id"],
                                "source": a["source"],
                                "note": "owner-private-note"}, headers=h1)

    c2 = TestClient(app_module.app)
    h2 = _register(c2, "notestranger")
    r = c2.get("/api/notes", params={"article_id": a["article_id"],
                                     "source": a["source"]}, headers=h2)
    assert r.status_code == 200, r.text
    assert "owner-private-note" not in r.text


# --- Regressions -----------------------------------------------------------

def test_note_for_missing_article_is_404_not_500(app_module):
    """A stale tab must not produce a server error.

    notes.article_id is a foreign key, so starring a paper that has since left
    the library raised sqlite3.IntegrityError and surfaced as 500. Reachable
    normally: a "replace" fetch or a library switch changes every article id
    under an already-open results page.
    """
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)

    r = c.post("/api/notes", json={
        "article_id": "gone-from-this-library", "source": "pubmed",
        "note": "still here?", "starred": True,
    }, headers=headers)
    assert r.status_code == 404, f"{r.status_code}: {r.text}"
    assert "detail" in r.json()


def test_stale_star_after_corpus_replace_is_404(app_module):
    """The real-world path: star a paper, replace the corpus, star it again."""
    c = TestClient(app_module.app)
    headers = _register(c)
    arts = _seed(app_module, c, headers)
    stale = arts[0]

    # Replace the corpus; article ids from the previous page are now gone.
    uid = _uid()
    pipe = core.get_pipeline(uid)
    try:
        pipe.db.clear_all()
    finally:
        core.release_pipeline(uid)

    r = c.post("/api/notes", json={
        "article_id": stale["article_id"], "source": stale["source"],
        "starred": True,
    }, headers=headers)
    assert r.status_code == 404, f"{r.status_code}: {r.text}"


@pytest.mark.parametrize("path, payload", [
    ("/api/search", {"query_text": "health"}),
    ("/api/search/seed", {"seed": "anything"}),
    ("/api/search/starred", {}),
])
def test_search_posts_require_csrf(app_module, path, payload):
    """Every state-changing-shaped POST needs the double-submit token.

    common.js already sends X-CSRF-Token on all non-GET calls, so requiring it
    costs the frontend nothing and closes the inconsistency with /api/notes.
    """
    c = TestClient(app_module.app)
    _register(c)              # cookies present, header deliberately omitted
    r = c.post(path, json=payload)
    assert r.status_code == 403, f"{path}: {r.status_code} {r.text}"


def test_search_still_works_with_csrf_header(app_module):
    """Guard against the check breaking legitimate use."""
    c = TestClient(app_module.app)
    headers = _register(c)
    _seed(app_module, c, headers)
    r = c.post("/api/search", json={"query_text": "health", "top_k": 3},
               headers=headers)
    assert r.status_code == 200, r.text
