"""Live background jobs must not be dropped by the progress LRU (audit A09)."""

from app import core


def _reset_jobs():
    core._all_progress.clear()
    core._job_futures.clear()
    core._job_sync.clear()


def test_live_job_survives_progress_lru(monkeypatch):
    """Claiming fetch, then touching many other users, must not free the slot."""
    monkeypatch.setattr(core, "MAX_CACHED_USERS", 2)
    _reset_jobs()
    try:
        assert core.try_begin_user_job("live", "fetch") is True
        for i in range(8):
            core.snapshot_jobs(f"other{i}")
        assert core.try_begin_user_job("live", "fetch") is False
        view = core.snapshot_jobs("live")["fetch"]
        assert view["active"] is True
        assert "live" in core._all_progress
        assert ("live", "fetch") in core._job_sync
    finally:
        _reset_jobs()


def test_idle_progress_is_still_evicted(monkeypatch):
    monkeypatch.setattr(core, "MAX_CACHED_USERS", 2)
    _reset_jobs()
    try:
        assert core.try_begin_user_job("live", "fetch") is True
        core.snapshot_jobs("idle-a")
        core.snapshot_jobs("idle-b")
        core.snapshot_jobs("idle-c")
        assert "live" in core._all_progress
        assert len(core._all_progress) <= 3  # live + cap idle, never unbounded
        idle = [uid for uid in core._all_progress if uid != "live"]
        assert len(idle) <= 2
    finally:
        _reset_jobs()


def test_job_markers_block_duplicate_claim(monkeypatch):
    """Even if the slot looks idle, a live worker marker must refuse a second start."""
    monkeypatch.setattr(core, "MAX_CACHED_USERS", 50)
    _reset_jobs()
    try:
        assert core.try_begin_user_job("u", "embed") is True
        core._all_progress["u"]["embed"]["active"] = False
        assert core.try_begin_user_job("u", "embed") is False
    finally:
        _reset_jobs()
