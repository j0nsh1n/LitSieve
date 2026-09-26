from __future__ import annotations

import re
from pathlib import Path

from test_themed_controls import _blocks6
from test_ui_tokens import _wcag_contrast

REPO = Path(__file__).resolve().parents[1]
CSS = (REPO / "static" / "css" / "style.css").read_text(encoding="utf-8")
JS = (REPO / "static" / "js" / "form-validation.js").read_text(encoding="utf-8")
PAGES = ("login.html", "register.html", "reset_password.html")


def test_every_auth_form_suppresses_browser_bubbles_and_loads_the_shared_script():
    for page in PAGES:
        html = (REPO / "templates" / page).read_text(encoding="utf-8")
        forms = re.findall(r"<form\b[^>]*class=\"auth-form[^\"]*\"[^>]*>", html)
        assert forms, page
        assert all(" novalidate" in form for form in forms), page
        assert len(re.findall(r'<script src="/static/js/form-validation\.js\?v=[0-9a-z]+" defer></script>', html)) == 1, page
        assert 'name="username"' in html and " required" in html, page
    register = (REPO / "templates" / "register.html").read_text(encoding="utf-8")
    reset = (REPO / "templates" / "reset_password.html").read_text(encoding="utf-8")
    assert 'minlength="3"' in register
    assert 'minlength="8"' in register and 'minlength="8"' in reset


def test_shared_validation_uses_browser_constraints_and_field_messages():
    assert "input.checkValidity()" in JS
    assert "input.validity" in JS
    assert "validity.valueMissing" in JS and "validity.tooShort" in JS
    assert "validity.typeMismatch" in JS and "validity.patternMismatch" in JS
    assert "if (input.type === 'email') return 'Enter your email address'" in JS
    assert "confirmation.setCustomValidity('The two passwords do not match')" in JS
    assert "event.preventDefault()" in JS and "firstInvalid.focus()" in JS
    assert "input.addEventListener('input'" in JS
    assert "aria-invalid" in JS and "aria-describedby" in JS
    assert "message.textContent = wordsFor(input)" in JS
    assert "clearError(input)" in JS


def test_field_messages_inherit_auth_error_and_use_look_tokens():
    error = re.search(r"\.auth-error \{([^}]*)\}", CSS).group(1)
    field = re.search(r"\.auth-error\.auth-field-error \{([^}]*)\}", CSS).group(1)
    invalid = re.search(r'\.auth-form input\[aria-invalid="true"\] \{([^}]*)\}', CSS).group(1)
    assert "color: var(--err)" in error and "border: 1px solid var(--err)" in error
    assert "var(--space-2)" in field and "margin-bottom: 0" in field
    assert "border-color: var(--err)" in invalid
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", field + invalid)
    assert "message.textContent" in JS, "forced-colors still has text, not a colour-only signal"


def test_error_text_clears_4_5_to_1_in_all_14_look_theme_blocks():
    assert "color: var(--err)" in re.search(r"\.auth-error \{([^}]*)\}", CSS).group(1)
    failures = []
    for label, tokens in _blocks6():
        for ground in ("--surface", "--bg"):
            contrast = _wcag_contrast(tokens["--err"], tokens[ground])
            if contrast < 4.5:
                failures.append(f"{label} error text on {ground}: {contrast:.2f}")
    assert not failures, "; ".join(failures)
