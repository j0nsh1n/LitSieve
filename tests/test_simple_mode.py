"""Simple / Advanced UI mode — structural guardrails (Phase 5).

Simple mode is a client preference (localStorage.uiMode + data-mode on <html>).
These tests lock the contracts that are easy to break silently: theme-init
must set mode pre-paint, the nav must renumber without gaps when Clusters is
hidden, and hidden source checkboxes must still participate in fetch.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import route_paths
from fastapi.testclient import TestClient

from app.main import app

REPO = Path(__file__).resolve().parents[1]


def test_theme_init_sets_data_mode_before_paint():
    """theme-init must apply data-mode synchronously in <head> (no flash)."""
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    tag = re.search(r"<script[^>]*theme-init\.js[^>]*>", base)
    assert tag, "base.html no longer loads theme-init.js"
    assert "defer" not in tag.group(0), tag.group(0)
    assert "async" not in tag.group(0), tag.group(0)
    assert "type=\"module\"" not in tag.group(0).lower(), tag.group(0)
    head = base.split("</head>")[0]
    assert "theme-init.js" in head, "theme-init.js must be in <head>"

    init = (REPO / "static" / "js" / "theme-init.js").read_text(encoding="utf-8")
    assert "uiMode" in init
    assert "data-mode" in init
    assert "localStorage.getItem('uiMode')" in init or 'localStorage.getItem("uiMode")' in init
    # Must never load as module / deferred itself.
    assert "type=\"module\"" not in init
    assert "no defer" in init.lower() or "Must stay a plain blocking" in init


def test_mode_toggle_replaces_reading_mode():
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'id="mode-toggle"' in base
    assert "reading-toggle" not in base
    assert "readingMode" not in (REPO / "static" / "js" / "theme-init.js").read_text(
        encoding="utf-8"
    )
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "setUiMode" in common
    assert "isSimpleMode" in common
    assert "reading-toggle" not in common
    assert "setReadingMode" not in common


def test_simple_nav_steps_are_contiguous():
    """Simple mode hides Clusters; remaining steps must be 1, 2, 3 with no gap."""
    base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
    # Workflow tuples: (key, label, href, tip, simple_step)
    rows = re.findall(
        r'\(\s*"(\w+)"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"[^"]*"\s*,\s*"(\d*)"\s*\)',
        base,
    )
    assert rows, "base.html workflow must include simple_step as 5th tuple field"
    by_key = dict(rows)
    assert "clusters" in by_key, by_key
    assert by_key["clusters"] == "", "Clusters has no Simple step number (hidden)"
    visible = [by_key[k] for k in ("data_management", "statistics", "search")]
    assert visible == ["1", "2", "3"], f"Simple steps must be contiguous 1-3, got {visible}"

    # data-step-simple attributes drive the JS renumberer.
    assert 'data-step-simple="{{ simple_step }}"' in base or 'data-step-simple="' in base
    assert "nav-step-{{ key }}" in base or "nav-step-" in base

    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert 'html[data-mode="simple"] .nav-step-clusters' in css
    assert "display: none" in css


def test_hidden_source_grid_still_submits_checked_sources():
    """Guard the 'hidden control still submits' trap.

    Simple mode CSS-hides the source grid; fetch must still read every checked
    checkbox (no :visible / offsetParent filter). Topics auto-check sources.
    """
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    assert "source-option-grid" in css
    # Hide via display on the section, not by disabling inputs.
    hide_block = re.search(
        r'html\[data-mode="simple"\][^{]*source-option-grid[^{]*\{[^}]+\}',
        css,
        re.DOTALL,
    )
    assert hide_block, "Simple mode must hide the source grid via CSS"
    assert "display:" in hide_block.group(0)
    assert "pointer-events: none" not in hide_block.group(0)

    dm_js = (REPO / "static" / "js" / "data_management.js").read_text(encoding="utf-8")
    # doFetch source collection — must not filter by visibility.
    assert "source-option-grid input[type=\"checkbox\"]:checked" in dm_js or (
        "source-option-grid input[type='checkbox']:checked" in dm_js
    )
    assert "offsetParent" not in dm_js
    assert ":visible" not in dm_js
    assert "updateRecommendedSources" in dm_js
    # Auto-check when topics selected.
    assert "checkbox.checked = recommended.has(sourceId)" in dm_js


def test_register_seeds_simple_mode_cookie(tmp_path, monkeypatch):
    """Brand-new accounts get ui_mode_seed=simple; login alone must not."""
    from app import core
    from app.storage.user_db import UserDatabase

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)

    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "username": "newstudent1",
            "password": "tpw-fixture-0001",
            "password_confirm": "tpw-fixture-0001",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.cookies.get("ui_mode_seed") == "simple"

    # Logout then login of an "existing" account must not re-seed Simple.
    client.post("/logout", follow_redirects=False)
    # Clear client cookie jar seed so we only see what login sets.
    client.cookies.clear()
    r2 = client.post(
        "/login",
        data={"username": "newstudent1", "password": "tpw-fixture-0001"},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)
    assert r2.cookies.get("ui_mode_seed") in (None, "")


def test_clusters_route_still_exists():
    """Simple mode removes Clusters from the nav only — URL must still work."""
    paths = route_paths(app)
    assert "/clusters" in paths
