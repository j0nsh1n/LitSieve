"""HTTP security headers.

The app already sets HttpOnly/Secure/SameSite auth cookies and relies on the
host (Render / HF Spaces) for TLS. These headers close the remaining gaps:
they stop a browser from silently downgrading to plain HTTP, from guessing
content types, and from letting a hostile page frame the app.
"""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware

# One year, and eligible for browser preload lists.
HSTS_VALUE = "max-age=31536000; includeSubDomains"

# Inline <script> blocks (the pre-paint theme switch in base.html) and 36
# inline style="" attributes across the templates mean 'unsafe-inline' is
# required for now. The policy is still worth having: it blocks script from
# any *external* origin, which is the injection path that actually matters.
# Tightening this further means moving those inline blocks into files or
# adding per-request nonces.
CSP_VALUE = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    # Outbound API calls are made server-side, so the browser never needs to
    # reach a third party directly.
    "connect-src 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "object-src 'none'",
])

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": CSP_VALUE,
}


def https_enforced() -> bool:
    """True when the app expects to be served over HTTPS.

    Mirrors the auth-cookie rule: DEBUG means local http://localhost, where
    sending HSTS would pin the browser to HTTPS for a year and make the dev
    server unreachable — a genuinely painful thing to undo per-browser.
    """
    return os.getenv("DEBUG", "").strip().lower() not in ("1", "true", "yes")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for header, value in BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        if https_enforced():
            response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response
