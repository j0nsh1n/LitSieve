"""The product uses its own instant help text instead of browser title bubbles."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((REPO / "templates").rglob("*.html"))
SCRIPTS = sorted((REPO / "static" / "js").glob("*.js"))


def test_product_ui_has_no_native_title_tooltips():
    html_title = re.compile(r"(?:^|[<\s])title=(?:\"|')")
    property_title = re.compile(r"\.title\s*=")
    set_title = re.compile(r"setAttribute\(\s*(?:\"|')title(?:\"|')")
    failures = []
    for path in [*TEMPLATES, *SCRIPTS]:
        text = path.read_text(encoding="utf-8")
        if html_title.search(text) or property_title.search(text) or set_title.search(text):
            failures.append(path.relative_to(REPO).as_posix())
    assert not failures, "native title tooltip found in: " + ", ".join(failures)


def test_tooltip_runtime_loads_on_app_and_public_pages():
    entry_templates = [
        REPO / "templates" / name
        for name in (
            "base.html",
            "feature_guide.html",
            "landing.html",
            "login.html",
            "register.html",
            "reset_password.html",
            "verify_email.html",
        )
    ]
    tag = re.compile(r'<script src="/static/js/tooltips\.js\?v=([0-9a-z]+)" defer></script>')
    versions = {}
    for path in entry_templates:
        m = tag.search(path.read_text(encoding="utf-8"))
        assert m, path.name
        versions[path.name] = m.group(1)
    assert len(set(versions.values())) == 1, f"tooltips.js cache-bust differs: {versions}"


def test_icon_tooltips_keep_accessible_names():
    theme_toggle = (REPO / "templates" / "partials" / "theme_toggle.html").read_text(encoding="utf-8")
    assert 'data-tip="Toggle theme"' in theme_toggle
    assert 'aria-label="Toggle theme"' in theme_toggle

    search = (REPO / "static" / "js" / "search.js").read_text(encoding="utf-8")
    assert 'data-tip="${starred ? \'Remove star\' : \'Star article\'}"' in search
    assert 'aria-label="${starred ? \'Remove star\' : \'Star article\'}"' in search
    assert "starBtn.dataset.tip = next ? 'Remove star' : 'Star article'" in search
    assert "starBtn.dataset.tip = next ? 'Star article' : 'Remove star'" in search
    assert "starBtn.setAttribute('aria-label', starBtn.dataset.tip)" in search



def test_bubble_stays_open_for_the_pointer_and_never_strands():
    """WCAG 1.4.13: hover text must stay open while the pointer moves onto it.

    There is no JS test runner here, so this pins the three mechanisms; the
    behaviour itself was driven in Chromium (see the commit message).
    """
    css = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
    js = (REPO / "static" / "js" / "tooltips.js").read_text(encoding="utf-8")
    bubble = re.search(r"\.app-tooltip \{([^}]*)\}", css).group(1)
    assert "pointer-events: none" not in bubble, "the bubble must take the pointer"
    bridge = re.search(r"\.app-tooltip::before \{([^}]*)\}", css)
    assert bridge and "height: calc(0.5625rem + 1px)" in bridge.group(1), "bridge must span the 9px gap plus the border"
    assert "var gap = 9;" in js, "the bridge height is tied to this gap"
    assert "tooltip.addEventListener('pointerleave'" in js
    assert re.search(r"\|\| !onScreen\(target\)\)", js), "a control scrolled off screen must hide its bubble"
