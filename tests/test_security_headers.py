"""Security response headers (and the DEBUG carve-out for HSTS)."""

from __future__ import annotations

import pathlib

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


def test_csp_has_no_unsafe_inline():
    """An 'unsafe-inline' script-src makes injected <script> executable again."""
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in csp, csp
    assert "unsafe-eval" not in csp, csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp


def test_no_inline_scripts_in_templates():
    """Inline <script> would be blocked by the CSP, so the page would break.

    Any new script must go in static/js and be referenced with src=.
    """
    import re

    templates = pathlib.Path(__file__).resolve().parents[1] / "templates"
    offenders = []
    for path in sorted(templates.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        for tag in re.findall(r"<script\b[^>]*>", html):
            if "src=" not in tag:
                offenders.append(f"{path.name}: {tag}")
    assert not offenders, "inline <script> blocked by CSP: " + "; ".join(offenders)


def test_no_inline_style_attributes_in_templates():
    """style="" is blocked by style-src 'self'; use a .u-* utility class."""
    import re

    templates = pathlib.Path(__file__).resolve().parents[1] / "templates"
    offenders = []
    for path in sorted(templates.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        if re.search(r"<[^>]*\sstyle=\"", html):
            offenders.append(path.name)
    assert not offenders, "inline style attributes blocked by CSP: " + ", ".join(offenders)


def test_theme_init_is_render_blocking_in_head():
    """theme-init must not gain defer/async or dark mode flashes white.

    Also applies uiMode → data-mode pre-paint (Simple/Advanced).
    """
    import re

    base = pathlib.Path(__file__).resolve().parents[1] / "templates" / "base.html"
    html = base.read_text(encoding="utf-8")
    tag = re.search(r"<script[^>]*theme-init\.js[^>]*>", html)
    assert tag, "base.html no longer loads theme-init.js"
    assert "defer" not in tag.group(0), tag.group(0)
    assert "async" not in tag.group(0), tag.group(0)
    head = html.split("</head>")[0]
    assert "theme-init.js" in head, "theme-init.js must be in <head>"

    init = (
        pathlib.Path(__file__).resolve().parents[1] / "static" / "js" / "theme-init.js"
    ).read_text(encoding="utf-8")
    assert "uiMode" in init
    assert "data-mode" in init
