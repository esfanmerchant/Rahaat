"""Decisions API (`/v1/decisions`): the list, one decision's two views, and replay.

    GET  /v1/decisions                  paged and filtered list (route, outcome, rule version, dates); no personal data
    GET  /v1/decisions/{id}             the citizen's reason and the full trace (auditors: masked)
    POST /v1/decisions/{id}/replay      recompute from the stored snapshot and pinned versions; differences listed

Officers see the raw trace only when Row Level Security lets them read the application (an active consent);
otherwise the attempt is refused and recorded. Auditors always get identifiers and names masked.
"""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.contracts.decision import ReplayResult
from app.core import audit, metrics
from app.core.deps import Principal, get_db
from app.core.errors import Forbidden, NotFound
from app.core.policy import Policy
from app.db import models
from app.modules.decision import replay as replay_service
from app.modules.decision import service
from app.modules.decision.model import get_model
from app.modules.decision.schemas import DecisionList, DecisionView

router = APIRouter(prefix="/v1/decisions", tags=["decisions"])
_read = Policy("decisions:read", ["officer", "auditor"], description="A decision's explanation and trace (auditors: masked)")
_list = Policy("decisions:list", ["officer", "auditor"], description="The decision list, without personal data")
_replay = Policy("decisions:replay", ["officer", "auditor"], description="Recompute a stored decision and compare")

__all__ = ["DecisionView", "router"]


def _load(db: Session, principal: Principal, decision_id: UUID) -> models.Decision:
    decision = db.get(models.Decision, decision_id)
    if decision is None or decision.tenant_id != principal.tenant_id:
        raise NotFound("Decision not found.", code="decision_not_found")
    if principal.role == "officer" and db.get(models.Application, decision.application_id) is None:
        metrics.ACCESS_DENIED.labels("consent").inc()
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="decision", object_id=decision.id, result="denied", reason="no_active_consent",
            details={"application_id": str(decision.application_id)},
        )  # fmt: skip
        raise Forbidden("You cannot see this person's case without their active consent.", code="consent_required")
    return decision


@router.get("", response_model=DecisionList, summary="Decisions, newest first, filtered; no personal data")
def list_decisions(
    principal: Principal = Depends(_list),
    db: Session = Depends(get_db),
    route: Literal["auto", "ask_more", "human"] | None = Query(None),
    outcome: Literal["approved", "rejected", "needs_proof", "needs_human"] | None = Query(None),
    rule_version_id: UUID | None = Query(None),
    rule_version_no: int | None = Query(None, ge=1),
    decided_from: date | None = Query(None, description="First day, inclusive (UTC)"),
    decided_to: date | None = Query(None, description="Last day, inclusive (UTC)"),
    application_id: UUID | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=120),
) -> DecisionList:
    return replay_service.list_decisions(db, principal, route=route, outcome=outcome, rule_version_id=rule_version_id,
                                         rule_version_no=rule_version_no, decided_from=decided_from, decided_to=decided_to,
                                         application_id=application_id, limit=limit, cursor=cursor)  # fmt: skip


@router.get("/{decision_id}", response_model=DecisionView, summary="A decision: the citizen's reason and the auditor's trace")
def get_decision(decision_id: UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> DecisionView:
    decision = _load(db, principal, decision_id)
    redact = principal.role != "officer"
    return DecisionView(user_view=service.user_view(decision), trace=service.trace_view(db, decision, redact=redact), case_id=decision.case_id,
                        replay_available=decision.model_version == get_model().version)  # fmt: skip


@router.post("/{decision_id}/replay", response_model=ReplayResult, summary="Recompute from the stored snapshot and pinned versions")
def replay(decision_id: UUID, principal: Principal = Depends(_replay), db: Session = Depends(get_db)) -> ReplayResult:
    decision = _load(db, principal, decision_id)
    result = replay_service.replay(db, decision)
    audit.write(
        db, tenant_id=principal.tenant_id, action="decision.replayed", actor_id=principal.user_id, actor_role=principal.role,
        object_type="decision", object_id=decision.id, input_hash=decision.input_hash, model_version=decision.model_version,
        rule_version_id=decision.rule_version_id, result="ok" if result.match else "mismatch",
        details={"match": result.match, "replayed_result_hash": result.replayed_result_hash, "differences": len(result.differences)},
    )  # fmt: skip
    db.commit()
    return result
