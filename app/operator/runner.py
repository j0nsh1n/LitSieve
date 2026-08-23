"""Invoke a named operator action via a fixed script path. No shell=True."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.operator.paths import code_root

ACTION_SCRIPTS = {
    "list_files": "tools/operator/list_files.py",
    "read_file": "tools/operator/read_file.py",
    "save_file": "tools/operator/save_file.py",
    "diff": "tools/operator/diff.py",
    "validate": "tools/operator/validate.py",
    "commit": "tools/operator/commit.py",
    "deploy": "tools/operator/deploy.py",
    "rollback": "tools/operator/rollback.py",
    "revert_last": "tools/operator/revert_last.py",
    "grok_status": "tools/operator/grok_status.py",
    "ask_grok": "tools/operator/ask_grok.py",
}

_SECRET_RE = re.compile(
    r"(?i)(secret_key|password|passwd|token|authorization|api[_-]?key)\s*[=:]\s*\S+"
)
TIMEOUTS = {
    "list_files": 30,
    "read_file": 15,
    "save_file": 15,
    "diff": 30,
    "validate": 240,
    "commit": 30,
    "deploy": 180,
    "rollback": 180,
    "revert_last": 180,
    "grok_status": 10,
    "ask_grok": 180,
}


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1=[redacted]", text or "")


def script_path(action: str) -> Path:
    if action not in ACTION_SCRIPTS:
        raise ValueError("Unknown action.")
    root = code_root()
    path = (root / ACTION_SCRIPTS[action]).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise ValueError("Action script is outside the repo.")
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def run_action(
    action: str,
    argv: Optional[List[str]] = None,
    *,
    stdin: Optional[bytes] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    path = script_path(action)
    cmd = [sys.executable, str(path), *(argv or [])]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(code_root())
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            timeout=TIMEOUTS.get(action, 60),
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"{action} timed out.", "output": ""}
    except OSError as exc:
        return {"ok": False, "detail": f"{action} could not start: {exc}", "output": ""}
    stdout = redact(proc.stdout.decode("utf-8", "replace") if isinstance(proc.stdout, bytes) else (proc.stdout or ""))
    stderr = redact(proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else (proc.stderr or ""))
    payload: Dict[str, Any]
    try:
        payload = json.loads(stdout.strip().splitlines()[-1] if stdout.strip() else "{}")
        if not isinstance(payload, dict):
            payload = {"ok": False, "detail": "Action returned invalid output."}
    except (json.JSONDecodeError, IndexError):
        payload = {
            "ok": proc.returncode == 0,
            "detail": "Action returned no JSON.",
            "output": (stdout + stderr)[-4000:],
        }
    if stderr and "output" not in payload:
        payload["output"] = (payload.get("output") or "") + stderr[-2000:]
    payload["ok"] = bool(payload.get("ok")) and proc.returncode == 0
    if not payload["ok"] and not payload.get("detail"):
        payload["detail"] = f"{action} failed."
    return payload
