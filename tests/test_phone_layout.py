"""Phone layout contracts (Phase 15).

These read the stylesheet and templates the way the earlier layout tests do.
The measured proof lives in design_mockups/ui3/capture/phonecheck.mjs, which
drives the real pages at 390 px; these tests keep the rules that run from
being deleted or scoped away by accident.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
PHONE = CSS[CSS.index("/* === Phones (Phase 15)") :]


def _block(text: str, query: str) -> str:
    """Body of the first @media block with this query inside `text`."""
    start = text.index(f"@media ({query})")
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : i]
    raise AssertionError("unbalanced block")


def test_phone_search_bar_is_one_row_with_an_icon_button():
    html = (REPO / "templates" / "search.html").read_text(encoding="utf-8")
    btn = html[html.index('<button id="search-btn"') : html.index("</button>", html.index('<button id="search-btn"'))]
    assert 'aria-label="Search"' in btn
    assert 'class="search-btn-label"' in btn
    assert 'class="search-btn-icon"' in btn
    phone = _block(PHONE, "max-width: 640px")
    card = re.search(r'html\[data-mode="simple"\] \.searchcard \{([^}]+)\}', phone)
    assert card and "flex-direction: row" in card.group(1)
    assert "html[data-mode=\"simple\"] .searchcard .search-btn-label { display: none; }" in phone
    btn_rule = re.search(r'html\[data-mode="simple"\] \.searchcard #search-btn \{([^}]+)\}', phone)
    assert btn_rule and "min-width: 2.75rem" in btn_rule.group(1)


def test_phone_query_bar_sticks_once_results_exist():
    phone = _block(PHONE, "max-width: 640px")
    rule = re.search(r'html\[data-mode="simple"\] body\.simple-screen-ready #search-query-top \{([^}]+)\}', phone)
    assert rule, "sticky query bar rule missing"
    assert "position: sticky" in rule.group(1)
    assert "z-index: 30" in rule.group(1)
    assert "top: var(--nav-h" in rule.group(1)
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "setProperty('--nav-h', nav.offsetHeight + 'px')" in common


def test_phone_compact_rows_have_thumb_sized_open_button():
    phone = _block(PHONE, "max-width: 640px")
    toggle = re.search(r'html\[data-mode="simple"\] \.result-toggle \{([^}]+)\}', phone)
    assert toggle and "min-height: 2.75rem" in toggle.group(1) and "min-width: 2.75rem" in toggle.group(1)
    assert 'html[data-mode="simple"] .result-row:not(.is-open) .result-tags { display: none; }' in phone
    venue = re.search(r'html\[data-mode="simple"\] \.result-row:not\(\.is-open\) \.result-venue \{([^}]+)\}', phone)
    assert venue and "text-overflow: ellipsis" in venue.group(1)


def test_phone_tools_strip_stays_on_one_row():
    phone = _block(PHONE, "max-width: 640px")
    strip = re.search(r'html\[data-mode="simple"\] \.simple-tools-strip,\s*html\[data-mode="simple"\] \.simple-screen-dock \{([^}]+)\}', phone)
    assert strip and "flex-wrap: nowrap" in strip.group(1)
    narrow = re.search(r'html\[data-mode="simple"\] \.simple-screen-dock #simple-screen-open-btn \{([^}]+)\}', phone)
    assert narrow and "width: auto" in narrow.group(1)


def test_phone_getting_started_folds_to_one_line():
    html = (REPO / "templates" / "partials" / "collect_ui.html").read_text(encoding="utf-8")
    assert 'class="gs-sample-ask-short">New here?</span>' in html
    assert 'class="gs-sample-note"' in html
    assert 'class="info-text gs-lead"' in html
    phone = _block(PHONE, "max-width: 640px")
    assert 'html[data-mode="simple"] #getting-started-card .gs-sample-ask-short { display: inline; }' in phone
    hidden = re.search(r'html\[data-mode="simple"\] #getting-started-card \.gs-lead,\s*html\[data-mode="simple"\] #getting-started-card \.gs-sample-ask,\s*html\[data-mode="simple"\] #getting-started-card \.gs-sample-note \{ display: none; \}', phone)
    assert hidden


def test_phone_drawer_is_a_panel_over_a_scrim_with_tall_rows():
    tablet = _block(PHONE, "max-width: 900px")
    assert "body.nav-menu-open::after" in tablet
    assert "background: var(--scrim)" in tablet
    rows = re.search(r'body\.nav-menu-open \.navbar \.nav-username,\s*body\.nav-menu-open \.navbar \.nav-logout \{([^}]+)\}', tablet)
    assert rows and "min-height: 2.75rem" in rows.group(1)
    assert ".account-sidenav::after" in tablet
    # A tap on the scrim lands on the body; the existing outside-pointerdown
    # handler must keep closing the drawer.
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    drawer = common[common.index("const drawer = document.getElementById('nav-drawer')") :]
    assert "document.addEventListener('pointerdown'" in drawer
    assert "if (nav.contains(e.target)) return;" in drawer


def test_phone_dialog_fields_stack_and_checkboxes_are_thumb_sized():
    phone = _block(PHONE, "max-width: 640px")
    assert ".lra-modal-fields { grid-template-columns: 1fr; }" in phone
    box = re.search(r'input\[type="checkbox"\] \{([^}]+)\}', PHONE)
    assert box and "width: 1.25rem" in box.group(1)


def test_set_loading_keeps_button_markup():
    """Buttons with an icon or dual-mode labels must survive a loading cycle intact."""
    common = (REPO / "static" / "js" / "common.js").read_text(encoding="utf-8")
    fn = common[common.index("function setLoading") : common.index("function setStatus")]
    assert "data-keep-content" in fn
    assert "dataset.originalHtml = buttonEl.innerHTML" in fn
    assert "buttonEl.innerHTML = buttonEl.dataset.originalHtml" in fn
    assert "dataset.originalText" not in fn
    search = (REPO / "templates" / "search.html").read_text(encoding="utf-8")
    assert '<button id="search-btn" class="btn btn-primary" aria-label="Search" data-keep-content>' in search
    collect = (REPO / "templates" / "partials" / "collect_ui.html").read_text(encoding="utf-8")
    assert 'id="fetch-btn" class="btn btn-primary" data-keep-content>' in collect
