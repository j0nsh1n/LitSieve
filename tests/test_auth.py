from datetime import datetime, timedelta, timezone

import jwt

from app import auth


def test_hash_and_verify_roundtrip():
    hashed = auth.hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert auth.verify_password("correct horse battery staple", hashed) is True
    assert auth.verify_password("wrong password", hashed) is False


def test_create_and_decode_token_roundtrip():
    token = auth.create_token("user-123", "alice")
    payload = auth.decode_token(token)
    assert payload is not None
    assert payload["user_id"] == "user-123"
    assert payload["username"] == "alice"


def test_expired_token_is_rejected():
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    payload = {"user_id": "u", "username": "bob", "exp": expired}
    token = jwt.encode(payload, auth._SECRET_KEY, algorithm=auth.ALGORITHM)
    assert auth.decode_token(token) is None


def test_create_token_includes_token_version():
    token = auth.create_token("user-123", "alice", token_version=3)
    payload = auth.decode_token(token)
    assert payload is not None
    assert payload["tv"] == 3
    assert payload["user_id"] == "user-123"
