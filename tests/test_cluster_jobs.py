"""Theme grouping returns a receipt and keeps an owned library alive until completion."""

import asyncio
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import numpy as np
import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app import core
from app.services.pipeline import LiteratureSearchPipeline
from app.storage.user_db import UserDatabase


@pytest.fixture
def cluster_client(tmp_path, monkeypatch):
    from app.main import app

    @asynccontextmanager
    async def isolated_lifespan(_app):
        yield

    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "data"))
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    for name in ("_pipelines", "_all_progress"):
        monkeypatch.setattr(core, name, OrderedDict())
    for name in ("_pipeline_refcounts", "_pending_close", "_job_futures", "_job_sync"):
        monkeypatch.setattr(core, name, {})
    monkeypatch.setattr(app.router, "lifespan_context", isolated_lifespan)
    with TestClient(app) as client:
        response = client.post("/register", data={
            "username": "theme-fixture", "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        }, follow_redirects=False)
        assert response.status_code == 302
        uid = db.get_by_username("theme-fixture")["id"]
        library_id = client.get("/api/libraries").json()["active_id"]
        yield client, uid, library_id
    for pipe in core._pipelines.values():
        pipe.close()
    db.conn.close()


def _headers(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def _paper():
    return {"article_id": "one", "source": "pubmed", "title": "A theme paper",
            "abstract": "Complete original abstract", "year": "2024", "authors": [], "journal": "Fixture"}


def _until_done(client):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        slot = client.get("/api/progress").json()["cluster"]
        if not slot["active"]:
            return slot
        time.sleep(0.01)
    pytest.fail("Cluster job did not terminate")


def test_receipt_progress_conflict_and_completion_use_original_library(cluster_client, monkeypatch):
    client, uid, library_id = cluster_client
    pipe = core.get_pipeline(uid, library_id)
    pipe.db.insert_articles([_paper()])
    core.release_pipeline(uid, library_id)
    entered, finish = threading.Event(), threading.Event()

    def cluster(self, *, n_clusters, method, progress_callback):
        assert self is pipe
        assert method == "kmeans" and n_clusters == 2
        progress_callback(1, 3, "Finding themes")
        entered.set()
        assert finish.wait(3)
        self.db.insert_clusters({("one", "pubmed"): (0, "Theme")})
        progress_callback(3, 3, "Themes ready")
        return [], {}, {}, 1

    monkeypatch.setattr(LiteratureSearchPipeline, "cluster_articles", cluster)
    body = {"wait": False, "library_id": library_id, "method": "kmeans", "n_clusters": 2}
    try:
        receipt = client.post("/api/create-clusters", json=body, headers=_headers(client))
        assert receipt.status_code == 202 and receipt.json() == {"status": "started"}
        assert entered.wait(1)
        active = client.get("/api/progress").json()["cluster"]
        assert active["active"] and active["done"] == 1 and active["total"] == 3
        assert active["message"] == "Finding themes" and active["library_id"] == library_id
        assert core._pipeline_refcounts[core.pipeline_cache_key(uid, library_id)] == 1
        view = core.snapshot_jobs(uid)["cluster"]
        assert view["worker_alive"] and not view["can_cancel"] and not view["can_clear"]
        assert client.post("/api/create-clusters", json=body, headers=_headers(client)).status_code == 409
        assert client.post("/api/create-clusters", json={**body, "wait": True}, headers=_headers(client)).status_code == 409
        other = client.post("/api/libraries", json={"name": "Other"}, headers=_headers(client))
        assert other.status_code == 200
    finally:
        finish.set()
    completed = _until_done(client)
    assert completed["error"] is None
    assert completed["result"]["status"] == "success"
    assert completed["result"]["resolved_n_clusters"] == 1
    assert completed["result"]["clusters"][0]["cluster_label"] == "Theme"
    assert completed["result"]["auto"] is False
    assert core._pipeline_refcounts.get(core.pipeline_cache_key(uid, library_id), 0) == 0
    assert client.get("/api/clusters").json()["clusters"] == []
    scoped = client.get("/api/clusters/0/articles", params={"library_id": library_id, "include_abstract": True}).json()
    assert scoped["articles"][0]["abstract"] == "Complete original abstract"
    assert "abstract" not in client.get("/api/clusters/0/articles", params={"library_id": library_id}).json()["articles"][0]
    assert pipe.db.get_excluded_keys() == set()


def test_failure_closes_slot_and_sync_default_still_works(cluster_client, monkeypatch):
    client, uid, library_id = cluster_client

    def broken(self, **kwargs):
        raise RuntimeError("Grouping failed")

    monkeypatch.setattr(LiteratureSearchPipeline, "cluster_articles", broken)
    response = client.post("/api/create-clusters", json={"wait": False}, headers=_headers(client))
    assert response.status_code == 202
    failed = _until_done(client)
    assert failed["error"] == "Grouping failed" and failed["result"] is None
    assert not core.job_worker_alive(uid, "cluster")
    monkeypatch.setattr(LiteratureSearchPipeline, "cluster_articles", lambda self, **kwargs: None)
    sync = client.post("/api/create-clusters", json={}, headers=_headers(client))
    assert sync.status_code == 200 and sync.json()["clusters"] == []
    assert sync.json()["auto"] is True
    assert not core.job_worker_alive(uid, "cluster")
    assert core._pipeline_refcounts.get(core.pipeline_cache_key(uid, library_id), 0) == 0


def test_cluster_validation_auth_csrf_and_read_isolation(cluster_client):
    client, _uid, _library_id = cluster_client
    assert client.post("/api/create-clusters", json={"wait": False}).status_code == 403
    assert TestClient(client.app).post("/api/create-clusters", json={}).status_code == 401
    assert client.post("/api/create-clusters", json={"method": "density"}, headers=_headers(client)).status_code == 422
    assert client.post("/api/create-clusters", json={"library_id": "foreign"}, headers=_headers(client)).status_code == 400
    for path in ("/api/clusters", "/api/clusters/0/articles"):
        assert client.get(path, params={"library_id": "foreign"}).status_code == 400


def test_executor_submission_failure_releases_job_and_library(cluster_client, monkeypatch):
    client, uid, library_id = cluster_client

    def unavailable(self, executor, function, *args):
        raise RuntimeError("Executor unavailable")

    monkeypatch.setattr(asyncio.BaseEventLoop, "run_in_executor", unavailable)
    response = client.post("/api/create-clusters", json={"wait": False}, headers=_headers(client))
    assert response.status_code == 500
    slot = client.get("/api/progress").json()["cluster"]
    assert not slot["active"] and slot["error"] == "Executor unavailable"
    assert not core.job_worker_alive(uid, "cluster")
    assert core._pipeline_refcounts.get(core.pipeline_cache_key(uid, library_id), 0) == 0


def test_cluster_progress_is_not_evicted_or_cancellable(monkeypatch):
    monkeypatch.setattr(core, "_all_progress", OrderedDict())
    monkeypatch.setattr(core, "_job_sync", {})
    monkeypatch.setattr(core, "_job_futures", {})
    monkeypatch.setattr(core, "MAX_CACHED_USERS", 1)
    assert core.try_begin_user_job("running", "cluster", library_id="library")
    with core._progress_lock:
        core._ensure_progress("other")
    assert "running" in core._all_progress
    assert core.list_job_queue()[0]["task"] == "cluster"
    assert not core.clear_stale_job("running", "cluster")[0]
    core._job_sync.clear()
    assert core.clear_stale_job("running", "cluster")[0]
    assert not core._all_progress["running"]["cluster"]["active"]


def test_real_grouping_reports_stages_without_excluding_papers(tmp_path):
    pipe = LiteratureSearchPipeline(str(tmp_path / "articles.db"))
    rows = [{**_paper(), "article_id": str(i), "title": f"Theme paper {i}"} for i in range(6)]
    try:
        pipe.db.insert_articles(rows)
        pipe.db.insert_embeddings({(str(i), "pubmed"): np.array([i % 2, 1 - i % 2], dtype=np.float32) for i in range(6)}, model_name="general")
        stages = []
        result = pipe.cluster_articles(n_clusters=2, method="kmeans", progress_callback=lambda *args: stages.append(args))
        assert result[3] == 2
        assert [stage[0] for stage in stages] == [0, 1, 2, 3]
        assert all(stage[1] == 3 for stage in stages)
        assert len(pipe.db.get_all_clusters()) == 2
        assert pipe.db.get_excluded_keys() == set()
    finally:
        pipe.close()
