"""Shared disclaimer macros — keep landing / app / guides / auth in sync."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from main import app


TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
CACHE_BUST = "20260717r2"

# Canonical phrases that must appear in the full banner (single source of truth).
FULL_PHRASES = (
    "Starting point only",
    "publicly accessible",
    "not a complete library search",
    "medical, legal, or professional advice",
)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def _plain(html: str) -> str:
    """Strip tags and collapse whitespace for phrase checks."""
    text = re.sub(r"<[^>]+>", " ", str(html))
    return re.sub(r"\s+", " ", text).strip().lower()


def test_macros_export_all_variants():
    env = _env()
    macros = env.get_template("macros/disclaimers.html").module
    for name in ("scope_banner", "scope_auth", "scope_footer", "scope_fetch", "scope_search"):
        assert hasattr(macros, name), f"missing macro {name}"


def test_banner_contains_canonical_phrases():
    env = _env()
    macros = env.get_template("macros/disclaimers.html").module
    html = macros.scope_banner()
    plain = _plain(html)
    for phrase in FULL_PHRASES:
        assert phrase.lower() in plain, f"banner missing: {phrase}"
    assert 'class="site-disclaimer"' in html
    assert 'role="note"' in html


def test_auth_and_footer_share_core_limits():
    env = _env()
    macros = env.get_template("macros/disclaimers.html").module
    auth = macros.scope_auth()
    foot = macros.scope_footer()
    compact = macros.scope_footer(compact=True)
    assert "Starting point only" in auth
    assert "Public research databases only" in auth
    assert "professional advice" in auth.lower() or "medical" in auth.lower()
    assert "Public research databases only" in foot
    assert "starting point" in foot.lower()
    assert "Public research databases only" in compact
    assert "classroom study aid" in compact


def test_fetch_and_search_variants_mark_starting_point():
    env = _env()
    macros = env.get_template("macros/disclaimers.html").module
    fetch = macros.scope_fetch()
    search = macros.scope_search()
    assert "Starting point only" in fetch
    assert "public research" in fetch.lower()
    assert "Paywalled" in fetch
    assert "Starting point only" in search
    assert "only papers already in your" in _plain(search)


def test_public_pages_render_shared_banner():
    client = TestClient(app)
    landing = client.get("/")
    assert landing.status_code == 200
    plain = _plain(landing.text)
    for phrase in FULL_PHRASES:
        assert phrase.lower() in plain, f"landing missing: {phrase}"
    assert f"style.css?v={CACHE_BUST}" in landing.text

    guide = client.get("/learn/multi-source-search")
    assert guide.status_code == 200
    gplain = _plain(guide.text)
    for phrase in FULL_PHRASES:
        assert phrase.lower() in gplain, f"guide missing: {phrase}"
    assert f"style.css?v={CACHE_BUST}" in guide.text


def test_auth_pages_render_shared_auth_disclaimer():
    client = TestClient(app)
    for path in ("/login", "/register"):
        r = client.get(path)
        assert r.status_code == 200
        assert "Starting point only" in r.text
        assert "Public research databases only" in r.text
        assert f"style.css?v={CACHE_BUST}" in r.text


def test_no_inline_disclaimer_drift_in_templates():
    """Templates should include the macros file, not hard-code banner copy."""
    forbidden_snippets = (
        "This tool searches a set of",
        "Literature Research Aide works with",
        "Uses publicly accessible research databases",
        "Public research databases for gathering candidates",
    )
    skip = {"macros/disclaimers.html"}
    for path in TEMPLATES.rglob("*.html"):
        rel = path.relative_to(TEMPLATES).as_posix()
        if rel in skip:
            continue
        text = path.read_text(encoding="utf-8")
        for snip in forbidden_snippets:
            assert snip not in text, f"{rel} still hard-codes disclaimer: {snip!r}"
