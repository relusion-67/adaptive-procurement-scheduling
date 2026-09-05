"""Password hashing and JWT issuance/validation.

Deliberately built on the standard library (`hashlib.pbkdf2_hmac`, `hmac`,
`secrets`) plus PyJWT rather than pulling in passlib/bcrypt: PBKDF2-SHA256
is a NIST/OWASP-approved KDF, the stdlib implementation is maintained by
CPython itself, and this keeps the auth surface to one small, auditable
module instead of a heavier dependency tree.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

_PBKDF2_ALGORITHM = "sha256"
_PBKDF2_ITERATIONS = 390_000
_SALT_BYTES = 16

TOKEN_TYPE = "access"


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password. Never store the plaintext value."""
    salt = secrets.token_hex(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        plain_password.encode("utf-8"),
        bytes.fromhex(salt),
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${derived.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time comparison of a plaintext password against a hash
    produced by `hash_password`. Fails safe (returns False) on any
    malformed stored hash rather than raising.
    """
    try:
        algorithm, iterations_str, salt, expected_hex = hashed_password.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
    except (ValueError, AttributeError):
        return False

    derived = hashlib.pbkdf2_hmac(
        _PBKDF2_ALGORITHM,
        plain_password.encode("utf-8"),
        bytes.fromhex(salt),
        iterations,
    )
    return hmac.compare_digest(derived.hex(), expected_hex)


# --------------------------------------------------------------------------
# JWT access tokens
# --------------------------------------------------------------------------


@dataclass
class TokenPayload:
    user_id: int
    role: str
    expires_at: datetime


class TokenError(Exception):
    """Raised for any malformed, expired, or otherwise invalid token.

    Deliberately a single error type: the caller (the auth dependency)
    always maps this to a 401, and callers should not be able to
    distinguish "expired" from "forged" from "malformed" through
    behavior, since that distinction is not useful to a legitimate client
    and is useful to an attacker.
    """


def create_access_token(*, user_id: int, role: str) -> str:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": TOKEN_TYPE,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as error:
        raise TokenError("Invalid or expired token") from error

    if payload.get("type") != TOKEN_TYPE:
        raise TokenError("Invalid token type")

    try:
        user_id = int(payload["sub"])
        role = str(payload["role"])
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    except (KeyError, TypeError, ValueError) as error:
        raise TokenError("Malformed token payload") from error

    return TokenPayload(user_id=user_id, role=role, expires_at=expires_at)
