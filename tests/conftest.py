"""Pytest configuration: ensure a SECRET_KEY is present before importing auth."""

import os
import sys

import pytest

# Provide a deterministic key so auth.py imports cleanly and tokens can be created.
# Not a production secret — process-local only for the test suite.
os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")

# Fixture credentials for HTTP / auth tests. Meet min length; not real secrets.
# Import these instead of scattering password-looking string literals in tests.
TEST_PASSWORD = "tpw-fixture-0001"
TEST_PASSWORD_ALT = "tpw-fixture-0002"

# Make the application modules importable (tests/ lives one level below repo root).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Register/login limits are IP-keyed; many HTTP tests share TestClient host.

    Clear the in-memory limiter between tests so suite order cannot 429 flaky.
    """
    yield
    try:
        from app.core import limiter
        if hasattr(limiter, "reset"):
            limiter.reset()
        elif getattr(limiter, "_storage", None) is not None:
            limiter._storage.reset()
    except Exception:
        pass


def route_paths(fastapi_app) -> set:
    """All registered route paths.

    FastAPI stores ``include_router`` results as wrapper objects rather than
    flattening them into ``app.routes``, so a naive comprehension over
    ``app.routes`` silently returns almost nothing. The OpenAPI schema is the
    version-independent source of truth — important here because the callers
    are guardrail tests that must fail loudly, not vacuously pass.
    """
    return set(fastapi_app.openapi().get("paths", {}))
