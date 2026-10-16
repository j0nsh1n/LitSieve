"""Cancel-aware HTTP retries: abort the ladder without burning the full backoff."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests

from app.fetchers import base as base_module
from app.fetchers.base import (
    FetchCancelled,
    FetchError,
    HttpClient,
    set_cancel_check,
    set_fetch_deadline,
    source_fetch_budget,
)
from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline


@pytest.fixture(autouse=True)
def _clear_cancel_token():
    set_cancel_check(None)
    set_fetch_deadline(None)
    yield
    set_cancel_check(None)
    set_fetch_deadline(None)


def _ok_response(status: int = 200) -> Mock:
    resp = Mock()
    resp.status_code = status
    resp.text = ""
    resp.headers = {}
    return resp


def test_cancel_before_first_attempt():
    client = HttpClient(delay=0, max_retries=4)
    client.session = Mock()
    set_cancel_check(lambda: True)

    with pytest.raises(FetchCancelled) as ei:
        client.request("GET", "https://example.test/x")

    assert str(ei.value) == "Cancelled"
    assert ei.value.kind == "cancelled"
    client.session.request.assert_not_called()


def test_cancel_during_backoff_stops_retry():
    client = HttpClient(delay=0, max_retries=4)
    client.session = Mock()
    client.session.request.side_effect = requests.exceptions.Timeout("slow")

    cancelled = [False]

    def flag():
        return cancelled[0]

    set_cancel_check(flag)
    # Flip after the first failure so backoff sees cancel mid-sleep.
    original_sleep = base_module.time.sleep

    def sleep_and_cancel(seconds):
        cancelled[0] = True
        original_sleep(min(seconds, 0.01))

    base_module.time.sleep = sleep_and_cancel
    try:
        started = time.monotonic()
        with pytest.raises(FetchCancelled):
            client.request("GET", "https://example.test/x")
        elapsed = time.monotonic() - started
    finally:
        base_module.time.sleep = original_sleep

    assert client.session.request.call_count == 1
    assert elapsed < 1.0


def test_no_cancel_preserves_retry(monkeypatch):
    monkeypatch.setattr(base_module.time, "sleep", lambda _s: None)
    client = HttpClient(delay=0, max_retries=4)
    client.session = Mock()
    client.session.request.side_effect = [
        requests.exceptions.Timeout("t1"),
        requests.exceptions.Timeout("t2"),
        _ok_response(200),
    ]
    set_cancel_check(lambda: False)

    resp = client.request("GET", "https://example.test/x")

    assert resp.status_code == 200
    assert client.session.request.call_count == 3


def test_fetch_one_binds_thread_local(tmp_path, monkeypatch):
    seen = {"bound": False}

    def cancel_flag():
        return False

    class _StubFetcher:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            check = getattr(base_module._CANCEL_TOKEN, "check", None)
            seen["bound"] = check is cancel_flag
            assert check is not None
            assert check() is False
            return []

    monkeypatch.setitem(pipeline_mod.FETCHERS, "pubmed", _StubFetcher)

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "cancel.db"))
    try:
        p.fetch_articles_parallel(
            query="q",
            sources=["pubmed"],
            max_results=1,
            cancel_check=cancel_flag,
        )
    finally:
        p.close()

    assert seen["bound"] is True
    assert getattr(base_module._CANCEL_TOKEN, "check", None) is None


@pytest.mark.parametrize("failure", ["timeout", 429, 503])
def test_http_retry_and_backoff_share_a_wall_clock_budget(failure):
    client = HttpClient(timeout=45, delay=0, budget_seconds=0.06)
    client.session = Mock()
    if failure == "timeout":
        client.session.request.side_effect = requests.exceptions.Timeout("dead host")
    else:
        resp = _ok_response(failure)
        resp.headers = {"Retry-After": "60"}
        client.session.request.return_value = resp

    started = time.monotonic()
    with pytest.raises(FetchError) as error:
        client.get("https://example.test/dead")
    elapsed = time.monotonic() - started

    if failure == "timeout":
        assert error.value.kind == "timeout"
        assert 0.05 <= elapsed < 0.5
    else:
        # Retry-After 60 cannot fit in the budget, so it fails at once (audit 18.8).
        assert error.value.kind == ("rate_limited" if failure == 429 else "network")
        assert elapsed < 0.05
    assert client.session.request.call_count == 1
    assert 0 < client.session.request.call_args.kwargs["timeout"] <= 0.06


def test_remaining_source_budget_is_shared_by_pages_and_clients(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(base_module.time, "monotonic", lambda: now[0])
    set_fetch_deadline(10.1)
    timeouts = []

    def page(*_args, **kwargs):
        timeouts.append(kwargs["timeout"])
        now[0] += 0.06
        return _ok_response()

    first, second = HttpClient(delay=0), HttpClient(delay=0)
    first.session.request = page
    second.session.request = page
    assert first.get("https://example.test/first").status_code == 200
    with pytest.raises(FetchError) as error:
        second.get("https://example.test/second")
    assert error.value.kind == "timeout"
    assert timeouts == pytest.approx([0.1, 0.04])


def test_standalone_client_keeps_its_budget_between_requests(monkeypatch):
    now = [10.0]
    monkeypatch.setattr(base_module.time, "monotonic", lambda: now[0])
    client = HttpClient(delay=0, budget_seconds=1)
    client.session.request = Mock(return_value=_ok_response())
    client.get("https://example.test/first")
    now[0] += 1.1
    with pytest.raises(FetchError) as error:
        client.get("https://example.test/next")
    assert error.value.kind == "timeout"
    assert client.session.request.call_count == 1


@pytest.mark.parametrize("raw", ["", "garbage", "0", "-1", "nan", "inf"])
def test_invalid_source_budget_uses_the_default(monkeypatch, raw):
    monkeypatch.setenv("LITSIEVE_FETCH_SOURCE_TIMEOUT", raw)
    assert source_fetch_budget() == 90


def test_pipeline_keeps_fast_articles_while_a_source_exceeds_its_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("LITSIEVE_FETCH_SOURCE_TIMEOUT", "0.04")
    fast_inserted = threading.Event()
    progress = []
    article = {
        "article_id": "fast-1", "source": "fast", "title": "Fast paper",
        "abstract": "Completed source results remain in the library.",
        "authors": [], "year": "2026", "journal": "Fixture",
    }

    class Fast:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            return [article]

    class Slow(Fast):
        def search_and_fetch(self, query, max_results):
            assert fast_inserted.wait(1), "other sources were blocked behind the slow source"
            time.sleep(0.06)
            return []

    def on_progress(done, total, **extra):
        progress.append((done, total, extra))
        if extra.get("source") == "fast" and extra.get("source_state") == "done":
            fast_inserted.set()

    monkeypatch.setitem(pipeline_mod.FETCHERS, "fast", Fast)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "slow", Slow)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "budget.db"))
    try:
        result = p.fetch_articles_parallel("q", ["fast", "slow"], progress_callback=on_progress)
        assert result["fast"]["count"] == 1
        assert result["fast"]["error"] is None
        assert result["slow"]["error_kind"] == "timeout"
        assert p.db.get_article_by_id("fast-1", "fast")["title"] == "Fast paper"
    finally:
        p.close()
    final = progress[-1][2]["source_progress"]
    assert final["fast"]["state"] == "done"
    assert final["slow"]["state"] == "done"
    assert final["slow"]["error_kind"] == "timeout"
    assert final["slow"]["elapsed_seconds"] >= 0.06
    assert final["slow"]["finished_at"] >= final["slow"]["started_at"]
    assert any(row[2]["source_state"] == "running" for row in progress)


def test_progress_reports_source_states_and_increasing_running_time(monkeypatch):
    from fastapi.testclient import TestClient

    from app import core
    from app.main import app
    from app.routes import corpus

    monkeypatch.setattr(corpus, "current_user", lambda _request: {"user_id": "deadline-fixture"})

    monkeypatch.setattr(corpus, "owned_library_id", lambda _uid, lib=None: lib or "L1")
    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    core.update_progress(
        "deadline-fixture", "L1", "fetch", active=True,
        source_progress={
            "openaire": {"state": "running", "started_at": 100, "finished_at": None,
                         "elapsed_seconds": 0, "error_kind": None},
            "fast": {"state": "done", "started_at": 100, "finished_at": 101,
                     "elapsed_seconds": 1, "error_kind": None},
            "queued": {"state": "queued", "started_at": None, "finished_at": None,
                       "elapsed_seconds": 0, "error_kind": None},
        },
    )
    monkeypatch.setattr(corpus.time, "time", lambda: 162)
    client = TestClient(app)
    response = client.get("/api/progress")
    assert response.status_code == 200
    rows = response.json()["fetch"]["source_progress"]
    assert rows["openaire"]["state"] == "running"
    assert rows["openaire"]["elapsed_seconds"] == 62
    assert rows["fast"]["elapsed_seconds"] == 1
    assert rows["queued"]["started_at"] is None
    monkeypatch.setattr(corpus.time, "time", lambda: 163)
    assert client.get("/api/progress").json()["fetch"]["source_progress"]["openaire"]["elapsed_seconds"] == 63
    assert core._all_progress["deadline-fixture"]["L1"]["fetch"]["source_progress"]["openaire"]["elapsed_seconds"] == 0


def test_fetch_job_reports_running_source_then_keeps_fast_results_on_http_timeout(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import core
    from app.main import app
    from app.routes import corpus

    uid = "budget-job-fixture"
    monkeypatch.setenv("LITSIEVE_FETCH_SOURCE_TIMEOUT", "0.3")
    monkeypatch.setattr(corpus, "current_user", lambda _request: {"user_id": uid})
    monkeypatch.setattr(corpus, "owned_library_id", lambda _uid, lib=None: lib or "L1")
    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    monkeypatch.setattr(corpus.quota, "is_over_quota", lambda *_args, **_kw: False)
    monkeypatch.setattr(corpus.quota, "usage_report", lambda *_args: {})
    article = {
        "article_id": "fast-1", "source": "fast", "title": "Fast paper",
        "abstract": "An article from the source that completed.",
        "authors": [], "year": "2026", "journal": "Fixture",
    }
    calls = []

    class Fast:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            return [article]

    class DeadHost(Fast):
        def search_and_fetch(self, query, max_results):
            http = HttpClient(delay=0, timeout=45)

            def timeout(*_args, **kwargs):
                calls.append(kwargs["timeout"])
                time.sleep(kwargs["timeout"])
                raise requests.exceptions.Timeout("host did not respond")

            http.session.request = timeout
            http.get("https://example.test/dead")

    monkeypatch.setitem(pipeline_mod.FETCHERS, "fast", Fast)
    monkeypatch.setitem(pipeline_mod.FETCHERS, "openaire", DeadHost)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "http-budget.db"))
    core.update_progress(uid, "L1", "fetch", active=True)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                corpus._run_multi_fetch, p, query="q", sources=["fast", "openaire"],
                max_results=10, email="test@example.test", clear_first=False, uid=uid, lib_id="L1",
            )
            client = TestClient(app)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                fetch = client.get("/api/progress").json()["fetch"]
                if fetch.get("by_source", {}).get("fast") == 1:
                    break
                time.sleep(0.005)
            running = fetch["source_progress"]
            assert running["fast"]["state"] == "done"
            assert running["openaire"]["state"] == "running"
            assert running["openaire"]["started_at"] is not None
            assert running["openaire"]["elapsed_seconds"] >= 0
            result = future.result(timeout=2)
        assert result["total_fetched"] == 1
        assert result["error_kinds"]["openaire"] == "timeout"
        final = client.get("/api/progress").json()["fetch"]["source_progress"]
        assert final["openaire"]["state"] == "done"
        assert final["openaire"]["error_kind"] == "timeout"
        assert len(calls) == 1
        assert 0 < calls[0] <= 0.3
    finally:
        p.close()


def test_cancel_closes_progress_for_running_and_queued_sources(tmp_path, monkeypatch):
    cancelled = threading.Event()
    snapshots = []

    class Slow:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            cancelled.wait(1)
            base_module.check_fetch_deadline()
            return []

    names = [f"source-{i}" for i in range(8)]
    for name in names:
        monkeypatch.setitem(pipeline_mod.FETCHERS, name, Slow)

    def on_progress(done, total, **extra):
        snapshots.append(extra["source_progress"])
        if sum(row["state"] == "running" for row in snapshots[-1].values()) == 6:
            cancelled.set()

    p = LiteratureSearchPipeline(db_path=str(tmp_path / "cancel-progress.db"))
    try:
        result = p.fetch_articles_parallel(
            "q", names, cancel_check=cancelled.is_set, progress_callback=on_progress,
        )
    finally:
        p.close()
    assert set(result) == set(names)
    assert all(row["error_kind"] == "cancelled" for row in result.values())
    assert all(row["state"] == "done" for row in snapshots[-1].values())
    assert all(row["error_kind"] == "cancelled" for row in snapshots[-1].values())


def test_new_fetch_slot_does_not_reuse_previous_source_progress(monkeypatch):
    from app import core

    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    monkeypatch.setattr(core, "_job_sync", {})
    monkeypatch.setattr(core, "_job_futures", {})
    uid = "new-fetch-fixture"
    core.update_progress(
        uid, "L1", "fetch", sources=["old"], by_source={"old": 1}, source_status={"old": "ok"},
        source_progress={"old": {"state": "done"}},
    )
    assert core.try_begin_user_job(uid, "L1", "fetch") is True
    slot = core._all_progress[uid]["L1"]["fetch"]
    assert slot["sources"] == []
    assert slot["source_status"] == {}
    assert slot["by_source"] == {}
    assert slot["source_progress"] == {}


def test_pipeline_inserts_completed_pages_from_a_timed_out_source(tmp_path, monkeypatch):
    article = {
        "article_id": "partial-1", "source": "openaire", "title": "Completed page",
        "abstract": "This page completed before a later request timed out.",
        "authors": [], "year": "2026", "journal": "Fixture",
    }

    class Partial:
        def __init__(self, email=None):
            pass

        def search_and_fetch(self, query, max_results):
            raise FetchError("Later page timed out", kind="timeout", articles=[article])

    monkeypatch.setitem(pipeline_mod.FETCHERS, "openaire", Partial)
    p = LiteratureSearchPipeline(db_path=str(tmp_path / "partial.db"))
    try:
        result = p.fetch_articles_parallel("q", ["openaire"])
        assert result["openaire"]["count"] == 1
        assert result["openaire"]["error_kind"] == "timeout"
        assert p.db.get_article_by_id("partial-1", "openaire")["title"] == "Completed page"
    finally:
        p.close()
