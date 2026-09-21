"""Per-account looks: register picker, Account change, cookie + CSS skins."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from app.content.looks import DEFAULT_LOOK, LOOK_CARDS, LOOKS, normalize_look, parse_look
from app.main import app
from app.storage.user_db import UserDatabase

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
INIT = (REPO / "static" / "js" / "theme-init.js").read_text(encoding="utf-8")


_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")
_CONTRAST_INKS = ("--text", "--text-soft", "--accent", "--ok", "--warn", "--err")
_CONTRAST_GROUNDS = ("--bg", "--surface")


def _read(*parts: str) -> str:
    return REPO.joinpath(*parts).read_text(encoding="utf-8")


def _client(tmp_path, monkeypatch):
    from app import core

    db = UserDatabase(str(tmp_path / "users.db"))
    monkeypatch.setattr(core, "user_db", db)
    return TestClient(app), db


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("csrf_token") or ""}


def _css_block_tokens(block: str) -> dict[str, str]:
    return {
        m.group(1): re.sub(r"\s+", " ", m.group(2)).strip()
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)
    }


def _rule_body(css: str, needle: str) -> str:
    i = css.find(needle)
    assert i >= 0, f"missing {needle}"
    brace = css.index("{", i)
    depth = 0
    for j in range(brace, len(css)):
        if css[j] == "{":
            depth += 1
        elif css[j] == "}":
            depth -= 1
            if depth == 0:
                return css[brace + 1 : j]
    raise AssertionError(f"unbalanced {needle}")


def _srgb_channel(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    r = int(raw[0:2], 16) / 255
    g = int(raw[2:4], 16) / 255
    b = int(raw[4:6], 16) / 255
    return 0.2126 * _srgb_channel(r) + 0.7152 * _srgb_channel(g) + 0.0722 * _srgb_channel(b)


def _wcag_contrast(fg: str, bg: str) -> float:
    lighter = max(_relative_luminance(fg), _relative_luminance(bg))
    darker = min(_relative_luminance(fg), _relative_luminance(bg))
    return (lighter + 0.05) / (darker + 0.05)


def test_look_allowlist_rejects_unknown():
    assert parse_look("lab") == "lab"
    assert parse_look("LAB") == "lab"
    assert parse_look("nope") is None
    assert parse_look("") is None
    assert normalize_look("nope") == DEFAULT_LOOK
    assert LOOKS == ("workshop", "broadsheet", "lab", "night", "catalog")


def test_create_user_stores_look_and_defaults_workshop(tmp_path):
    db = UserDatabase(str(tmp_path / "users.db"))
    plain = db.create_user("plain", "hash")
    assert plain["look"] == "workshop"
    assert db.get_by_id(plain["id"])["look"] == "workshop"
    lab = db.create_user("labuser", "hash", look="lab")
    assert lab["look"] == "lab"
    assert db.get_by_username("labuser")["look"] == "lab"
    assert db.set_look(lab["id"], "catalog") == "catalog"
    assert db.get_by_id(lab["id"])["look"] == "catalog"
    assert db.set_look(lab["id"], "not-a-look") is None
    assert db.get_by_id(lab["id"])["look"] == "catalog"


def test_register_page_has_no_look_picker():
    html = TestClient(app).get("/register").text
    assert "look-picker" not in html
    assert "data-look-pick" not in html
    assert 'id="look-field"' not in html
    assert "Create Account" in html


def test_register_defaults_workshop_and_opens_look_prompt(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    r = client.post(
        "/register",
        data={
            "username": "lookstudent",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert "pickLook=1" in (r.headers.get("location") or "")
    assert r.cookies.get("ui_look") == "workshop"
    assert r.cookies.get("ui_mode_seed") == "simple"
    assert r.cookies.get("ui_look_prompt") == "1"
    row = db.get_by_username("lookstudent")
    assert row is not None
    assert row["look"] == "workshop"


def test_register_ignores_look_form_field(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    r = client.post(
        "/register",
        data={
            "username": "fallbacklook",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
            "look": "lab",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), r.text
    assert r.cookies.get("ui_look") == "workshop"
    assert db.get_by_username("fallbacklook")["look"] == "workshop"


def test_login_sets_look_cookie_from_account(tmp_path, monkeypatch):
    client, _db = _client(tmp_path, monkeypatch)
    r = client.post(
        "/register",
        data={
            "username": "returner2",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    saved = client.post(
        "/api/account/look",
        json={"look": "catalog"},
        headers=_csrf(client),
    )
    assert saved.status_code == 200, saved.text
    client.post("/logout", follow_redirects=False)
    client.cookies.clear()
    r2 = client.post(
        "/login",
        data={"username": "returner2", "password": TEST_PASSWORD},
        follow_redirects=False,
    )
    assert r2.status_code in (302, 303)
    assert "pickLook" not in (r2.headers.get("location") or "")
    assert r2.cookies.get("ui_look") == "catalog"
    assert r2.cookies.get("ui_mode_seed") in (None, "")
    assert r2.cookies.get("ui_look_prompt") in (None, "")


def test_account_look_get_and_post(tmp_path, monkeypatch):
    client, db = _client(tmp_path, monkeypatch)
    r = client.post(
        "/register",
        data={
            "username": "changer",
            "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD,
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    anon = TestClient(app)
    assert anon.get("/api/account/look").status_code == 401
    assert anon.post("/api/account/look", json={"look": "lab"}).status_code in (401, 403)
    got = client.get("/api/account/look")
    assert got.status_code == 200
    assert got.json()["look"] == "workshop"
    assert got.json()["looks"] == list(LOOKS)
    no_csrf = client.post("/api/account/look", json={"look": "night"})
    assert no_csrf.status_code == 403
    bad = client.post(
        "/api/account/look", json={"look": "neon"}, headers=_csrf(client),
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/account/look", json={"look": "night"}, headers=_csrf(client),
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["look"] == "night"
    assert ok.cookies.get("ui_look") == "night"
    assert db.get_by_username("changer")["look"] == "night"
    page = client.get("/account")
    assert page.status_code == 200
    assert 'id="account-look"' in page.text
    assert page.text.count('data-look-pick="') == 5
    assert 'data-look-pick="night"' in page.text
    assert 'aria-pressed="true"' in page.text


def test_look_picker_renders_without_app_context():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(REPO / "templates")), autoescape=True)
    html = env.get_template("partials/look_picker.html").render()
    assert html.count('data-look-pick="') == 5
    for look_id, title, blurb in LOOK_CARDS:
        assert f'data-look-pick="{look_id}"' in html
        assert title in html
        assert blurb in html
    empty = env.get_template("partials/look_picker.html").render(look_cards=())
    assert empty.count('data-look-pick="') == 5


def test_look_card_css_keeps_a_visible_hit_target():
    body = _rule_body(CSS, ".look-card {")
    assert "min-height:" in body
    assert "appearance: none" in body


def test_theme_init_applies_look_from_cookie_before_local_storage():
    assert "data-look" in INIT
    assert "ui_look" in INIT
    assert "uiLook" in INIT
    cookie_read = INIT.find("ui_look=")
    storage_read = INIT.find("getItem('uiLook')")
    assert cookie_read != -1 and storage_read != -1
    assert cookie_read < storage_read
    assert "LRA_LOOKS" in INIT
    assert "LRA_LOOK_CARDS" in INIT
    assert "window.applyUiLook" in INIT
    for look_id in LOOKS:
        assert look_id in INIT


def test_look_prompt_opens_after_register_not_login():
    common = _read("static", "js", "common.js")
    assert "function promptLookIfNeeded" in common
    assert "function lookPromptPending" in common
    assert "ui_look_prompt" in common
    assert "pickLook" in common
    prompt_fn = common.split("function promptLookIfNeeded")[1].split("// === Multi-library")[0]
    assert "look-prompt-modal" in prompt_fn
    assert "onReady:" in prompt_fn
    assert "/api/account/look" in prompt_fn
    assert "applyUiLook" in prompt_fn
    # A failed save reports its error. Nothing reads "Not Found" as success.
    save_fail = prompt_fn.split("/api/account/look")[1].split(".catch(")[1]
    assert "showNotification" in save_fail and "'error'" in save_fail
    assert "not found" not in prompt_fn.lower()
    assert "style=" not in prompt_fn
    for look_id, title, blurb in LOOK_CARDS:
        assert f"id: '{look_id}'" in INIT or f'id: "{look_id}"' in INIT
        assert title in INIT
        assert blurb in INIT


def test_account_js_saves_look_without_inline_style():
    js = _read("static", "js", "account.js")
    assert "function wireLookPicker" in js
    fn = js.split("function wireLookPicker")[1].split("async function loadLibraryManager")[0]
    assert "/api/account/look" in fn
    assert "applyUiLook" in fn
    # "Saved." only on the success path; a failed save shows its error.
    assert fn.count("'Saved.'") == 1
    assert "not found" not in fn.lower()
    assert "setAttribute('data-look'" in fn or 'setAttribute("data-look"' in fn
    assert "style=" not in fn


def test_each_look_has_light_and_dark_token_blocks():
    for look_id in ("broadsheet", "lab", "catalog"):
        light = _rule_body(CSS, f'html[data-look="{look_id}"] {{')
        dark = _rule_body(CSS, f'html[data-look="{look_id}"][data-theme="dark"] {{')
        pref = _rule_body(CSS, f'html[data-look="{look_id}"]:not([data-theme="light"]) {{')
        assert "--accent" in light and "--accent" in dark and "--accent" in pref
        light_tok = _css_block_tokens(light)
        dark_tok = _css_block_tokens(dark)
        pref_tok = _css_block_tokens(pref)
        for key in ("--bg", "--accent"):
            assert dark_tok[key] == pref_tok[key], f"{look_id} dark/prefers drifted on {key}"
            assert light_tok[key] != dark_tok[key], f"{look_id} light and dark share {key}"
    night = _rule_body(CSS, 'html[data-look="night"] {')
    night_light = _rule_body(CSS, 'html[data-look="night"][data-theme="light"] {')
    assert _css_block_tokens(night)["--bg"] != _css_block_tokens(night_light)["--bg"]


def test_look_inks_meet_wcag_aa_on_page_grounds():
    failures = []
    blocks = []
    for look_id in ("broadsheet", "lab", "catalog"):
        blocks.append((f"{look_id} light", _rule_body(CSS, f'html[data-look="{look_id}"] {{')))
        blocks.append(
            (f"{look_id} dark", _rule_body(CSS, f'html[data-look="{look_id}"][data-theme="dark"] {{'))
        )
        blocks.append(
            (
                f"{look_id} prefers-dark",
                _rule_body(CSS, f'html[data-look="{look_id}"]:not([data-theme="light"]) {{'),
            )
        )
    blocks.append(("night dark", _rule_body(CSS, 'html[data-look="night"] {')))
    blocks.append(
        ("night light", _rule_body(CSS, 'html[data-look="night"][data-theme="light"] {'))
    )
    for label, body in blocks:
        tokens = _css_block_tokens(body)
        for name in _CONTRAST_INKS:
            value = tokens.get(name, "")
            assert _HEX6.fullmatch(value), f"{label} {name} is not a 6-digit hex: {value!r}"
        for ground_name in _CONTRAST_GROUNDS:
            ground = tokens.get(ground_name, "")
            assert _HEX6.fullmatch(ground), f"{label} {ground_name} is not a 6-digit hex: {ground!r}"
            for ink_name in _CONTRAST_INKS:
                ratio = _wcag_contrast(tokens[ink_name], ground)
                if ratio < 4.5:
                    failures.append(
                        f"{label} {ink_name}={tokens[ink_name]} on {ground_name}={ground}: {ratio:.3f}"
                    )
    assert not failures, "contrast below 4.5:1: " + "; ".join(failures)
