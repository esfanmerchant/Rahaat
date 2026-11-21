"""Digital Twin service: run a draft over stored decisions and labelled cases in a sandbox, then publish or discard.

    run(db, principal, body) -> TwinRunOut      reads decisions and rule versions; writes one twin_runs row
    request_publish(db, principal, run_id, reason)   hands the draft to the four-eyes flow (a second admin publishes)
    discard(db, principal, run_id, reason)           records that the draft is not going ahead

Sandbox: the engine functions used here are pure, so no notification, payment, case or decision can be
written. The only rows a run adds are its `twin_runs` row and the audit entry that records it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.decision import CostMatrix
from app.contracts.engine import DecisionInput, RuleSetSnapshot
from app.core import audit
from app.core.deps import Principal
from app.core.errors import Conflict, NotFound, Unprocessable
from app.db import models
from app.modules.decision import paging
from app.modules.decision.engine import ROUTES, decide, route_for
from app.modules.decision.model import get_model
from app.modules.evals import decision_eval as E
from app.modules.evals.service import tenant_costs
from app.modules.rules import dsl as rule_dsl
from app.modules.rules import service as rules_service
from app.modules.twin import simulate as S
from app.modules.twin.schemas import ChangedCaseOut, TwinRunIn, TwinRunList, TwinRunOut, TwinRunSummary

LIVE_LIMIT = 5000


def _version(db: Session, principal: Principal, version_id: uuid.UUID) -> models.RuleVersion:
    version = db.get(models.RuleVersion, version_id)
    if version is None or version.tenant_id != principal.tenant_id:
        raise NotFound("Rule version not found.", code="rule_version_not_found")
    return version


def _latest_decisions(db: Session, tenant_id: uuid.UUID) -> list[models.Decision]:
    """The newest decision of each application in the department (a resubmission replaces the earlier one)."""
    rows = db.scalars(
        select(models.Decision).where(models.Decision.tenant_id == tenant_id)
        .order_by(models.Decision.created_at.desc(), models.Decision.id.desc()).limit(LIVE_LIMIT)
    ).all()  # fmt: skip
    seen: set[uuid.UUID] = set()
    out = []
    for row in rows:
        if row.application_id not in seen:
            seen.add(row.application_id)
            out.append(row)
    return out


def _side(inp: DecisionInput, rules: RuleSetSnapshot, costs: CostMatrix) -> dict[str, Any]:
    """One side of a changed case, from a full decide() (route_for gives the same route; tested)."""
    result = decide(inp, rules, costs, get_model())
    action = {"approved": "approve", "rejected": "reject", "needs_proof": "ask_proof", "needs_human": "human"}[result.outcome]
    return {"outcome": result.outcome, "route": result.route, "p_ok": result.p_ok, "expected_cost": result.expected_costs.get(action, 0.0),
            "reasons": [r for r in result.reasons if not r.startswith("cost.")][:4] or result.reasons[:2]}  # fmt: skip


def run(db: Session, principal: Principal, body: TwinRunIn) -> TwinRunOut:
    draft = _version(db, principal, body.draft_version_id)
    errors = rule_dsl.validate(draft.dsl)
    if errors:
        raise Unprocessable("The draft has errors. Fix them before running the Digital Twin.", code="rules_invalid",
                            extra={"errors": [e.as_dict() for e in errors]})  # fmt: skip
    base_id = body.base_version_id or db.scalar(select(models.RuleSet.active_version_id).where(models.RuleSet.id == draft.rule_set_id))
    base = _version(db, principal, base_id) if base_id else None
    if base is not None and base.rule_set_id != draft.rule_set_id:
        raise Conflict("Compare versions of the same rule set.", code="different_rule_sets")
    base_snapshot = rules_service.snapshot(base) if base else rules_service.snapshot(draft)
    draft_snapshot = rules_service.snapshot(draft)
    costs = tenant_costs(db, principal.tenant_id)
    model = get_model()

    inputs: dict[str, DecisionInput] = {}
    live_summary: dict[str, Any] | None = None
    live_cases: list[S.TwinCase] = []
    if body.include_live:
        skipped = differs = 0
        for row in _latest_decisions(db, principal.tenant_id):
            try:
                inp = DecisionInput.model_validate(row.input_snapshot)
            except ValueError:
                skipped += 1
                continue
            case = S.live_case(f"decision:{row.id}", inp, base_snapshot.dsl, draft_snapshot.dsl, model)
            live_cases.append(case)
            inputs[case.ref] = inp
            differs += ROUTES[route_for(case.before, costs)[0]][1] != row.outcome
        live_summary = S.summarise(live_cases, costs, payment_before=base_snapshot.dsl.get("payment_pkr"),
                                   payment_after=draft_snapshot.dsl.get("payment_pkr"))  # fmt: skip
        live_summary.update({"skipped": skipped, "base_differs_from_stored": differs})

    synthetic_summary: dict[str, Any] | None = None
    synthetic_cases: list[S.TwinCase] = []
    world_inputs: dict[str, DecisionInput] = {}
    if body.include_synthetic:
        base_scores = E.cached_scores(base_snapshot.dsl, model)
        draft_scores = E.cached_scores(draft_snapshot.dsl, model)
        synthetic_cases = S.synthetic_cases(base_scores, draft_scores)
        synthetic_summary = S.summarise(synthetic_cases, costs, payment_before=base_snapshot.dsl.get("payment_pkr"),
                                        payment_after=draft_snapshot.dsl.get("payment_pkr"))  # fmt: skip
        world_inputs = {case.case_id: case.inp for case in E.heldout_world().cases}

    sample: list[dict[str, Any]] = []
    for case, _, _ in S.changed_sample([*live_cases, *synthetic_cases], costs):
        found = inputs.get(case.ref) if case.dataset == "live" else world_inputs.get(case.ref)
        if found is None:
            continue
        inp = found
        sample.append({
            "ref": case.ref, "dataset": case.dataset, "slices": case.slices,
            "before": _side(inp, base_snapshot, costs),
            "after": _side(inp, draft_snapshot, costs),
        })  # fmt: skip

    flagged = sorted({*(f"live:{s}" for s in (live_summary or {}).get("flagged_slices", [])),
                      *(f"synthetic:{s}" for s in (synthetic_summary or {}).get("flagged_slices", []))})  # fmt: skip
    summary = {
        "draft_version_no": draft.version_no, "base_version_no": base.version_no if base else None, "model_version": model.version,
        "costs": costs.model_dump(mode="json"), "rule_changes": rule_dsl.diff(base_snapshot.dsl, draft_snapshot.dsl),
        "live": live_summary, "synthetic": synthetic_summary, "sample": sample, "flagged_slices": flagged,
    }  # fmt: skip
    twin = models.TwinRun(id=uuid.uuid4(), tenant_id=principal.tenant_id, draft_version_id=draft.id, base_version_id=base.id if base else None,
                          status="done", summary=summary, created_by=principal.user_id, created_at=datetime.now(UTC))  # fmt: skip
    db.add(twin)
    db.flush()
    audit.write(db, tenant_id=principal.tenant_id, action="twin.run", actor_id=principal.user_id, actor_role=principal.role, object_type="twin_run",
                object_id=twin.id, rule_version_id=draft.id, model_version=model.version,
                details={"draft_version_no": draft.version_no, "base_version_no": base.version_no if base else None,
                         "changed_live": (live_summary or {}).get("changed"), "changed_synthetic": (synthetic_summary or {}).get("changed"),
                         "flagged_slices": flagged})  # fmt: skip
    return out(db, twin)


def out(db: Session, twin: models.TwinRun) -> TwinRunOut:
    s = dict(twin.summary or {})
    draft = db.get(models.RuleVersion, twin.draft_version_id)
    return TwinRunOut.model_validate({
        "id": twin.id, "created_at": twin.created_at.astimezone(UTC).isoformat(), "status": twin.status, "draft_version_id": twin.draft_version_id,
        "draft_version_no": s.get("draft_version_no", draft.version_no if draft else 0), "draft_status": draft.status if draft else "missing",
        "base_version_id": twin.base_version_id, "base_version_no": s.get("base_version_no"), "model_version": s.get("model_version", ""),
        "costs": s.get("costs", {}), "rule_changes": s.get("rule_changes", []), "live": s.get("live"), "synthetic": s.get("synthetic"),
        "sample": [ChangedCaseOut.model_validate(x) for x in s.get("sample", [])], "flagged_slices": s.get("flagged_slices", []),
        "decided_reason": s.get("decided_reason"),
    })  # fmt: skip


def _load(db: Session, principal: Principal, run_id: uuid.UUID, *, lock: bool = False) -> models.TwinRun:
    query = select(models.TwinRun).where(models.TwinRun.id == run_id, models.TwinRun.tenant_id == principal.tenant_id)
    twin = db.scalar(query.with_for_update() if lock else query)
    if twin is None:
        raise NotFound("Digital Twin run not found.", code="twin_run_not_found")
    return twin


def get(db: Session, principal: Principal, run_id: uuid.UUID) -> TwinRunOut:
    return out(db, _load(db, principal, run_id))


def list_runs(db: Session, principal: Principal, *, limit: int, cursor: str | None) -> TwinRunList:
    query = select(models.TwinRun).where(models.TwinRun.tenant_id == principal.tenant_id)
    after = paging.before((models.TwinRun.created_at, models.TwinRun.id), cursor)
    if after is not None:
        query = query.where(after)
    rows = db.scalars(query.order_by(models.TwinRun.created_at.desc(), models.TwinRun.id.desc()).limit(limit + 1)).all()
    items = [TwinRunSummary(id=r.id, created_at=r.created_at.astimezone(UTC).isoformat(), status=r.status, draft_version_id=r.draft_version_id,
                            base_version_id=r.base_version_id, changed_live=((r.summary or {}).get("live") or {}).get("changed"),
                            changed_synthetic=((r.summary or {}).get("synthetic") or {}).get("changed"),
                            flagged_slices=(r.summary or {}).get("flagged_slices", [])) for r in rows[:limit]]  # fmt: skip
    return TwinRunList(items=items, next_cursor=paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None)


def _decide(db: Session, principal: Principal, twin: models.TwinRun, status: str, reason: str, action: str) -> None:
    twin.status = status
    twin.summary = {**(twin.summary or {}), "decided_reason": reason, "decided_by": str(principal.user_id)}
    db.flush()
    audit.write(db, tenant_id=principal.tenant_id, action=action, actor_id=principal.user_id, actor_role=principal.role, object_type="twin_run",
                object_id=twin.id, rule_version_id=twin.draft_version_id, reason=reason, details={"status": status})  # fmt: skip


def request_publish(db: Session, principal: Principal, run_id: uuid.UUID, reason: str) -> TwinRunOut:
    """Send the draft to the four-eyes flow. A second admin publishes it with POST /v1/rules/versions/{id}/publish."""
    twin = _load(db, principal, run_id, lock=True)
    if twin.status != "done":
        raise Conflict(f"This run is {twin.status}.", code="twin_run_decided")
    draft = _version(db, principal, twin.draft_version_id)
    if draft.status == rules_service.EDITABLE:
        rules_service.request_approval(db, principal, draft.id, reason)
    elif draft.status != rules_service.PENDING:
        raise Conflict(f"The draft is {draft.status}; only a draft can be sent for approval.", code="not_a_draft")
    _decide(db, principal, twin, "publishing", reason, "twin.publish_requested")
    return out(db, twin)


def discard(db: Session, principal: Principal, run_id: uuid.UUID, reason: str) -> TwinRunOut:
    twin = _load(db, principal, run_id, lock=True)
    if twin.status != "done":
        raise Conflict(f"This run is {twin.status}.", code="twin_run_decided")
    _decide(db, principal, twin, "discarded", reason, "twin.discarded")
    return out(db, twin)
