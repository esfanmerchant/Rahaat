"""`GET /v1/decisions/{id}`: the citizen's reason and the full trace, for officers and auditors.

Officers see the raw trace only when Row Level Security lets them read the application (an active consent);
otherwise the attempt is refused and recorded. Auditors always get identifiers and names masked.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts.decision import DecisionTrace, DecisionUserView
from app.core import audit, metrics
from app.core.deps import Principal, get_db
from app.core.errors import Forbidden, NotFound
from app.core.policy import Policy
from app.db import models
from app.modules.decision import service

router = APIRouter(prefix="/v1/decisions", tags=["decisions"])
_read = Policy("decisions:read", ["officer", "auditor"], description="A decision's explanation and trace (auditors: masked)")


class DecisionView(BaseModel):
    user_view: DecisionUserView
    trace: DecisionTrace


@router.get("/{decision_id}", response_model=DecisionView, summary="A decision: the citizen's reason and the auditor's trace")
def get_decision(decision_id: UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> DecisionView:
    decision = db.get(models.Decision, decision_id)
    if decision is None or decision.tenant_id != principal.tenant_id:
        raise NotFound("Decision not found.", code="decision_not_found")
    redact = principal.role != "officer"
    if not redact and db.get(models.Application, decision.application_id) is None:
        metrics.ACCESS_DENIED.labels("consent").inc()
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="decision", object_id=decision.id, result="denied", reason="no_active_consent",
            details={"application_id": str(decision.application_id)},
        )  # fmt: skip
        raise Forbidden("You cannot see this person's case without their active consent.", code="consent_required")
    return DecisionView(user_view=service.user_view(decision), trace=service.trace_view(db, decision, redact=redact))
