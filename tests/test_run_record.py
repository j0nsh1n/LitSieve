"""P1.6: each library keeps Collect inputs and Search questions, without email."""

from __future__ import annotations

import importlib
import json
import os
import pathlib
import shutil
import sqlite3
import time

import numpy as np
import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.fetchers.base import FetchError
from app.fetchers.doaj import DOAJFetcher
from app.fetchers.hal import HALFetcher
from app.routes import corpus as corpus_routes
from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import shares
from app.storage.database import ArticleDatabase
from app.storage.libraries import (
    create_library,
    delete_library,
    ensure_libraries,
    get_active_library_id,
    library_db_path,
)
from app.storage.run_record import KEEP_ROWS, RANKER_VERSION, scrub_secrets
from app.storage.user_db import UserDatabase
from app.version import APP_VERSION

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

SECRET_EMAIL = "p16-never-store@litpilot.test"
ROOT = pathlib.Path(__file__).resolve().parents[1]


class _FakeFetcher:
    SOURCE_NAME = "pubmed"

    def __init__(self, email=None, **kwargs):
        self.email = email
        self.sent_query = None

    def search_and_fetch(self, query, max_results=200):
        self.sent_query = f"SAFE:{query}"
        return [{
            "article_id": "fake-1",
            "source": "pubmed",
            "title": f"Fake article about {query}",
            "abstract": "A canned abstract used for run-record testing.",
            "year": "2024",
            "authors": ["Tester T"],
            "journal": "Journal of Testing",
        }]


class _FailingFetcher:
    def __init__(self, email=None, **kwargs):
        pass

    def search_and_fetch(self, query, max_results=200):
        raise FetchError("source down", kind="network")


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _register(client, username="runrec"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD,
              "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return _csrf(client)


def _uid(username="runrec"):
    row = core.user_db.get_by_username(username)
    assert row is not None
    return row["id"]


def _lib_db(username="runrec"):
    uid = _uid(username)
    lib_id = get_active_library_id(uid)
    return ArticleDatabase(str(library_db_path(uid, lib_id))), uid, lib_id


def _fetch_rows(db):
    return db.conn.execute(
        "SELECT id, raw_input, mode, outcome, app_version, sources_json, "
        "per_source_json, finished_at FROM fetch_runs ORDER BY id"
    ).fetchall()


def _question_rows(db):
    return db.conn.execute(
        "SELECT kind, question_text, filters_json, embedding_model, "
        "ranker_version, result_keys_json FROM question_log ORDER BY id"
    ).fetchall()


def _db_bytes_contain(db_path: str, needle: str) -> bool:
    path = pathlib.Path(db_path)
    blob = path.read_bytes() if path.is_file() else b""
    wal = pathlib.Path(str(path) + "-wal")
    if wal.is_file():
        blob += wal.read_bytes()
    return needle.encode("utf-8") in blob


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "templates", tmp_path / "templates")
    shutil.copytree(ROOT / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))

    main = importlib.import_module("app.main")
    core.user_db = UserDatabase(db_path=str(tmp_path / "users.db"))
    core._pipelines.clear()
    core._pipeline_refcounts.clear()
    core._all_progress.clear()
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FakeFetcher)
    try:
        core.limiter.reset()
    except Exception:
        pass
    return main


def test_scrub_secrets_strips_email_and_keys():
    text = scrub_secrets(
        f"q {SECRET_EMAIL} api_key=abcd1234xyz NCBI_API_KEY=secretkey99"
    )
    assert SECRET_EMAIL not in text
    assert "abcd1234xyz" not in text
    assert "secretkey99" not in text
    assert "[email]" in text
    assert "[key]" in text


def test_new_and_migrated_databases_have_run_tables(tmp_path):
    fresh = ArticleDatabase(str(tmp_path / "fresh.db"))
    try:
        names = {
            r[0] for r in fresh.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "fetch_runs" in names and "question_log" in names
    finally:
        fresh.close()

    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE articles (article_id TEXT, source TEXT, title TEXT, "
        "abstract TEXT, PRIMARY KEY (article_id, source))"
    )
    conn.commit()
    conn.close()
    migrated = ArticleDatabase(str(old))
    try:
        names = {
            r[0] for r in migrated.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "fetch_runs" in names and "question_log" in names
        migrated._ensure_run_record_tables(migrated.conn.cursor())
        migrated.conn.commit()
        assert migrated.conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == 0
    finally:
        migrated.close()


def test_sync_fetch_writes_a_finished_row(app_module):
    client = TestClient(app_module.app)
    headers = _register(client, "syncfetch")
    r = client.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "sleep and screens",
            "max_results": 5,
            "email": SECRET_EMAIL,
            "wait": True,
            "clear_first": True,
            "topics": ["health"],
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    db, uid, lib_id = _lib_db("syncfetch")
    try:
        rows = _fetch_rows(db)
        assert len(rows) == 1
        _id, raw, mode, outcome, version, sources, per_source, finished = rows[0]
        assert raw == "sleep and screens"
        assert mode == "replace"
        assert outcome == "success"
        assert version == APP_VERSION
        assert json.loads(sources) == ["pubmed"]
        payload = json.loads(per_source)
        assert payload["pubmed"]["sent_query"] == "SAFE:sleep and screens"
        assert payload["pubmed"]["inserted"] == 1
        assert finished
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert not _db_bytes_contain(db.db_path, SECRET_EMAIL)
    finally:
        db.close()


def test_background_fetch_writes_a_finished_row(app_module):
    client = TestClient(app_module.app)
    headers = _register(client, "bgfetch")
    r = client.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"],
            "query": "background query",
            "max_results": 5,
            "wait": False,
            "clear_first": False,
        },
        headers=headers,
    )
    assert r.status_code == 202, r.text
    deadline = time.time() + 5
    while time.time() < deadline:
        prog = client.get("/api/progress").json()
        if not (prog.get("fetch") or {}).get("active"):
            break
        time.sleep(0.05)
    db, _, _ = _lib_db("bgfetch")
    try:
        rows = _fetch_rows(db)
        assert len(rows) == 1
        assert rows[0][1] == "background query"
        assert rows[0][2] == "append"
        assert rows[0][3] == "success"
        assert rows[0][7]
    finally:
        db.close()


def test_cancelled_fetch_records_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FakeFetcher)
    monkeypatch.setattr(corpus_routes, "is_job_cancelled", lambda *a, **k: True)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "cancel.db"))
    try:
        result = corpus_routes._run_multi_fetch(
            p, query="cancel me", sources=["pubmed"], max_results=5,
            email=SECRET_EMAIL, clear_first=False, uid="u", lib_id="L",
        )
        assert result["status"] == "cancelled"
        rows = _fetch_rows(p.db)
        assert len(rows) == 1
        assert rows[0][3] == "cancelled"
        assert rows[0][7]
        p.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        assert not _db_bytes_contain(p.db.db_path, SECRET_EMAIL)
    finally:
        p.close()


def test_failed_fetch_records_error(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)

    def boom(*_a, **_k):
        raise RuntimeError("disk failed")

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "err.db"))
    try:
        monkeypatch.setattr(p, "fetch_articles_parallel", boom)
        with pytest.raises(RuntimeError, match="disk failed"):
            corpus_routes._run_multi_fetch(
                p, query="boom", sources=["pubmed"], max_results=5,
                email=None, clear_first=False, uid="u", lib_id="L",
            )
        rows = _fetch_rows(p.db)
        assert len(rows) == 1
        assert rows[0][3] == "error"
        assert rows[0][7]
    finally:
        p.close()


def test_source_error_still_finishes_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FailingFetcher)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "srcerr.db"))
    try:
        result = corpus_routes._run_multi_fetch(
            p, query="x", sources=["pubmed"], max_results=5,
            email=None, clear_first=False, uid="u", lib_id="L",
        )
        assert result["errors"]
        rows = _fetch_rows(p.db)
        assert rows[0][3] == "success"
        per = json.loads(rows[0][6])
        assert per["pubmed"]["error_kind"] == "network"
    finally:
        p.close()


def test_email_never_lands_in_the_library_file(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FakeFetcher)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "email.db"))
    try:
        corpus_routes._run_multi_fetch(
            p, query="caffeine", sources=["pubmed"], max_results=5,
            email=SECRET_EMAIL, clear_first=True, uid="u", lib_id="L",
        )
        p.db.compact()
        assert not _db_bytes_contain(p.db.db_path, SECRET_EMAIL)
        raw = p.db.conn.execute("SELECT raw_input, per_source_json FROM fetch_runs").fetchone()
        assert SECRET_EMAIL not in raw[0]
        assert SECRET_EMAIL not in raw[1]
    finally:
        p.close()


def test_pruning_keeps_the_newest_50(tmp_path):
    db = ArticleDatabase(str(tmp_path / "prune.db"))
    try:
        for i in range(KEEP_ROWS + 3):
            db.insert_fetch_run(
                started_at=f"2026-01-01T00:00:{i:02d}Z",
                raw_input=f"q{i}",
                sources=["pubmed"],
                topics=[],
                areas=[],
                mode="append",
                max_results=5,
                app_version="6.0.0",
            )
            db.insert_question_log(
                created_at=f"2026-01-01T00:00:{i:02d}Z",
                kind="search",
                question_text=f"ask {i}",
                filters={},
                embedding_model="general",
                result_keys=[],
            )
        fetch_ids = [r[0] for r in db.conn.execute(
            "SELECT id FROM fetch_runs ORDER BY id"
        )]
        q_ids = [r[0] for r in db.conn.execute(
            "SELECT id FROM question_log ORDER BY id"
        )]
        assert len(fetch_ids) == KEEP_ROWS
        assert len(q_ids) == KEEP_ROWS
        assert fetch_ids[-1] == KEEP_ROWS + 3
        assert q_ids[-1] == KEEP_ROWS + 3
        leftovers = db.conn.execute(
            "SELECT raw_input FROM fetch_runs ORDER BY id"
        ).fetchall()
        assert leftovers[0][0] == "q3"
        assert leftovers[-1][0] == f"q{KEEP_ROWS + 2}"
    finally:
        db.close()


def _seed_search(client, headers, username):
    r = client.post("/api/load-sample-corpus", json={"clear_first": True}, headers=headers)
    assert r.status_code == 200, r.text
    uid = _uid(username)
    pipe = core.get_pipeline(uid)
    try:
        arts = pipe.db.get_all_articles()
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


def test_search_seed_starred_and_preview_write_question_log(app_module):
    client = TestClient(app_module.app)
    headers = _register(client, "qlog")
    arts = _seed_search(client, headers, "qlog")
    seed = arts[0]
    client.post(
        "/api/notes",
        json={"article_id": seed["article_id"], "source": seed["source"],
              "starred": True, "note": ""},
        headers=headers,
    )
    search = client.post(
        "/api/search",
        json={"query_text": "health sleep", "top_k": 3, "lexical_boost": True},
        headers=headers,
    )
    assert search.status_code == 200, search.text
    seeded = client.post(
        "/api/search/seed",
        json={"seed": seed["article_id"], "top_k": 4},
        headers=headers,
    )
    assert seeded.status_code == 200, seeded.text
    starred = client.post("/api/search/starred", json={"top_k": 5}, headers=headers)
    assert starred.status_code == 200, starred.text
    preview = client.post(
        "/api/screening/quick-preview",
        json={"query": "Does sleep help memory?", "fraction": 0.25},
        headers=headers,
    )
    assert preview.status_code == 200, preview.text

    db, _, _ = _lib_db("qlog")
    try:
        kinds = [row[0] for row in _question_rows(db)]
        assert kinds == ["search", "seed", "starred", "narrow_preview"]
        search_row = _question_rows(db)[0]
        assert search_row[1] == "health sleep"
        assert search_row[3] == "general"
        assert search_row[4] == RANKER_VERSION
        keys = json.loads(search_row[5])
        assert keys
        assert keys[0][0] and keys[0][1]
        filters = json.loads(search_row[2])
        assert filters["top_k"] == 3
        assert filters["lexical_boost"] is True
        assert _question_rows(db)[1][1] == seed["article_id"]
        assert _question_rows(db)[2][1] == ""
        assert "Does sleep help memory?" in _question_rows(db)[3][1]
    finally:
        db.close()


def test_question_log_write_failure_does_not_break_search(app_module, monkeypatch):
    client = TestClient(app_module.app)
    headers = _register(client, "failog")
    _seed_search(client, headers, "failog")

    def boom(self, *a, **k):
        raise RuntimeError("cannot write question_log")

    monkeypatch.setattr(ArticleDatabase, "insert_question_log", boom)
    r = client.post(
        "/api/search",
        json={"query_text": "health", "top_k": 2},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["results"]


def test_clone_drops_fetch_runs_and_question_log(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    src = library_db_path("owner", "lib1")
    src.parent.mkdir(parents=True, exist_ok=True)
    db = ArticleDatabase(str(src))
    db.insert_articles([{
        "article_id": "p0", "source": "pubmed", "title": "T",
        "abstract": "A", "year": "2020", "authors": ["A"], "journal": "J",
    }], dedupe=False)
    db.insert_fetch_run(
        started_at="2026-01-01T00:00:00Z", raw_input="secret question",
        sources=["pubmed"], topics=["health"], areas=[], mode="replace",
        max_results=10, app_version="6.0.0",
    )
    db.insert_question_log(
        created_at="2026-01-01T00:00:00Z", kind="search",
        question_text="secret question", filters={}, embedding_model="general",
        result_keys=[["p0", "pubmed"]],
    )
    db.close()

    shares.clone_library_data("owner", "lib1", "student", "lib2")
    dest = ArticleDatabase(str(library_db_path("student", "lib2")))
    try:
        assert dest.conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == 0
        assert dest.conn.execute("SELECT COUNT(*) FROM question_log").fetchone()[0] == 0
        assert dest.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
        assert "fetch_runs" not in shares.CLONE_TABLES
        assert "question_log" not in shares.CLONE_TABLES
    finally:
        dest.close()


def test_start_over_clears_run_records(tmp_path):
    db = ArticleDatabase(str(tmp_path / "start.db"))
    try:
        db.insert_articles([{
            "article_id": "keep", "source": "pubmed", "title": "Keep",
            "abstract": "A", "year": "2020", "authors": ["A"], "journal": "J",
        }, {
            "article_id": "drop", "source": "pubmed", "title": "Drop",
            "abstract": "A", "year": "2020", "authors": ["A"], "journal": "J",
        }], dedupe=False)
        db.upsert_note("keep", "pubmed", note="keep me", starred=True)
        db.insert_fetch_run(
            started_at="2026-01-01T00:00:00Z", raw_input="old run",
            sources=["pubmed"], topics=[], areas=[], mode="replace",
            max_results=5, app_version="6.0.0",
        )
        db.insert_question_log(
            created_at="2026-01-01T00:00:00Z", kind="search",
            question_text="old q", filters={}, embedding_model="general",
            result_keys=[],
        )
        db.keep_starred_and_noted()
        assert db.conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM question_log").fetchone()[0] == 0
        assert db.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
    finally:
        db.close()


def test_deleted_library_file_is_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    uid = "user-p16"
    ensure_libraries(uid)
    second = create_library(uid, "Extra")["library"]["id"]
    path = library_db_path(uid, second)
    db = ArticleDatabase(str(path))
    db.insert_fetch_run(
        started_at="2026-01-01T00:00:00Z", raw_input="gone",
        sources=["pubmed"], topics=[], areas=[], mode="append",
        max_results=1, app_version="6.0.0",
    )
    db.close()
    assert path.is_file()
    delete_library(uid, second)
    assert not path.exists()
    assert not path.parent.exists()


def test_replace_fetch_swap_leaves_run_records(tmp_path, monkeypatch):
    monkeypatch.setattr(corpus_routes, "update_progress", lambda *a, **k: None)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _FakeFetcher)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "swap.db"))
    try:
        p.db.insert_articles([{
            "article_id": "old", "source": "pubmed", "title": "Old",
            "abstract": "A", "year": "2020", "authors": ["A"], "journal": "J",
        }], dedupe=False)
        p.db.insert_fetch_run(
            started_at="2026-01-01T00:00:00Z", raw_input="prior",
            sources=["pubmed"], topics=[], areas=[], mode="replace",
            max_results=5, app_version="6.0.0",
        )
        corpus_routes._run_multi_fetch(
            p, query="new", sources=["pubmed"], max_results=5,
            email=None, clear_first=True, uid="u", lib_id="L",
        )
        inputs = [r[0] for r in p.db.conn.execute(
            "SELECT raw_input FROM fetch_runs ORDER BY id"
        )]
        assert inputs == ["prior", "new"]
    finally:
        p.close()


def test_admin_and_support_do_not_read_run_record_tables():
    for rel in (
        "app/routes/admin.py",
        "app/routes/support.py",
        "app/storage/helpdesk.py",
        "app/storage/user_db.py",
    ):
        text = (ROOT / rel).read_text()
        assert "fetch_runs" not in text
        assert "question_log" not in text


def test_doaj_and_hal_record_the_sanitized_query():
    from app.fetchers.querytext import lucene_safe, solr_safe

    doaj = DOAJFetcher()
    with pytest.raises(FetchError) as ei:
        doaj.search_and_fetch("???")
    assert ei.value.kind == "bad_query"
    assert doaj.sent_query == ""
    assert doaj.remember_sent_query(lucene_safe("heart?disease")) == "heart disease"

    hal = HALFetcher()
    with pytest.raises(FetchError) as ei:
        hal.search_and_fetch("???")
    assert ei.value.kind == "bad_query"
    assert hal.sent_query == ""
    assert "\\?" in hal.remember_sent_query(solr_safe("heart?disease"))
