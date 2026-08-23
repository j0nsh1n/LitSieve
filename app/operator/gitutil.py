"""Git helpers for the operator pipeline. Never uses shell=True."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List, Sequence

from app.operator.paths import repo_root, staging_root


class GitError(RuntimeError):
    pass


def git(cwd: Path, args: Sequence[str], *, timeout: int = 60, check: bool = True) -> subprocess.CompletedProcess:
    cmd = ["git", "-C", str(cwd), *list(args)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git failed: {exc}") from exc
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "git error").strip()
        raise GitError(err[:800])
    return proc


def rev_parse(cwd: Path, rev: str = "HEAD") -> str:
    proc = git(cwd, ["rev-parse", rev])
    return (proc.stdout or "").strip()


def is_git_repo(cwd: Path) -> bool:
    if not cwd.is_dir():
        return False
    proc = git(cwd, ["rev-parse", "--is-inside-work-tree"], check=False)
    return proc.returncode == 0 and "true" in (proc.stdout or "")


def ensure_staging() -> Path:
    """Create a linked worktree for edits. Never writes into the live tree."""
    repo = repo_root()
    staging = staging_root()
    if staging.exists() and is_git_repo(staging):
        return staging
    if not is_git_repo(repo):
        raise GitError("This host is not a git checkout; Ops cannot stage edits.")
    staging.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists() and not any(staging.iterdir()):
        staging.rmdir()
    git(repo, ["worktree", "add", "-B", "operator-staging", str(staging), "HEAD"], timeout=120)
    return staging


def status_porcelain(cwd: Path) -> str:
    proc = git(cwd, ["status", "--porcelain"])
    return proc.stdout or ""


def tracked_dirty(cwd: Path) -> List[str]:
    """Modified/staged/deleted TRACKED files. Untracked are ignored on purpose:
    `git reset --hard` leaves them alone, so they must not block a deploy."""
    proc = git(cwd, ["status", "--porcelain", "--untracked-files=no"])
    return [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]


def diff_vs(cwd: Path, ref: str) -> str:
    proc = git(cwd, ["diff", ref, "--"], check=False)
    staged = git(cwd, ["diff", "--cached", ref, "--"], check=False)
    parts = [(proc.stdout or ""), (staged.stdout or "")]
    return "".join(parts)


def commit_all(cwd: Path, message: str, *, name: str) -> str:
    git(cwd, ["add", "-A"])
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = name
    env["GIT_AUTHOR_EMAIL"] = "ops@localhost"
    env["GIT_COMMITTER_NAME"] = name
    env["GIT_COMMITTER_EMAIL"] = "ops@localhost"
    cmd = ["git", "-C", str(cwd), "commit", "-m", message]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=60, check=False, shell=False, env=env,
    )
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "commit failed").strip()[:800])
    return rev_parse(cwd)


def reset_hard(cwd: Path, sha: str) -> None:
    git(cwd, ["reset", "--hard", sha], timeout=120)


def files_changed(cwd: Path, a: str, b: str) -> List[str]:
    proc = git(cwd, ["diff", "--name-only", a, b])
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
