"""Compute the public pulse: counts and sums over the demo departments, and a replay of the labelled synthetic cases.

Reads use a system session and plain aggregate queries, so nothing personal is selected. The replay is scored by the active
rule version and model with the evals functions, so every number comes from the running engine.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import system_session
from app.db import models
from app.demo_accounts import DEMO_TENANTS
from app.modules.decision.engine import route_for
from app.modules.decision.model import get_model
from app.modules.evals import decision_eval as E
from app.modules.evals import service as evals_service
from app.modules.pulse import shaping as S

CACHE_SECONDS: Final = 15.0
_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "value": None}


def live_counts(db: Session, tenant_ids: list[Any]) -> dict[str, Any]:
    """Aggregate counts and sums across the given departments. Group-by queries only; no row-level data leaves."""
    apps = db.execute(
        select(models.Application.status, func.count()).where(models.Application.tenant_id.in_(tenant_ids)).group_by(models.Application.status)
    ).all()  # fmt: skip
    decisions = db.execute(
        select(models.Decision.route, models.Decision.outcome, func.count()).where(models.Decision.tenant_id.in_(tenant_ids))
        .group_by(models.Decision.route, models.Decision.outcome)
    ).all()  # fmt: skip
    pays = db.execute(
        select(models.Payment.status, func.count(), func.coalesce(func.sum(models.Payment.amount_pkr), 0))
        .where(models.Payment.tenant_id.in_(tenant_ids)).group_by(models.Payment.status)
    ).all()  # fmt: skip
    scams = db.execute(
        select(models.ScamReport.label, func.count()).where(models.ScamReport.tenant_id.in_(tenant_ids)).group_by(models.ScamReport.label)
    ).all()  # fmt: skip
    chain = db.scalar(select(func.count()).select_from(models.AuditLog).where(models.AuditLog.tenant_id.in_(tenant_ids))) or 0
    return {
        "applications_by_status": S.count_map(((str(a), int(b)) for a, b in apps), S.APPLICATION_STATUSES),
        "decisions_by_route": S.decisions_by_route((str(a), str(b), int(c)) for a, b, c in decisions),
        "payments": S.payments_shape((str(a), int(b), int(c)) for a, b, c in pays),
        "scam": S.scam_shape((str(a), int(b)) for a, b in scams),
        "audit_chain_length": int(chain),
        "departments": len(tenant_ids),
    }


def replay(db: Session, tenant_ids: list[Any]) -> dict[str, Any]:
    """Score the held-out labelled set by the first demo department that has active rules."""
    for tenant_id in tenant_ids:
        rules = evals_service.active_snapshot(db, tenant_id)
        if rules is None:
            continue
        costs = evals_service.tenant_costs(db, tenant_id)
        model = get_model()
        scores = E.cached_scores(rules.dsl, model)
        report = E.analyse(scores, costs)
        params = rules.dsl.get("params") if isinstance(rules.dsl, dict) else None
        floor = float((params or {}).get("confidence_floor", 0.0))
        approve_at = float(report["thresholds"]["approve"])
        rows = []
        for s in S.sample(scores):
            action, _ = route_for(s.pricing, costs)
            code = S.reason_code(action, s.pricing.guards, s.pricing.proof, s.pricing.p_ok, approve_at)
            rows.append(S.replay_row(action, p_ok=s.pricing.p_ok, ok=s.ok, eligible=s.eligible, kind=s.fraud or s.truth_class, code=code))
        return {
            "available": True, "replay_source": S.REPLAY_SOURCE, "rule_version_no": rules.version_no, "model_version": model.version,
            "cases_scored": len(scores), "cases": rows, "headline": S.headline(report["operating_point"], report["thresholds"], floor),
        }  # fmt: skip
    return {"available": False, "replay_source": S.REPLAY_SOURCE, "rule_version_no": None, "model_version": None, "cases_scored": 0, "cases": [],
            "headline": None}  # fmt: skip


def demo_slugs() -> list[str]:
    return [t["slug"] for t in DEMO_TENANTS]


def compute() -> dict[str, Any]:
    started = time.perf_counter()
    slugs = demo_slugs()
    with system_session() as db:
        tenants = db.execute(select(models.Tenant.id, models.Tenant.slug).where(models.Tenant.slug.in_(slugs))).all()
        order = {slug: i for i, slug in enumerate(slugs)}
        ids = [row[0] for row in sorted(tenants, key=lambda r: order.get(r[1], 99))]
        counts = live_counts(db, ids)
        replayed = replay(db, ids)
    return {
        "generated_at": datetime.now(UTC).isoformat(), "cache_seconds": int(CACHE_SECONDS),
        "notice": "Prototype. Not an official service. Counts are from the demo departments; the replay is synthetic.",
        "live": counts, "replay": replayed, "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }  # fmt: skip


def pulse(now: float | None = None) -> dict[str, Any]:
    """The pulse, recomputed at most every `CACHE_SECONDS` seconds per process."""
    clock = time.monotonic() if now is None else now
    with _lock:
        hit = _cache["value"]
        if hit is not None and clock - float(_cache["at"]) < CACHE_SECONDS:
            return hit  # type: ignore[no-any-return]
    value = compute()
    with _lock:
        _cache.update(at=clock, value=value)
    return value


def reset_cache() -> None:
    with _lock:
        _cache.update(at=0.0, value=None)
