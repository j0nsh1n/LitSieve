"""Security response headers (and the DEBUG carve-out for HSTS)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import security
from app.main import app


def test_baseline_headers_present_on_public_page():
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_headers_also_on_api_and_error_responses():
    client = TestClient(app)
    # 401 from an authenticated endpoint still carries the headers.
    r = client.get("/api/statistics")
    assert r.status_code in (401, 403)
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_hsts_suppressed_in_debug(monkeypatch):
    """HSTS must not be sent over local http:// — it would pin the browser."""
    monkeypatch.setenv("DEBUG", "true")
    assert security.https_enforced() is False
    r = TestClient(app).get("/")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_sent_when_not_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    assert security.https_enforced() is True
    r = TestClient(app).get("/")
    assert r.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    assert "includeSubDomains" in r.headers["Strict-Transport-Security"]
