"""Logging configuration: console + a rotating file on disk.

Before this, the app logged to stdout only. Self-hosted behind systemd that
means everything lands in the journal, mixed with every other unit, and is gone
after the journal rotates — so a report like "the site hung for a moment" had no
durable record to check against.

Two things are deliberate:

* **Rotation is not optional.** This runs on someone's desktop; an unbounded log
  is a slow disk-filling bug, and a full disk takes the site down. Defaults cap
  total usage at LOG_MAX_BYTES * (LOG_BACKUP_COUNT + 1) ≈ 30 MB.
* **uvicorn's loggers are attached explicitly.** uvicorn configures
  ``uvicorn.access`` / ``uvicorn.error`` with ``propagate=False``, so a handler
  on the root logger never sees the access log. Attaching directly is what puts
  request lines in the file alongside application logs.

Configure with LOG_FILE (empty disables the file), LOG_LEVEL, LOG_MAX_BYTES,
LOG_BACKUP_COUNT. Never fails the app: if the log path cannot be opened we warn
on the console and carry on, because losing logs must not take down the site.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

DEFAULT_LOG_FILE = "logs/litpilot.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024   # 5 MB per file
DEFAULT_BACKUP_COUNT = 5              # + 5 rotations ≈ 30 MB ceiling

_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"

# Loggers uvicorn owns; they do not propagate, so they need the handler directly.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")

_configured = False


def _int_env(name: str, default: int) -> int:
    """Read an int env var, falling back to the default on anything unusable."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def log_file_path() -> str:
    """Configured log file, or "" when file logging is switched off."""
    raw = os.getenv("LOG_FILE")
    return DEFAULT_LOG_FILE if raw is None else raw.strip()


def configure_logging(force: bool = False) -> None:
    """Install console + rotating-file handlers on the root and uvicorn loggers.

    Idempotent: repeated calls (uvicorn --reload re-imports the app) will not
    stack duplicate handlers.
    """
    global _configured
    if _configured and not force:
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    if not isinstance(level, int):
        level = logging.INFO

    formatter = logging.Formatter(_FORMAT)
    root = logging.getLogger()
    root.setLevel(level)

    # Replace our own handlers rather than adding to them, so --reload and
    # repeated imports cannot multiply output.
    for handler in [h for h in root.handlers if getattr(h, "_lra_owned", False)]:
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._lra_owned = True  # type: ignore[attr-defined]
    root.addHandler(console)

    file_handler = None
    path = log_file_path()
    if path:
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            file_handler = RotatingFileHandler(
                path,
                maxBytes=_int_env("LOG_MAX_BYTES", DEFAULT_MAX_BYTES),
                backupCount=_int_env("LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT),
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler._lra_owned = True  # type: ignore[attr-defined]
            root.addHandler(file_handler)
        except OSError as exc:
            # Read-only mount, bad path, permissions: keep serving, log to console.
            file_handler = None
            logging.getLogger(__name__).warning(
                "File logging disabled (%s): %s", path, exc,
            )

    # Mirror the file handler onto uvicorn's loggers -- this is what captures the
    # access log ("GET / 200") into the file.
    #
    # Only onto the ones that stop propagation, though: uvicorn.error propagates
    # into uvicorn, so attaching to both writes every startup/error line twice.
    # Testing `propagate` rather than hard-coding which is which keeps this
    # correct if uvicorn changes its config.
    for name in _UVICORN_LOGGERS:
        uv = logging.getLogger(name)
        for handler in [h for h in uv.handlers if getattr(h, "_lra_owned", False)]:
            uv.removeHandler(handler)
            handler.close()
        if file_handler is not None and not uv.propagate:
            uv.addHandler(file_handler)

    _configured = True
