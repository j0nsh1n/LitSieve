"""SMTP sending: transport security, credential hygiene, message contents.

`mailer.send()` was entirely untested (43% file coverage). It decides whether
credentials cross the wire under TLS, so a silent regression there would leak
the SMTP password rather than break anything visibly. Sending is exercised
against fake smtplib classes — no network, no real mailbox.
"""

from __future__ import annotations

import pytest

from app.services import mailer


class _FakeSMTP:
    """Records what a real smtplib.SMTP would have been asked to do."""

    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.started_tls = False
        self.logged_in = None
        self.sent = []
        self.quit_called = False
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.quit_called = True
        return False

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, message):
        self.sent.append(message)


class _FakeSMTPSSL(_FakeSMTP):
    instances: list = []


@pytest.fixture
def smtp(monkeypatch):
    _FakeSMTP.instances = []
    _FakeSMTPSSL.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSMTPSSL)
    return _FakeSMTP, _FakeSMTPSSL


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD",
                "SMTP_FROM", "SMTP_SSL", "SMTP_STARTTLS", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


def _configure(monkeypatch, **overrides):
    env = {
        "SMTP_HOST": "smtp.example.test",
        "SMTP_FROM": "noreply@example.test",
        "SMTP_USER": "mailuser",
        "SMTP_PASSWORD": "s3cret-password",
    }
    env.update(overrides)
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


# --- Configuration gate ----------------------------------------------------

def test_not_configured_by_default():
    assert mailer.is_configured() is False


def test_send_without_config_raises_mailerror():
    with pytest.raises(mailer.MailError):
        mailer.send("someone@example.test", "subject", "body")


def test_host_without_from_is_not_configured(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    assert mailer.is_configured() is False


def test_from_falls_back_to_user(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_USER", "mailuser@example.test")
    assert mailer.from_address() == "mailuser@example.test"
    assert mailer.is_configured() is True


# --- Transport security ----------------------------------------------------

def test_plain_port_uses_starttls_by_default(monkeypatch, smtp):
    """Default path must upgrade to TLS before login."""
    plain, ssl_cls = smtp
    _configure(monkeypatch)
    mailer.send("to@example.test", "s", "b")

    assert len(plain.instances) == 1 and not ssl_cls.instances
    conn = plain.instances[0]
    assert conn.started_tls is True, "credentials would cross the wire in clear"
    assert conn.logged_in == ("mailuser", "s3cret-password")
    assert conn.timeout == mailer.DEFAULT_TIMEOUT


def test_ssl_mode_uses_smtp_ssl_and_not_starttls(monkeypatch, smtp):
    plain, ssl_cls = smtp
    _configure(monkeypatch, SMTP_SSL="true", SMTP_PORT="465")
    mailer.send("to@example.test", "s", "b")

    assert len(ssl_cls.instances) == 1 and not plain.instances
    conn = ssl_cls.instances[0]
    assert conn.port == 465
    assert conn.started_tls is False, "STARTTLS on an implicit-TLS socket"
    assert conn.context is not None, "SMTP_SSL must use an SSL context"


def test_default_port_is_587(monkeypatch, smtp):
    plain, _ = smtp
    _configure(monkeypatch)
    mailer.send("to@example.test", "s", "b")
    assert plain.instances[0].port == 587


def test_login_skipped_when_no_user(monkeypatch, smtp):
    """Some relays accept unauthenticated local submission."""
    plain, _ = smtp
    _configure(monkeypatch, SMTP_USER=None)
    mailer.send("to@example.test", "s", "b")
    assert plain.instances[0].logged_in is None


def test_starttls_can_be_disabled_explicitly(monkeypatch, smtp):
    """Opt-out exists for local relays, but must require saying so."""
    plain, _ = smtp
    _configure(monkeypatch, SMTP_STARTTLS="false")
    mailer.send("to@example.test", "s", "b")
    assert plain.instances[0].started_tls is False


# --- Failure handling ------------------------------------------------------

def test_failure_raises_mailerror_without_the_password(monkeypatch, smtp):
    """An SMTP error must never carry the credential into logs or responses."""
    plain, _ = smtp
    _configure(monkeypatch)

    def boom(self, user, password):
        raise RuntimeError(f"535 auth failed for {user}")

    monkeypatch.setattr(_FakeSMTP, "login", boom)

    with pytest.raises(mailer.MailError) as exc:
        mailer.send("to@example.test", "s", "b")
    assert "s3cret-password" not in str(exc.value)


def test_connection_error_is_wrapped(monkeypatch, smtp):
    def refuse(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer.smtplib, "SMTP", refuse)
    _configure(monkeypatch)
    with pytest.raises(mailer.MailError):
        mailer.send("to@example.test", "s", "b")


# --- Message contents ------------------------------------------------------

def test_message_headers_and_body(monkeypatch, smtp):
    plain, _ = smtp
    _configure(monkeypatch)
    mailer.send("student@example.test", "Subject line", "Body text here")

    msg = plain.instances[0].sent[0]
    assert msg["To"] == "student@example.test"
    assert msg["From"] == "noreply@example.test"
    assert msg["Subject"] == "Subject line"
    assert "Body text here" in msg.get_content()


def test_verification_link_uses_public_base_url(monkeypatch, smtp):
    """A wrong base URL sends users to a host that cannot verify them."""
    plain, _ = smtp
    _configure(monkeypatch)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.litpilot.org/")
    mailer.send_verification("student@example.test", "studentname", "tok123")

    body = plain.instances[0].sent[0].get_content()
    assert "https://www.litpilot.org/verify-email?token=tok123" in body
    assert "https://www.litpilot.org//verify-email" not in body, "double slash"
    assert "studentname" in body


def test_password_reset_email_carries_the_code(monkeypatch, smtp):
    plain, _ = smtp
    _configure(monkeypatch)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://www.litpilot.org")
    mailer.send_password_reset("student@example.test", "studentname", "CODE-42")

    body = plain.instances[0].sent[0].get_content()
    assert "CODE-42" in body
    assert "https://www.litpilot.org/reset-password" in body
    # Users who did not ask must be told nothing has changed yet.
    assert "not changed" in body.lower()


def test_public_base_url_default_and_trailing_slash(monkeypatch):
    assert mailer.public_base_url() == "http://localhost:7860"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test/")
    assert mailer.public_base_url() == "https://example.test"


def test_status_reports_config_without_secrets(monkeypatch):
    _configure(monkeypatch)
    report = mailer.status()
    assert report["configured"] is True
    assert report["host"] == "smtp.example.test"
    assert "s3cret-password" not in str(report), "status must not expose the password"
    assert "password" not in {k.lower() for k in report}
