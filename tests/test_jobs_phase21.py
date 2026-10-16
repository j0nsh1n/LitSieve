"""Audit 21.1-21.5 and 21.8: cancel, library binding, slot claims, bounds."""

from pathlib import Path

from fastapi.testclient import TestClient
from test_integration_accounts import _register, app_module  # noqa: F401

from app import core
from app.routes import corpus

ROOT = Path(__file__).resolve().parents[1]


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


class _Stats:
    def get_statistics(self):
        return {"articles_with_embeddings": 0}


def test_cancel_stops_a_prepare_between_batches(monkeypatch):
    uid = "cancel-embed"
    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    core.update_progress(uid, "L1", "embed", active=True)
    batches = []

    class Pipe(_Stats):
        def create_embeddings(self, model, progress_callback, only_missing):
            for done in (32, 64, 96):
                batches.append(done)
                progress_callback(done, 96)
                if done == 32:
                    core.request_job_cancel(uid, "L1", "embed")
            return {"embeddings_created": 96}

    result = corpus._run_create_embeddings(Pipe(), model="general", only_missing=True, uid=uid, lib_id="L1")
    assert result["status"] == "cancelled"
    assert batches == [32, 64]  # stopped at the first batch after the cancel


def test_a_sync_prepare_does_not_take_over_a_running_one(app_module):
    client = TestClient(app_module.app)
    _register(client, "syncembed")
    uid = core.user_db.get_by_username("syncembed")["id"]
    lib = client.get("/api/libraries").json()["active_id"]
    assert core.try_begin_user_job(uid, lib, "embed")
    r = client.post("/api/create-embeddings", json={"wait": True}, headers=_csrf(client))
    assert r.status_code == 409
    assert "already being prepared in this library" in r.json()["detail"].lower()
    assert core._ensure_progress(uid, lib)["embed"]["active"] is True


def test_duplicate_threshold_is_bounded(app_module):
    client = TestClient(app_module.app)
    _register(client, "dupbounds")
    r = client.post("/api/detect-duplicates", json={"threshold": -1}, headers=_csrf(client))
    assert r.status_code == 422
    src = (ROOT / "app" / "routes" / "corpus.py").read_text()
    assert "await run_in_thread(p.detect_duplicates, threshold=req.threshold)" in src


def test_fetch_sources_are_known_and_unique(app_module):
    client = TestClient(app_module.app)
    _register(client, "srcvalid")
    r = client.post(
        "/api/fetch-articles-multi",
        json={"sources": ["pubmed", "nowhere"], "query": "x", "max_results": 5, "wait": True},
        headers=_csrf(client),
    )
    assert r.status_code == 400
    assert "Unknown database: nowhere" in r.json()["detail"]
    r = client.post(
        "/api/fetch-articles-multi",
        json={"sources": ["pubmed", "pubmed"], "query": "x", "max_results": 5, "wait": True},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert list(r.json()["by_source"]) == ["pubmed"]


def test_page_bound_routes_refuse_a_library_this_account_does_not_own(app_module):
    client = TestClient(app_module.app)
    _register(client, "libbound")
    foreign = {"library_id": "not-mine"}
    for path, body in (
        ("/api/start-over", {}),
        ("/api/load-sample-corpus", {"clear_first": True}),
        ("/api/detect-duplicates", {"threshold": 0.98}),
        ("/api/screening/quick-preview", {"query": "q", "fraction": 0.25}),
        ("/api/clusters/1/screening", {"action": "exclude"}),
    ):
        r = client.post(path, json={**body, **foreign}, headers=_csrf(client))
        assert r.status_code == 400, (path, r.status_code, r.text)


def test_the_page_sends_its_library_with_those_calls():
    collect = (ROOT / "static" / "js" / "collect.js").read_text()
    tools = (ROOT / "static" / "js" / "simple_tools.js").read_text()
    assert "body: withPageLibrary({ clear_first: !!clearFirst })" in collect
    assert "body: withPageLibrary({ threshold: 0.98 })" in collect
    assert tools.count("body: withPageLibrary({ query, fraction })") == 3
    assert "apiCall('/api/start-over', { method: 'POST', body: withPageLibrary({}) })" in tools


def test_progress_is_scoped_to_the_library_asked_for(app_module):
    client = TestClient(app_module.app)
    _register(client, "twolibs")
    uid = core.user_db.get_by_username("twolibs")["id"]
    first = client.get("/api/libraries").json()["active_id"]
    second_id = client.post("/api/libraries", json={"name": "Second"}, headers=_csrf(client)).json()["active_id"]
    assert second_id != first
    assert core.try_begin_user_job(uid, first, "fetch")
    assert client.get("/api/progress", params={"library_id": first}).json()["fetch"]["active"] is True
    assert client.get("/api/progress", params={"library_id": second_id}).json()["fetch"]["active"] is False
    assert client.get("/api/progress", params={"library_id": "nope"}).status_code == 400
    r = client.post("/api/jobs/fetch/cancel", json={"library_id": second_id}, headers=_csrf(client))
    assert r.status_code == 409
    r = client.post("/api/jobs/fetch/cancel", json={"library_id": first}, headers=_csrf(client))
    assert r.status_code == 200
    assert core.is_job_cancelled(uid, first, "fetch")


def test_a_second_library_runs_while_the_account_limit_holds(app_module):
    client = TestClient(app_module.app)
    _register(client, "joblimit")
    uid = core.user_db.get_by_username("joblimit")["id"]
    first = client.get("/api/libraries").json()["active_id"]
    assert core.try_begin_user_job(uid, first, "embed")
    assert core.try_begin_user_job(uid, "elsewhere", "fetch")
    r = client.post("/api/create-embeddings", json={"wait": True}, headers=_csrf(client))
    assert r.status_code == 409
    assert "already being prepared in this library" in r.json()["detail"]
    third = client.post("/api/libraries", json={"name": "Third"}, headers=_csrf(client)).json()["active_id"]
    r = client.post("/api/create-embeddings", json={"wait": True, "library_id": third}, headers=_csrf(client))
    assert r.status_code == 409
    assert "already running 2 jobs" in r.json()["detail"]


def test_every_page_poll_names_its_library():
    for name in ("search.js", "collect.js", "simple_tools.js"):
        src = (ROOT / "static" / "js" / name).read_text()
        assert "apiCall('/api/progress')" not in src, name
    common = (ROOT / "static" / "js" / "common.js").read_text()
    assert "'/api/progress' + (id ? '?library_id='" in common


def test_review_follow_ups_hold():
    """Checks for the four defects a review of Phases 19-21 found."""
    search = (ROOT / "static" / "js" / "search.js").read_text()
    assert "const embedNow = (progress && progress.embed) || embed;" in search
    tools = (ROOT / "static" / "js" / "simple_tools.js").read_text()
    undo = tools[tools.index("async function doSimpleScreenDuplicatesUndo("):tools.index("function getResearchQuestionCandidate(")]
    assert "library_id=" in undo and "withPageLibrary({ items, action: 'include' })" in undo
    collect = (ROOT / "static" / "js" / "collect.js").read_text()
    embed = collect[collect.index("async function doCreateEmbeddings("):]
    assert embed.index("data.status === 'cancelled'") < embed.index("const created = data.embeddings_created")
    assert "already being prepared" in collect
    assert "Papers are already being prepared" in (ROOT / "app" / "routes" / "corpus.py").read_text()
    pack = collect[collect.index("function applyTopicPack("):collect.index("function toggleTopic(")]
    assert "layaAreas = new Set();" in pack
