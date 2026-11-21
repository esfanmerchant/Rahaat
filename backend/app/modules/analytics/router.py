"""The impact report.

GET /v1/admin/impact    handoff rate, time to decision, fraud flagged, cost per claim, payments, time saved; counted from this department's rows
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.analytics import impact, service
from app.modules.analytics.schemas import ImpactOut

router = APIRouter(prefix="/v1/admin", tags=["admin: impact"])
_read = Policy(
    "impact:read", ["admin", "officer"], description="The department's impact report: counted from its own decisions, cases and payments", cost=3
)


@router.get("/impact", response_model=ImpactOut, summary="Impact report: handoff rate, time, fraud flagged, cost per claim, payments")
def get_impact(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    days: int = Query(90, ge=1, le=365, description="Window in days"),
    assumed_minutes_per_manual_review: float = Query(
        impact.ASSUMED_MINUTES_PER_MANUAL_REVIEW, ge=1, le=240, description="An assumption, used only until officer review times are measured"
    ),
) -> ImpactOut:
    return service.compute(db, principal, days=days, assumed_minutes=assumed_minutes_per_manual_review)
