"""Per-account storage cap (MAX_USER_STORAGE_MB).

Guardrails: the cap must be enforced *before* work starts, must not silently
truncate a corpus, and must stay disable-able for single-user local runs.
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


def _register(client, username="quotauser"):
    r = client.post(
        "/register",
        data={"username": username, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code == 302, r.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_limit_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv(quota.ENV_KEY, raising=False)
    assert quota.limit_bytes() == quota.DEFAULT_MAX_MB * 1024 * 1024

    monkeypatch.setenv(quota.ENV_KEY, "10")
    assert quota.limit_bytes() == 10 * 1024 * 1024

    # 0 disables the cap entirely (single-user local runs).
    monkeypatch.setenv(quota.ENV_KEY, "0")
    assert quota.limit_bytes() == 0
    assert quota.is_over_quota("anyone") is False

    # Garbage must not crash the app or silently mean "unlimited".
    monkeypatch.setenv(quota.ENV_KEY, "not-a-number")
    assert quota.limit_bytes() == quota.DEFAULT_MAX_MB * 1024 * 1024

    # inf / NaN / negatives → default (negatives must not disable the cap).
    for bad in ("inf", "-inf", "nan", "-5"):
        monkeypatch.setenv(quota.ENV_KEY, bad)
        assert quota.limit_bytes() == quota.DEFAULT_MAX_MB * 1024 * 1024


def test_usage_counts_bytes_across_all_libraries(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    uid = "user-1"
    root = tmp_path / "ud" / uid / "libraries" / "lib-a"
    root.mkdir(parents=True)
    (root / "articles.db").write_bytes(b"x" * 4096)
    other = tmp_path / "ud" / uid / "libraries" / "lib-b"
    other.mkdir(parents=True)
    (other / "articles.db").write_bytes(b"y" * 2048)

    assert quota.usage_bytes(uid) == 6144
    # A different account is unaffected.
    assert quota.usage_bytes("user-2") == 0


def test_check_quota_raises_only_when_over(tmp_path, monkeypatch):
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "ud"))
    monkeypatch.setenv(quota.ENV_KEY, "1")  # 1 MB
    uid = "user-1"
    root = tmp_path / "ud" / uid
    root.mkdir(parents=True)

    (root / "small.db").write_bytes(b"x" * 1024)
    quota.check_quota(uid)  # under: no raise

    # Exactly at the cap (>=) is over — not only "strictly greater".
    (root / "exact.db").write_bytes(b"x" * (1024 * 1024 - 1024))
    assert quota.usage_bytes(uid) == 1024 * 1024
    with pytest.raises(quota.QuotaExceeded):
        quota.check_quota(uid)
    assert quota.is_over_quota(uid) is True

    (root / "extra.db").write_bytes(b"x" * 10)
    with pytest.raises(quota.QuotaExceeded):
        quota.check_quota(uid)


def test_fetch_refused_with_507_when_over_quota(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c)
    # Force "over quota" without writing hundreds of MB.
    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 10**9)
    monkeypatch.setenv(quota.ENV_KEY, "1")

    r = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"], "query": "x", "max_results": 5,
            "wait": True, "clear_first": False,
        },
        headers=headers,
    )
    assert r.status_code == 507, r.text
    body = r.json()
    assert "storage limit" in body["detail"].lower()
    assert body["quota"]["over_limit"] is True


def test_wait_true_fetch_conflicts_with_active_job(app_module):
    """wait=True must use the same per-user fetch slot as background jobs."""
    from app import core

    c = TestClient(app_module.app)
    headers = _register(c, "fetchlock")
    uid = core.user_db.get_by_username("fetchlock")["id"]
    with core._progress_lock:
        core._ensure_progress(uid)["fetch"].update(
            {"active": True, "done": 0, "total": 1, "result": None, "error": None}
        )
    r = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"], "query": "x", "max_results": 1,
            "wait": True, "clear_first": True,
        },
        headers=headers,
    )
    assert r.status_code == 409, r.text
    assert "already running" in r.json()["detail"].lower()


def test_fetch_clear_first_allowed_when_over_quota(app_module, monkeypatch):
    """Replace-mode fetch must not be blocked so an over-limit account can recover."""
    from app.routes import corpus as corpus_routes

    c = TestClient(app_module.app)
    headers = _register(c, "quotaclear")
    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 10**9)
    monkeypatch.setenv(quota.ENV_KEY, "1")

    # Append (clear_first=false) still blocked.
    r = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"], "query": "x", "max_results": 1,
            "wait": True, "clear_first": False,
        },
        headers=headers,
    )
    assert r.status_code == 507, r.text

    # Stub the job body so we only test preflight (no network).
    monkeypatch.setattr(
        corpus_routes,
        "_run_multi_fetch",
        lambda *a, **k: {
            "status": "success",
            "total_fetched": 0,
            "by_source": {},
            "ok_sources": {},
            "errors": {},
            "error_kinds": {},
            "cleared_first": True,
            "cancelled": False,
            "quota_stopped": False,
        },
    )
    r = c.post(
        "/api/fetch-articles-multi",
        json={
            "sources": ["pubmed"], "query": "x", "max_results": 1,
            "wait": True, "clear_first": True,
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json().get("status") == "success"


def test_embeddings_and_sample_corpus_also_gated(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c, "quotauser2")
    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 10**9)
    monkeypatch.setenv(quota.ENV_KEY, "1")

    r = c.post("/api/create-embeddings", json={"wait": True}, headers=headers)
    assert r.status_code == 507, r.text

    # Append sample without clear — still gated. (clear_first=true is allowed.)
    r = c.post("/api/load-sample-corpus", json={"clear_first": False}, headers=headers)
    assert r.status_code == 507, r.text


def test_statistics_exposes_storage_usage(app_module):
    c = TestClient(app_module.app)
    _register(c, "quotauser3")
    stats = c.get("/api/statistics").json()
    assert "storage" in stats
    for key in ("used_mb", "limit_mb", "percent", "over_limit"):
        assert key in stats["storage"], key
    assert stats["storage"]["over_limit"] is False


def test_fetch_finish_status_distinguishes_quota_from_cancel():
    status, cancelled = quota.fetch_finish_status(cancelled=False, hit_quota=True)
    assert status == "quota_stopped"
    assert cancelled is False

    status, cancelled = quota.fetch_finish_status(cancelled=True, hit_quota=False)
    assert status == "cancelled"
    assert cancelled is True

    # Quota wins if both somehow fire.
    status, cancelled = quota.fetch_finish_status(cancelled=True, hit_quota=True)
    assert status == "quota_stopped"
    assert cancelled is False

    status, cancelled = quota.fetch_finish_status(cancelled=False, hit_quota=False)
    assert status == "success"
    assert cancelled is False


def test_would_increase_stored_text():
    assert quota.would_increase_stored_text("", "a") is True
    assert quota.would_increase_stored_text("aa", "a") is False
    assert quota.would_increase_stored_text("a", "a") is False
    assert quota.would_increase_stored_text("a", None) is False
    assert quota.would_increase_stored_text("é", "e") is False  # 2 bytes -> 1


def _first_article(username: str):
    uid = core.user_db.get_by_username(username)["id"]
    p = core.get_pipeline(uid)
    try:
        arts = p.db.get_all_articles()
        assert arts
        return arts[0]
    finally:
        core.release_pipeline(uid)


def test_note_growth_blocked_when_over_quota(app_module, monkeypatch):
    """The reproduced hole: a megabyte-scale note stored after the cap was hit."""
    from app.schemas import NOTE_MAX_CHARS

    c = TestClient(app_module.app)
    headers = _register(c, "notequota")
    r = c.post("/api/load-sample-corpus", json={"clear_first": True}, headers=headers)
    assert r.status_code == 200, r.text
    art = _first_article("notequota")
    key = {"article_id": art["article_id"], "source": art["source"]}

    r = c.post("/api/notes", json={**key, "note": "keep"}, headers=headers)
    assert r.status_code == 200, r.text

    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 10**9)
    monkeypatch.setenv(quota.ENV_KEY, "1")

    r = c.post("/api/notes", json={**key, "note": "keep plus more"}, headers=headers)
    assert r.status_code == 507, r.text
    assert "storage limit" in r.json()["detail"].lower()
    got = c.get("/api/notes", params=key, headers=headers).json()
    assert got["note"] == "keep"

    r = c.post("/api/notes", json={**key, "note": "k"}, headers=headers)
    assert r.status_code == 200, r.text
    got = c.get("/api/notes", params=key, headers=headers).json()
    assert got["note"] == "k"

    r = c.post("/api/notes", json={**key, "note": ""}, headers=headers)
    assert r.status_code == 200, r.text

    r = c.post("/api/notes", json={**key, "starred": True}, headers=headers)
    assert r.status_code == 200, r.text

    r = c.post("/api/notes", json={**key, "note": "x" * (NOTE_MAX_CHARS + 1)}, headers=headers)
    assert r.status_code == 422, r.text


def test_share_join_and_ai_keypoints_gated_when_over_quota(app_module, monkeypatch):
    c = TestClient(app_module.app)
    headers = _register(c, "growthgate")
    r = c.post("/api/load-sample-corpus", json={"clear_first": True}, headers=headers)
    assert r.status_code == 200, r.text
    art = _first_article("growthgate")

    monkeypatch.setattr(quota, "usage_bytes", lambda uid: 10**9)
    monkeypatch.setenv(quota.ENV_KEY, "1")

    r = c.post("/api/shares/join", json={"code": "ABCD-EFGH"}, headers=headers)
    assert r.status_code == 507, r.text

    r = c.post(
        "/api/ai/key-points",
        json={
            "article_id": art["article_id"],
            "source": art["source"],
            "key_points": ["one finding"],
        },
        headers=headers,
    )
    assert r.status_code == 507, r.text
