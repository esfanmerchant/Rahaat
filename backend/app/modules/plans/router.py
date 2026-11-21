"""Usage and plans. Changing a department's plan is not an API call: there is no platform-admin role (see DECISIONS)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import system_session
from app.core.deps import Principal, get_db
from app.core.policy import Policy, Public
from app.modules.plans import service

router = APIRouter(tags=["plans and usage"])
_usage = Policy("usage:read", ["admin"], description="This department's monthly usage against its plan limits")


class MetricUsage(BaseModel):
    metric: str
    label: str
    used: int
    limit: int | None = Field(description="None when the plan does not limit this metric")
    percent_used: float | None
    reached: bool = Field(description="True when the next unit would be refused")


class MonthUsage(BaseModel):
    period: str = Field(description="YYYY-MM, UTC")
    counts: dict[str, int]


class PlanRef(BaseModel):
    code: str
    name: str


class UsageOut(BaseModel):
    period: str
    resets_at: str
    plan: PlanRef | None = Field(description="None when the department has no plan: nothing is limited")
    metrics: list[MetricUsage]
    history: list[MonthUsage] = Field(description="The five months before this one, newest first")


class PlanOut(BaseModel):
    code: str
    name: str
    price_pkr: int = Field(description="Per month; prototype figures only")
    limits: dict[str, int]


@router.get("/v1/admin/usage", response_model=UsageOut, summary="This month's usage with limits and percent used, and the months before")
def get_usage(principal: Principal = Depends(_usage), db: Session = Depends(get_db)) -> UsageOut:
    return UsageOut.model_validate(service.usage_report(db, principal.tenant_id))


@router.get("/v1/plans", response_model=list[PlanOut], summary="The plans and their monthly limits (prototype figures)")
def list_plans(_: None = Depends(Public("The plan catalogue is public information; no personal or department data"))) -> list[PlanOut]:
    with system_session() as db:  # the plans table is global and readable by everyone; this reads nothing else
        return [PlanOut.model_validate(p) for p in service.public_plans(db)]
