"""The application status machine. Every status change in the system goes through `move()`.

    draft -> submitted -> approved -> paid
                       -> rejected
                       -> needs_proof -> submitted (after more proof)
                       -> in_review   -> approved | rejected | needs_proof
    any open status -> on_hold_consent (consent withdrawn) -> back to where it was
    any open status -> withdrawn (the person stops)

Cases (officer actions) and payments call `move()` too, so an illegal jump such as draft -> paid is
impossible from anywhere.
"""

from __future__ import annotations

from typing import Final, Protocol

from app.contracts.common import ApplicationStatus
from app.core.errors import Conflict

TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "draft": frozenset({"submitted", "on_hold_consent", "withdrawn"}),
    "submitted": frozenset({"approved", "rejected", "needs_proof", "in_review", "on_hold_consent", "withdrawn"}),
    "needs_proof": frozenset({"submitted", "in_review", "on_hold_consent", "withdrawn"}),
    "in_review": frozenset({"approved", "rejected", "needs_proof", "on_hold_consent", "withdrawn"}),
    "approved": frozenset({"paid", "in_review", "on_hold_consent"}),
    "rejected": frozenset({"in_review"}),  # an appeal reopens the case for a person
    "paid": frozenset(),
    "on_hold_consent": frozenset({"draft", "submitted", "needs_proof", "in_review", "approved", "withdrawn"}),
    "withdrawn": frozenset(),
}

# The citizen can still change answers and add proof.
EDITABLE: Final[frozenset[str]] = frozenset({"draft", "needs_proof"})
# Submitting is allowed from here; from anywhere else a repeat submit returns the first result.
SUBMITTABLE: Final[frozenset[str]] = frozenset({"draft", "needs_proof"})
# Withdrawing consent puts these on hold. Approved is included: the payment must not go out without consent.
HOLD_ON_WITHDRAWAL: Final[frozenset[str]] = frozenset({"draft", "submitted", "needs_proof", "in_review", "approved"})

OUTCOME_STATUS: Final[dict[str, ApplicationStatus]] = {
    "approved": "approved",
    "rejected": "rejected",
    "needs_proof": "needs_proof",
    "needs_human": "in_review",
}


def can_move(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def check_move(current: str, target: str) -> None:
    if not can_move(current, target):
        raise Conflict(
            "This application cannot change to that state.",
            code="invalid_transition",
            extra={"from_status": current, "to_status": target},
        )


class _HasStatus(Protocol):
    status: str


def move(application: _HasStatus, target: str) -> str:
    """Change the status if the machine allows it. Returns the previous status."""
    previous = application.status
    check_move(previous, target)
    application.status = target
    return previous


def resume_status(held_from: str | None, *, submitted: bool) -> str:
    """Where an application on hold goes back to when consent is granted again."""
    if held_from and held_from in TRANSITIONS["on_hold_consent"]:
        return held_from
    # Unknown history: a submitted application goes to a person, a draft stays a draft.
    return "in_review" if submitted else "draft"
