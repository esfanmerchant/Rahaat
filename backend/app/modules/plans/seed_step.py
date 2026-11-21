"""Seed: the three public plans, and the demo departments on `government` (high limits)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.demo_accounts import DEMO_TENANTS
from app.modules.plans import rules

ORDER = 30


def seed(db: Session) -> None:
    existing = {p.code: p for p in db.scalars(select(models.Plan)).all()}
    for code, name, price, limits in rules.PLAN_CATALOGUE:
        plan = existing.get(code)
        if plan is None:
            plan = models.Plan(code=code, name=name, price_pkr=price, limits=dict(limits))
            db.add(plan)
        else:
            plan.name, plan.price_pkr, plan.limits = name, price, dict(limits)
        existing[code] = plan
    db.flush()
    demo = existing[rules.DEMO_PLAN]
    for spec in DEMO_TENANTS:
        tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == spec["slug"]))
        if tenant is not None and tenant.plan_id != demo.id:
            tenant.plan_id = demo.id
