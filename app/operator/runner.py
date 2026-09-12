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


_DIAGNOSTIC_KEYS = ("detail", "output", "error", "message")


def decode_action_payload(
    stdout: str,
    stderr: str,
    returncode: int,
    action: str,
) -> Dict[str, Any]:
    """Parse action JSON first, then redact diagnostic fields only.

    Source `content` must stay intact so the editor does not save redacted code.
    Parse failure is always a failed action, even if the process exited 0.
    """
    raw_out = stdout or ""
    raw_err = stderr or ""
    try:
        line = raw_out.strip().splitlines()[-1] if raw_out.strip() else "{}"
        payload = json.loads(line)
        if not isinstance(payload, dict):
            payload = {"ok": False, "detail": "Action returned invalid output."}
    except (json.JSONDecodeError, IndexError):
        return {
            "ok": False,
            "detail": "Action returned no JSON.",
            "output": redact((raw_out + raw_err)[-4000:]),
        }
    payload["ok"] = bool(payload.get("ok")) and returncode == 0
    if raw_err and "output" not in payload:
        payload["output"] = raw_err[-2000:]
    for key in _DIAGNOSTIC_KEYS:
        val = payload.get(key)
        if isinstance(val, str):
            payload[key] = redact(val)
    if not payload["ok"] and not payload.get("detail"):
        payload["detail"] = f"{action} failed."
    return payload


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
    stdout = proc.stdout.decode("utf-8", "replace") if isinstance(proc.stdout, bytes) else (proc.stdout or "")
    stderr = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else (proc.stderr or "")
    return decode_action_payload(stdout, stderr, proc.returncode, action)
