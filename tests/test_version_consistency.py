"""One version string, everywhere it is shown.

The number lives in app/main.py, but the health endpoint, the admin summary,
and four template footers repeat it by hand. 5.4.0 shipped with the footers
and the health payload still saying the old number, so this test reads the
FastAPI version and checks every other copy against it.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"\bv?(\d+\.\d+\.\d+)\b")


def test_health_reports_the_app_version():
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["version"] == app.version


def test_every_hardcoded_version_matches_the_app():
    expected = app.version
    admin = (REPO / "app" / "routes" / "admin.py").read_text(encoding="utf-8")
    assert f'"version": "{expected}"' in admin
    for name in ("base.html", "login.html", "landing.html", "feature_guide.html"):
        text = (REPO / "templates" / name).read_text(encoding="utf-8")
        found = {m.group(1) for m in VERSION_RE.finditer(text)}
        assert found == {expected}, f"{name} shows {sorted(found)}, app is {expected}"
    main_doc = (REPO / "app" / "main.py").read_text(encoding="utf-8")
    assert f"LitSieve v{expected}" in main_doc
