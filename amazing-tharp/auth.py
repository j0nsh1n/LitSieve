"""
Authentication helpers
JWT token creation/verification and bcrypt password hashing.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext
from fastapi import Request

load_dotenv()

_SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not _SECRET_KEY:
    # Warn instead of raising during import so tests and utilities can import this module.
    print("⚠️ SECRET_KEY is not set. create_token will raise if called. Set SECRET_KEY in environment or .env.")

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_token(user_id: str, username: str) -> str:
    if not _SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured. Cannot create JWT tokens.")
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    payload = {"user_id": user_id, "username": username, "exp": expire}
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