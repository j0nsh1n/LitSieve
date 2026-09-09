"""Deploy progress on disk, so an interrupted deploy can still be recovered.

Audit finding A04. The deploy used to keep `previous_sha` in a local variable
and let the web process write the audit row after `run_action` returned. Both
die with the process — and the restart the deploy itself triggers is what kills
it, because the helper shares the web service's control group.

Everything a recovery needs is therefore written here *before* the step that can
kill us, and the deploy process writes its own outcome rather than relying on a
caller that may never resume.

The file is small, local, and disposable: it records one in-flight or most
recent deploy, never a history. `operator_deploys` in users.db remains the
durable history.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Phases are ordered. Anything other than a terminal phase means a deploy was
# interrupted, which is the case an operator needs to see.
PHASE_STARTED = "started"
PHASE_RESET = "reset"
PHASE_DEPS = "deps"
PHASE_RESTARTING = "restarting"
PHASE_HEALTH = "health"
PHASE_ROLLING_BACK = "rolling_back"
PHASE_DONE = "done"

TERMINAL_PHASES = (PHASE_DONE,)


def state_path() -> Path:
    """Where the in-flight deploy record lives.

    Overridable so tests never touch the operator's real state file.
    """
    raw = (os.getenv("LITSIEVE_DEPLOY_STATE") or "").strip()
    if raw:
        return Path(raw).resolve()
    return (Path.home() / ".local" / "share" / "litsieve" / "deploy-state.json").resolve()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(**fields: Any) -> Dict[str, Any]:
    """Merge `fields` into the record and flush atomically.

    Atomic because the restart can land between any two syscalls: a half-written
    JSON file would lose the previous SHA, which is the one thing recovery
    cannot reconstruct without reading the reflog.
    """
    record = read() or {}
    record.update({k: v for k, v in fields.items() if v is not None})
    record["updated_at"] = _now()
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".deploy-state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave a stray temp file behind; the deploy continues either way.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return record


def read() -> Optional[Dict[str, Any]]:
    """The current record, or None when absent or unreadable.

    A corrupt file is treated as absent rather than raising: a deploy must not
    fail because its own bookkeeping is damaged.
    """
    try:
        with open(state_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear() -> None:
    try:
        state_path().unlink()
    except OSError:
        pass


def begin(*, sha: str, previous_sha: str, actor_username: str = "") -> Dict[str, Any]:
    """Open a record before the live checkout is touched."""
    clear()
    return write(
        sha=sha,
        previous_sha=previous_sha,
        actor_username=actor_username,
        phase=PHASE_STARTED,
        result="",
        detail="",
        started_at=_now(),
    )


def finish(*, result: str, detail: str = "") -> Dict[str, Any]:
    return write(phase=PHASE_DONE, result=result, detail=detail)


def interrupted() -> Optional[Dict[str, Any]]:
    """A record left in a non-terminal phase, meaning nobody finished the job.

    The operator UI reads this to distinguish "no deploy running" from "a deploy
    died holding the live checkout at an unknown revision".
    """
    record = read()
    if not record:
        return None
    if record.get("phase") in TERMINAL_PHASES:
        return None
    return record
