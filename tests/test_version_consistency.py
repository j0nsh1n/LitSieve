"""One version string, everywhere it is shown (audit 23.5).

It lives in app/version.py. FastAPI, /health, the admin summary, support
packets and the template footers read it from there; 5.4.0 shipped with
footers and the health payload still saying the old number when each place
repeated it by hand.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import APP_VERSION

REPO = Path(__file__).resolve().parents[1]


def test_the_app_and_health_report_the_one_version():
    assert app.version == APP_VERSION
    client = TestClient(app)
    assert client.get("/health").json()["version"] == APP_VERSION


def test_no_other_file_spells_the_version_out():
    for path in list((REPO / "app").rglob("*.py")) + list((REPO / "templates").rglob("*.html")):
        if path.name == "version.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert APP_VERSION not in text, f"{path.relative_to(REPO)} repeats {APP_VERSION}"


def test_footers_render_the_version():
    for name in ("base.html", "login.html", "landing.html", "feature_guide.html"):
        text = (REPO / "templates" / name).read_text(encoding="utf-8")
        assert "{{ app_version }}" in text, name
    client = TestClient(app)
    for path in ("/", "/login"):
        body = client.get(path).text
        assert f"v{APP_VERSION}" in body, path
