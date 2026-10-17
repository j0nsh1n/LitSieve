"""Finished jobs are recorded for Admin Overview; old history is pruned (20.5)."""

from datetime import datetime, timedelta, timezone

from app import core
from app.storage.user_db import UserDatabase


def _db(tmp_path, monkeypatch):
    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    monkeypatch.setattr(core, "_job_sync", {})
    monkeypatch.setattr(core, "_job_futures", {})
    return db


def _records(db):
    with db._lock:
        return db.conn.execute(
            "SELECT user_id, library_id, task, outcome, error_kinds FROM job_records ORDER BY id"
        ).fetchall()


def test_each_finished_job_is_recorded_once(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    assert core.try_begin_user_job("u", "L1", "fetch")
    result = {"status": "success", "error_kinds": {"pubmed": "rate_limited", "arxiv": "ok"}}
    core.update_progress("u", "L1", "fetch", active=False, result=result, error=None)
    core.update_progress("u", "L1", "fetch", active=False)  # the sync paths' finally
    assert core.try_begin_user_job("u", "L1", "embed")
    core.update_progress("u", "L1", "embed", active=False, result=None, error="boom")
    assert core.try_begin_user_job("u", "L2", "fetch")
    core.update_progress("u", "L2", "fetch", active=False, result={"status": "cancelled"})
    rows = _records(db)
    assert [(r[1], r[2], r[3]) for r in rows] == [
        ("L1", "fetch", "success"), ("L1", "embed", "failed"), ("L2", "fetch", "cancelled"),
    ]
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    summary = db.job_record_summary(since)
    assert summary == {"finished": 3, "failed": 1, "source_errors": {"pubmed": 1}}


def test_progress_updates_while_running_are_not_records(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    assert core.try_begin_user_job("u", "L1", "embed")
    core.update_progress("u", "L1", "embed", done=5, total=10)
    core.update_progress("u", "L1", "embed", active=False)  # idle slot reset, never ran here
    assert len(_records(db)) == 1
    core.update_progress("u", "L9", "embed", active=False)
    assert len(_records(db)) == 1


def test_prune_keeps_recent_history_and_drops_old(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    now = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)

    def at(days):
        return (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    with db._lock:
        for i, days in enumerate((91, 89)):
            db.conn.execute(
                "INSERT INTO auth_events (id, user_id, username, kind, ip, detail, created_at) "
                "VALUES (?, 'u', 'u', 'login', '', '', ?)", (f"e{i}", at(days)),
            )
            db.conn.execute(
                "INSERT INTO job_records (user_id, library_id, task, outcome, finished_at) "
                "VALUES ('u', 'L', 'fetch', 'success', ?)", (at(days),),
            )
        for i, days in enumerate((8, 6, -1)):
            db.conn.execute(
                "INSERT INTO one_time_logins (token_hash, user_id, expires_at, used, created_at) "
                "VALUES (?, 'u', ?, 0, ?)", (f"t{i}", at(days), at(days + 1)),
            )
            db.conn.execute(
                "INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES (?, 'u', ?)",
                (f"r{i}", at(days)),
            )
            db.conn.execute(
                "INSERT INTO email_verification_tokens (username, email, token_hash, expires_at) "
                "VALUES ('u', 'u@example.test', ?, ?)", (f"v{i}", at(days)),
            )
        db.conn.commit()
    removed = db.prune(now)
    assert removed == {
        "auth_events": 1, "job_records": 1, "email_verification_tokens": 1,
        "password_reset_tokens": 1, "one_time_logins": 1,
    }
    with db._lock:
        left = {
            t: db.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in removed
        }
    assert left == {
        "auth_events": 1, "job_records": 1, "email_verification_tokens": 2,
        "password_reset_tokens": 2, "one_time_logins": 2,
    }
    assert db.prune(now) == {t: 0 for t in removed}


def test_overview_failures_come_from_records(tmp_path, monkeypatch):
    from test_admin import _admin_client

    client, db = _admin_client(tmp_path, monkeypatch, username="recadmin")
    monkeypatch.setattr(core, "_all_progress", core.OrderedDict())
    db.add_job_record("x", "L", "fetch", "failed", {"semanticscholar": "rate_limited"})
    db.add_job_record("x", "L", "fetch", "success", {})
    d = client.get("/api/admin/overview").json()
    assert d["jobs"]["failed"] == 1 and d["jobs"]["finished"] == 2
    assert d["jobs_window_hours"] == 24
    health = {row["id"]: row["recent_errors"] for row in d["source_health"]}
    assert health.get("semanticscholar") == 1


def test_overview_wording_no_longer_says_since_restart():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert "since the last restart" not in (root / "static" / "js" / "admin.js").read_text()
    assert "Jobs (since restart)" not in (root / "templates" / "admin.html").read_text()
