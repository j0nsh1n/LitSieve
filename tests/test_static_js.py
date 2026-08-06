"""Syntax-check the browser JavaScript.

There is no npm and no build step, so nothing else looks at these files: a
stray brace ships straight to users while the entire Python suite stays green.
A broken data_management.js would take out the whole fetch/prepare page.

esprima only understands up to ES2019, so the few modern tokens the codebase
uses (`?.`, `??`) are down-levelled before parsing. Everything structural —
braces, functions, blocks, statements — is still genuinely parsed.
"""

from __future__ import annotations

import pathlib
import re

import pytest

esprima = pytest.importorskip(
    "esprima", reason="esprima not installed; CI installs it (see ci.yml)"
)

JS_DIR = pathlib.Path(__file__).resolve().parent.parent / "static" / "js"


def _downlevel(src: str) -> str:
    """Replace tokens esprima cannot lex, without changing structure."""
    return src.replace("?.", ".").replace("??=", "=").replace("??", "||")


def _js_files():
    return sorted(JS_DIR.glob("*.js"))


def test_there_are_js_files_to_check():
    """Guard against the glob silently matching nothing."""
    assert _js_files(), f"no .js found under {JS_DIR}"


@pytest.mark.parametrize("path", _js_files(), ids=lambda p: p.name)
def test_js_parses(path):
    try:
        esprima.parseScript(_downlevel(path.read_text()))
    except Exception as exc:  # noqa: BLE001 - esprima raises its own Error type
        pytest.fail(f"{path.name} is not valid JavaScript: {exc}")


def test_theme_init_stays_loadable_before_paint():
    """It must remain a plain classic script.

    theme-init.js sets the theme and UI mode on <html> before first paint. As a
    module or with defer it runs too late and users see a flash of the wrong
    theme/layout, and inline would break the `script-src 'self'` CSP.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    for name in ("base.html", "login.html", "landing.html", "register.html"):
        html = (root / "templates" / name).read_text()
        tag = re.search(r"<script[^>]*theme-init[^>]*>", html)
        assert tag, f"{name} does not load theme-init.js"
        markup = tag.group(0)
        for forbidden in ("defer", "async", 'type="module"'):
            assert forbidden not in markup, f"{name}: theme-init must not use {forbidden}"


def test_ci_installs_the_js_parser():
    """Otherwise the parse tests above silently skip and prove nothing."""
    root = pathlib.Path(__file__).resolve().parent.parent
    ci = (root / ".github" / "workflows" / "ci.yml").read_text()
    assert "esprima" in ci, "add esprima to the CI install step or these tests skip"


def test_shared_assets_use_one_cache_bust_version():
    """Every template must request the same build of a shared asset.

    theme-init.js and style.css are loaded by both base.html and the public
    templates (which do not extend it). When only base.html's ?v= was bumped,
    returning visitors on /login, /register and the landing page kept getting a
    cached older script — so a fix could ship and simply not reach them.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    for asset in ("theme-init.js", "style.css"):
        versions = {}
        for path in sorted((root / "templates").glob("*.html")):
            found = re.findall(rf"{re.escape(asset)}\?v=([0-9a-z]+)", path.read_text())
            for v in found:
                versions.setdefault(v, []).append(path.name)
        if not versions:
            continue
        assert len(versions) == 1, (
            f"{asset} requested at multiple versions: "
            + "; ".join(f"{v} in {sorted(set(f))}" for v, f in versions.items())
        )
