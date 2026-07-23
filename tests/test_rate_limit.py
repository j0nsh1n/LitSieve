"""Unit tests for per-user rate-limit key selection."""

from starlette.requests import Request

from app import auth
from app.core import rate_limit_key


def _make_request(cookies: dict | None = None, client_host: str = "203.0.113.10") -> Request:
    headers = []
    if cookies:
        cookie_val = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers.append((b"cookie", cookie_val.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 54321),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_rate_limit_key_anonymous_uses_ip():
    req = _make_request(cookies=None, client_host="198.51.100.7")
    assert rate_limit_key(req) == "198.51.100.7"


def test_rate_limit_key_authenticated_uses_user_id():
    uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    token = auth.create_token(uid, "alice")
    req = _make_request(cookies={"access_token": token}, client_host="198.51.100.7")
    assert rate_limit_key(req) == f"user:{uid}"
