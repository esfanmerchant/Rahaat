"""Payment rules as pure functions: the state machine, the four-eyes limit, reconciliation."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

DEFAULT_FOUR_EYES_LIMIT_PKR = 15_000  # DECISIONS 17; tenant configuration overrides it

TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_approval": frozenset({"approved", "cancelled"}),
    "approved": frozenset({"submitted", "settled", "failed", "cancelled"}),
    "submitted": frozenset({"settled", "failed"}),
    "failed": frozenset({"submitted", "settled", "failed", "cancelled"}),  # failed -> failed: another attempt failed
    "settled": frozenset({"reversed"}),
    "reversed": frozenset(),
    "cancelled": frozenset(),
}
RELEASABLE = frozenset({"approved", "submitted", "failed"})


class IllegalPaymentTransition(ValueError):
    def __init__(self, current: str, wanted: str) -> None:
        super().__init__(f"a payment cannot go from {current} to {wanted}")
        self.current, self.wanted = current, wanted


def can_move(current: str, wanted: str) -> bool:
    return wanted in TRANSITIONS.get(current, frozenset())


def check_move(current: str, wanted: str) -> None:
    if not can_move(current, wanted):
        raise IllegalPaymentTransition(current, wanted)


def four_eyes_limit(tenant_config: dict[str, Any] | None) -> int:
    try:
        return int((tenant_config or {}).get("payment_four_eyes_limit_pkr", DEFAULT_FOUR_EYES_LIMIT_PKR))
    except (TypeError, ValueError):
        return DEFAULT_FOUR_EYES_LIMIT_PKR


def needs_second_approver(amount_pkr: int, limit_pkr: int) -> bool:
    """At or below the limit a payment is released at once; above it a second person must release it."""
    return amount_pkr > limit_pkr


def may_release(approver_id: uuid.UUID, excluded: Iterable[uuid.UUID | str | None]) -> bool:
    """The second approver is never the person who approved the case or asked for the payment."""
    return str(approver_id) not in {str(x) for x in excluded if x}


def idempotency_key(application_id: uuid.UUID) -> str:
    """One payment per application, ever: the key is derived from the application, not from the request."""
    return f"application:{application_id}"


def reconciliation_status(expected_pkr: int, settled_pkr: int | None) -> str:
    if settled_pkr is None:
        return "missing_on_rail"
    return "matched" if settled_pkr == expected_pkr else "amount_mismatch"
