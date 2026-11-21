"""Replay a stored decision, list decisions, and recheck the silent-guess invariant on stored rows (B11, B13).

    replay(db, decision) -> ReplayResult          recomputed from the stored snapshot, pinned rule version,
                                                   stored cost matrix and the model; differences listed
    list_decisions(db, principal, ...)            paged and filtered, without personal data
    stored_silent_guesses(db, decision)           the invariant on a stored row (facts rebuilt from its snapshot)

A replay must match bit for bit: same input hash, same result hash. A difference is reported field by field,
never smoothed over (a model version that is no longer available is a difference, not a match).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.decision import CostMatrix, ReplayResult, RuleTraceItem
from app.contracts.engine import DecisionInput, DecisionResult, RuleSetSnapshot
from app.core.audit import hash_payload
from app.core.deps import Principal
from app.db import models
from app.modules.decision import paging
from app.modules.decision.engine import ENGINE_VERSION, decide, invariant_violations
from app.modules.decision.facts import build_facts
from app.modules.decision.model import get_model
from app.modules.decision.schemas import DecisionList, DecisionSummary
from app.modules.rules import service as rules_service

OUTCOME_ACTION = {"approved": "approve", "rejected": "reject", "needs_proof": "ask_proof", "needs_human": "human"}


def _fmt(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 160 else text[:157] + "..."


def _diff(path: str, stored: Any, replayed: Any, out: list[str]) -> None:
    if isinstance(stored, dict) and isinstance(replayed, dict):
        for key in sorted(set(stored) | set(replayed)):
            _diff(f"{path}.{key}", stored.get(key), replayed.get(key), out)
    elif isinstance(stored, list) and isinstance(replayed, list) and len(stored) == len(replayed):
        for i, (a, b) in enumerate(zip(stored, replayed, strict=True)):
            _diff(f"{path}[{i}]", a, b, out)
    elif stored != replayed:
        out.append(f"{path}: stored {_fmt(stored)}, replayed {_fmt(replayed)}")


def recompute(db: Session, decision: models.Decision) -> tuple[DecisionResult, RuleSetSnapshot, list[str]]:
    """The decision again, from what was stored. Returns the result, the pinned rules and setup differences."""
    notes: list[str] = []
    rules = rules_service.get_version_snapshot(db, decision.rule_version_id)
    if rules.content_hash and rules.content_hash != hash_payload(rules.dsl):
        notes.append("rule_version: its rules no longer match the hash stored when it was frozen")
    model = get_model()
    if decision.model_version != model.version:
        notes.append(f"model_version: stored {decision.model_version}, available {model.version} (the pinned model cannot be loaded)")
    if decision.engine_version != ENGINE_VERSION:
        notes.append(f"engine_version: stored {decision.engine_version}, running {ENGINE_VERSION}")
    inp = DecisionInput.model_validate(decision.input_snapshot)
    costs = CostMatrix.model_validate(decision.cost_matrix or {})
    return decide(inp, rules, costs, model), rules, notes


def replay(db: Session, decision: models.Decision) -> ReplayResult:
    result, _, differences = recompute(db, decision)
    if result.input_hash != decision.input_hash:
        differences.append(f"input_hash: stored {decision.input_hash}, replayed {result.input_hash}")
    stored = {
        "route": decision.route, "outcome": decision.outcome, "p_ok": decision.p_ok, "probabilities": decision.probabilities,
        "expected_costs": decision.expected_costs, "reasons": decision.reasons, "guards": decision.guards, "rule_trace": decision.rule_trace,
    }  # fmt: skip
    replayed = {
        "route": result.route, "outcome": result.outcome, "p_ok": result.p_ok, "probabilities": result.probabilities,
        "expected_costs": result.expected_costs, "reasons": result.reasons, "guards": result.guards,
        "rule_trace": [t.model_dump(mode="json") for t in result.rule_trace],
    }  # fmt: skip
    for key in stored:
        _diff(key, stored[key], replayed[key], differences)
    if result.result_hash != decision.result_hash and not differences:
        differences.append("result_hash: the stored hash differs although every compared field agrees (explanation or handoff text changed)")
    match = result.result_hash == decision.result_hash and not differences
    return ReplayResult(decision_id=str(decision.id), match=match, stored_result_hash=decision.result_hash,
                        replayed_result_hash=result.result_hash, differences=differences[:50])  # fmt: skip


def stored_silent_guesses(decision: models.Decision, dsl: dict[str, Any] | None) -> list[str]:
    """The invariant on a stored decision. Facts are rebuilt from the snapshot with the pinned version's parameters."""
    if decision.route != "auto":
        return []
    try:
        inp = DecisionInput.model_validate(decision.input_snapshot)
    except ValueError:
        return ["snapshot_unreadable"]
    params = (dsl or {}).get("params", {}) or {}
    thresholds = (decision.explanation or {}).get("engine", {}).get("thresholds") or {}
    return invariant_violations(
        route=decision.route, outcome=decision.outcome, guards=list(decision.guards or []), facts=build_facts(inp, params),
        rule_trace=[RuleTraceItem.model_validate(t) for t in decision.rule_trace or []], p_ok=float(decision.p_ok or 0.0),
        p_eligible=float((decision.probabilities or {}).get("p_eligible", 0.0)), thresholds=thresholds,
    )  # fmt: skip


def _decided_at(decision: models.Decision) -> str:
    stamp = (decision.input_snapshot or {}).get("decided_at")
    return str(stamp) if stamp else decision.created_at.isoformat()


def summary_of(decision: models.Decision, version_no: int | None) -> DecisionSummary:
    extras = (decision.explanation or {}).get("engine", {})
    action = OUTCOME_ACTION.get(decision.outcome)
    return DecisionSummary(
        id=decision.id, application_id=decision.application_id, case_id=decision.case_id, created_at=decision.created_at.isoformat(),
        decided_at=_decided_at(decision), route=decision.route, outcome=decision.outcome, rule_version_id=decision.rule_version_id,
        rule_version_no=extras.get("rule_version_no", version_no), model_version=decision.model_version, engine_version=decision.engine_version,
        p_ok=decision.p_ok, guards=list(decision.guards or []), main_reason=(decision.reasons or [None])[0],
        expected_cost=(decision.expected_costs or {}).get(action) if action else None, latency_ms=decision.latency_ms,
        ask_proof=extras.get("ask_proof"),
    )  # fmt: skip


def list_decisions(db: Session, principal: Principal, *, route: str | None, outcome: str | None, rule_version_id: uuid.UUID | None,
                   rule_version_no: int | None, decided_from: date | None, decided_to: date | None, application_id: uuid.UUID | None,
                   limit: int, cursor: str | None) -> DecisionList:  # fmt: skip
    query = select(models.Decision).where(models.Decision.tenant_id == principal.tenant_id)
    if route:
        query = query.where(models.Decision.route == route)
    if outcome:
        query = query.where(models.Decision.outcome == outcome)
    if rule_version_id:
        query = query.where(models.Decision.rule_version_id == rule_version_id)
    if rule_version_no is not None:
        ids = db.scalars(select(models.RuleVersion.id).where(models.RuleVersion.tenant_id == principal.tenant_id,
                                                              models.RuleVersion.version_no == rule_version_no)).all()  # fmt: skip
        query = query.where(models.Decision.rule_version_id.in_(list(ids)))
    if application_id:
        query = query.where(models.Decision.application_id == application_id)
    if decided_from:
        query = query.where(models.Decision.created_at >= datetime.combine(decided_from, time.min, tzinfo=UTC))
    if decided_to:
        query = query.where(models.Decision.created_at <= datetime.combine(decided_to, time.max, tzinfo=UTC))
    after = paging.before((models.Decision.created_at, models.Decision.id), cursor)
    if after is not None:
        query = query.where(after)
    rows = db.scalars(query.order_by(models.Decision.created_at.desc(), models.Decision.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    version_ids = {r.rule_version_id for r in page}
    versions = {v.id: v.version_no for v in db.scalars(select(models.RuleVersion).where(models.RuleVersion.id.in_(version_ids)))}
    next_cursor = paging.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return DecisionList(items=[summary_of(r, versions.get(r.rule_version_id)) for r in page], next_cursor=next_cursor)
