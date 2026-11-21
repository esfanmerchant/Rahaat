"""Metering and enforcement of plan limits (`usage_counters`, one row per department, metric and month).

    consume(db, tenant_id, "applications")      raises PlanLimitReached (429) when this month's limit is used up
    try_consume(db, tenant_id, "sms")           False instead of raising: for work that can degrade (a text message)

The increment is one atomic `INSERT ... ON CONFLICT DO UPDATE ... WHERE count + n <= limit`: two requests that
race for the last unit cannot both get it, and nothing is read before it is written. It runs in the caller's
transaction, so a request that fails afterwards does not use up a unit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.db import RlsContext, session_scope
from app.core.errors import AppError, NotFound
from app.core.logging import get_logger
from app.db import models
from app.modules.plans import rules

log = get_logger("rahat.plans")


class PlanLimitReached(AppError):
    status, code, title = 429, "plan_limit_reached", "This department has used its plan limit for this month"

    def __init__(self, metric: str, limit: int, used: int, now: datetime) -> None:
        reset = rules.resets_at(now)
        super().__init__(
            f"The monthly limit for {rules.METRIC_LABELS.get(metric, metric).lower()} is used up. It starts again on {reset.date().isoformat()}.",
            extra={"metric": metric, "limit": limit, "used": used, "resets_at": reset.isoformat(timespec="seconds")},
            headers={"Retry-After": str(max(1, int((reset - now).total_seconds())))},
        )  # fmt: skip
        self.metric = metric


def _now() -> datetime:
    return datetime.now(UTC)


def plan_limits(db: Session, tenant_id: uuid.UUID) -> dict[str, Any] | None:
    """The limits of the department's plan, or None when it has no plan (then nothing is limited)."""
    cache: dict[uuid.UUID, dict[str, Any] | None] = db.info.setdefault("plan_limits", {})
    if tenant_id not in cache:
        plan_id = db.scalar(select(models.Tenant.plan_id).where(models.Tenant.id == tenant_id))
        plan = db.get(models.Plan, plan_id) if plan_id else None
        cache[tenant_id] = dict(plan.limits or {}) if plan else None
    return cache[tenant_id]


def used_this_month(db: Session, tenant_id: uuid.UUID, metric: str, now: datetime | None = None) -> int:
    value = db.scalar(select(models.UsageCounter.count).where(
        models.UsageCounter.tenant_id == tenant_id, models.UsageCounter.metric == metric,
        models.UsageCounter.period == rules.period_of(now or _now())))  # fmt: skip
    return int(value or 0)


def try_consume(db: Session, tenant_id: uuid.UUID, metric: str, amount: int = 1, *, now: datetime | None = None) -> bool:
    """Take `amount` units of this month's allowance. False (and nothing written) when the limit would be passed."""
    if metric not in rules.METRICS:
        raise ValueError(f"unknown usage metric {metric!r}")
    now = now or _now()
    limit = rules.limit_for(plan_limits(db, tenant_id), metric)
    if limit is not None and amount > limit:
        return False  # a first row of a limited metric must not start above the limit either
    insert = pg_insert(models.UsageCounter).values(
        id=uuid.uuid4(), tenant_id=tenant_id, metric=metric, period=rules.period_of(now), count=amount, updated_at=now
    )
    upsert = insert.on_conflict_do_update(
        constraint="uq_usage_counter",
        set_={"count": models.UsageCounter.count + amount, "updated_at": now},
        where=None if limit is None else (models.UsageCounter.count + amount <= limit),
    ).returning(models.UsageCounter.count)
    return db.execute(upsert).first() is not None


def consume(db: Session, tenant_id: uuid.UUID, metric: str, amount: int = 1, *, now: datetime | None = None) -> None:
    now = now or _now()
    if try_consume(db, tenant_id, metric, amount, now=now):
        return
    limit = rules.limit_for(plan_limits(db, tenant_id), metric) or 0
    raise PlanLimitReached(metric, limit, used_this_month(db, tenant_id, metric, now), now)


def consume_committed(rls: RlsContext, tenant_id: uuid.UUID, metric: str, amount: int = 1) -> None:
    """`consume` in its own committed transaction, for endpoints that do not commit (or commit late) themselves."""
    with session_scope(rls) as db:
        consume(db, tenant_id, metric, amount)


def enforce_api_calls(tenant_id: uuid.UUID, key_id: uuid.UUID) -> None:
    """Refuse an API key call once this month's `api_calls` are used up. Metering itself is `apikeys.record_use`."""
    now = _now()
    ctx = RlsContext(role="api_client", tenant_id=tenant_id, user_id=key_id)
    with session_scope(ctx) as db:
        limit = rules.limit_for(plan_limits(db, tenant_id), "api_calls")
        if limit is None:
            return
        used = used_this_month(db, tenant_id, "api_calls", now)
        if rules.would_exceed(used, 1, limit):
            raise PlanLimitReached("api_calls", limit, used, now)


# --- reports and administration -----------------------------------------------------------------------


def usage_report(db: Session, tenant_id: uuid.UUID, *, now: datetime | None = None, months: int = 6) -> dict[str, Any]:
    now = now or _now()
    limits = plan_limits(db, tenant_id)
    tenant = db.get(models.Tenant, tenant_id)
    plan = db.get(models.Plan, tenant.plan_id) if tenant and tenant.plan_id else None
    periods = rules.previous_periods(now, months)
    rows = db.execute(select(models.UsageCounter.period, models.UsageCounter.metric, models.UsageCounter.count).where(
        models.UsageCounter.tenant_id == tenant_id, models.UsageCounter.period.in_(periods))).all()  # fmt: skip
    counts: dict[str, dict[str, int]] = {p: {} for p in periods}
    for period, metric, count in rows:
        counts[period][metric] = int(count)
    current = periods[-1]
    metrics = []
    for metric in rules.METRICS:
        used = counts[current].get(metric, 0)
        limit = rules.limit_for(limits, metric)
        metrics.append({"metric": metric, "label": rules.METRIC_LABELS[metric], "used": used, "limit": limit,
                        "percent_used": rules.percent_used(used, limit), "reached": rules.would_exceed(used, 1, limit)})  # fmt: skip
    return {
        "period": current, "resets_at": rules.resets_at(now).isoformat(timespec="seconds"),
        "plan": {"code": plan.code, "name": plan.name} if plan else None, "metrics": metrics,
        "history": [{"period": p, "counts": {m: counts[p].get(m, 0) for m in rules.METRICS}} for p in reversed(periods[:-1])],
    }  # fmt: skip


def public_plans(db: Session) -> list[dict[str, Any]]:
    rows = {p.code: p for p in db.scalars(select(models.Plan).where(models.Plan.code.in_(rules.PUBLIC_PLAN_CODES))).all()}
    return [{"code": c, "name": rows[c].name, "price_pkr": rows[c].price_pkr, "limits": dict(rows[c].limits or {})}
            for c in rules.PUBLIC_PLAN_CODES if c in rows]  # fmt: skip


def set_tenant_plan(db: Session, tenant_id: uuid.UUID, code: str) -> None:
    """Platform operation (seed, CLI). There is no platform-admin role in the API, so no endpoint changes a plan."""
    plan = db.scalar(select(models.Plan).where(models.Plan.code == code))
    tenant = db.get(models.Tenant, tenant_id)
    if plan is None or tenant is None:
        raise NotFound("No such plan or department.")
    tenant.plan_id = plan.id
