"""Evaluation service: the department's threshold analysis, stored runs, and the cost matrix.

    analysis(db, tenant_id, costs=None)          the analysis for the active rule version (not stored)
    run_and_store(db, principal)                 the same, stored in `eval_runs` (kind "decision")
    latest(db, principal)                        the newest stored run, or a fresh analysis when none exists
    what_if(db, principal, costs)                curves and thresholds for other costs; nothing is saved
    save_cost_matrix(db, principal, costs, reason)   audited; the next decision uses it

Scores of the labelled cases are cached per rule content and model, so only the first analysis of a rule
version pays for scoring (about a second); every later one, slider moves included, takes tens of ms.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.decision import CostMatrix
from app.contracts.engine import RuleSetSnapshot
from app.core import audit
from app.core.deps import Principal
from app.core.errors import NotFound
from app.db import models
from app.modules.decision import paging
from app.modules.decision.model import get_model
from app.modules.evals import decision_eval as E
from app.modules.evals.schemas import CostMatrixOut, DecisionAnalysisOut, EvalRunList, EvalRunSummary, ThresholdsOut
from app.modules.rules import service as rules_service

KIND = "decision"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def active_snapshot(db: Session, tenant_id: uuid.UUID) -> RuleSetSnapshot | None:
    """The active rule version of the department's first rule set, or None when it has none."""
    rule_set = db.scalar(select(models.RuleSet).where(models.RuleSet.tenant_id == tenant_id).order_by(models.RuleSet.created_at).limit(1))
    if rule_set is None or rule_set.active_version_id is None:
        return None
    version = db.get(models.RuleVersion, rule_set.active_version_id)
    return rules_service.snapshot(version) if version is not None else None


def tenant_costs(db: Session, tenant_id: uuid.UUID) -> CostMatrix:
    tenant = db.get(models.Tenant, tenant_id)
    return CostMatrix.model_validate((tenant.cost_matrix if tenant else None) or {})


def _rules(db: Session, tenant_id: uuid.UUID) -> RuleSetSnapshot:
    snapshot = active_snapshot(db, tenant_id)
    if snapshot is None:
        raise NotFound("This department has no published rules to analyse.", code="no_active_rules")
    return snapshot


def analysis(db: Session, tenant_id: uuid.UUID, costs: CostMatrix | None = None, *, rules: RuleSetSnapshot | None = None) -> dict[str, Any]:
    """The full analysis as a dict (the shape of `DecisionAnalysisOut`, without run fields)."""
    started = time.perf_counter()
    rules = rules or _rules(db, tenant_id)
    costs = costs or tenant_costs(db, tenant_id)
    model = get_model()
    scores = E.cached_scores(rules.dsl, model)
    report = E.analyse(scores, costs)
    report.update({
        "rule_version_id": rules.rule_version_id, "rule_version_no": rules.version_no, "model_version": model.version,
        "dataset": E.dataset_info(E.heldout_world(), scores), "elapsed_ms": int((time.perf_counter() - started) * 1000),
    })  # fmt: skip
    return report


def to_out(report: dict[str, Any], *, run: models.EvalRun | None = None) -> DecisionAnalysisOut:
    return DecisionAnalysisOut.model_validate({
        **report, "run_id": run.id if run else None, "stored": run is not None, "created_at": _iso(run.created_at) if run else None,
    })  # fmt: skip


def _store(db: Session, tenant_id: uuid.UUID, report: dict[str, Any], *, actor: Principal | None, note: str | None) -> models.EvalRun:
    metrics = {
        "operating_point": report["operating_point"], "thresholds": report["thresholds"], "best_threshold": report["best_threshold"],
        "roc_auc": report["roc_auc"], "average_precision": report["average_precision"], "ece": report["reliability"]["ece"],
        "brier": report["reliability"]["brier"], "costs": report["costs"], "dataset": report["dataset"],
        "rule_version_no": report["rule_version_no"], "note": note,
    }  # fmt: skip
    artifacts = {
        "cost_curve": report["cost_curve"], "roc": report["roc"], "pr": report["pr"], "reliability": report["reliability"],
        "confusion": report["confusion"], "explanation": report["explanation"], "approvable_cases": report["approvable_cases"],
    }  # fmt: skip
    run = models.EvalRun(
        id=uuid.uuid4(), tenant_id=tenant_id, kind=KIND, model_version=report["model_version"],
        rule_version_id=uuid.UUID(report["rule_version_id"]) if report.get("rule_version_id") else None, status="done",
        metrics=metrics, artifacts=artifacts, created_at=datetime.now(UTC),
    )  # fmt: skip
    db.add(run)
    db.flush()
    audit.write(
        db, tenant_id=tenant_id, action="eval.run_stored", actor_type="user" if actor else "system",
        actor_id=actor.user_id if actor else None, actor_role=actor.role if actor else None, object_type="eval_run", object_id=run.id,
        model_version=run.model_version, rule_version_id=run.rule_version_id,
        details={"kind": KIND, "cost_per_case": report["operating_point"]["cost_per_case"],
                 "false_approvals": report["operating_point"]["false_approvals"], "cases": report["operating_point"]["n"]},
    )  # fmt: skip
    return run


def _report_of(run: models.EvalRun) -> dict[str, Any]:
    m, a = run.metrics or {}, run.artifacts or {}
    return {
        "costs": m.get("costs", {}), "thresholds": m.get("thresholds", {}), "operating_point": m.get("operating_point", {}),
        "confusion": a.get("confusion", {}), "cost_curve": a.get("cost_curve", []), "best_threshold": m.get("best_threshold", {}),
        "roc": a.get("roc", []), "roc_auc": m.get("roc_auc"), "pr": a.get("pr", []), "average_precision": m.get("average_precision"),
        "approvable_cases": a.get("approvable_cases", 0), "reliability": a.get("reliability", {}), "explanation": a.get("explanation", ""),
        "dataset": m.get("dataset", {}), "rule_version_id": str(run.rule_version_id) if run.rule_version_id else None,
        "rule_version_no": m.get("rule_version_no"), "model_version": run.model_version or "", "elapsed_ms": None,
    }  # fmt: skip


def run_and_store(db: Session, principal: Principal, *, note: str | None = None) -> DecisionAnalysisOut:
    report = analysis(db, principal.tenant_id)
    run = _store(db, principal.tenant_id, report, actor=principal, note=note)
    return to_out(report, run=run)


def latest_run(db: Session, tenant_id: uuid.UUID, kind: str = KIND) -> models.EvalRun | None:
    return db.scalar(
        select(models.EvalRun).where(models.EvalRun.tenant_id == tenant_id, models.EvalRun.kind == kind)
        .order_by(models.EvalRun.created_at.desc(), models.EvalRun.id.desc()).limit(1)
    )  # fmt: skip


def latest(db: Session, principal: Principal) -> DecisionAnalysisOut:
    """The newest stored run if it matches the active rules and costs; otherwise a fresh analysis (not stored)."""
    run = latest_run(db, principal.tenant_id)
    rules = active_snapshot(db, principal.tenant_id)
    costs = tenant_costs(db, principal.tenant_id)
    if run is not None and rules is not None:
        current = str(run.rule_version_id) == rules.rule_version_id and (run.metrics or {}).get("costs") == costs.model_dump(mode="json")
        if current and run.model_version == get_model().version:
            return to_out(_report_of(run), run=run)
    return to_out(analysis(db, principal.tenant_id, costs, rules=rules))


def what_if(db: Session, principal: Principal, costs: CostMatrix) -> DecisionAnalysisOut:
    return to_out(analysis(db, principal.tenant_id, costs))


def list_runs(db: Session, principal: Principal, *, kind: str | None, limit: int, before: str | None) -> EvalRunList:
    query = select(models.EvalRun).where(models.EvalRun.tenant_id == principal.tenant_id)
    if kind:
        query = query.where(models.EvalRun.kind == kind)
    after = paging.before((models.EvalRun.created_at, models.EvalRun.id), before)
    if after is not None:
        query = query.where(after)
    rows = db.scalars(query.order_by(models.EvalRun.created_at.desc(), models.EvalRun.id.desc()).limit(limit + 1)).all()
    items = [EvalRunSummary(id=r.id, kind=r.kind, created_at=_iso(r.created_at) or "", model_version=r.model_version,
                            rule_version_id=r.rule_version_id, metrics={k: v for k, v in (r.metrics or {}).items() if k != "dataset"})
             for r in rows[:limit]]  # fmt: skip
    cursor = paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None
    return EvalRunList(items=items, next_cursor=cursor)


# --- the cost matrix -----------------------------------------------------------------------------------


def thresholds_of(costs: CostMatrix) -> ThresholdsOut:
    return ThresholdsOut(
        approve=round(costs.approve_threshold(1.0), 4), reject=round(costs.reject_threshold(1.0), 4), queue_days=1.0,
        approve_formula=f"1 - ({costs.human_review:g} + {costs.delay_per_day:g} x 1 day) / {costs.wrong_approve:g}",
        reject_formula=f"1 - ({costs.human_review:g} + {costs.delay_per_day:g} x 1 day) / {costs.wrong_reject:g}",
    )  # fmt: skip


def get_cost_matrix(db: Session, principal: Principal) -> CostMatrixOut:
    costs = tenant_costs(db, principal.tenant_id)
    return CostMatrixOut(costs=costs, thresholds=thresholds_of(costs))


def save_cost_matrix(db: Session, principal: Principal, costs: CostMatrix, reason: str) -> CostMatrixOut:
    """Store the department's costs (audited, old and new). The next decision reads them; thresholds follow."""
    tenant = db.get(models.Tenant, principal.tenant_id)
    if tenant is None:
        raise NotFound("Department not found.", code="tenant_not_found")
    before = CostMatrix.model_validate(tenant.cost_matrix or {})
    tenant.cost_matrix = costs.model_dump(mode="json")
    db.flush()
    audit.write(
        db, tenant_id=principal.tenant_id, action="tenant.cost_matrix_changed", actor_id=principal.user_id, actor_role=principal.role,
        object_type="tenant", object_id=principal.tenant_id, reason=reason,
        details={"before": before.model_dump(mode="json"), "after": costs.model_dump(mode="json"),
                 "approve_threshold": {"before": round(before.approve_threshold(1.0), 4), "after": round(costs.approve_threshold(1.0), 4)},
                 "reject_threshold": {"before": round(before.reject_threshold(1.0), 4), "after": round(costs.reject_threshold(1.0), 4)}},
    )  # fmt: skip
    run_id = None
    if active_snapshot(db, principal.tenant_id) is not None:
        report = analysis(db, principal.tenant_id, costs)
        run_id = _store(db, principal.tenant_id, report, actor=principal, note="cost matrix saved").id
    return CostMatrixOut(costs=costs, thresholds=thresholds_of(costs), eval_run_id=run_id)
