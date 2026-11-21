"""DB-free tests of the switch-ticket rules and the PIN attempt limit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.modules.helpers import tickets
from app.modules.helpers.tickets import SwitchRecord, attempts_left, check_ticket, lock_remaining

NOW = datetime(2026, 11, 21, 16, 0, tzinfo=UTC)
PERSON = uuid.uuid4()
DELEGATION = uuid.uuid4()


def _record(raw: str, *, person: uuid.UUID = PERSON, delegation: uuid.UUID | None = DELEGATION, action: str = tickets.SWITCHED,
            expires: datetime | None = NOW + timedelta(minutes=10)) -> SwitchRecord:  # fmt: skip
    return SwitchRecord(action=action, person_id=person, delegation_id=delegation, ticket_hash=tickets.ticket_hash(raw),
                        expires_at=expires, at=NOW - timedelta(minutes=5))  # fmt: skip


def test_a_matching_live_ticket_passes() -> None:
    raw, hashed = tickets.new_ticket()
    assert hashed == tickets.ticket_hash(raw) and raw not in hashed
    assert check_ticket(_record(raw), ticket=raw, person_id=PERSON, live_delegation_ids=[DELEGATION], now=NOW) is None


def test_every_way_a_ticket_fails() -> None:
    raw, _ = tickets.new_ticket()
    live = [DELEGATION]
    assert check_ticket(_record(raw), ticket=None, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_required"
    assert check_ticket(_record(raw), ticket="  ", person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_required"
    assert check_ticket(None, ticket=raw, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_invalid"
    other, _ = tickets.new_ticket()
    assert check_ticket(_record(raw), ticket=other, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_invalid"
    # Bound to one person: the same ticket does not open another family.
    assert check_ticket(_record(raw), ticket=raw, person_id=uuid.uuid4(), live_delegation_ids=live, now=NOW) == "ticket_invalid"
    # Ending the switch, or a newer switch, leaves no active record for the old ticket.
    ended = _record(raw, action=tickets.SWITCH_ENDED)
    assert check_ticket(ended, ticket=raw, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_invalid"
    # Revoked delegation: a new delegation never revives a ticket issued under the old one.
    assert check_ticket(_record(raw), ticket=raw, person_id=PERSON, live_delegation_ids=[], now=NOW) == "ticket_invalid"
    assert check_ticket(_record(raw), ticket=raw, person_id=PERSON, live_delegation_ids=[uuid.uuid4()], now=NOW) == "ticket_invalid"
    assert check_ticket(_record(raw, delegation=None), ticket=raw, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_invalid"
    expired = _record(raw, expires=NOW - timedelta(seconds=1))
    assert check_ticket(expired, ticket=raw, person_id=PERSON, live_delegation_ids=live, now=NOW) == "ticket_expired"


def test_lock_after_the_limit_and_it_ends_by_itself() -> None:
    fails = [NOW - timedelta(minutes=m) for m in (14, 10, 6, 3, 1)]
    assert lock_remaining(fails[:4], now=NOW, limit=5) is None
    remaining = lock_remaining(fails, now=NOW, limit=5)
    assert remaining is not None and remaining == timedelta(minutes=1), "unlocks when the oldest counted failure leaves the window"
    assert lock_remaining(fails, now=NOW + timedelta(minutes=1, seconds=1), limit=5) is None
    # A successful switch resets the family count.
    assert lock_remaining(fails, now=NOW, limit=5, since=NOW - timedelta(minutes=2)) is None
    # Failures older than the window do not count.
    assert lock_remaining([NOW - timedelta(minutes=20)] * 9, now=NOW, limit=5) is None


def test_attempts_left_counts_down_to_zero() -> None:
    assert attempts_left([], now=NOW, limit=5) == 5
    assert attempts_left([NOW] * 3, now=NOW, limit=5) == 2
    assert attempts_left([NOW] * 7, now=NOW, limit=5) == 0
    assert attempts_left([NOW - timedelta(minutes=1)] * 3, now=NOW, limit=5, since=NOW - timedelta(seconds=30)) == 5
