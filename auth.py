"""
Authentication helpers
JWT token creation/verification and bcrypt password hashing.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from dotenv import load_dotenv
from fastapi import Request
from jwt import InvalidTokenError
from passlib.context import CryptContext

load_dotenv()

# Login id: short handle OR email-style. Stored lowercased; not used in file paths
# (per-user data is keyed by UUID). Digits 0-9 allowed; null/control chars are not.
_LOGIN_ALLOWED = re.compile(r"^[a-z0-9._+\-@]+$")
_LOGIN_HAS_ALNUM = re.compile(r"[a-z0-9]")
LOGIN_MIN_LEN = 3
LOGIN_MAX_LEN = 64


def validate_login_name(raw: str) -> Optional[str]:
    """Validate a username or email-style login.

    Returns an error message, or None if the value is acceptable.
    Caller should still .strip().lower() before storage (this function does not
    mutate the input).
    """
    if raw is None:
        return "Login is required."
    # Reject embedded control characters (including null bytes) before other checks.
    if any(ord(c) < 32 for c in raw):
        return "Login contains invalid characters."
    u = raw.strip().lower()
    if len(u) < LOGIN_MIN_LEN or len(u) > LOGIN_MAX_LEN:
        return f"Login must be {LOGIN_MIN_LEN}-{LOGIN_MAX_LEN} characters."
    if not _LOGIN_ALLOWED.fullmatch(u):
        return "Use letters, numbers, and . _ + - @ only (email-style logins OK)."
    if not _LOGIN_HAS_ALNUM.search(u):
        return "Login must include at least one letter or number."
    if u.count("@") > 1:
        return "Login can contain at most one @."
    if "@" in u:
        local, _, domain = u.partition("@")
        if not local or not domain:
            return "That doesn’t look like a valid email address."
        if domain.startswith(".") or domain.endswith(".") or ".." in domain:
            return "That doesn’t look like a valid email address."
        if "." not in domain:
            return "Email domain should include a dot (e.g. school.edu)."
        if local.startswith(".") or local.endswith(".") or ".." in local:
            return "That doesn’t look like a valid email address."
    return None


_SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
_DEBUG = os.getenv("DEBUG", "").strip().lower() in ("1", "true", "yes")

if not _SECRET_KEY:
    if _DEBUG:
        # Allow imports/tests in debug mode; tokens cannot be created without a key.
        print("⚠️ SECRET_KEY is not set (DEBUG mode). Tokens cannot be created.")
    else:
        raise RuntimeError(
            "SECRET_KEY is not configured. Set SECRET_KEY in the environment "
            "(or .env), or set DEBUG=true for local development."
        )

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str, username: str, token_version: int = 0) -> str:
    if not _SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured. Cannot create JWT tokens.")
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    payload = {
        "user_id": user_id,
        "username": username,
        "tv": int(token_version or 0),
        "exp": expire,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    if not _SECRET_KEY:
        return None
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[ALGORITHM])
    except InvalidTokenError:
        return None


def get_current_user(request: Request) -> Optional[dict]:
    """Read the JWT cookie and return the decoded payload, or None."""
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)