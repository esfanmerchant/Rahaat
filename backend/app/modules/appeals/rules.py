"""Appeal and complaint rules. Pure functions with DB-free tests.

An appeal is allowed for an application that was rejected (by the engine or by an officer), once per decision,
within `WINDOW_DAYS` of that decision, and it is decided by an officer who had no part in the first decision.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Final, Literal

WINDOW_DAYS: Final = 30
SLA_DAYS: Final = 5  # matches the `appeal` case SLA (120 hours)

AppealOutcome = Literal["upheld", "overturned"]
ComplaintCategory = Literal["service", "staff", "scam_attempt", "payment", "other"]
ComplaintOutcome = Literal["resolved", "dismissed"]

COMPLAINT_REASON_PREFIX: Final = "complaint_"


def ineligible_reason(
    *, application_status: str, decided_at: datetime | None, now: datetime, decision_id: uuid.UUID | None,
    earlier: Iterable[tuple[str, uuid.UUID | None]],
) -> str | None:  # fmt: skip
    """None when the person may appeal, else a stable problem code.

    `earlier` is every earlier appeal on this application as (status, decision_id). A withdrawn appeal does not count.
    """
    if application_status != "rejected":
        return "appeal_not_applicable"  # nothing went against the person (or it is still being decided)
    if decided_at is None or now - decided_at > timedelta(days=WINDOW_DAYS):
        return "appeal_window_closed"
    for status, appealed_decision in earlier:
        if status == "open":
            return "appeal_already_open"
        if status in ("upheld", "overturned") and appealed_decision == decision_id:
            return "appeal_already_decided"  # one appeal per decision; a new decision can be appealed again
    return None


def days_left(decided_at: datetime | None, now: datetime) -> int:
    if decided_at is None:
        return 0
    return max(0, (decided_at + timedelta(days=WINDOW_DAYS) - now).days)


def may_decide(user_id: uuid.UUID, original_deciders: Iterable[uuid.UUID]) -> bool:
    """A different officer: nobody who reviewed, decided or second-approved the first decision decides the appeal."""
    return user_id not in set(original_deciders)


def collect_deciders(rows: Iterable[tuple[Any, Any]]) -> set[uuid.UUID]:
    """Reviewer and second approver ids from (reviewer_user_id, second_approver_id) rows, ignoring empty ones."""
    return {value for row in rows for value in row if isinstance(value, uuid.UUID)}


def appeal_citizen_status(status: str) -> str:
    """What the citizen is told. Never the officer's notes."""
    return {"open": "being_checked", "upheld": "first_answer_stays", "overturned": "approved_after_appeal", "withdrawn": "withdrawn"}.get(
        status, "being_checked"
    )


def complaint_route(category: str) -> tuple[str, int]:
    """(case kind, priority): scam reports go to the scam queue, staff complaints sooner than the rest."""
    if category == "scam_attempt":
        return "scam_review", 20
    if category == "staff":
        return "complaint", 30
    return "complaint", 50


def complaint_reason(category: str) -> str:
    return f"{COMPLAINT_REASON_PREFIX}{category}"


def category_of(opened_reason: str) -> str:
    return opened_reason.removeprefix(COMPLAINT_REASON_PREFIX) if opened_reason.startswith(COMPLAINT_REASON_PREFIX) else "other"


def complaint_citizen_status(case_status: str) -> str:
    if case_status in ("resolved", "closed"):
        return "resolved"
    if case_status in ("open", "assigned"):
        return "received"
    return "being_checked"
