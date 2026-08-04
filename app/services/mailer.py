"""Optional outbound email (verification links, password resets).

Deliberately provider-agnostic: any SMTP service works (Resend, Brevo, Mailgun,
SES, a school relay, a Gmail app password). Configure with

    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM
    SMTP_STARTTLS (default true), SMTP_SSL (default false)
    PUBLIC_BASE_URL   e.g. https://your-app.example  (for links in emails)

**When SMTP_HOST is unset the whole feature is off**: `is_configured()` returns
False, the Account UI hides the recovery-email section, and password reset keeps
its existing on-screen-code behaviour. Nothing here should ever be a hard
dependency — the app must run fine with no mail server, which is the default.

Sending is blocking (smtplib), so callers must use `run_in_thread`.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class MailError(RuntimeError):
    """Sending failed. Message is safe to log, not to show verbatim to users."""


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _flag(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in ("1", "true", "yes", "on")


def is_configured() -> bool:
    """True when enough SMTP settings exist to attempt a send."""
    return bool(_env("SMTP_HOST") and from_address())


def from_address() -> str:
    """Envelope/from address; falls back to SMTP_USER when FROM is unset."""
    return _env("SMTP_FROM") or _env("SMTP_USER")


def public_base_url() -> str:
    """Base URL used to build links in emails (no trailing slash)."""
    return _env("PUBLIC_BASE_URL", "http://localhost:7860").rstrip("/")


def status() -> dict:
    """Non-secret summary for the UI / diagnostics."""
    return {
        "configured": is_configured(),
        "host": _env("SMTP_HOST"),
        "from": from_address(),
        "base_url": public_base_url(),
    }


def send(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises MailError on any failure.

    Blocking: call via `run_in_thread` from a request handler.
    """
    if not is_configured():
        raise MailError("SMTP is not configured (set SMTP_HOST and SMTP_FROM).")

    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT", "587") or 587)
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    use_ssl = _flag("SMTP_SSL", False)
    use_starttls = _flag("SMTP_STARTTLS", not use_ssl)

    message = EmailMessage()
    message["From"] = from_address()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=DEFAULT_TIMEOUT, context=context) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=DEFAULT_TIMEOUT) as smtp:
                if use_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if user:
                    smtp.login(user, password)
                smtp.send_message(message)
    except Exception as exc:
        # Never leak the recipient or SMTP credentials into a user-facing error.
        logger.warning("SMTP send failed via %s:%s — %s", host, port, exc)
        raise MailError(f"Could not send email: {exc}") from exc


def send_verification(to: str, username: str, token: str) -> None:
    link = f"{public_base_url()}/verify-email?token={token}"
    send(
        to,
        "Confirm your email — LitSieve",
        (
            f"Hi {username},\n\n"
            "Confirm this address so it can be used to reset your password:\n\n"
            f"{link}\n\n"
            "The link expires in 1 hour and can be used once.\n"
            "If you did not add this address, you can ignore this email — "
            "nothing changes until the link is used.\n"
        ),
    )


def send_password_reset(to: str, username: str, code: str) -> None:
    link = f"{public_base_url()}/reset-password"
    send(
        to,
        "Password reset code — LitSieve",
        (
            f"Hi {username},\n\n"
            f"Your one-time password reset code is:\n\n    {code}\n\n"
            f"Enter it at {link} together with your new password.\n"
            "The code expires in 1 hour and can be used once.\n"
            "If you did not request this, you can ignore this email — your "
            "password has not changed.\n"
        ),
    )
