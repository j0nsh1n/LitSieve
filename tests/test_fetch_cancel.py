"""Cancel-aware HTTP retries: abort the ladder without burning the full backoff."""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
import requests

from app.fetchers import base as base_module
from app.fetchers.base import FetchCancelled, HttpClient, set_cancel_check
from app.services import pipeline as pipeline_mod
from app.services.pipeline import LiteratureSearchPipeline


@pytest.fixture(autouse=True)
def _clear_cancel_token():
    set_cancel_check(None)
    yield
    set_cancel_check(None)


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
