"""The case state machine, SLA and override rules. Pure functions with DB-free tests.

    open -> assigned -> in_review -> resolved -> closed
      \\-> escalated (priority raised)     \\-> waiting_proof -> in_review (proof arrived)
    resolved -> open (reopen, with a reason)

Every action needs a reason (enforced by the request model). There are no bulk actions: each endpoint
acts on one case, after the officer has the handoff package in front of them.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from app.contracts.common import CaseAction

STATUSES = ("open", "assigned", "in_review", "waiting_proof", "escalated", "resolved", "closed")
ACTIVE = frozenset({"open", "assigned", "in_review", "waiting_proof", "escalated"})
CASE_ACTIONS: tuple[CaseAction, ...] = ("approve", "reject", "request_proof", "escalate")

CaseEventName = Literal[
    "assign", "start_review", "approve", "reject", "request_proof", "escalate", "proof_received", "reopen", "close"
]

_DECIDABLE = frozenset({"open", "assigned", "in_review", "escalated", "waiting_proof"})
TRANSITIONS: dict[str, tuple[frozenset[str], str | None]] = {
    # event: (allowed from, to). None means "keep the current status" (assigning an in-review case).
    "assign": (ACTIVE, None),
    "start_review": (frozenset({"open", "assigned", "escalated"}), "in_review"),
    "approve": (_DECIDABLE, "resolved"),
    "reject": (_DECIDABLE, "resolved"),
    "request_proof": (frozenset({"open", "assigned", "in_review", "escalated"}), "waiting_proof"),
    "escalate": (frozenset({"open", "assigned", "in_review", "waiting_proof"}), "escalated"),
    "proof_received": (frozenset({"waiting_proof"}), "in_review"),
    "reopen": (frozenset({"resolved"}), "open"),
    "close": (frozenset({"resolved"}), "closed"),
}

SLA_HOURS: dict[str, float] = {
    "application_review": 48, "document_review": 24, "duplicate_review": 48, "complaint": 72,
    "appeal": 120, "correction": 72, "scam_review": 12,
}  # fmt: skip
ESCALATED_SLA = timedelta(hours=24)
URGENT_PRIORITY = 20  # at or below this the SLA is halved
ESCALATION_STEP = 20


class IllegalCaseTransition(ValueError):
    def __init__(self, current: str, event: str) -> None:
        super().__init__(f"a case that is {current} cannot {event.replace('_', ' ')}")
        self.current, self.event = current, event


def next_status(current: str, event: str) -> str:
    if event not in TRANSITIONS:
        raise IllegalCaseTransition(current, event)
    allowed_from, target = TRANSITIONS[event]
    if current not in allowed_from:
        raise IllegalCaseTransition(current, event)
    if event == "assign":
        return "assigned" if current in ("open", "escalated") else current
    assert target is not None
    return target


def allowed_actions(status: str) -> list[CaseAction]:
    return [action for action in CASE_ACTIONS if status in TRANSITIONS[action][0]]


def sla_due(kind: str, priority: int, now: datetime) -> datetime:
    hours = SLA_HOURS.get(kind, 48.0)
    if priority <= URGENT_PRIORITY:
        hours /= 2
    return now + timedelta(hours=hours)


def escalated_priority(priority: int) -> int:
    """Lower is more urgent."""
    return max(0, priority - ESCALATION_STEP)


def escalated_sla(current: datetime | None, now: datetime) -> datetime:
    target = now + ESCALATED_SLA
    return min(current, target) if current else target


_APPROVE_LABELS = frozenset({"eligible", "approve", "approved", "genuine"})


def engine_lean(outcome: str | None, p_ok: float | None, hypotheses: list[dict[str, Any]] | None = None) -> str | None:
    """Which way the engine leaned, to tell whether the officer overrode it. None when it gave no lean."""
    if outcome == "approved":
        return "approve"
    if outcome == "rejected":
        return "reject"
    if outcome == "needs_proof":
        return "request_proof"
    ranked = sorted(hypotheses or [], key=lambda h: float(h.get("probability", 0.0)), reverse=True)
    if ranked:
        return "approve" if str(ranked[0].get("label", "")).lower() in _APPROVE_LABELS else "reject"
    if p_ok is not None:
        return "approve" if p_ok >= 0.5 else "reject"
    return None


def overrode_engine(action: str, lean: str | None) -> bool:
    """An officer overrides the engine when they approve what it leaned to reject, or the reverse."""
    return action in ("approve", "reject") and lean in ("approve", "reject") and action != lean


def review_seconds(first_seen: datetime | None, now: datetime) -> int | None:
    if first_seen is None:
        return None
    return max(0, int((now - first_seen).total_seconds()))
