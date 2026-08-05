"""The dev server must not share data with the live site.

run_dev.sh runs from the repo, which is also the service's WorkingDirectory.
Without explicit isolation it opens the *production* accounts DB and paper
libraries: a test fetch writes into a real student's library, a stray click can
change a real password, and two processes sharing one rotating log file lose
lines when it rolls over.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.storage.user_db import DEFAULT_USERS_DB, UserDatabase, users_db_path

RUN_DEV = pathlib.Path(__file__).resolve().parent.parent / "run_dev.sh"


# --- USERS_DB env ----------------------------------------------------------

def test_defaults_to_users_db(monkeypatch):
    monkeypatch.delenv("USERS_DB", raising=False)
    assert users_db_path() == DEFAULT_USERS_DB


def test_env_overrides_path(monkeypatch):
    monkeypatch.setenv("USERS_DB", "dev_users.db")
    assert users_db_path() == "dev_users.db"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_env_falls_back(monkeypatch, blank):
    """An empty var must not mean 'open a file called empty-string'."""
    monkeypatch.setenv("USERS_DB", blank)
    assert users_db_path() == DEFAULT_USERS_DB


def test_database_actually_opens_the_env_path(tmp_path, monkeypatch):
    target = tmp_path / "isolated_users.db"
    monkeypatch.setenv("USERS_DB", str(target))
    db = UserDatabase()
    try:
        db.create_user("devuser", "$2b$12$" + "x" * 53)
        assert target.exists(), "USERS_DB path was not used"
        assert db.db_path == str(target)
    finally:
        db.conn.close()

    # And the production file is untouched by that write.
    assert not (tmp_path / DEFAULT_USERS_DB).exists()


def test_explicit_argument_still_wins(tmp_path, monkeypatch):
    """Tests pass db_path directly; env must not override an explicit choice."""
    monkeypatch.setenv("USERS_DB", str(tmp_path / "from_env.db"))
    explicit = tmp_path / "explicit.db"
    db = UserDatabase(db_path=str(explicit))
    try:
        assert db.db_path == str(explicit)
        assert explicit.exists()
    finally:
        db.conn.close()


# --- run_dev.sh defaults ---------------------------------------------------

def test_run_dev_isolates_all_three_stores():
    """Isolation must be the default, not something you remember to type."""
    src = RUN_DEV.read_text()
    for var, expected in (("USERS_DB", "dev_users.db"),
                          ("USER_DATA_DIR", "dev_data"),
                          ("LOG_FILE", "logs/dev.log")):
        pattern = rf'export {var}="\$\{{{var}:-{re.escape(expected)}\}}"'
        assert re.search(pattern, src), f"run_dev.sh does not default {var}"


def test_run_dev_allows_override():
    """`${VAR:-default}` keeps an explicit export working."""
    src = RUN_DEV.read_text()
    assert "${USERS_DB:-" in src, "override form lost; env would be ignored"


def test_dev_data_paths_are_gitignored():
    root = pathlib.Path(__file__).resolve().parent.parent
    ignored = (root / ".gitignore").read_text()
    for entry in ("dev_users.db", "dev_data/"):
        assert entry in ignored, f"{entry} not gitignored"


def test_run_dev_warns_if_pointed_at_live_data():
    """Overriding back to production should be loud, not silent."""
    src = RUN_DEV.read_text()
    assert "WARNING" in src and "users.db" in src


# --- Driver-agnostic integrity errors --------------------------------------

def test_duplicate_username_raises_valueerror_not_integrityerror(tmp_path, monkeypatch):
    """Must stay a clean 'already taken', including under SQLCipher.

    create_user caught sqlite3.IntegrityError by name, which stops matching when
    DB_ENCRYPTION_KEY selects the sqlcipher3 driver — a taken username would
    have become a 500 only on encrypted deployments.
    """
    monkeypatch.setenv("USERS_DB", str(tmp_path / "dupes.db"))
    db = UserDatabase()
    try:
        db.create_user("taken", "$2b$12$" + "x" * 53)
        with pytest.raises(ValueError, match="already taken"):
            db.create_user("taken", "$2b$12$" + "y" * 53)
    finally:
        db.conn.close()


def test_no_driver_specific_integrity_catches_remain():
    """Guardrail: naming a driver's exception class reintroduces the bug."""
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in root.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"except\s+(sqlite3|sqlcipher3)\S*\.IntegrityError", line):
                offenders.append(f"{path.relative_to(root.parent)}:{i}")
    assert not offenders, (
        "use dbconn.integrity_errors() instead: " + ", ".join(offenders)
    )
