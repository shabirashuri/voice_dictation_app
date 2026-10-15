"""Password hashing (bcrypt) and JWT access tokens (HS256)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

ALGORITHM = "HS256"


class AuthConfigError(RuntimeError):
    """JWT_SECRET is missing or too weak."""


def _secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise AuthConfigError("JWT_SECRET must be set to at least 32 characters")
    return secret


def _expire_minutes() -> int:
    try:
        return int(os.environ.get("JWT_EXPIRE_MINUTES", "720"))
    except ValueError:
        return 720


def _bcrypt_rounds() -> int:
    """Work factor; 12 by default. Tests lower it via BCRYPT_ROUNDS."""
    try:
        return min(max(int(os.environ.get("BCRYPT_ROUNDS", "12")), 4), 16)
    except ValueError:
        return 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(_bcrypt_rounds())).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


# Used to keep login timing similar whether or not the email exists.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode("ascii")


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(user_id: int) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    minutes = _expire_minutes()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=minutes)}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM), minutes * 60


def decode_access_token(token: str) -> int | None:
    """Return the user id for a valid, unexpired token, else None."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
        return int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        return None
