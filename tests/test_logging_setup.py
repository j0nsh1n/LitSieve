"""Durable logs on disk.

The app logged to stdout only, so self-hosted behind systemd everything landed
in the journal and aged out. A user report like "it hung for a moment" had no
record to check. These tests pin the parts that are easy to regress: rotation
(an unbounded log fills a desktop's disk and takes the site down), uvicorn's
non-propagating access logger, and never crashing when the path is unwritable.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from app import logging_setup


@pytest.fixture(autouse=True)
def _restore_logging():
    """Logging is global; put it back so we cannot poison other test modules."""
    root = logging.getLogger()
    saved_root = list(root.handlers)
    saved_level = root.level
    saved_uv = {n: (list(logging.getLogger(n).handlers),
                    logging.getLogger(n).propagate)
                for n in logging_setup._UVICORN_LOGGERS}
    yield
    for h in [h for h in root.handlers if h not in saved_root]:
        root.removeHandler(h)
        h.close()
    root.handlers[:] = saved_root
    root.setLevel(saved_level)
    for name, (handlers, propagate) in saved_uv.items():
        logging.getLogger(name).handlers[:] = handlers
        logging.getLogger(name).propagate = propagate
    logging_setup._configured = False


def test_writes_to_the_configured_file(tmp_path, monkeypatch):
    target = tmp_path / "logs" / "litpilot.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    logging_setup.configure_logging(force=True)

    logging.getLogger("app.test").warning("hello-from-test")

    assert target.exists(), "log file was not created"
    assert "hello-from-test" in target.read_text()


def test_creates_missing_parent_directory(tmp_path, monkeypatch):
    target = tmp_path / "deep" / "nested" / "app.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    logging_setup.configure_logging(force=True)
    logging.getLogger("app.test").error("made-the-dirs")
    assert target.exists()


def test_rotation_is_bounded(tmp_path, monkeypatch):
    """An unbounded log is a disk-filling bug on a self-hosted box."""
    target = tmp_path / "rot.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    monkeypatch.setenv("LOG_MAX_BYTES", "2000")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "2")
    logging_setup.configure_logging(force=True)

    log = logging.getLogger("app.test")
    for i in range(400):
        log.info("filler line %s %s", i, "x" * 80)

    produced = sorted(p.name for p in tmp_path.glob("rot.log*"))
    # base + at most backupCount rotations, and nothing unbounded
    assert len(produced) <= 3, produced
    total = sum(p.stat().st_size for p in tmp_path.glob("rot.log*"))
    assert total < 20_000, f"rotation not bounding size: {total} bytes"


def test_empty_log_file_disables_file_logging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOG_FILE", "")
    logging_setup.configure_logging(force=True)
    logging.getLogger("app.test").info("console only")
    assert not (tmp_path / "logs").exists(), "file logging should be off"


def test_unwritable_path_does_not_crash(tmp_path, monkeypatch):
    """Losing logs must never take the site down."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file")
    monkeypatch.setenv("LOG_FILE", str(blocker / "sub" / "app.log"))
    logging_setup.configure_logging(force=True)   # must not raise
    logging.getLogger("app.test").info("still alive")

    # Console logging must survive so the operator is not left blind.
    # Check only handlers *we* installed -- pytest puts its own _FileHandler on
    # the root logger, which would otherwise look like a false positive.
    ours = [h for h in logging.getLogger().handlers
            if getattr(h, "_lra_owned", False)]
    assert ours, "no handlers left after a failed file handler"
    assert not any(isinstance(h, logging.FileHandler) for h in ours), (
        "a broken file handler must not be installed"
    )
    assert any(isinstance(h, logging.StreamHandler) for h in ours), (
        "console logging must still work when the file cannot be opened"
    )


def test_uvicorn_access_log_reaches_the_file(tmp_path, monkeypatch):
    """uvicorn's loggers set propagate=False, so they need the handler directly.

    Without this the access log ("GET / 200") never lands in the file, which is
    exactly the record we want when someone reports a slow page.
    """
    target = tmp_path / "access.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    # uvicorn configures its loggers before importing the app, so propagate is
    # already False by the time configure_logging() runs.
    uv = logging.getLogger("uvicorn.access")
    uv.propagate = False
    logging_setup.configure_logging(force=True)

    uv.warning('GET /health 200')

    assert "GET /health 200" in target.read_text()


def test_repeat_configuration_does_not_duplicate_handlers(tmp_path, monkeypatch):
    """uvicorn --reload re-imports the app; handlers must not stack."""
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "dup.log"))
    logging_setup.configure_logging(force=True)
    first = len(logging.getLogger().handlers)
    logging_setup.configure_logging(force=True)
    logging_setup.configure_logging(force=True)
    assert len(logging.getLogger().handlers) == first


def test_level_is_configurable(tmp_path, monkeypatch):
    target = tmp_path / "lvl.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    logging_setup.configure_logging(force=True)

    log = logging.getLogger("app.test")
    log.info("should-not-appear")
    log.error("should-appear")

    body = target.read_text()
    assert "should-appear" in body
    assert "should-not-appear" not in body


def test_bad_numeric_env_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_FILE", str(tmp_path / "bad.log"))
    monkeypatch.setenv("LOG_MAX_BYTES", "not-a-number")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "-5")
    logging_setup.configure_logging(force=True)     # must not raise
    assert logging_setup._int_env("LOG_MAX_BYTES", 123) == 123
    assert logging_setup._int_env("LOG_BACKUP_COUNT", 7) == 7


def test_app_code_no_longer_prints():
    """print() in a server is invisible to operators and unfilterable.

    Guardrail: keeps fetcher errors going to the logger (and now the log file)
    instead of stdout.
    """
    import re
    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.match(r"^\s*print\(", line):
                offenders.append(f"{path.relative_to(app_dir.parent)}:{i}")
    assert not offenders, "print() calls in app/: " + ", ".join(offenders)


def test_fetchers_have_loggers():
    """Every fetcher that reports anything must do it through a logger."""
    fetchers = (pathlib.Path(__file__).resolve().parent.parent / "app" / "fetchers")
    missing = []
    for path in fetchers.glob("*.py"):
        src = path.read_text()
        if "logger." in src and "getLogger" not in src:
            missing.append(path.name)
    assert not missing, f"fetchers using logger without getLogger: {missing}"


def test_default_log_path_is_gitignored():
    """The default log must never be committable."""
    root = pathlib.Path(__file__).resolve().parent.parent
    ignored = (root / ".gitignore").read_text()
    assert "logs/" in ignored or "*.log" in ignored
    assert logging_setup.DEFAULT_LOG_FILE.startswith("logs/")


def test_env_example_documents_logging():
    root = pathlib.Path(__file__).resolve().parent.parent
    body = (root / ".env.example").read_text()
    for key in ("LOG_FILE", "LOG_LEVEL", "LOG_MAX_BYTES", "LOG_BACKUP_COUNT"):
        assert key in body, f"{key} missing from .env.example"


def test_env_example_documents_model_vars():
    """These shipped earlier without ever being written down."""
    root = pathlib.Path(__file__).resolve().parent.parent
    body = (root / ".env.example").read_text()
    for key in ("MAX_LOADED_MODELS", "EXTRA_EMBEDDING_MODELS"):
        assert key in body, f"{key} missing from .env.example"


def test_uvicorn_error_lines_are_not_duplicated(tmp_path, monkeypatch):
    """uvicorn.error propagates into uvicorn; handling both doubled every line.

    Caught by reading a real log file, not by a unit test -- keep it pinned.
    """
    target = tmp_path / "dupe.log"
    monkeypatch.setenv("LOG_FILE", str(target))
    # Reproduce uvicorn's actual layout: error propagates, uvicorn terminates.
    logging.getLogger("uvicorn").propagate = False
    err = logging.getLogger("uvicorn.error")
    err.propagate = True
    logging_setup.configure_logging(force=True)

    err.warning("startup-marker")

    body = target.read_text()
    assert body.count("startup-marker") == 1, (
        f"expected exactly one line, got {body.count('startup-marker')}:\n{body}"
    )
