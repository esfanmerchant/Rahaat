"""Password and PIN hashing, access tokens and refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import Unauthorized, Unprocessable

_ALGORITHM = "HS256"  # pinned: tokens signed with anything else, including "none", are rejected
_REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub", "sid", "tid", "role", "jti"]


@lru_cache
def _hasher() -> PasswordHasher:
    if get_settings().app_env == "test":
        return PasswordHasher(time_cost=1, memory_cost=8 * 1024, parallelism=1)
    return PasswordHasher()  # argon2id with the library's recommended parameters


@lru_cache
def _dummy_hash() -> str:
    return _hasher().hash(secrets.token_hex(16))


def hash_secret(secret: str) -> str:
    return _hasher().hash(secret)


def verify_secret(stored_hash: str | None, secret: str) -> bool:
    """Always performs one hash verification, so a missing account takes as long as a wrong password."""
    try:
        return _hasher().verify(stored_hash or _dummy_hash(), secret) and stored_hash is not None
    except (VerificationError, InvalidHashError):
        return False


_COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "12345678", "123456789", "1234567890",
        "qwerty123", "qwertyuiop", "iloveyou", "admin123", "administrator", "welcome123", "letmein123",
        "pakistan123", "pakistan1947", "karachi123", "lahore123", "abc12345", "changeme", "rahat123",
    }
)  # fmt: skip
_TRIVIAL_PINS = frozenset({"0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
                           "1234", "4321", "0123", "1212", "123456", "000000", "111111", "654321"})  # fmt: skip


def check_password_strength(password: str, *, email: str | None = None) -> None:
    lowered = password.lower()
    if len(password) < 10:
        raise Unprocessable("Use at least 10 characters.", code="weak_password")
    if lowered in _COMMON_PASSWORDS:
        raise Unprocessable("That password is too common.", code="weak_password")
    if email and email.split("@")[0].lower() in lowered:
        raise Unprocessable("Do not put your email name in the password.", code="weak_password")


def check_pin_strength(pin: str) -> None:
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise Unprocessable("The PIN must be 4 to 6 digits.", code="weak_pin")
    if pin in _TRIVIAL_PINS:
        raise Unprocessable("Choose a PIN that is harder to guess.", code="weak_pin")


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Returns (raw token for the cookie, hash for the database). The raw value is never stored."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: UUID
    session_id: UUID
    tenant_id: UUID
    role: str
    person_id: UUID | None
    expires_at: int


def issue_access_token(
    *, user_id: UUID, session_id: UUID, tenant_id: UUID, role: str, person_id: UUID | None
) -> tuple[str, int]:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "sid": str(session_id),
        "tid": str(tenant_id),
        "role": role,
        "pid": str(person_id) if person_id else None,
        "iat": now,
        "exp": now + settings.access_ttl_seconds,
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=_ALGORITHM, headers={"kid": settings.jwt_active_kid})
    return token, settings.access_ttl_seconds


def decode_access_token(token: str) -> AccessClaims:
    settings = get_settings()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        key = settings.jwt_keys().get(kid or "")
        if key is None:
            raise Unauthorized("Your sign-in is not valid. Please sign in again.", code="invalid_token")
        claims = jwt.decode(
            token,
            key,
            algorithms=[_ALGORITHM],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": _REQUIRED_CLAIMS},
        )
        return AccessClaims(
            user_id=UUID(claims["sub"]),
            session_id=UUID(claims["sid"]),
            tenant_id=UUID(claims["tid"]),
            role=str(claims["role"]),
            person_id=UUID(claims["pid"]) if claims.get("pid") else None,
            expires_at=int(claims["exp"]),
        )
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your sign-in has expired.", code="token_expired") from exc
    except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
        raise Unauthorized("Your sign-in is not valid. Please sign in again.", code="invalid_token") from exc
