#!/usr/bin/env python3
"""Notice when the public site is down, and say so.

Why this exists
---------------
On 2026-08-05 the site was unreachable for 4h47m and nothing reported it. The
Cloudflare tunnel token had been revoked the previous day, but cloudflared never
re-authenticates an *established* connection, so the failure stayed invisible
until the machine's scheduled ~05:01 reboot forced a fresh registration. By then
nobody was awake.

Every signal available at the time looked healthy:

  * systemd said the tunnel service was ``active`` — the process was running
    fine, it just could not register
  * the app answered ``/health`` 200 on loopback — the app was never the problem
  * ``curl`` against the public hostname returned 403 either way, because
    Cloudflare's managed challenge answers at the edge before the tunnel is
    involved

So this checks the two things that actually distinguish "up" from "down":
the app responds locally, and the tunnel currently holds registered
connections. Run it from a systemd timer (deploy/litsieve-watchdog.timer).

It emails on state *changes* rather than every failed poll, so a long outage is
one message and not one every five minutes. Alerts reuse the app's own SMTP
config, so there is nothing extra to set up beyond WATCHDOG_EMAIL_TO.

Exit codes: 0 healthy, 1 unhealthy, 2 could not run the checks.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_STATE = REPO / "logs" / "watchdog_state.json"

HEALTH_URL = os.getenv("WATCHDOG_HEALTH_URL", "http://127.0.0.1:7860/health")
TUNNEL_UNIT = os.getenv("WATCHDOG_TUNNEL_UNIT", "cloudflared-litpilot-token")
APP_UNIT = os.getenv("WATCHDOG_APP_UNIT", "litsieve-uvicorn")
TIMEOUT = int(os.getenv("WATCHDOG_TIMEOUT", "10") or 10)
# Re-send while still down, so a multi-day outage does not go quiet after one
# email. 0 disables the reminder.
REMIND_AFTER_HOURS = float(os.getenv("WATCHDOG_REMIND_HOURS", "12") or 12)


@dataclass
class Result:
    healthy: bool = True
    problems: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def fail(self, problem: str) -> None:
        self.healthy = False
        self.problems.append(problem)


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 127, str(exc)


def check_app(result: Result) -> None:
    """The app must actually answer, not merely have a live process.

    systemd only knows whether the process exists; a wedged worker still counts
    as ``active``. Hitting /health is what distinguishes the two.
    """
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=TIMEOUT) as resp:
            body = resp.read(500).decode("utf-8", "replace")
            if resp.status != 200:
                result.fail(f"app /health returned HTTP {resp.status}")
                return
            if '"healthy"' not in body:
                result.fail(f"app /health did not report healthy: {body[:120]}")
                return
            result.details.append(f"app: {body.strip()[:80]}")
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        result.fail(f"app unreachable at {HEALTH_URL}: {exc}")


def check_tunnel(result: Result) -> None:
    """The tunnel must hold registered connections, not just be running.

    This is the exact failure that went unnoticed: `is-active` said active while
    every registration attempt was rejected with "Invalid tunnel secret".
    """
    code, out = _run(["systemctl", "--user", "is-active", f"{TUNNEL_UNIT}.service"])
    state = out.strip() or "unknown"
    if state != "active":
        result.fail(f"tunnel service is {state}")
        return

    # Look at the recent journal: a healthy connector registers connections and
    # logs no auth errors. Window is generous so a quiet period is not a false
    # alarm, and we compare the *latest* of each rather than raw counts, because
    # errors from before a fix stay in the window.
    code, out = _run(
        ["journalctl", "--user", "-u", TUNNEL_UNIT, "--since", "-30min",
         "--no-pager", "-o", "short-unix"],
        timeout=20,
    )
    if code != 0:
        result.details.append(f"tunnel: could not read journal ({out.strip()[:80]})")
        return

    last_ok = _last_timestamp(out, r"Registered tunnel connection")
    last_err = _last_timestamp(out, r"Invalid tunnel secret|Unauthorized")

    if last_err is not None and (last_ok is None or last_err > last_ok):
        result.fail(
            "tunnel is rejected by Cloudflare (Invalid tunnel secret). "
            "The token was probably rotated or revoked — update "
            "secrets/cloudflared.env and restart the service."
        )
        return

    if last_ok is not None:
        result.details.append("tunnel: connections registered")


def _last_timestamp(journal: str, pattern: str) -> float | None:
    """Newest unix timestamp among journal lines matching pattern."""
    newest = None
    for line in journal.splitlines():
        if not re.search(pattern, line):
            continue
        head = line.split(" ", 1)[0]
        try:
            ts = float(head)
        except ValueError:
            continue
        if newest is None or ts > newest:
            newest = ts
    return newest


def load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        print(f"watchdog: could not write state to {path}: {exc}", file=sys.stderr)


def send_alert(subject: str, body: str) -> bool:
    """Email via the app's own mailer. Never raises: alerting is best-effort."""
    to = (os.getenv("WATCHDOG_EMAIL_TO") or "").strip()
    if not to:
        print("watchdog: WATCHDOG_EMAIL_TO not set; not emailing", file=sys.stderr)
        return False
    try:
        sys.path.insert(0, str(REPO))
        from app.services import mailer

        if not mailer.is_configured():
            print("watchdog: SMTP not configured; not emailing", file=sys.stderr)
            return False
        mailer.send(to, subject, body)
        return True
    except Exception as exc:  # noqa: BLE001 - never let alerting break the check
        print(f"watchdog: alert failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="where to remember the previous result")
    ap.add_argument("--quiet", action="store_true",
                    help="only print when something is wrong")
    ap.add_argument("--no-email", action="store_true",
                    help="check and report, but never send mail")
    args = ap.parse_args()

    result = Result()
    check_app(result)
    check_tunnel(result)

    state_path = Path(args.state)
    state = load_state(state_path)
    was_healthy = state.get("healthy", True)
    since = float(state.get("since") or 0)
    last_alert = float(state.get("last_alert") or 0)
    now = time.time()

    host = socket.gethostname()
    summary = "; ".join(result.problems) if result.problems else "all checks passed"

    changed = result.healthy != was_healthy
    stale = (
        not result.healthy
        and REMIND_AFTER_HOURS > 0
        and (now - last_alert) > REMIND_AFTER_HOURS * 3600
    )

    if not args.no_email and (changed or stale):
        if result.healthy:
            down_for = _human(now - since) if since else "an unknown period"
            ok = send_alert(
                f"[LitSieve] recovered on {host}",
                f"The site is reachable again.\n\nIt was down for {down_for}.\n\n"
                + "\n".join(result.details) + "\n",
            )
        else:
            ok = send_alert(
                f"[LitSieve] DOWN on {host}",
                "The public site looks down.\n\n"
                "Problems:\n  - " + "\n  - ".join(result.problems) + "\n\n"
                "Check:\n"
                f"  systemctl --user status {APP_UNIT}.service\n"
                f"  journalctl --user -u {TUNNEL_UNIT} -n 30 --no-pager\n"
                "  curl -sS http://127.0.0.1:7860/health\n\n"
                "Note: curl against the public hostname returns 403 even when\n"
                "healthy (Cloudflare managed challenge), so check locally.\n",
            )
        if ok:
            last_alert = now

    save_state(state_path, {
        "healthy": result.healthy,
        "since": now if changed else (since or now),
        "last_alert": last_alert,
        "checked_at": now,
        "summary": summary,
    })

    if not result.healthy:
        print(f"UNHEALTHY: {summary}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"OK: {summary}" + ("" if not result.details else
                                  " (" + "; ".join(result.details) + ")"))
    return 0


def _human(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, _ = divmod(rem, 60)
    if h and m:
        return f"{h}h {m}m"
    if h:
        return f"{h}h"
    return f"{m}m"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"watchdog: check failed to run: {exc}", file=sys.stderr)
        sys.exit(2)
