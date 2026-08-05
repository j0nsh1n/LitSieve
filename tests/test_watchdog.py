"""Watchdog for the failure that went unnoticed for 4h47m.

The Cloudflare token was revoked while the site kept serving on already-open
connections; the outage only began at the next unattended reboot. Every
available signal looked fine — systemd said the tunnel was `active`, the app
answered /health 200, and curl against the public hostname returns 403 whether
the tunnel is up or not (managed challenge). These tests pin the checks that
actually distinguish up from down.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("wd", REPO / "tools" / "watchdog.py")
wd = importlib.util.module_from_spec(_spec)
sys.modules["wd"] = wd
_spec.loader.exec_module(wd)


def _journal(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def registered(ts: float) -> str:
    return f"{ts} cloudflared: INF Registered tunnel connection connIndex=0"


def auth_error(ts: float) -> str:
    return (f'{ts} cloudflared: ERR Register tunnel error from server side '
            'error="Unauthorized: Invalid tunnel secret" connIndex=0')


# Ordering is decided by the timestamp, not the line order in the journal.
REGISTERED = registered(1785900100.0)
AUTH_ERROR = auth_error(1785900200.0)


def _fake_run(active="active", journal=""):
    def run(cmd, timeout=10):
        if cmd[:3] == ["systemctl", "--user", "is-active"]:
            return 0, active + "\n"
        if cmd[0] == "journalctl":
            return 0, journal
        return 0, ""
    return run


# --- Tunnel checks ---------------------------------------------------------

def test_auth_failure_is_caught_even_though_service_is_active(monkeypatch):
    """The exact 2026-08-05 failure: active unit, rejected registrations."""
    monkeypatch.setattr(wd, "_run", _fake_run("active", _journal(AUTH_ERROR)))
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is False
    assert any("Invalid tunnel secret" in p for p in r.problems)
    assert any("secrets/cloudflared.env" in p for p in r.problems), (
        "the alert should say how to fix it"
    )


def test_registered_connections_are_healthy(monkeypatch):
    monkeypatch.setattr(wd, "_run", _fake_run("active", _journal(REGISTERED)))
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is True


def test_errors_before_a_successful_reconnect_are_not_an_alarm(monkeypatch):
    """After fixing the token the old errors stay in the journal window.

    Counting errors would keep alerting forever; compare recency instead.
    """
    # error first, then a *later* successful registration
    journal = _journal(auth_error(1785900200.0), registered(1785900300.0))
    monkeypatch.setattr(wd, "_run", _fake_run("active", journal))
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is True, r.problems


def test_new_errors_after_a_reconnect_do_alarm(monkeypatch):
    # registered, then rejected again later (token revoked while running)
    journal = _journal(registered(1785900100.0), auth_error(1785900400.0))
    monkeypatch.setattr(wd, "_run", _fake_run("active", journal))
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is False


def test_stopped_tunnel_is_caught(monkeypatch):
    monkeypatch.setattr(wd, "_run", _fake_run("inactive", ""))
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is False
    assert any("inactive" in p for p in r.problems)


def test_unreadable_journal_does_not_false_alarm(monkeypatch):
    """Missing journal access is not evidence the site is down."""
    def run(cmd, timeout=10):
        if cmd[:3] == ["systemctl", "--user", "is-active"]:
            return 0, "active\n"
        return 1, "No journal files were found."
    monkeypatch.setattr(wd, "_run", run)
    r = wd.Result()
    wd.check_tunnel(r)
    assert r.healthy is True


# --- App checks ------------------------------------------------------------

def test_app_unreachable_is_caught(monkeypatch):
    monkeypatch.setattr(wd, "HEALTH_URL", "http://127.0.0.1:1/health")
    r = wd.Result()
    wd.check_app(r)
    assert r.healthy is False
    assert any("unreachable" in p for p in r.problems)


# --- Alert de-duplication --------------------------------------------------

def test_state_roundtrip(tmp_path):
    p = tmp_path / "state.json"
    wd.save_state(p, {"healthy": False, "since": 1.0})
    assert wd.load_state(p)["healthy"] is False


def test_corrupt_state_does_not_crash(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert wd.load_state(p) == {}


def test_alert_without_recipient_is_a_no_op(monkeypatch, capsys):
    """Missing config must not raise inside a timer run."""
    monkeypatch.delenv("WATCHDOG_EMAIL_TO", raising=False)
    assert wd.send_alert("subject", "body") is False


def test_alert_failure_never_raises(monkeypatch):
    """Alerting is best-effort; a broken SMTP must not break the check."""
    monkeypatch.setenv("WATCHDOG_EMAIL_TO", "ops@example.test")
    from app.services import mailer
    monkeypatch.setattr(mailer, "is_configured", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("smtp exploded")
    monkeypatch.setattr(mailer, "send", boom)
    assert wd.send_alert("s", "b") is False


@pytest.mark.parametrize("seconds, expected", [
    (0, "0m"), (90, "1m"), (3600, "1h"), (17220, "4h 47m"),
])
def test_human_duration(seconds, expected):
    assert wd._human(seconds) == expected


# --- Units -----------------------------------------------------------------

def test_timer_and_service_units_exist():
    for name in ("litsieve-watchdog.service", "litsieve-watchdog.timer"):
        assert (REPO / "deploy" / name).exists(), f"missing {name}"


def test_service_tolerates_the_unhealthy_exit_code():
    """Exit 1 means 'site is down', not 'unit is broken'."""
    body = (REPO / "deploy" / "litsieve-watchdog.service").read_text()
    assert "SuccessExitStatus=0 1" in body


def test_timer_runs_after_boot_and_periodically():
    """The machine reboots unattended ~05:01, which is when this bites."""
    body = (REPO / "deploy" / "litsieve-watchdog.timer").read_text()
    assert "OnBootSec=" in body
    assert "OnUnitActiveSec=" in body
