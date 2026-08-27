"""Named operator actions. Invoked by tools/operator/*.py with argv only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from app.operator import gitutil, paths
from app.operator.paths import PathJailError

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
MSG_RE = re.compile(r"^[^\x00-\x1f]{1,200}$")
OUTPUT_TAIL = 4000
FAST_TESTS = (
    "tests/test_ops.py",
    "tests/test_admin.py",
    "tests/test_guardrails.py",
)
LOCKFILES = ("requirements.txt", "pyproject.toml")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_out(payload: Dict[str, Any], code: int = 0) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return code


def _fail(detail: str, *, extra: Dict[str, Any] | None = None) -> int:
    body = {"ok": False, "detail": detail}
    if extra:
        body.update(extra)
    return _json_out(body, 1)


def cmd_list_files(_argv: List[str]) -> int:
    root = gitutil.ensure_staging()
    files = paths.walk_text_files(root)
    return _json_out({"ok": True, "files": files, "root_label": "staging"})


def cmd_read_file(argv: List[str]) -> int:
    if not argv:
        return _fail("path is required")
    root = gitutil.ensure_staging()
    try:
        full = paths.jail(root, argv[0])
    except PathJailError as exc:
        return _fail(str(exc))
    if not full.is_file():
        return _fail("File not found.")
    try:
        text = paths.read_text_capped(full)
    except PathJailError as exc:
        return _fail(str(exc))
    except OSError:
        return _fail("Could not read that file.")
    return _json_out({"ok": True, "path": paths.rel_from(root, full), "content": text})


def cmd_save_file(argv: List[str]) -> int:
    if not argv:
        return _fail("path is required")
    root = gitutil.ensure_staging()
    try:
        full = paths.jail(root, argv[0])
    except PathJailError as exc:
        return _fail(str(exc))
    if not paths.looks_text_name(argv[0]):
        return _fail("Only text files can be saved.")
    raw = sys.stdin.buffer.read()
    if paths.is_binary_bytes(raw):
        return _fail("Binary writes are not allowed.")
    if len(raw) > paths.MAX_FILE_BYTES:
        return _fail(f"File is larger than {paths.MAX_FILE_BYTES} bytes.")
    before = b""
    if full.is_file():
        try:
            before = full.read_bytes()
        except OSError:
            before = b""
    full.parent.mkdir(parents=True, exist_ok=True)
    tmp = full.with_name(full.name + ".ops-tmp")
    tmp.write_bytes(raw)
    tmp.replace(full)
    return _json_out({
        "ok": True,
        "path": paths.rel_from(root, full),
        "before_hash": _sha256(before) if before else "",
        "after_hash": _sha256(raw),
    })


def cmd_diff(_argv: List[str]) -> int:
    staging = gitutil.ensure_staging()
    live = paths.live_root()
    try:
        live_sha = gitutil.rev_parse(live) if gitutil.is_git_repo(live) else ""
    except gitutil.GitError:
        live_sha = ""
    if not live_sha:
        live_sha = "HEAD"
    unstaged = gitutil.git(staging, ["diff"], check=False)
    cached = gitutil.git(staging, ["diff", "--cached"], check=False)
    vs_live = gitutil.git(staging, ["diff", live_sha, "--"], check=False)
    status = gitutil.status_porcelain(staging)
    try:
        staging_sha = gitutil.rev_parse(staging)
    except gitutil.GitError:
        staging_sha = ""
    diff_text = (vs_live.stdout or "") + (unstaged.stdout or "") + (cached.stdout or "")
    return _json_out({
        "ok": True,
        "live_sha": live_sha,
        "staging_sha": staging_sha,
        "dirty": bool(status.strip()),
        "empty": not bool(diff_text.strip() or status.strip()),
        "diff": diff_text[-20000:],
        "status": status,
    })


def _run_fixed(cmd: List[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, check=False, shell=False,
    )


def cmd_validate(_argv: List[str]) -> int:
    staging = gitutil.ensure_staging()
    steps = []
    py = sys.executable
    compile_targets = [p for p in ("app", "tools") if (staging / p).is_dir()]
    if not compile_targets:
        compile_targets = ["."]
    try:
        compile_proc = _run_fixed(
            [py, "-m", "compileall", "-q", *compile_targets],
            cwd=staging, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _fail(f"syntax check failed: {exc}")
    steps.append({
        "name": "syntax",
        "ok": compile_proc.returncode == 0,
        "output": ((compile_proc.stdout or "") + (compile_proc.stderr or ""))[-OUTPUT_TAIL:],
    })
    ruff_ok = True
    if (staging / "pyproject.toml").is_file() or (staging / "ruff.toml").is_file():
        try:
            ruff_proc = _run_fixed([py, "-m", "ruff", "check", "app", "tools"], cwd=staging, timeout=120)
            ruff_ok = ruff_proc.returncode == 0
            steps.append({
                "name": "ruff",
                "ok": ruff_ok,
                "output": ((ruff_proc.stdout or "") + (ruff_proc.stderr or ""))[-OUTPUT_TAIL:],
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            ruff_ok = False
            steps.append({"name": "ruff", "ok": False, "output": str(exc)})
    test_ok = True
    tests = [t for t in FAST_TESTS if (staging / t).is_file()]
    if tests:
        try:
            pytest_proc = _run_fixed(
                [py, "-m", "pytest", "-q", "--tb=line", *tests],
                cwd=staging, timeout=180,
            )
            test_ok = pytest_proc.returncode == 0
            steps.append({
                "name": "pytest",
                "ok": test_ok,
                "output": ((pytest_proc.stdout or "") + (pytest_proc.stderr or ""))[-OUTPUT_TAIL:],
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            test_ok = False
            steps.append({"name": "pytest", "ok": False, "output": str(exc)})
    ok = compile_proc.returncode == 0 and ruff_ok and test_ok
    sha = ""
    try:
        sha = gitutil.rev_parse(staging)
    except gitutil.GitError:
        pass
    return _json_out({"ok": ok, "steps": steps, "sha": sha}, 0 if ok else 1)


def cmd_commit(argv: List[str]) -> int:
    if not argv:
        return _fail("commit message is required")
    message = argv[0].strip()
    if not MSG_RE.fullmatch(message):
        return _fail("Commit message must be 1–200 characters with no control chars.")
    staging = gitutil.ensure_staging()
    if not gitutil.status_porcelain(staging).strip():
        return _fail("Nothing to commit.")
    name = (os.getenv("LITSIEVE_OPS_AUTHOR") or "operator").strip() or "operator"
    try:
        sha = gitutil.commit_all(staging, f"remote-edit: {message}", name=name)
    except gitutil.GitError as exc:
        return _fail(str(exc))
    return _json_out({"ok": True, "sha": sha, "message": f"remote-edit: {message}"})


def _health_ok() -> bool:
    mode = (os.getenv("LITSIEVE_HEALTH_MODE") or "http").strip().lower()
    if mode == "file":
        path = Path(os.getenv("LITSIEVE_HEALTH_FILE") or "")
        if not path.is_file():
            return False
        return path.read_text(encoding="utf-8", errors="replace").strip().lower() == "ok"
    url = (os.getenv("LITSIEVE_HEALTH_URL") or "http://127.0.0.1:7860/health").strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return False
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = resp.read(400).decode("utf-8", "replace")
            return resp.status == 200 and "healthy" in body.lower()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _restart_service() -> None:
    if (os.getenv("LITSIEVE_SKIP_RESTART") or "").strip() in ("1", "true", "yes"):
        return
    unit = "litsieve-uvicorn.service"
    subprocess.run(
        ["systemctl", "--user", "restart", unit],
        capture_output=True, text=True, timeout=60, check=False, shell=False,
    )


def _poll_health(*, attempts: int = 20, delay: float = 0.4) -> bool:
    for _ in range(attempts):
        if _health_ok():
            return True
        time.sleep(delay)
    return False


def _sync_deps(live: Path, prev: str, new: str) -> None:
    if not prev or not new:
        return
    try:
        changed = set(gitutil.files_changed(live, prev, new))
    except gitutil.GitError:
        return
    if not any(name in changed for name in LOCKFILES):
        return
    venv_py = live / "venv" / "bin" / "python"
    py = str(venv_py) if venv_py.is_file() else sys.executable
    req = live / "requirements.txt"
    if req.is_file():
        subprocess.run(
            [py, "-m", "pip", "install", "-r", str(req)],
            capture_output=True, text=True, timeout=300, check=False, shell=False,
        )


def _do_deploy(sha: str) -> Dict[str, Any]:
    live = paths.live_root()
    if not gitutil.is_git_repo(live):
        return {"ok": False, "detail": "Live directory is not a git checkout."}
    if not SHA_RE.fullmatch(sha):
        return {"ok": False, "detail": "SHA is not valid."}
    # Deploy resets the live checkout hard. Uncommitted work on TRACKED files
    # would be destroyed with no way back (rollback restores a commit, not a
    # working tree), so refuse and name the files instead.
    try:
        dirty = gitutil.tracked_dirty(live)
    except gitutil.GitError as exc:
        return {"ok": False, "detail": str(exc)}
    if dirty:
        preview = ", ".join(entry[3:] or entry for entry in dirty[:5])
        if len(dirty) > 5:
            preview += f", and {len(dirty) - 5} more"
        return {
            "ok": False,
            "detail": (
                f"Live checkout has {len(dirty)} uncommitted change(s): {preview}. "
                "Commit or stash them first — deploy would discard them."
            ),
            "dirty_live": dirty,
        }
    try:
        prev = gitutil.rev_parse(live)
    except gitutil.GitError as exc:
        return {"ok": False, "detail": str(exc)}
    try:
        gitutil.reset_hard(live, sha)
    except gitutil.GitError as exc:
        return {"ok": False, "detail": str(exc), "previous_sha": prev}
    _sync_deps(live, prev, sha)
    _restart_service()
    if _poll_health():
        return {"ok": True, "sha": sha, "previous_sha": prev, "rolled_back": False}
    try:
        gitutil.reset_hard(live, prev)
    except gitutil.GitError as exc:
        return {
            "ok": False,
            "detail": f"Health check failed and rollback failed: {exc}",
            "previous_sha": prev,
            "sha": sha,
            "rolled_back": False,
        }
    _restart_service()
    _poll_health()
    return {
        "ok": False,
        "detail": "Health check failed; previous commit was restored.",
        "sha": sha,
        "previous_sha": prev,
        "rolled_back": True,
    }


def cmd_deploy(argv: List[str]) -> int:
    if not argv:
        return _fail("sha is required")
    sha = argv[0].strip().lower()
    staging = gitutil.ensure_staging()
    live = paths.live_root()
    try:
        live_sha = gitutil.rev_parse(live)
        staging_sha = gitutil.rev_parse(staging)
    except gitutil.GitError as exc:
        return _fail(str(exc))
    if sha != staging_sha and not staging_sha.startswith(sha) and not sha.startswith(staging_sha[:7]):
        # Allow short SHA if it matches staging HEAD.
        if not staging_sha.startswith(sha):
            return _fail("Deploy SHA must be the staging HEAD you just reviewed.")
    sha = staging_sha
    vs = gitutil.git(staging, ["diff", live_sha, "--"], check=False)
    dirty = gitutil.status_porcelain(staging).strip()
    if dirty:
        return _fail("Commit staging changes before deploying.")
    if not (vs.stdout or "").strip() and live_sha == sha:
        return _fail("Nothing to deploy — staging matches the live commit.")
    result = _do_deploy(sha)
    if not result.get("ok"):
        return _json_out(result, 1)
    return _json_out(result)


def cmd_rollback(argv: List[str]) -> int:
    live = paths.live_root()
    if argv and SHA_RE.fullmatch(argv[0].strip().lower()):
        target = argv[0].strip().lower()
        # Expand short sha via git
        try:
            target = gitutil.rev_parse(live, target)
        except gitutil.GitError:
            try:
                target = gitutil.rev_parse(paths.repo_root(), argv[0].strip().lower())
            except gitutil.GitError as exc:
                return _fail(str(exc))
    else:
        try:
            current = gitutil.rev_parse(live)
        except gitutil.GitError as exc:
            return _fail(str(exc))
        log = gitutil.git(live, ["log", "-2", "--format=%H"], check=False)
        shas = [line.strip() for line in (log.stdout or "").splitlines() if line.strip()]
        if len(shas) < 2:
            return _fail("No previous commit to roll back to.")
        target = shas[1] if shas[0].startswith(current[:7]) else shas[0]
    result = _do_deploy(target)
    result["action"] = "rollback"
    return _json_out(result, 0 if result.get("ok") else 1)


def cmd_revert_last(_argv: List[str]) -> int:
    return cmd_rollback([])


def grok_bin() -> Path | None:
    """Fixed candidate paths only. HTTP never supplies the binary."""
    home = Path.home()
    names = []
    env = (os.getenv("GROK_BIN") or "").strip()
    if env:
        names.append(Path(env))
    names.extend([
        home / ".local" / "bin" / "grok",
        home / ".grok" / "bin" / "grok",
        Path("/usr/local/bin/grok"),
        Path("/usr/bin/grok"),
    ])
    for cand in names:
        try:
            resolved = cand.expanduser().resolve()
        except OSError:
            continue
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            continue
        if not resolved.name.startswith("grok"):
            continue
        return resolved
    return None


def _grok_env() -> dict:
    env = os.environ.copy()
    home = str(Path.home())
    env["HOME"] = home
    prefix = f"{home}/.local/bin:{home}/.grok/bin"
    env["PATH"] = prefix + ":" + (env.get("PATH") or "")
    return env


_SESSION_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _grok_base_args(binary: Path, staging: Path) -> list:
    return [
        str(binary),
        "--cwd", str(staging),
        "--output-format", "plain",
        "--max-turns", "8",
        "--always-approve",
        "--disable-web-search",
        "--no-subagents",
        "--disallowed-tools", "run_terminal_cmd",
    ]


def cmd_grok_status(_argv: List[str]) -> int:
    binary = grok_bin()
    if not binary:
        return _json_out({
            "ok": True,
            "available": False,
            "detail": "Grok Build CLI not found. Install with: curl -fsSL https://x.ai/cli/install.sh | bash",
            "install": "curl -fsSL https://x.ai/cli/install.sh | bash",
        })
    try:
        proc = subprocess.run(
            [str(binary), "--version"],
            capture_output=True, text=True, timeout=8, check=False, shell=False,
            env=_grok_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _json_out({"ok": True, "available": False, "detail": str(exc)})
    version = ((proc.stdout or proc.stderr) or "").strip().splitlines()[0] if proc.returncode == 0 else ""
    staging = ""
    try:
        staging = str(gitutil.ensure_staging())
    except Exception:
        staging = str(paths.staging_root())
    sid = (os.getenv("LITSIEVE_GROK_SESSION") or "").strip()
    tui = f"grok --cwd {staging}" if staging else "grok"
    if _SESSION_RE.fullmatch(sid):
        tui = f"grok --cwd {staging} --resume {sid}"
    return _json_out({
        "ok": True,
        "available": proc.returncode == 0,
        "connected": proc.returncode == 0,
        "version": version,
        "binary": str(binary),
        "tui_command": tui,
        "staging_cwd": staging,
        "session": sid if _SESSION_RE.fullmatch(sid) else "",
    })


def cmd_ask_grok(argv: List[str]) -> int:
    prompt = (argv[0] if argv else "").strip()
    rel = (argv[1] if len(argv) > 1 else "").strip()
    if len(prompt) < 3 or len(prompt) > 2000:
        return _fail("Prompt must be 3–2000 characters.")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in prompt):
        return _fail("Prompt contains control characters.")
    binary = grok_bin()
    if not binary:
        return _fail("Grok Build CLI is not installed on this host.")
    staging = gitutil.ensure_staging()
    if rel:
        try:
            paths.jail(staging, rel)
        except PathJailError as exc:
            return _fail(str(exc))
    focus = f" Focus on staging file {rel}." if rel else ""
    full = (
        "You are helping the LitSieve operator on a git staging worktree. "
        "Only read or edit files in this directory. Do not run shell commands. "
        "Do not open .env, secrets, databases, or paths outside this tree."
        f"{focus}\n\n{prompt}"
    )
    sid = (os.getenv("LITSIEVE_GROK_SESSION") or "").strip()
    base = _grok_base_args(binary, staging)

    def _run(extra: list) -> subprocess.CompletedProcess:
        cmd = [base[0], "-p", full, *base[1:], *extra]
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False,
            shell=False, env=_grok_env(),
        )

    try:
        proc = None
        if _SESSION_RE.fullmatch(sid):
            proc = _run(["--resume", sid])
            err = ((proc.stderr or "") + (proc.stdout or "")).lower()
            if proc.returncode != 0 and ("not found" in err or "no session" in err or "unknown session" in err):
                proc = _run(["--session-id", sid])
        else:
            proc = _run([])
    except subprocess.TimeoutExpired:
        return _fail("Grok timed out.")
    except OSError as exc:
        return _fail(f"Could not start Grok: {exc}")
    text = ((proc.stdout or "") + (proc.stderr or ""))[-OUTPUT_TAIL:]
    if proc.returncode != 0:
        return _fail(text.strip() or "Grok failed.", extra={"output": text})
    return _json_out({"ok": True, "text": text.strip(), "path": rel, "session": sid})


ACTIONS = {
    "list_files": cmd_list_files,
    "read_file": cmd_read_file,
    "save_file": cmd_save_file,
    "diff": cmd_diff,
    "validate": cmd_validate,
    "commit": cmd_commit,
    "deploy": cmd_deploy,
    "rollback": cmd_rollback,
    "revert_last": cmd_revert_last,
    "grok_status": cmd_grok_status,
    "ask_grok": cmd_ask_grok,
}
