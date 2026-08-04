#!/usr/bin/env python3
"""Check SMTP settings and send one test email.

Run this after filling the SMTP_* values in .env, before relying on account
recovery:

    ./venv/bin/python tools/send_test_email.py you@example.com

It reports what is configured (never printing the password), then sends a
single plain-text message and explains the common failures in plain language
instead of raising a bare SMTP traceback.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.services import mailer  # noqa: E402


def _mask(value: str) -> str:
    if not value:
        return "(not set)"
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}…{value[-2:]} ({len(value)} chars)"


def explain(exc: Exception) -> str:
    """Map the usual SMTP failures to something actionable."""
    text = str(exc).lower()
    if "authentication" in text or "535" in text or "credentials" in text:
        return (
            "Authentication failed. For Brevo, SMTP_USER is the login shown on\n"
            "  SMTP & API → SMTP, and SMTP_PASSWORD is an *SMTP key* generated\n"
            "  there — not your Brevo account password."
        )
    if "sender" in text or "from" in text or "not verified" in text or "550" in text:
        return (
            "The From address was rejected. Verify SMTP_FROM in Brevo under\n"
            "  Senders, Domains & Dedicated IPs → Senders (you confirm it with a\n"
            "  6-digit code), then use exactly that address."
        )
    if "timed out" in text or "timeout" in text or "connection" in text:
        return (
            "Could not reach the server. Check SMTP_HOST/SMTP_PORT and that\n"
            "  outbound port 587 is not blocked on this network."
        )
    if "starttls" in text or "ssl" in text or "tls" in text:
        return (
            "TLS negotiation failed. Port 587 wants SMTP_STARTTLS=true and\n"
            "  SMTP_SSL=false; port 465 wants the opposite."
        )
    return "Unexpected error — the raw message above is the best clue."


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    recipient = sys.argv[1].strip()

    import os

    print("SMTP configuration")
    print(f"  host        : {os.getenv('SMTP_HOST') or '(not set)'}")
    print(f"  port        : {os.getenv('SMTP_PORT') or '587 (default)'}")
    print(f"  starttls    : {os.getenv('SMTP_STARTTLS') or 'true (default)'}")
    print(f"  ssl         : {os.getenv('SMTP_SSL') or 'false (default)'}")
    print(f"  user        : {os.getenv('SMTP_USER') or '(not set)'}")
    print(f"  password    : {_mask(os.getenv('SMTP_PASSWORD') or '')}")
    print(f"  from        : {mailer.from_address() or '(not set)'}")
    print(f"  base url    : {mailer.public_base_url()}")
    print()

    if not mailer.is_configured():
        print("Not configured: SMTP_HOST and SMTP_FROM are both required.")
        print("The app runs fine like this — the recovery-email section just")
        print("stays switched off and password reset shows a code on screen.")
        return 1

    print(f"Sending a test message to {recipient} …")
    try:
        mailer.send(
            recipient,
            "Test — LitSieve",
            "If you can read this, SMTP is working.\n\n"
            "Account recovery emails (verification links and password reset "
            "codes) will send from this address.\n",
        )
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic tool
        print(f"\nFAILED: {exc}\n")
        print(explain(exc))
        return 1

    print("\nSent. Check the inbox (and the spam folder).")
    print(
        "If it landed in spam: that is expected without domain authentication.\n"
        "Gmail/Yahoo/Microsoft want SPF+DKIM on your own domain — add and verify\n"
        "one in Brevo when you want reliable delivery to students."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
