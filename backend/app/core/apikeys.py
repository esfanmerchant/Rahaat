"""API keys: format, hashing, the scope vocabulary, verification on every request and metering.

A key looks like `rk_<prefix>_<secret>`: a public 10-character prefix that finds the row, and 32 random bytes
that prove possession. It is shown once at creation. The database keeps only the prefix and a SHA-256 hash of
the whole key, so a copy of the database cannot be used to call the API. A key is looked up again on every
request, so revoking it or letting it expire takes effect on the very next call.

A key is a principal with role `api_client` in its department. Row Level Security treats that role like an
officer for consent, so a key never reads a person whose consent is withdrawn. Routes admit keys only through
`Policy(..., api_scopes=[...])`; a role list never admits a key.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, metrics
from app.core.db import RlsContext, session_scope, system_session
from app.core.errors import Unauthorized
from app.core.logging import get_logger
from app.db import models

log = get_logger("rahat.apikeys")

API_CLIENT_ROLE: Final = "api_client"
KEY_MARKER: Final = "rk_"
_KEY_SHAPE = re.compile(r"^rk_([a-f0-9]{10})_([A-Za-z0-9_-]{43})$")
_LAST_USED_EVERY = timedelta(seconds=30)  # last-used is written at most this often per key


@dataclass(frozen=True, slots=True)
class ApiScope:
    name: str
    description: str
    personal_data: bool  # keys with such a scope need a second admin before they work


API_SCOPES: Final[dict[str, ApiScope]] = {
    scope.name: scope
    for scope in (
        ApiScope("cases:read", "Read the review queue: status, priority, reason code and the person's name while their consent "
                               "allows. Never the case file.", personal_data=True),  # fmt: skip
        ApiScope("payments:read", "Read payments: amount, status and payment reference. No names.", personal_data=False),
        ApiScope("scam:check", "Check a message for signs of a scam.", personal_data=False),
        ApiScope("channels:ussd", "Feature-phone channel: carry USSD sessions of mock numbers (status, message check, stop "
                                  "sharing, callback). The person proves themselves with a code or PIN.", personal_data=True),
        ApiScope("channels:sms", "Feature-phone channel: carry inbound SMS commands of mock numbers and send the replies.",
                 personal_data=True),
    )
}


@dataclass(frozen=True, slots=True)
class ApiKeyIdentity:
    """A verified key, as the rest of the request sees it. Never holds the secret or its hash."""

    id: UUID
    tenant_id: UUID
    prefix: str
    name: str
    scopes: tuple[str, ...]
    rate_limit_per_min: int


def generate() -> tuple[str, str, str]:
    """A new key. Returns (the key to show once, its public prefix, the hash to store)."""
    prefix = secrets.token_hex(5)
    raw = f"{KEY_MARKER}{prefix}_{secrets.token_urlsafe(32)}"
    return raw, prefix, hash_key(raw)


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_prefix(raw: str) -> str | None:
    """The prefix of a well-formed key, or None. Malformed keys are refused before any database lookup."""
    match = _KEY_SHAPE.match(raw.strip())
    return match.group(1) if match else None


def looks_like_api_key(raw: str) -> bool:
    return raw.strip().startswith(KEY_MARKER)


def period(now: datetime) -> str:
    """The metering period: the calendar month in UTC."""
    return now.astimezone(UTC).strftime("%Y-%m")


_INVALID = "This API key is not valid."
_DENIALS: Final[dict[str, str]] = {
    "api_key_invalid": _INVALID,
    "api_key_revoked": "This API key was revoked. Ask your department's admin for a new one.",
    "api_key_expired": "This API key has expired. Ask your department's admin for a new one.",
    "api_key_tenant_inactive": "The department this API key belongs to is not active.",
}


class KeyRefused(Unauthorized):
    """A real key's prefix was presented but the key may not be used. Carries what the audit row needs.

    `authenticate` does not write the record itself: the caller first charges the network's rate limit, so
    someone replaying a revoked key cannot grow a department's audit chain faster than that limit.
    """

    def __init__(self, *, key_id: UUID, tenant_id: UUID, prefix: str, reason: str) -> None:
        super().__init__(_DENIALS[reason], code="invalid_api_key" if reason == "api_key_invalid" else reason)
        self.key_id, self.tenant_id, self.prefix, self.reason = key_id, tenant_id, prefix, reason


def authenticate(raw: str) -> ApiKeyIdentity:
    """Verify a presented key. Raises 401 for anything but a live key of an active department.

    The lookup by prefix happens before there is a caller, so it uses the system context, like sign-in.
    Attempts with a real key's prefix (wrong secret, revoked, expired) raise `KeyRefused`, which the caller
    records with `record_refusal` once it has charged the rate limit.
    """
    prefix = parse_prefix(raw)
    if prefix is None:
        metrics.API_KEY_EVENTS.labels("malformed").inc()
        raise Unauthorized(_INVALID, code="invalid_api_key")
    digest = hash_key(raw)
    now = datetime.now(UTC)
    with system_session() as db:
        found = db.execute(
            select(models.ApiKey, models.Tenant.status)
            .join(models.Tenant, models.Tenant.id == models.ApiKey.tenant_id)
            .where(models.ApiKey.prefix == prefix)
        ).first()
        if found is None:
            metrics.API_KEY_EVENTS.labels("unknown").inc()
            raise Unauthorized(_INVALID, code="invalid_api_key")
        key, tenant_status = found
        db.expunge(key)
    reason = None
    if not hmac.compare_digest(key.key_hash, digest):
        reason = "api_key_invalid"
    elif key.revoked_at is not None:
        reason = "api_key_revoked"
    elif key.expires_at is not None and key.expires_at <= now:
        reason = "api_key_expired"
    elif tenant_status != "active":
        reason = "api_key_tenant_inactive"
    if reason is not None:
        metrics.API_KEY_EVENTS.labels(reason).inc()
        raise KeyRefused(key_id=key.id, tenant_id=key.tenant_id, prefix=key.prefix, reason=reason)
    metrics.API_KEY_EVENTS.labels("authenticated").inc()
    return ApiKeyIdentity(
        id=key.id, tenant_id=key.tenant_id, prefix=key.prefix, name=key.name,
        scopes=tuple(str(s) for s in (key.scopes or [])), rate_limit_per_min=int(key.rate_limit_per_min),
    )  # fmt: skip


def record_refusal(refused: KeyRefused) -> None:
    """The refused attempt, in its own committed transaction: the request fails, the record stays."""
    try:
        with system_session() as db:
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            audit.write(db, tenant_id=refused.tenant_id, action="access.denied", actor_type="api_key", actor_id=refused.key_id,
                        actor_role=API_CLIENT_ROLE, object_type="api_key", object_id=refused.key_id, result="denied",
                        reason=refused.reason, details={"prefix": refused.prefix})  # fmt: skip
            if refused.reason == "api_key_invalid":  # someone knows a real prefix but not the secret
                db.add(models.SecurityEvent(tenant_id=refused.tenant_id, kind="api_key_misuse", severity="high",
                                            details={"prefix": refused.prefix, "key_id": str(refused.key_id)}))  # fmt: skip
    except Exception:  # noqa: BLE001  (a failure to record must never hide the refusal itself)
        log.exception("could not record a refused API key attempt")


def record_use(identity: ApiKeyIdentity) -> None:
    """Meter one admitted call (`usage_counters`, metric `api_calls`, this month) and note when the key was last used.

    Runs in the key's own department context, in its own transaction, because the request's session rolls
    back whatever a read-only endpoint leaves uncommitted. A metering failure is logged, never raised.
    """
    now = datetime.now(UTC)
    ctx = RlsContext(role=API_CLIENT_ROLE, tenant_id=identity.tenant_id, user_id=identity.id)
    try:
        with session_scope(ctx) as db:
            upsert = pg_insert(models.UsageCounter).values(
                id=uuid.uuid4(), tenant_id=identity.tenant_id, metric="api_calls", period=period(now), count=1, updated_at=now
            )
            db.execute(upsert.on_conflict_do_update(
                constraint="uq_usage_counter", set_={"count": models.UsageCounter.count + 1, "updated_at": now},
            ))  # fmt: skip
            db.execute(
                update(models.ApiKey)
                .where(models.ApiKey.id == identity.id,
                       or_(models.ApiKey.last_used_at.is_(None), models.ApiKey.last_used_at < now - _LAST_USED_EVERY))
                .values(last_used_at=now)
            )  # fmt: skip
        metrics.API_KEY_EVENTS.labels("metered").inc()
    except Exception:  # noqa: BLE001
        log.exception("could not meter an API key call")


def monthly_calls(db: Session, tenant_id: UUID, *, now: datetime | None = None) -> int:
    """API calls metered for the department this month, read in the caller's own session."""
    value = db.scalar(
        select(models.UsageCounter.count).where(
            models.UsageCounter.tenant_id == tenant_id,
            models.UsageCounter.metric == "api_calls",
            models.UsageCounter.period == period(now or datetime.now(UTC)),
        )
    )
    return int(value or 0)
