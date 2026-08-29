"""Shared disclaimer macros — keep landing / app / guides / auth in sync."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.main import app

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"

# Canonical phrases that must appear in the full banner (single source of truth).
FULL_PHRASES = (
    "Starting point only",
    "publicly accessible",
    "not a complete library search",
    "medical, legal, or professional advice",
)

# Public pages (landing/auth/guides) and the app shell (base.html) may bump
# style.css?v= independently — only require a non-empty cache-bust token.
_STYLE_CACHE_BUST = re.compile(r"style\.css\?v=[A-Za-z0-9._-]+")


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
    for name in ("scope_banner", "scope_auth", "scope_footer", "scope_fetch", "scope_search", "scope_reader"):
        assert hasattr(macros, name), f"missing macro {name}"


def test_reader_disclaimer_is_educational_not_clinical():
    env = _env()
    macros = env.get_template("macros/disclaimers.html").module
    text = macros.scope_reader()
    assert "educational reading aid" in text.lower()
    assert "medical, legal, or professional advice" in text.lower()
    js = (TEMPLATES.parent / "static" / "js" / "reader.js").read_text(encoding="utf-8")
    low = js.lower()
    for banned in ("clinically verified", "medically accurate", "guaranteed"):
        assert banned not in low


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
    assert "student starting point" in compact


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
    assert _STYLE_CACHE_BUST.search(landing.text), "landing missing style.css?v=…"

    guide = client.get("/learn/multi-source-search")
    assert guide.status_code == 200
    gplain = _plain(guide.text)
    for phrase in FULL_PHRASES:
        assert phrase.lower() in gplain, f"guide missing: {phrase}"
    assert _STYLE_CACHE_BUST.search(guide.text), "guide missing style.css?v=…"


def test_auth_pages_render_shared_auth_disclaimer():
    client = TestClient(app)
    for path in ("/login", "/register"):
        r = client.get(path)
        assert r.status_code == 200
        assert "Starting point only" in r.text
        assert "Public research databases only" in r.text
        assert _STYLE_CACHE_BUST.search(r.text), f"{path} missing style.css?v=…"


def test_app_shell_stylesheet_cache_bust_matches_base_template():
    """base.html is the app shell; keep its ?v= token present (CodeRabbit)."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    m = _STYLE_CACHE_BUST.search(base)
    assert m, "base.html missing style.css?v= cache-bust"
    # Token must change when CSS changes — currently 20260726r3 on this branch.
    assert "style.css?v=" in base


def test_no_inline_disclaimer_drift_in_templates():
    """Templates should include the macros file, not hard-code banner copy."""
    forbidden_snippets = (
        "This tool searches a set of",
        "LitSieve works with",
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


# --- Brand consistency -----------------------------------------------------

def test_no_stale_product_name_in_user_facing_surfaces():
    """The product is LitSieve. Earlier names must not survive in the UI.

    Excluded, because they are not product names:
      * the public hostname litpilot.org (a Cloudflare/registrar fact)
      * `_HKDF_INFO_*` — key-derivation labels baked into stored ciphertext.
        Renaming those would change the derived key and make every existing
        encrypted AI key undecryptable, so they are frozen forever.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    targets = [
        *(root / "templates").rglob("*.html"),
        *(root / "static").rglob("*.js"),
        *(root / "app").rglob("*.py"),
    ]

    offenders = []
    for path in targets:
        for i, line in enumerate(path.read_text().splitlines(), 1):
            # Strip the domain before looking for the old product name.
            if "_HKDF_INFO" in line:
                continue          # frozen crypto constant, see docstring
            stripped = re.sub(r"litpilot\.(org|duckdns\.org)", "", line, flags=re.I)
            if re.search(r"litpilot|literature[ _-]research[ _-]aide", stripped, re.I):
                offenders.append(f"{path.relative_to(root)}:{i}")

    assert not offenders, "stale product name: " + ", ".join(offenders)


def test_brand_appears_in_the_nav_and_footer():
    """Guard the rename actually landed where users see it."""
    import pathlib
    base = (pathlib.Path(__file__).resolve().parent.parent
            / "templates" / "base.html").read_text()
    assert "LitSieve" in base
    assert "LitPilot" not in base
