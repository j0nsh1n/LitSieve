"""Job slots: per (account, library, task), two per account, never lost to the LRU."""

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
        assert core.try_begin_user_job("live", "L1", "fetch") is True
        for i in range(8):
            core.library_progress(f"other{i}", "L1")
        assert core.try_begin_user_job("live", "L1", "fetch") is False
        view = core.snapshot_jobs("live")["fetch"]
        assert view["active"] is True
        assert view["library_id"] == "L1"
        assert "live" in core._all_progress
        assert ("live", "L1", "fetch") in core._job_sync
    finally:
        _reset_jobs()


def test_idle_progress_is_still_evicted(monkeypatch):
    monkeypatch.setattr(core, "MAX_CACHED_USERS", 2)
    _reset_jobs()
    try:
        assert core.try_begin_user_job("live", "L1", "fetch") is True
        core.library_progress("idle-a", "L1")
        core.library_progress("idle-b", "L1")
        core.library_progress("idle-c", "L1")
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
        assert core.try_begin_user_job("u", "L1", "embed") is True
        core._all_progress["u"]["L1"]["embed"]["active"] = False
        assert core.try_begin_user_job("u", "L1", "embed") is False
    finally:
        _reset_jobs()


def test_each_library_has_its_own_slot_up_to_the_account_limit():
    _reset_jobs()
    try:
        assert core.try_begin_user_job("u", "L1", "fetch") is True
        assert core.try_begin_user_job("u", "L2", "fetch") is True
        assert core.account_jobs_full("u") is True
        assert core.try_begin_user_job("u", "L3", "fetch") is False
        assert core.try_begin_user_job("u", "L1", "embed") is False
        assert core.try_begin_user_job("other", "L3", "fetch") is True

        core.update_progress("u", "L1", "fetch", active=False)
        assert core.account_jobs_full("u") is False
        assert core.try_begin_user_job("u", "L3", "fetch") is True
    finally:
        _reset_jobs()


def test_library_progress_shows_only_that_library():
    _reset_jobs()
    try:
        assert core.try_begin_user_job("u", "L1", "fetch", message="one") is True
        assert core.library_progress("u", "L1")["fetch"]["active"] is True
        assert core.library_progress("u", "L2")["fetch"]["active"] is False
        assert core.request_job_cancel("u", "L2", "fetch") is False
        assert core.request_job_cancel("u", "L1", "fetch") is True
        assert core.is_job_cancelled("u", "L1", "fetch") is True
        assert core.is_job_cancelled("u", "L2", "fetch") is False
    finally:
        _reset_jobs()


def test_snapshot_prefers_the_running_slot_and_keeps_its_library():
    _reset_jobs()
    try:
        core.update_progress("u", "L1", "fetch", active=False, error="old failure")
        assert core.try_begin_user_job("u", "L2", "fetch") is True
        view = core.snapshot_jobs("u")["fetch"]
        assert view["active"] is True and view["library_id"] == "L2"
        assert core.snapshot_jobs("nobody")["embed"]["state"] == "idle"
        assert "nobody" not in core._all_progress
    finally:
        _reset_jobs()
