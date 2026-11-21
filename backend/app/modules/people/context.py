"""Which person is this request about? One dependency answers it for every person-facing route.

* A citizen is always their own person (`person_id` from the verified token).
* A helper names the person in `X-Acting-For`, must hold a live, unexpired delegation from that person
  whose scopes cover the action, and must send the switch ticket that the family's PIN unlocked for this
  session (`X-Helper-Ticket`, see `app/modules/helpers/tickets.py`). Anything else is a 403 and an audit
  row that survives the failed request.

A person id is never read from the body or the query string. Row Level Security checks the same thing
again inside the database (`app_can_read_person`), so a bug here still cannot leak another person's data.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, metrics
from app.core.deps import Principal, get_db
from app.core.errors import Forbidden
from app.core.policy import Policy
from app.db import models
from app.modules.helpers import tickets

Scope = Literal["track", "apply", "upload"]
DELEGATION_SCOPES: Final[frozenset[str]] = frozenset({"track", "apply", "upload"})
PERSON_ROLES: Final = ("citizen", "helper")

# Calls that are metered as `ai_calls` against the department's plan (the person check has passed by then).
# Typing the answer instead of speaking it always works, so refusing a spoken one never blocks an application.
AI_CALL_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset({("POST", "/v1/voice/interpret"), ("POST", "/v1/voice/stt")})

_DENIED_MESSAGE = "You cannot do this for that person."
_TICKET_MESSAGES: Final[dict[str, str]] = {
    "ticket_required": "Enter this family's PIN first.",
    "ticket_invalid": "Enter this family's PIN again.",
    "ticket_expired": "Enter this family's PIN again.",
}


@dataclass(frozen=True, slots=True)
class PersonContext:
    principal: Principal
    person_id: UUID
    via_helper: bool
    scope: str

    @property
    def tenant_id(self) -> UUID:
        return self.principal.tenant_id

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id

    def audit_fields(self) -> dict[str, Any]:
        """Who did it and for whom, for `audit.write`. A helper's rows name both the helper and the person."""
        return {
            "actor_id": self.principal.user_id,
            "actor_role": self.principal.role,
            "acting_for_person_id": self.person_id if self.via_helper else None,
        }


def deny(principal: Principal, code: str, *, scope: str, person_id: UUID | None = None, detail: str = _DENIED_MESSAGE,
         extra: dict[str, Any] | None = None) -> Forbidden:  # fmt: skip
    """Record the refused attempt in its own transaction, then return the error to raise."""
    metrics.ACCESS_DENIED.labels("person").inc()
    audit.write_independent(
        tenant_id=principal.tenant_id,
        action="access.denied",
        actor_id=principal.user_id,
        actor_role=principal.role,
        acting_for_person_id=person_id,
        object_type="person",
        object_id=person_id,
        result="denied",
        reason=code,
        details={"scope": scope, **(extra or {})},
    )
    return Forbidden(detail, code=code)


def _parse_person_id(raw: str | None) -> UUID | None:
    if not raw or not raw.strip():
        return None
    try:
        return UUID(raw.strip())
    except ValueError:
        return None


def live_delegations(db: Session, *, tenant_id: UUID, helper_user_id: UUID, person_id: UUID) -> list[models.HelperDelegation]:
    now = datetime.now(UTC)
    return list(
        db.scalars(
            select(models.HelperDelegation).where(
                models.HelperDelegation.tenant_id == tenant_id,
                models.HelperDelegation.helper_user_id == helper_user_id,
                models.HelperDelegation.person_id == person_id,
                models.HelperDelegation.revoked_at.is_(None),
                models.HelperDelegation.expires_at > now,
            )
        ).all()
    )


def resolve_person(db: Session, principal: Principal, acting_for: str | None, scope: str, ticket: str | None = None) -> PersonContext:
    """The core check, separate from FastAPI so it can be called from sync and other non-HTTP entry points.

    Order for a helper: which person, a live delegation, the scope, then the switch ticket. Every refusal
    is audited in its own transaction.
    """
    if scope not in DELEGATION_SCOPES:
        raise ValueError(f"unknown delegation scope {scope!r}")
    if principal.role == "citizen":
        if principal.person_id is None:
            raise deny(principal, "no_person_record", scope=scope, detail="Your account has no person record in this department.")
        named = _parse_person_id(acting_for)
        if acting_for and named != principal.person_id:
            raise deny(principal, "acting_for_not_allowed", scope=scope, person_id=named)
        return PersonContext(principal=principal, person_id=principal.person_id, via_helper=False, scope=scope)

    if principal.role == "helper":
        if not acting_for or not acting_for.strip():
            raise deny(principal, "acting_for_required", scope=scope, detail="Choose the family you are helping first.")
        person_id = _parse_person_id(acting_for)
        if person_id is None:
            raise deny(principal, "acting_for_invalid", scope=scope)
        delegations = live_delegations(db, tenant_id=principal.tenant_id, helper_user_id=principal.user_id, person_id=person_id)
        if not delegations:
            raise deny(principal, "no_delegation", scope=scope, person_id=person_id)
        if not any(scope in (d.scopes or []) for d in delegations):
            raise deny(principal, "scope_not_delegated", scope=scope, person_id=person_id)
        record = tickets.latest_switch(db, tenant_id=principal.tenant_id, session_id=principal.session_id)
        refused = tickets.check_ticket(record, ticket=ticket, person_id=person_id, live_delegation_ids=[d.id for d in delegations],
                                       now=datetime.now(UTC))  # fmt: skip
        if refused is not None:
            raise deny(principal, refused, scope=scope, person_id=person_id, detail=_TICKET_MESSAGES[refused])
        acting = dataclasses.replace(principal, acting_for_person_id=person_id)
        return PersonContext(principal=acting, person_id=person_id, via_helper=True, scope=scope)

    raise deny(principal, "role_not_allowed", scope=scope)


def acting_person(policy_name: str, scope: Scope, *, description: str = "") -> Callable[..., PersonContext]:
    """Route dependency: the policy marker (citizen or helper) plus the person check for `scope`."""
    policy = Policy(policy_name, PERSON_ROLES, description=description or f"A citizen for themself, or a helper with the {scope!r} scope")

    def dependency(
        request: Request,
        principal: Principal = Depends(policy),
        db: Session = Depends(get_db),
        x_acting_for: str | None = Header(
            default=None, alias="X-Acting-For", description="Helpers only: the person id this request is for"
        ),
        x_helper_ticket: str | None = Header(
            default=None, alias="X-Helper-Ticket", max_length=128,
            description="Helpers only: the ticket from POST /v1/helper/switch for that person",
        ),
    ) -> PersonContext:
        ctx = resolve_person(db, principal, x_acting_for, scope, x_helper_ticket)
        if (request.method, request.url.path) in AI_CALL_ROUTES:
            from app.modules.plans.service import consume_committed  # imported here: plans does not import people

            consume_committed(ctx.principal.rls(), ctx.tenant_id, "ai_calls")
        request.state.principal = ctx.principal
        return ctx

    return dependency
