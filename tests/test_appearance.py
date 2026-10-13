"""Appearance settings: a look is a preset; a student's changes ride on top."""

from __future__ import annotations

import re

from conftest import TEST_PASSWORD
from test_looks import (
    CSS,
    DARK_FIRST_LOOKS,
    INIT,
    LIGHT_FIRST_LOOKS,
    REPO,
    _client,
    _csrf,
    _css_block_tokens,
    _read,
    _rule_body,
    _wcag_contrast,
)

from app.content.appearance import PRESETS, SETTINGS, cookie_value, effective, parse_overrides
from app.content.looks import LOOKS


def _allowed(key: str) -> list[str]:
    return [value for value, _ in SETTINGS[key][1]]


def _register(client, name: str) -> None:
    r = client.post(
        "/register",
        data={"username": name, "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text


def test_every_look_presets_every_setting_with_an_allowed_value():
    assert set(PRESETS) == set(LOOKS)
    for look, preset in PRESETS.items():
        assert set(preset) == set(SETTINGS), look
        for key, value in preset.items():
            assert value in _allowed(key), f"{look} {key}={value}"
    assert len({p["layout"] for p in PRESETS.values()}) == len(LOOKS), "each look brings its own layout"


def test_theme_init_mirrors_the_settings_and_presets():
    block = re.search(r"var APPEARANCE = \{(.*?)\n    \};", INIT, re.S).group(1)
    js_settings = {
        key: re.findall(r"'([a-z]+)'", values)
        for key, values in re.findall(r"(\w+): \[([^\]]*)\]", block)
    }
    assert js_settings == {key: _allowed(key) for key in SETTINGS}

    base = dict(re.findall(r"(\w+): '([a-z]+)'", re.search(r"var BASE = \{([^}]*)\}", INIT).group(1)))
    presets_src = re.search(r"var PRESETS = \{(.*?)\n    \};", INIT, re.S).group(1)
    for look, body in re.findall(r"(\w+): \{([^}]*)\}", presets_src):
        assert {**base, **dict(re.findall(r"(\w+): '([a-z]+)'", body))} == PRESETS[look], look
    assert set(re.findall(r"^\s{8}(\w+): \{", presets_src, re.M)) == set(LOOKS)


def test_only_allowed_changes_from_the_preset_are_kept():
    assert parse_overrides({"layout": "table", "text": "huge", "nope": "x", "titles": "serif"}, "workshop") == {
        "layout": "table"
    }
    assert parse_overrides('{"layout": "list"}', "lab") == {"layout": "list"}
    assert parse_overrides("not json", "lab") == {}
    assert parse_overrides(["layout", "table"], "lab") == {}
    assert effective("lab", {"density": "roomy"})["density"] == "roomy"
    assert effective("lab", {})["layout"] == "table"
    assert cookie_value({"layout": "table", "density": "compact"}) == "layout.table~density.compact"


def test_appearance_saves_to_the_account_and_a_look_starts_fresh(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    _register(client, "tuner")
    assert client.get("/api/account/appearance").json()["appearance"] == {}

    r = client.post(
        "/api/account/appearance",
        json={"appearance": {"layout": "table", "accent": "teal", "text": "gigantic"}},
        headers=_csrf(client),
    )
    assert r.status_code == 200, r.text
    assert r.json()["appearance"] == {"accent": "teal", "layout": "table"}
    assert r.json()["effective"]["corners"] == PRESETS["workshop"]["corners"]
    assert r.cookies.get("ui_appearance") in ("layout.table~accent.teal", "accent.teal~layout.table")
    assert db.get_by_username("tuner")["appearance"] == {"accent": "teal", "layout": "table"}

    look = client.post("/api/account/look", json={"look": "night"}, headers=_csrf(client))
    assert look.status_code == 200
    assert look.cookies.get("ui_appearance") in ("", '""', None)
    assert db.get_by_username("tuner")["appearance"] == {}

    # The cookie names the look the settings were stored against, read under
    # the same lock, never the look the request started with.
    db.set_look(db.get_by_username("tuner")["id"], "lab")
    after = client.post("/api/account/appearance", json={"appearance": {"density": "roomy"}}, headers=_csrf(client))
    assert after.json()["look"] == "lab"
    assert after.cookies.get("ui_look") == "lab"


def test_appearance_api_needs_an_account_and_csrf(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient

    from app.main import app

    anon = TestClient(app)
    assert anon.get("/api/account/appearance").status_code == 401
    assert anon.post("/api/account/appearance", json={"appearance": {}}).status_code in (401, 403)
    _register(client, "csrfless")
    assert client.post("/api/account/appearance", json={"appearance": {"layout": "list"}}).status_code == 403


def test_login_restores_the_saved_appearance_cookie(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    _register(client, "returner3")
    client.post("/api/account/appearance", json={"appearance": {"density": "roomy"}}, headers=_csrf(client))
    client.post("/logout", follow_redirects=False)
    client.cookies.clear()
    r = client.post("/login", data={"username": "returner3", "password": TEST_PASSWORD}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert r.cookies.get("ui_appearance") == "density.roomy"


def test_controls_render_every_option_on_account_and_search():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(REPO / "templates")), autoescape=True)
    html = env.get_template("partials/appearance_controls.html").render(appearance_settings=SETTINGS)
    for key in SETTINGS:
        if key == "panel":
            assert 'data-setting="panel"' not in html  # docking lives in the panel's header
            continue
        assert f'data-setting="{key}"' in html
        for value in _allowed(key):
            assert f'data-value="{value}"' in html
    assert "data-appearance-reset" in html
    assert 'include "partials/appearance_controls.html"' in _read("templates", "account.html")
    panel = _read("templates", "partials", "settings_panel.html")
    for value in _allowed("panel"):
        assert f'data-dock="{value}"' in panel
    # Adjust look on Search opens the account panel at its Look section.
    assert 'data-settings-open="account-look"' in _read("templates", "partials", "simple_screening_card.html")


def test_every_setting_value_has_css():
    for key in SETTINGS:
        for value in _allowed(key):
            if (key, value) in {("accent", "look"), ("text", "standard"), ("measure", "standard"), ("density", "standard"), ("panel", "right")}:
                continue  # the html defaults
            assert f'html[data-{key}="{value}"]' in CSS or f'[data-{key}="{value}"]' in CSS, f"{key}={value}"


def _look_grounds(tone: str) -> list[str]:
    needles = []
    for look in LIGHT_FIRST_LOOKS:
        needles.append(f'html[data-look="{look}"] {{' if tone == "light" else f'html[data-look="{look}"][data-theme="dark"] {{')
    for look in DARK_FIRST_LOOKS:
        needles.append(f'html[data-look="{look}"][data-theme="light"] {{' if tone == "light" else f'html[data-look="{look}"] {{')
    needles.append(":root {" if tone == "light" else '[data-theme="dark"] {')
    grounds = []
    for needle in needles:
        tokens = _css_block_tokens(_rule_body(CSS, needle))
        grounds += [tokens["--bg"], tokens["--surface"]]
    return grounds


def test_accent_swatches_read_on_every_look_in_both_tones():
    failures = []
    for value in _allowed("accent"):
        if value == "look":
            continue
        for tone in ("light", "dark"):
            tokens = _css_block_tokens(_rule_body(CSS, f'html[data-accent="{value}"][data-tone="{tone}"] {{'))
            accent, on_accent = tokens["--accent"], tokens["--on-accent"]
            for ground in _look_grounds(tone):
                if _wcag_contrast(accent, ground) < 4.5:
                    failures.append(f"{value} {tone} {accent} on {ground}")
            if _wcag_contrast(on_accent, accent) < 4.5:
                failures.append(f"{value} {tone} text {on_accent} on {accent}")
    assert not failures, failures


def test_settings_from_a_stale_tab_are_refused(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    _register(client, "twotabs")
    client.post("/api/account/look", json={"look": "night"}, headers=_csrf(client))
    stale = client.post(
        "/api/account/appearance",
        json={"appearance": {"text": "large"}, "look": "workshop"},
        headers=_csrf(client),
    )
    assert stale.status_code == 409
    assert db.get_by_username("twotabs")["appearance"] == {}
    fresh = client.post(
        "/api/account/appearance",
        json={"appearance": {"text": "large"}, "look": "night"},
        headers=_csrf(client),
    )
    assert fresh.status_code == 200
    assert fresh.json()["appearance"] == {"text": "large"}


def test_logout_hands_the_next_person_the_default_look(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    _register(client, "leaver")
    client.post("/api/account/look", json={"look": "catalog"}, headers=_csrf(client))
    out = client.get("/logout", follow_redirects=False)
    assert out.cookies.get("ui_look") == "workshop"
    assert out.cookies.get("ui_appearance") in ("", '""', None)


def test_a_guest_look_lasts_only_as_long_as_the_guest(tmp_path, monkeypatch):
    from app import core

    client, _db = _client(tmp_path, monkeypatch)
    assert client.get("/guest", follow_redirects=False).status_code in (302, 303)
    r = client.post("/api/account/appearance", json={"appearance": {"density": "roomy"}}, headers=_csrf(client))
    assert r.status_code == 200, r.text
    cookie = [h for h in r.headers.get_list("set-cookie") if h.startswith("ui_appearance=")][0]
    assert f"Max-Age={core.GUEST_MAX_AGE_MINUTES * 60}" in cookie


def test_a_new_look_keeps_where_the_panel_docks(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    _register(client, "docker")
    client.post("/api/account/appearance", json={"appearance": {"panel": "left", "text": "large"}}, headers=_csrf(client))
    r = client.post("/api/account/look", json={"look": "lab"}, headers=_csrf(client))
    assert r.status_code == 200
    assert r.json()["appearance"] == {"panel": "left"}
    assert r.cookies.get("ui_appearance") == "panel.left"
    assert db.get_by_username("docker")["appearance"] == {"panel": "left"}


def test_only_the_embedded_account_page_may_be_framed_by_litsieve(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    _register(client, "framer")
    embedded = client.get("/account?embed=1")
    assert embedded.status_code == 200
    assert embedded.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in embedded.headers["Content-Security-Policy"]
    assert 'class="navbar' not in embedded.text and 'data-embed="1"' in embedded.text
    for path in ("/account", "/search", "/login"):
        r = client.get(path)
        assert r.headers["X-Frame-Options"] == "DENY", path
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"], path


def test_every_app_page_offers_the_account_panel_but_account_itself(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    _register(client, "paneluser")
    search = client.get("/search").text
    assert 'id="settings-panel"' in search and 'class="settings-panel-frame"' in search
    assert "const ACCOUNT_EMBED = '/account?embed=1';" in _read("static", "js", "common.js")
    assert 'data-settings-open=""' in search  # the account link in the nav
    assert 'id="settings-panel"' not in client.get("/account").text
