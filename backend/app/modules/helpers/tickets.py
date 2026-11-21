"""Switch tickets: how a helper on a shared phone proves which family they are with.

A helper enters a family's PIN (`POST /v1/helper/switch`) and gets a short-lived ticket back. The ticket is
a random value. Only its hash is stored, in the `helper.switched` audit row, together with the helper's
session, the person and the delegation it was issued under. Every helper request for a person carries the
ticket in `X-Helper-Ticket`, and `resolve_person` accepts it only when:

* it matches the newest switch row of this very session (switching to another family, or ending the
  switch, writes a newer row, so the previous ticket stops working at once);
* that row names the same person and has not expired;
* the delegation it was issued under is still live (revoking it kills a ticket already issued, and a new
  delegation never revives an old ticket).

The audit chain is the record of switches: append-only, hash-chained, and it already says who acted for
whom. Failed PINs are counted from the same rows, so the attempt limit survives a restart.

The pure functions here (`check_ticket`, `lock_remaining`) have DB-free tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models

TICKET_TTL: Final = timedelta(minutes=15)
SWITCHED: Final = "helper.switched"
SWITCH_ENDED: Final = "helper.switch_ended"
SWITCH_DENIED: Final = "helper.switch_denied"
SESSION_OBJECT: Final = "helper_session"

# Wrong family PINs: five per family in fifteen minutes, and fifteen across all families, then a pause.
PIN_WINDOW: Final = timedelta(minutes=15)
PIN_MAX_PER_FAMILY: Final = 5
PIN_MAX_PER_HELPER: Final = 15
COUNTED_FAILURES: Final = ("wrong_pin", "no_delegation")

TICKET_DENIALS: Final[frozenset[str]] = frozenset({"ticket_required", "ticket_invalid", "ticket_expired"})


def new_ticket() -> tuple[str, str]:
    """Returns (ticket for the client, hash for the audit row). The ticket itself is never stored."""
    raw = secrets.token_urlsafe(32)
    return raw, ticket_hash(raw)


def ticket_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SwitchRecord:
    """The newest switch row of one session."""

    action: str  # helper.switched | helper.switch_ended
    person_id: UUID | None
    delegation_id: UUID | None
    ticket_hash: str | None
    expires_at: datetime | None
    at: datetime

    @property
    def active(self) -> bool:
        return self.action == SWITCHED


def _parse_uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


def _parse_time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=UTC)


def record_from_row(row: models.AuditLog) -> SwitchRecord:
    try:
        details = json.loads(row.details or "{}")
    except ValueError:
        details = {}
    return SwitchRecord(
        action=row.action,
        person_id=row.acting_for_person_id,
        delegation_id=_parse_uuid(details.get("delegation_id")),
        ticket_hash=str(details["ticket_hash"]) if details.get("ticket_hash") else None,
        expires_at=_parse_time(details.get("expires_at")),
        at=row.ts,
    )


def latest_switch(db: Session, *, tenant_id: UUID, session_id: UUID | None) -> SwitchRecord | None:
    """The newest switch or end-of-switch row for this session (indexed lookup by object id)."""
    if session_id is None:
        return None
    row = db.scalars(
        select(models.AuditLog)
        .where(
            models.AuditLog.tenant_id == tenant_id,
            models.AuditLog.object_type == SESSION_OBJECT,
            models.AuditLog.object_id == str(session_id),
            models.AuditLog.action.in_((SWITCHED, SWITCH_ENDED)),
        )
        .order_by(models.AuditLog.seq.desc())
        .limit(1)
    ).first()
    return record_from_row(row) if row is not None else None


def check_ticket(record: SwitchRecord | None, *, ticket: str | None, person_id: UUID, live_delegation_ids: Iterable[UUID],
                 now: datetime) -> str | None:  # fmt: skip
    """Pure: None when the ticket lets this helper act for `person_id` right now, otherwise the refusal code."""
    if not ticket or not ticket.strip():
        return "ticket_required"
    if record is None or not record.active or record.ticket_hash is None:
        return "ticket_invalid"
    if not hmac.compare_digest(record.ticket_hash, ticket_hash(ticket.strip())):
        return "ticket_invalid"
    if record.person_id != person_id:
        return "ticket_invalid"
    if record.delegation_id is None or record.delegation_id not in set(live_delegation_ids):
        return "ticket_invalid"
    if record.expires_at is None or record.expires_at <= now:
        return "ticket_expired"
    return None


def lock_remaining(failures: Iterable[datetime], *, now: datetime, limit: int, window: timedelta = PIN_WINDOW,
                   since: datetime | None = None) -> timedelta | None:  # fmt: skip
    """Pure: how long switching stays locked, or None when another attempt is allowed.

    `failures` are the times of counted wrong attempts. Only those inside the window and after `since` (the
    last successful switch) count. Once `limit` of them are inside the window, the lock lasts until the
    oldest of those leaves it, so a pause always ends by itself.
    """
    start = now - window
    if since is not None and since > start:
        start = since
    recent = sorted(t for t in failures if t > start)
    if len(recent) < limit:
        return None
    unlock_at = recent[-limit] + window
    remaining = unlock_at - now
    return remaining if remaining > timedelta(0) else None


def attempts_left(failures: Iterable[datetime], *, now: datetime, limit: int, window: timedelta = PIN_WINDOW,
                  since: datetime | None = None) -> int:  # fmt: skip
    start = now - window
    if since is not None and since > start:
        start = since
    return max(0, limit - sum(1 for t in failures if t > start))
