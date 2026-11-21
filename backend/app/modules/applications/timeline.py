"""Tracking codes and the citizen's timeline. Both are pure; the timeline is derived on read, never stored."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from app.contracts.api import TimelineItem
from app.contracts.common import tracking_symbols

_TRACKING = re.compile(r"^R-(\d{5})$")


def new_tracking_number() -> int:
    return 10_000 + secrets.randbelow(90_000)


def format_tracking(number: int) -> str:
    return f"R-{number:05d}"


def tracking_number(code: str | None) -> int | None:
    match = _TRACKING.match(code or "")
    return int(match.group(1)) if match else None


def symbols_for(code: str | None) -> list[str]:
    number = tracking_number(code)
    return tracking_symbols(number) if number is not None else []


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    at: datetime
    outcome: str


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    at: datetime
    status: str


_DECISION_STEP = {
    "approved": ("approved", "timeline.approved"),
    "rejected": ("rejected", "timeline.rejected"),
    "needs_proof": ("needs_proof", "timeline.needs_proof"),
    "needs_human": ("in_review", "timeline.person_checking"),
}
_CURRENT_ONLY = {
    "on_hold_consent": "timeline.on_hold_consent",
    "withdrawn": "timeline.withdrawn",
}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def build_timeline(
    *,
    created_at: datetime,
    submitted_at: datetime | None,
    status: str,
    updated_at: datetime,
    decisions: list[DecisionEvent],
    payments: list[PaymentEvent],
    in_review_without_decision: bool = False,
) -> list[TimelineItem]:
    """Steps in time order. Rows written in one request can share a timestamp, so each kind has a rank."""
    steps: list[tuple[datetime, int, int, TimelineItem]] = []

    def add(at: datetime, rank: int, status_: str, key: str) -> None:
        steps.append((at, rank, len(steps), TimelineItem(at=_iso(at), status=status_, label_key=key)))

    add(created_at, 0, "draft", "timeline.started")
    if submitted_at is not None:
        add(submitted_at, 1, "submitted", "timeline.submitted")
    for decision in decisions:
        step = _DECISION_STEP.get(decision.outcome)
        if step:
            add(decision.at, 2, *step)
    if in_review_without_decision and submitted_at is not None:
        add(submitted_at, 2, "in_review", "timeline.person_checking")
    for payment in payments:
        if payment.status == "settled":
            add(payment.at, 3, "paid", "timeline.paid")
        else:
            add(payment.at, 3, "approved", f"timeline.payment_{payment.status}")
    if status in _CURRENT_ONLY:
        add(updated_at, 4, status, _CURRENT_ONLY[status])
    return [item for *_, item in sorted(steps, key=lambda s: (s[0], s[1], s[2]))]
