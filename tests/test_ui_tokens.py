"""Phase 7 design-system tokens and scale discipline (presentation only).

Locks the type / spacing / radius scales in style.css so hand-tuned values
cannot silently multiply again. No behaviour assertions — Simple/guest guards
remain the proof of presentation-only work.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")


# Documented in docs/UI_REFRESH_PLAN.md Part 1.
REQUIRED_TOKENS = (
    # type
    "--fs-xs",
    "--fs-sm",
    "--fs-base",
    "--fs-md",
    "--fs-lg",
    "--fs-xl",
    "--fs-2xl",
    "--fs-3xl",
    # line-height + measure
    "--lh-tight",
    "--lh-snug",
    "--lh-normal",
    "--lh-relaxed",
    "--measure",
    # spacing
    "--space-1",
    "--space-2",
    "--space-3",
    "--space-4",
    "--space-5",
    "--space-6",
    "--space-7",
    "--space-8",
    # radii
    "--radius-sm",
    "--radius-md",
    "--radius-full",
    # preserved colour/motion (must still exist)
    "--accent",
    "--text-body",
    "--elev-1",
    "--dur-fast",
    "--ease-soft",
    "--focus-ring",
)


def _root_block() -> str:
    """First :root { ... } block (token home)."""
    m = re.search(r":root\s*\{", CSS)
    assert m, ":root block missing"
    start = m.end()
    depth = 1
    i = start
    while i < len(CSS) and depth:
        if CSS[i] == "{":
            depth += 1
        elif CSS[i] == "}":
            depth -= 1
        i += 1
    return CSS[start : i - 1]


def test_root_defines_documented_scale_tokens():
    root = _root_block()
    missing = [t for t in REQUIRED_TOKENS if t not in root]
    assert not missing, f"missing from :root: {missing}"


def test_spacing_utilities_use_space_tokens():
    """Class names stay; values must come from the spacing scale."""
    for cls in (".u-mt-sm", ".u-mt-md", ".u-mt-lg", ".u-mt-xl", ".u-mt-form"):
        m = re.search(rf"{re.escape(cls)}\s*\{{[^}}]*margin-top\s*:\s*([^;]+);", CSS)
        assert m, f"{cls} missing"
        assert "var(--space-" in m.group(1), f"{cls} not on spacing scale: {m.group(1)}"


def test_preserved_colour_motion_tokens_still_present():
    """Phase 7 adds alongside existing tokens — never rename/remove them."""
    for t in ("--accent", "--text-body", "--elev-1", "--dur-fast", "--ease-soft", "--focus-ring"):
        assert t in CSS, t


def _css_without_comments() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _decl_values(prop: str) -> list[str]:
    """Property values for `prop:`; skip @supports (padding: …) false matches."""
    out = []
    for m in re.finditer(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;]+);", _css_without_comments()):
        v = m.group(1).strip()
        if "{" in v or "}" in v:
            continue
        out.append(v)
    return out


def _literal_lengths(value: str) -> list[str]:
    """rem/px/em lengths that are not already inside var(...)."""
    # Strip var(...) so we do not count token definitions' resolved forms in use sites.
    stripped = re.sub(r"var\([^)]*\)", "", value)
    return re.findall(r"[0-9.]+(?:rem|px|em)\b", stripped)


def test_font_size_scale_discipline():
    """At most 8 type steps — only --fs-* tokens (plus 0)."""
    allowed_vars = {
        "--fs-xs",
        "--fs-sm",
        "--fs-base",
        "--fs-md",
        "--fs-lg",
        "--fs-xl",
        "--fs-2xl",
        "--fs-3xl",
    }
    used = set()
    for v in _decl_values("font-size"):
        v_clean = v.replace("!important", "").strip()
        if v_clean in ("0", "inherit", "smaller", "larger"):
            continue
        lits = _literal_lengths(v_clean)
        assert not lits, f"literal font-size {v_clean!r}"
        for tok in re.findall(r"var\((--fs-[\w]+)\)", v_clean):
            used.add(tok)
            assert tok in allowed_vars, tok
    assert len(used) <= 8, f"too many type tokens in use: {sorted(used)}"
    assert used, "no --fs-* font-size usage found"


def test_border_radius_scale_discipline():
    """At most 3 radius steps — only --radius-* tokens (plus 0)."""
    allowed = {"--radius-sm", "--radius-md", "--radius-full"}
    used = set()
    for v in _decl_values("border-radius"):
        v_clean = v.replace("!important", "").strip()
        lits = _literal_lengths(v_clean)
        # 0 is fine; no raw 6px/12px etc.
        assert not lits, f"literal border-radius {v_clean!r}"
        for tok in re.findall(r"var\((--radius-[\w]+)\)", v_clean):
            used.add(tok)
            assert tok in allowed, tok
    assert len(used) <= 3, sorted(used)
    assert used


def test_padding_uses_spacing_scale_only():
    """Padding lengths come from --space-* (or 0 / env / max / calc of those)."""
    for prop in (
        "padding",
        "padding-top",
        "padding-right",
        "padding-bottom",
        "padding-left",
    ):
        for v in _decl_values(prop):
            lits = _literal_lengths(v)
            assert not lits, f"{prop}: literal length(s) {lits} in {v!r}"
