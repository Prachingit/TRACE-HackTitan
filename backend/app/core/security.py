"""Security utilities for TRACE — password hashing and JWT management."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from jose import JWTError, jwt

from app.config import settings

_ph = PasswordHasher()

ALGORITHM = "HS256"
COOKIE_NAME = "trace_session"


def hash_password(plaintext: str) -> str:
    """Return an Argon2 hash of the plaintext password."""
    return _ph.hash(plaintext)


def verify_password(plaintext: str, hashed: str) -> bool:
    """Return True if plaintext matches the stored Argon2 hash."""
    try:
        return _ph.verify(hashed, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: str, expiry_days: int = 7) -> str:
    """Create a signed JWT encoding the user_id claim."""
    expire = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Decode and verify a JWT, returning the user_id or None on any failure."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
