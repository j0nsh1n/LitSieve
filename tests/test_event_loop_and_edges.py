"""Fixes driven by real traffic on the public (cloudflared) deployment.

1. Password hashing must not run on the event loop. One uvicorn worker means one
   loop, so ~157 ms of bcrypt inside an `async def` froze *every* concurrent
   request. Measured before the fix: 6 concurrent signups took 942 ms (fully
   serialised) and a bystander's `GET /` went from 1.6 ms to 933 ms. A user
   reported this as the site "hanging for a moment".
2. IPv6 rate limiting must key on the /64 prefix. A single client is handed a
   whole /64, so per-address keying makes the login limiter bypassable.
3. /favicon.ico and /robots.txt must exist (both were logging 404s).
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import re

from conftest import TEST_PASSWORD

os.environ.setdefault("SECRET_KEY", "pytest-only-not-a-secret-32b-min!!")
os.environ["DEBUG"] = "true"

import pytest

for _dep in ("fastapi", "httpx", "jwt", "bcrypt", "multipart", "dotenv"):
    pytest.importorskip(_dep)

from fastapi.testclient import TestClient

from app.auth import hash_password_async, verify_password_async

# --- 1. Hashing off the event loop -----------------------------------------

def test_async_wrappers_match_sync_behaviour():
    async def go():
        h = await hash_password_async(TEST_PASSWORD)
        assert await verify_password_async(TEST_PASSWORD, h) is True
        assert await verify_password_async("wrong-password", h) is False
        # Malformed hashes must still return False rather than raise.
        assert await verify_password_async("x", "not-a-hash") is False
    asyncio.run(go())


def test_hashing_does_not_block_the_event_loop():
    """The loop must keep serving while a password is hashed.

    Counts timer ticks during a hash. Sync bcrypt pins the loop for its whole
    duration, so the tick count collapses toward zero.
    """
    async def go():
        ticks = 0
        stop = asyncio.Event()

        async def ticker():
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.001)

        t = asyncio.create_task(ticker())
        await asyncio.sleep(0.02)          # let the ticker spin up
        ticks = 0                          # measure only during the hash
        await hash_password_async(TEST_PASSWORD)
        stop.set()
        await t
        return ticks

    ticks = asyncio.run(go())
    # bcrypt at cost 12 is ~150 ms; even a slow runner should manage many ticks.
    assert ticks > 10, f"event loop appears blocked during hashing (ticks={ticks})"


def test_routes_do_not_call_bcrypt_synchronously():
    """Guardrail: a new sync call site would silently reintroduce the stall."""
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "app" / "routes" / "auth.py").read_text()
    bad = re.findall(r"(?<!await )(?<!_)\b(hash_password|verify_password)\(", src)
    assert not bad, f"sync bcrypt call(s) in routes/auth.py: {bad}"


# --- 2. IPv6 rate-limit bucketing ------------------------------------------

@pytest.mark.parametrize("addr, expected", [
    ("203.0.113.7", "203.0.113.7"),                    # IPv4 unchanged
    ("127.0.0.1", "127.0.0.1"),
    ("2a03:2880:18ff:1b::", "2a03:2880:18ff:1b::/64"),
    ("2a03:2880:18ff:1b::5", "2a03:2880:18ff:1b::/64"),  # same /64 -> same bucket
    ("2607:fb91:8887:c6e0:5814:429a:92c0:43d5", "2607:fb91:8887:c6e0::/64"),
    ("not-an-ip", "not-an-ip"),                        # unparseable passes through
])
def test_client_bucket(addr, expected, monkeypatch):
    from app import core
    monkeypatch.setattr(core, "get_remote_address", lambda request: addr)
    assert core.client_bucket(object()) == expected


def test_rotating_ipv6_addresses_share_one_bucket(monkeypatch):
    """The whole point: an attacker rotating within their /64 cannot get a fresh
    rate-limit budget per request."""
    from app import core
    seen = set()
    for i in range(50):
        monkeypatch.setattr(
            core, "get_remote_address", lambda request, i=i: f"2001:db8:abcd:1234::{i:x}",
        )
        seen.add(core.client_bucket(object()))
    assert seen == {"2001:db8:abcd:1234::/64"}


def test_distinct_ipv6_prefixes_stay_separate(monkeypatch):
    """Must not over-collapse: different networks keep independent budgets."""
    from app import core
    buckets = set()
    for prefix in ("2001:db8:1:1::1", "2001:db8:1:2::1", "2001:db8:2:1::1"):
        monkeypatch.setattr(core, "get_remote_address", lambda request, p=prefix: p)
        buckets.add(core.client_bucket(object()))
    assert len(buckets) == 3


def test_authenticated_users_still_get_their_own_bucket(monkeypatch):
    """Signed-in users must not share a bucket with everyone behind the NAT."""
    from app import core
    monkeypatch.setattr(core, "get_remote_address", lambda request: "2001:db8::1")
    monkeypatch.setattr(core, "get_current_user", lambda request: {"user_id": "u-123"})
    assert core.rate_limit_key(object()) == "user:u-123"


# --- 3. Root-level files ---------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    import shutil
    repo = pathlib.Path(__file__).resolve().parent.parent
    shutil.copytree(repo / "templates", tmp_path / "templates")
    shutil.copytree(repo / "static", tmp_path / "static")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("USER_DATA_DIR", str(tmp_path / "user_data"))
    import importlib
    main = importlib.import_module("app.main")
    return TestClient(main.app)


def test_favicon_is_served(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"\x00\x00\x01\x00", "not an ICO container"
    assert len(r.content) > 100


def test_robots_txt_is_served(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "User-agent: *" in body
    # Auth and API surfaces stay out of search results.
    for path in ("/api/", "/reset-password", "/join", "/account"):
        assert f"Disallow: {path}" in body


def test_public_pages_declare_a_favicon(client):
    """Without a <link>, browsers guess /favicon.ico — which is what 404'd."""
    for path in ("/", "/login", "/register"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'rel="icon"' in r.text, f"{path} has no favicon link"
