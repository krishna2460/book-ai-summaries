"""
JWT utilities — token creation and verification.

Uses python-jose for JWT encoding/decoding and passlib for password
hashing (bcrypt).

Token structure:
  {
    "sub": "<user_id as UUID string>",
    "exp": <expiry timestamp>,
    "iat": <issued-at timestamp>
  }

The JWT is stateless — we don't store tokens in the DB.  Revocation
is handled by short expiry times (24h default).  For a production
system, you'd add a token blocklist or switch to refresh tokens.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta

from jose import JWTError, jwt
import bcrypt

from app.config import settings

# ── Password hashing ─────────────────────────────────────
def _bcrypt_input(plain: str) -> bytes:
    """Apply bcrypt's 72-byte input limit without Passlib compatibility issues."""
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return bcrypt.hashpw(_bcrypt_input(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(_bcrypt_input(plain), hashed.encode("utf-8"))


# ── JWT creation ──────────────────────────────────────────
def create_access_token(user_id: uuid.UUID) -> str:
    """Create a signed JWT for an authenticated user.

    Parameters
    ----------
    user_id : uuid.UUID
        The user's database ID — becomes the `sub` claim.

    Returns
    -------
    str
        Encoded JWT string.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


# ── JWT verification ─────────────────────────────────────
def decode_access_token(token: str) -> uuid.UUID | None:
    """Decode and validate a JWT.

    Returns
    -------
    uuid.UUID | None
        The user_id from the `sub` claim, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        sub = payload.get("sub")
        if sub is None:
            return None
        return uuid.UUID(sub)
    except (JWTError, ValueError):
        return None
