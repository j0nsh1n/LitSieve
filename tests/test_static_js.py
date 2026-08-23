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
    for name in ("base.html", "login.html", "landing.html", "register.html", "feature_guide.html"):
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


def test_ops_python_highlighter_is_wired():
    root = pathlib.Path(__file__).resolve().parent.parent
    js = (JS_DIR / "ops.js").read_text(encoding="utf-8")
    # Ops chrome lives in its own stylesheet (operator-only, outside the
    # design-system token scale enforced on style.css).
    css = (root / "static" / "css" / "ops.css").read_text(encoding="utf-8")
    html = (root / "templates" / "ops.html").read_text(encoding="utf-8")
    assert "function highlightPython" in js
    assert "function paintHighlight" in js
    assert 'id="ops-hl"' in html
    assert ".ops-hl .tok-kw" in css
    assert ".ops-editor-wrap.is-py .ops-editor" in css


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


def test_public_pages_have_theme_toggle_without_common_js():
    """Landing and /learn guides can switch theme without loading common.js."""
    root = pathlib.Path(__file__).resolve().parent.parent
    init = (root / "static" / "js" / "theme-init.js").read_text(encoding="utf-8")
    assert "getElementById('theme-toggle')" in init or 'getElementById("theme-toggle")' in init
    assert "data-theme-bound" in init
    assert "localStorage.setItem('theme'" in init or 'localStorage.setItem("theme"' in init

    for name in ("landing.html", "feature_guide.html"):
        html = (root / "templates" / name).read_text(encoding="utf-8")
        # The button lives in a shared partial, so accept either the literal
        # markup or the include that pulls it in.
        has_toggle = (
            'id="theme-toggle"' in html
            or 'partials/theme_toggle.html' in html
        )
        assert has_toggle, f"{name} missing theme toggle"
        assert html.count('partials/theme_toggle.html') <= 1, (
            f"{name} includes the theme toggle more than once"
        )
        assert 'src="/static/js/common.js' not in html, f"{name} must not load common.js"


def test_count_bars_scale_to_series_max():
    """Articles-by-source and papers-by-year bars use the chart's own max.

    The longest bar is 100% of the track; shorter counts are count/max.
    A fixed global scale (or always-full bars) makes small years/sources
    look as large as the largest.
    """
    src = (JS_DIR / "statistics.js").read_text(encoding="utf-8")
    assert "function renderCountBars" in src
    assert "maxCount" in src
    # Width is relative to this series max, not a hard-coded total.
    assert "(row.count / maxCount) * 100" in src or "(count / maxCount) * 100" in src
    assert "renderYearTimeline" in src
    # Year chart reuses the same helper (one scale definition).
    year_fn = src[src.find("function renderYearTimeline") :]
    assert "renderCountBars" in year_fn[:800]


def test_count_bars_do_not_use_inline_style_attributes():
    """CSP is style-src 'self' with no unsafe-inline — style="" is ignored.

    Bar widths must be applied via CSS variables / CSSOM (setProperty), not
    style=\"width:…\" in innerHTML, or every bar renders full-width.
    """
    stats = (JS_DIR / "statistics.js").read_text(encoding="utf-8")
    dm = (JS_DIR / "data_management.js").read_text(encoding="utf-8")
    bars_fn = stats[stats.find("function renderCountBars") : stats.find("function renderYearTimeline")]
    # Forbid HTML style attributes; allow element.style.setProperty (CSSOM).
    assert 'style="' not in bars_fn and "style='" not in bars_fn
    assert "setProperty" in bars_fn and "--bar-pct" in bars_fn
    assert "source-bar-inner" in bars_fn
    # Coverage map on Data Management uses the same CSP-safe pattern.
    assert "--bar-pct" in dm
    assert 'style="width:' not in dm and "style='width:" not in dm
    css = (JS_DIR.parent / "css" / "style.css").read_text(encoding="utf-8")
    assert "var(--bar-pct" in css


def test_account_uses_site_modals_not_browser_dialogs():
    """Account destructive/input flows use in-app modals, not window.confirm/prompt/alert."""
    account = (JS_DIR / "account.js").read_text(encoding="utf-8")
    common = (JS_DIR / "common.js").read_text(encoding="utf-8")
    assert "function openSiteConfirm" in common
    assert "function openSitePrompt" in common
    assert "function openSiteAlert" in common
    assert "function openSiteModal" in common
    assert "function openSiteForm" in common
    # No browser dialogs left on Account.
    for bad in ("window.confirm", "window.prompt", "window.alert", "confirm(", "prompt(", "alert("):
        # allow openSiteConfirm / openSitePrompt names and variable names like password_confirm
        if bad in ("confirm(", "prompt(", "alert("):
            # strip function defs and openSite* calls
            stripped = account
            for keep in ("openSiteConfirm", "openSitePrompt", "openSiteAlert", "password_confirm", "new_password_confirm", "delete-confirm", "confirmCb", "confirmLabel"):
                stripped = stripped.replace(keep, "")
            assert bad not in stripped, f"account.js still uses browser {bad}"
        else:
            assert bad not in account
    assert "openSiteConfirm" in account
    assert "openSitePrompt" in account


def test_no_queueAnimationFrame_typo():
    """queueAnimationFrame is not a browser API; it throws and aborts page setup.

    Caught in production when Data Management never bound the fetch form
    submit handler and POST /data-management returned 405.
    """
    offenders = []
    for path in _js_files():
        if "queueAnimationFrame" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"undefined queueAnimationFrame in: {offenders}"


def test_mobile_nav_keeps_account_link_reachable():
    """Phones must not hide the Account control (≤640px used to display:none it).

    Users could Logout but never open /account from the mobile top bar.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert 'href="/account"' in base
    assert "nav-username" in base
    assert "nav-username-full" in base
    assert "nav-username-short" in base
    assert "Account" in base

    css = (root / "static" / "css" / "style.css").read_text(encoding="utf-8")
    # Extract the phones (≤640px) block so we do not match unrelated rules.
    phone = css[css.find("@media (max-width: 640px)") : css.find("@media (max-width: 380px)")]
    assert phone, "missing 640px media block"
    # Must not hide the account link entirely.
    assert re.search(r"\.nav-username\s*\{\s*display\s*:\s*none", phone) is None, (
        "phones hide .nav-username; Account is unreachable"
    )
    assert "nav-username-short" in phone
    assert "display: inline" in phone or "display:inline" in phone
