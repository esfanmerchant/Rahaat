"""Pure rules for API keys: status, scope checks, the second-admin gate and expiry on rotation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal

from app.core.apikeys import API_SCOPES
from app.core.errors import Unprocessable

KeyStatus = Literal["active", "pending_approval", "revoked", "expired"]

MAX_LIFETIME_DAYS = 365
MAX_RATE_PER_MINUTE = 1200  # well below a department's lane, so one key cannot use it all


def key_status(*, revoked_at: datetime | None, expires_at: datetime | None, pending: bool, now: datetime) -> KeyStatus:
    if revoked_at is not None:
        return "revoked"
    if expires_at is not None and expires_at <= now:
        return "expired"
    if pending:
        return "pending_approval"
    return "active"


def check_scopes(requested: Sequence[str], routes_by_scope: Mapping[str, Sequence[str]]) -> list[str]:
    """Known, unique scopes that at least one endpoint admits, in a stable order. Anything else is a repairable 422."""
    wanted = list(dict.fromkeys(s.strip() for s in requested))
    unknown = [s for s in wanted if s not in API_SCOPES]
    if unknown:
        raise Unprocessable("Some scopes do not exist.", code="unknown_scope", extra={"unknown_scopes": unknown})
    unused = [s for s in wanted if not routes_by_scope.get(s)]
    if unused:
        raise Unprocessable("No endpoint accepts these scopes yet.", code="scope_not_available", extra={"unavailable_scopes": unused})
    return sorted(wanted)


def needs_second_admin(scopes: Sequence[str]) -> bool:
    """A key that can read personal data works only after a second admin approves it (admins never read it themselves)."""
    return any(API_SCOPES[s].personal_data for s in scopes if s in API_SCOPES)


def rotated_expiry(*, expires_at: datetime | None, now: datetime, days: int | None) -> datetime:
    """The replacement ends when the old key would have ended, or sooner if the admin asks.

    Rotation replaces a secret; it never extends a key's life. Otherwise one admin could keep a key that a
    second admin approved alive for ever, one rotation at a time. A longer life means a new key.
    """
    end = expires_at if expires_at is not None else now + timedelta(days=MAX_LIFETIME_DAYS)
    if days is not None:
        end = min(end, now + timedelta(days=days))
    return end
