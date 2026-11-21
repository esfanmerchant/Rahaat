"""Rate limits as they stand right now for the admin's department: its two lanes, its people and its API keys."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import apikeys, ratelimit
from app.core.config import get_settings
from app.core.deps import Principal, get_db
from app.core.policy import Policy, describe_routes
from app.db import models

router = APIRouter(prefix="/v1/admin/rate-limits", tags=["admin: rate limits"])
_read = Policy("ratelimits:read", ["admin"], description="Current rate-limit use of this department, its people and its API keys")


class LimitsOut(BaseModel):
    enabled: bool
    anonymous_per_minute: int = Field(description="Per client network, for calls without a valid sign-in")
    user_per_minute: int
    department_per_minute: int = Field(description="Each of the two department lanes (people, API keys)")
    api_key_default_per_minute: int


class BucketOut(BaseModel):
    label: str
    per_minute: int
    remaining: int = Field(description="Requests that could be made right now")
    seconds_to_full: int


class PersonBucketOut(BucketOut):
    user_id: UUID
    display_name: str | None = None


class KeyBucketOut(BucketOut):
    key_id: UUID | None = None
    name: str | None = None


class RouteCostOut(BaseModel):
    method: str
    path: str
    cost: int


class RateLimitsOut(BaseModel):
    limits: LimitsOut
    department: list[BucketOut] = Field(description="Only lanes used since the process started appear here")
    people: list[PersonBucketOut]
    api_keys: list[KeyBucketOut]
    api_calls_this_month: int
    period: str
    costly_routes: list[RouteCostOut] = Field(description="Routes that count as more than one request")


@router.get("", response_model=RateLimitsOut, summary="Rate-limit use right now, and API calls metered this month")
def usage(request: Request, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> RateLimitsOut:
    limits = get_settings().rate_limits()
    views = ratelimit.LIMITER.snapshot(principal.tenant_id)
    user_ids = {UUID(v.label) for v in views if v.scope == "user"}
    names = dict(db.execute(select(models.User.id, models.User.display_name).where(models.User.id.in_(user_ids))).tuples().all()) if user_ids else {}
    key_rows = db.execute(select(models.ApiKey.prefix, models.ApiKey.id, models.ApiKey.name)
                          .where(models.ApiKey.tenant_id == principal.tenant_id)).tuples().all()  # fmt: skip
    keys = {prefix: (key_id, name) for prefix, key_id, name in key_rows}

    def base(v: ratelimit.BucketView) -> dict[str, object]:
        return {"label": v.label, "per_minute": v.per_minute, "remaining": v.remaining, "seconds_to_full": v.seconds_to_full}

    now = datetime.now(UTC)
    return RateLimitsOut(
        limits=LimitsOut(enabled=limits.enabled, anonymous_per_minute=limits.anonymous_per_minute, user_per_minute=limits.user_per_minute,
                         department_per_minute=limits.tenant_per_minute, api_key_default_per_minute=limits.api_key_default_per_minute),
        department=[BucketOut.model_validate(base(v)) for v in views if v.scope == "tenant"],
        people=[PersonBucketOut.model_validate({**base(v), "user_id": UUID(v.label), "display_name": names.get(UUID(v.label))})
                for v in views if v.scope == "user"],
        api_keys=[KeyBucketOut.model_validate({**base(v), "key_id": keys.get(v.label, (None, None))[0], "name": keys.get(v.label, (None, None))[1]})
                  for v in views if v.scope == "api_key"],
        api_calls_this_month=apikeys.monthly_calls(db, principal.tenant_id, now=now),
        period=apikeys.period(now),
        costly_routes=[RouteCostOut(method=e["method"], path=e["path"], cost=e["cost"]) for e in describe_routes(request.app) if e["cost"] > 1],
    )  # fmt: skip
