"""Scrollbars and dropdown lists are drawn in the look's own tokens.

The thumb and option colours are mixes of look tokens, so these tests do the
mix and measure the result in every look and theme instead of pinning hex.
"""

from __future__ import annotations

import re
from pathlib import Path

from test_looks import _rule_body
from test_ui_tokens import _css_block_tokens, _theme_token_blocks, _wcag_contrast

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
LIST_SELECT = "select:not([multiple]):not([size])"


def _all_token_blocks() -> list[tuple[str, dict[str, str]]]:
    """Workshop (the :root theme) plus every look, in each theme it defines."""
    blocks = list(_theme_token_blocks())
    for look in ("broadsheet", "lab", "catalog"):
        for label, needle in (
            (f"{look} light", f'html[data-look="{look}"] {{'),
            (f"{look} dark", f'html[data-look="{look}"][data-theme="dark"] {{'),
            (f"{look} prefers-dark", f'html[data-look="{look}"]:not([data-theme="light"]) {{'),
        ):
            blocks.append((label, _css_block_tokens(_rule_body(CSS, needle))))
    blocks.append(("night dark", _css_block_tokens(_rule_body(CSS, 'html[data-look="night"] {'))))
    blocks.append(
        ("night light", _css_block_tokens(_rule_body(CSS, 'html[data-look="night"][data-theme="light"] {')))
    )
    assert len(blocks) == 14
    return blocks


def _mix(a: str, b: str, pct: float) -> str:
    """color-mix(in srgb, a pct%, b): straight blend of the encoded channels."""
    ca = [int(a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(pct / 100 * x + (1 - pct / 100) * y):02x}" for x, y in zip(ca, cb))


def _at_rule_body(prelude: str) -> str:
    """Body of the first at-rule whose prelude matches, braces balanced."""
    start = CSS.index(prelude)
    i = CSS.index("{", start) + 1
    depth = 1
    j = i
    while depth:
        depth += {"{": 1, "}": -1}.get(CSS[j], 0)
        j += 1
    return CSS[i : j - 1]


def _own_rule(body: str, selector: str) -> str:
    """Declarations of the rule whose whole selector is `selector`, not a list containing it."""
    m = re.search(r"(?:^|[{};]|\*/)\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", body)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_scrollbar_thumb_clears_3_to_1_in_every_look_and_theme():
    m = re.search(r"--scrollbar-thumb:\s*color-mix\(in srgb, var\(--accent\) (\d+)%, var\(--bg\)\);", CSS)
    assert m, "--scrollbar-thumb must be the look's accent mixed into --bg"
    assert re.search(r"--scrollbar-thumb-hover:\s*var\(--accent\);", CSS)
    pct = int(m.group(1))
    failures = []
    for label, tokens in _all_token_blocks():
        for state, thumb in (("rest", _mix(tokens["--accent"], tokens["--bg"], pct)), ("hover", tokens["--accent"])):
            for ground in ("--bg", "--surface"):
                ratio = _wcag_contrast(thumb, tokens[ground])
                if ratio < 3.0:
                    failures.append(f"{label} {state} thumb {thumb} on {ground}: {ratio:.2f}")
    assert not failures, "scrollbar thumb below 3:1: " + "; ".join(failures)


def test_scrollbar_is_drawn_without_arrows_on_a_clear_track():
    assert "display: none" in _own_rule(CSS, "::-webkit-scrollbar-button"), "no arrow buttons"
    assert "background: transparent" in _own_rule(CSS, "::-webkit-scrollbar-track,\n::-webkit-scrollbar-corner")
    thumb = _own_rule(CSS, "::-webkit-scrollbar-thumb")
    for decl in ("var(--scrollbar-thumb)", "var(--radius-full)", "background-clip: padding-box"):
        assert decl in thumb


def test_scrollbar_color_is_only_the_firefox_fallback():
    """Once scrollbar-color is set, Chromium ignores ::-webkit-scrollbar and draws its stock bar."""
    fallback = _at_rule_body("@supports not selector(::-webkit-scrollbar)")
    assert "scrollbar-color: var(--scrollbar-thumb) transparent" in fallback
    outside = CSS.replace(fallback, "")
    assert "scrollbar-color" not in re.sub(r"/\*.*?\*/", "", outside, flags=re.S)


def test_dropdown_list_is_drawn_from_theme_tokens():
    body = _at_rule_body("@supports (appearance: base-select) and selector(::picker(select))")
    assert re.search(rf"{re.escape(LIST_SELECT)},\s*{re.escape(LIST_SELECT)}::picker\(select\)\s*\{{\s*appearance: base-select;", body)
    picker = _own_rule(body, f"{LIST_SELECT}::picker(select)")
    for token in ("var(--surface)", "var(--rule)", "var(--radius-md)", "var(--elev-2)", "var(--text)"):
        assert token in picker, f"open list must use {token}"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", body), "the themed list must not hard-code colours"


def test_option_states_stay_legible_in_every_look():
    body = _at_rule_body("@supports (appearance: base-select) and selector(::picker(select))")
    hover = _rule_body(body, f"{LIST_SELECT} option:hover,")
    tint = int(re.search(r"color-mix\(in srgb, var\(--accent\) (\d+)%, var\(--surface\)\)", hover).group(1))
    checked = _own_rule(body, f"{LIST_SELECT} option:checked")
    assert "color:" not in checked, "the chosen option keeps --text; accent text fails on the hover tint"
    assert "var(--accent)" in _own_rule(body, f"{LIST_SELECT} option::checkmark")
    failures = []
    for label, tokens in _all_token_blocks():
        for ground_label, ground in (("surface", tokens["--surface"]), ("hover", _mix(tokens["--accent"], tokens["--surface"], tint))):
            if _wcag_contrast(tokens["--text"], ground) < 4.5:
                failures.append(f"{label} text on {ground_label}")
            if _wcag_contrast(tokens["--accent"], ground) < 3.0:
                failures.append(f"{label} checkmark on {ground_label}")
    assert not failures, "; ".join(failures)


def test_os_list_colours_apply_only_without_base_select():
    fallback = _at_rule_body("@supports not ((appearance: base-select) and selector(::picker(select)))")
    option_rule = re.compile(r"select option,\s*\.nav-library-select option\s*\{[^}]*#fdfbf5")
    assert option_rule.search(fallback)
    outside = CSS.replace(fallback, "")
    assert not option_rule.search(outside), "the light OS-list option colours must not reach the themed list"


def test_dropdown_motion_honours_reduced_motion():
    body = _at_rule_body("@supports (appearance: base-select) and selector(::picker(select))")
    reduced = _at_rule_body("@media (prefers-reduced-motion: reduce) {\n        select")
    assert reduced in body
    assert "transition: none" in reduced


def test_dropdown_button_centres_its_label_and_arrow():
    """Phones give the switcher a 44px touch target; stretched items put the text at the top."""
    body = _at_rule_body("@supports (appearance: base-select) and selector(::picker(select))")
    assert "align-items: center" in _own_rule(body, LIST_SELECT)


# --- Form controls drawn in the look (slice 2) --------------------------------


def _hex6(value: str) -> str:
    value = value.strip()
    return "#" + "".join(c * 2 for c in value[1:]) if len(value) == 4 else value


def _blocks6() -> list[tuple[str, dict[str, str]]]:
    return [(label, {k: _hex6(v) if v.startswith("#") else v for k, v in t.items()})
            for label, t in _all_token_blocks()]


def test_checkbox_and_radio_are_drawn_and_legible_in_every_look():
    base = _own_rule(CSS, 'input[type="checkbox"],\ninput[type="radio"]')
    assert "appearance: none" in base
    border = re.search(r"border: 2px solid color-mix\(in srgb, var\(--text\) (\d+)%, var\(--bg\)\)", base)
    assert border, "the unchecked box border must be a --text/--bg mix"
    pct = int(border.group(1))
    assert "background: var(--accent)" in _own_rule(CSS, 'input[type="checkbox"]:checked')
    assert "background: var(--on-accent)" in _own_rule(CSS, 'input[type="checkbox"]::before')
    assert "background: var(--accent)" in _own_rule(CSS, 'input[type="radio"]::before')
    failures = []
    for label, t in _blocks6():
        edge = _mix(t["--text"], t["--bg"], pct)
        for ground in ("--bg", "--surface"):
            if _wcag_contrast(edge, t[ground]) < 3.0:
                failures.append(f"{label} border on {ground}")
            if _wcag_contrast(t["--accent"], t[ground]) < 3.0:
                failures.append(f"{label} checked fill on {ground}")
        if _wcag_contrast(t["--on-accent"], t["--accent"]) < 3.0:
            failures.append(f"{label} tick on accent")
    assert not failures, "; ".join(failures)


def test_high_contrast_modes_get_native_controls_back():
    forced = _at_rule_body("@media (forced-colors: active)")
    assert "appearance: auto" in forced
    assert "display: none" in forced


def test_selected_text_stays_readable_in_every_look():
    rule = _own_rule(CSS, "::selection")
    tint = re.search(r"background: color-mix\(in srgb, var\(--accent\) (\d+)%, var\(--bg\)\)", rule)
    assert tint and "color: var(--text)" in rule, "selection must be an accent tint behind the normal text colour"
    pct = int(tint.group(1))
    failures = []
    for label, t in _blocks6():
        ground = _mix(t["--accent"], t["--bg"], pct)
        if _wcag_contrast(t["--text"], ground) < 4.5:
            failures.append(f"{label} text {_wcag_contrast(t['--text'], ground):.2f}")
        if _wcag_contrast(ground, t["--bg"]) < 1.3:
            failures.append(f"{label} tint too close to the page")
    assert not failures, "; ".join(failures)


def test_placeholder_number_autofill_and_tap_flash_are_the_looks_own():
    placeholder = _own_rule(CSS, "::placeholder")
    assert "color: var(--text-soft)" in placeholder and "opacity: 1" in placeholder
    assert "appearance: textfield" in _own_rule(CSS, 'input[type="number"]')
    assert "-webkit-appearance: none" in _own_rule(
        CSS, 'input[type="number"]::-webkit-inner-spin-button,\ninput[type="number"]::-webkit-outer-spin-button')
    for sel in ("input:-webkit-autofill", "input:autofill"):
        assert "inset 0 0 0 100vmax var(--surface)" in _own_rule(CSS, sel), sel
    assert re.search(r"html \{\s*-webkit-tap-highlight-color: transparent;", CSS)


def test_glossary_disclosure_has_no_browser_triangle():
    summary = _own_rule(CSS, ".reader-glossary > summary")
    assert "list-style: none" in summary and "display: flex" in summary
    assert "display: none" in _own_rule(CSS, ".reader-glossary > summary::-webkit-details-marker")
    assert ".reader-glossary > summary::before" in CSS


def test_press_down_elements_keep_their_top_edge_clickable():
    """Anything that moves on :active loses clicks in its top edge unless a strip covers it."""
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    moving = set()
    for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        if "translateY(" in decls:
            for one in sel.split(","):
                one = one.strip()
                if one.endswith(":active") or one.endswith(":active:not(:disabled)"):
                    moving.add(one)
    assert moving, "expected press-down rules"
    strips = [sel for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body)
              if "bottom: 100%" in decls and "content:" in decls]
    covered = {s.strip() for sel in strips for s in sel.split(",")}
    missing = sorted(m for m in moving if f"{m}::after" not in covered)
    assert not missing, "press-down without an edge strip: " + ", ".join(missing)
