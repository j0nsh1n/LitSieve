"""Pytest configuration: ensure a SECRET_KEY is present before importing auth."""

import os
import sys

import pytest

# Provide a deterministic key so auth.py imports cleanly and tokens can be created.
os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")

# Make the application modules importable (tests/ lives one level below repo root).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Register/login limits are IP-keyed; many HTTP tests share TestClient host.

    Clear the in-memory limiter between tests so suite order cannot 429 flaky.
    """
    yield
    try:
        from main import limiter
        if hasattr(limiter, "reset"):
            limiter.reset()
        elif getattr(limiter, "_storage", None) is not None:
            limiter._storage.reset()
    except Exception:
        pass
