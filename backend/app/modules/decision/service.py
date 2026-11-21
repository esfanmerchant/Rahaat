"""Decision service: run the pure engine inside the caller's transaction, store it, explain it.

    decide(inp, rules, costs, model)                      the pure engine (re-exported from engine.py)
    decide_and_record(db, tenant_id=..., application_id=..., person_id=..., inp=...)   -> models.Decision
    user_view(decision)                                   what the citizen sees
    trace_view(db, decision, redact=...)                  what officers (raw) and auditors (masked) see
    engine_extras(decision)                               ask_proof, payment_pkr, rule_version_no for Track A

`decide_and_record` reads the active rule version, the tenant's cost matrix and the evidence model in the
caller's transaction, writes the `decisions` row and an `ai` audit row, and counts the route. It does not
commit: the submit pipeline commits the decision together with what it does next.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.decision import CostMatrix, DecisionTrace, DecisionUserView, Explanation, HandoffPackage, RuleTraceItem
from app.contracts.engine import DecisionInput, DecisionResult
from app.core import audit, metrics
from app.core.context import current_request_id
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier
from app.db import models
from app.modules.decision.engine import ENGINE_VERSION, decide
from app.modules.decision.model import EvidenceModelV1, get_model, registry_row
from app.modules.rules import service as rules_service

__all__ = ["decide", "decide_and_record", "engine_extras", "redact_snapshot", "trace_view", "user_view"]

log = get_logger("rahat.decision")
_registered: set[tuple[uuid.UUID, str]] = set()


def _ensure_model_registered(db: Session, tenant_id: uuid.UUID, model: EvidenceModelV1) -> None:
    """One `model_registry` row per tenant and model version, written the first time the version decides."""
    key = (tenant_id, model.version)
    if key in _registered:
        return
    exists = db.scalar(select(models.ModelRegistry.id).where(models.ModelRegistry.tenant_id == tenant_id,
                                                             models.ModelRegistry.version == model.version))  # fmt: skip
    if exists is None:
        try:
            with db.begin_nested():
                db.add(models.ModelRegistry(id=uuid.uuid4(), tenant_id=tenant_id, status="active", **registry_row(model)))
        except IntegrityError:  # another request registered it first
            log.info("model %s already registered for tenant %s", model.version, tenant_id)
    _registered.add(key)


def decide_and_record(db: Session, *, tenant_id: uuid.UUID, application_id: uuid.UUID, person_id: uuid.UUID, inp: DecisionInput,
                      actor_user_id: uuid.UUID | None = None) -> models.Decision:  # fmt: skip
    program = db.scalar(select(models.Program).where(models.Program.tenant_id == tenant_id, models.Program.slug == inp.program_slug))
    if program is None:
        raise NotFound("Program not found.", code="program_not_found")
    rules = rules_service.get_active(db, program.id)  # read inside this transaction: a publish applies to the next decision
    tenant = db.get(models.Tenant, tenant_id)
    costs = CostMatrix.model_validate((tenant.cost_matrix if tenant else None) or {})
    model = get_model()
    started = time.perf_counter()
    result = decide(inp, rules, costs, model)
    latency_ms = int((time.perf_counter() - started) * 1000)
    decision = models.Decision(
        id=uuid.uuid4(), tenant_id=tenant_id, application_id=application_id, person_id=person_id,
        rule_version_id=uuid.UUID(rules.rule_version_id), model_version=model.version, engine_version=ENGINE_VERSION,
        cost_matrix=costs.model_dump(mode="json"), input_snapshot=inp.model_dump(mode="json"), input_hash=result.input_hash,
        rule_trace=[t.model_dump(mode="json") for t in result.rule_trace], probabilities=dict(result.probabilities), p_ok=result.p_ok,
        expected_costs=dict(result.expected_costs), route=result.route, outcome=result.outcome, reasons=list(result.reasons),
        guards=list(result.guards), handoff=result.handoff.model_dump(mode="json") if result.handoff else None,
        explanation=_stored_explanation(result), guardrails={}, result_hash=result.result_hash, latency_ms=latency_ms,
        request_id=current_request_id(),
    )  # fmt: skip
    db.add(decision)
    db.flush()
    audit.write(
        db, tenant_id=tenant_id, action="decision.made", actor_type="ai", actor_id=ENGINE_VERSION, object_type="decision",
        object_id=decision.id, input_hash=result.input_hash, model_version=model.version, rule_version_id=decision.rule_version_id,
        details={"application_id": str(application_id), "route": result.route, "outcome": result.outcome, "guards": result.guards,
                 "result_hash": result.result_hash, "rule_version_no": result.rule_version_no,
                 "triggered_by": str(actor_user_id) if actor_user_id else None},
    )  # fmt: skip
    metrics.DECISIONS.labels(result.route).inc()
    _ensure_model_registered(db, tenant_id, model)
    return decision


def _stored_explanation(result: DecisionResult) -> dict[str, Any]:
    """The citizen's explanation plus the few engine fields the `decisions` table has no column for."""
    return {
        **result.explanation.model_dump(mode="json"),
        "engine": {"rule_version_no": result.rule_version_no, "ask_proof": result.ask_proof, "payment_pkr": result.payment_pkr,
                   "thresholds": result.thresholds, "p_eligible": result.p_eligible, "p_genuine": result.p_genuine},
    }  # fmt: skip


def engine_extras(decision: models.Decision) -> dict[str, Any]:
    """`ask_proof`, `payment_pkr`, `rule_version_no` and `thresholds` of a stored decision."""
    return dict((decision.explanation or {}).get("engine", {}))


def _decided_at(decision: models.Decision) -> str:
    stamp = (decision.input_snapshot or {}).get("decided_at")
    return str(stamp) if stamp else decision.created_at.isoformat()


def user_view(decision: models.Decision) -> DecisionUserView:
    return DecisionUserView(
        decision_id=str(decision.id), outcome=decision.outcome, route=decision.route,
        explanation=Explanation.model_validate(decision.explanation), rule_version_no=int(engine_extras(decision).get("rule_version_no") or 0),
        decided_at=_decided_at(decision),
    )  # fmt: skip


# --- redaction for auditors ----------------------------------------------------------------------------

_ID_KEYS = ("national_id", "id", "nid", "phone", "payout_account")
_NAME_KEYS = ("full_name", "name")


def mask_name(value: Any) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    return " ".join(part[0] + "•••" for part in value.split())


def _mask_dob(value: Any) -> Any:
    return f"{value[:4]}-••-••" if isinstance(value, str) and len(value) >= 4 else value


def _mask(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _NAME_KEYS:
        return mask_name(value)
    if key in _ID_KEYS:
        return mask_identifier(str(value))
    if key in ("dob", "date_of_birth"):
        return _mask_dob(value)
    return value


def redact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Mask names, identifiers and dates of birth; drop OCR text. Everything the rules used stays visible."""
    out = dict(snapshot)
    form = dict(out.get("form") or {})
    for key in (*_ID_KEYS, *_NAME_KEYS, "dob"):
        if isinstance(form.get(key), dict):
            form[key] = {**form[key], "value": _mask(key, form[key].get("value"))}
    out["form"] = form
    if isinstance(out.get("registry"), dict):
        out["registry"] = {k: _mask(k, v) for k, v in out["registry"].items()}
    documents = []
    for doc in out.get("documents") or []:
        doc = dict(doc)
        qr = dict(doc.get("qr") or {})
        if isinstance(qr.get("payload"), dict):
            qr["payload"] = {k: _mask(k, v) for k, v in qr["payload"].items()}
        doc["qr"] = qr
        ocr = dict(doc.get("ocr") or {})
        ocr["fields"] = dict.fromkeys(ocr.get("fields") or {}, "•••")
        ocr["raw_text"] = None
        doc["ocr"] = ocr
        documents.append(doc)
    out["documents"] = documents
    return out


def _redact_handoff(handoff: HandoffPackage) -> HandoffPackage:
    evidence = {k: v for k, v in handoff.evidence.items() if k != "ocr_text"}
    return handoff.model_copy(update={"evidence": evidence})


def trace_view(db: Session, decision: models.Decision, *, redact: bool) -> DecisionTrace:
    extras = engine_extras(decision)
    version_no = extras.get("rule_version_no")
    if version_no is None:
        version = db.get(models.RuleVersion, decision.rule_version_id)
        version_no = version.version_no if version else 0
    costs = CostMatrix.model_validate(decision.cost_matrix or {})
    queue_days = float((decision.input_snapshot or {}).get("queue_days", 1.0))
    thresholds = extras.get("thresholds") or {
        "approve": round(costs.approve_threshold(queue_days), 4), "reject": round(costs.reject_threshold(queue_days), 4),
    }  # fmt: skip
    reviews = db.scalars(
        select(models.HumanReview).where(models.HumanReview.decision_id == decision.id).order_by(models.HumanReview.created_at)
    ).all()
    handoff = HandoffPackage.model_validate(decision.handoff) if decision.handoff else None
    if handoff is not None and redact:
        handoff = _redact_handoff(handoff)
    return DecisionTrace(
        decision_id=str(decision.id), application_id=str(decision.application_id), route=decision.route,
        outcome=decision.outcome, rule_version_id=str(decision.rule_version_id), rule_version_no=int(version_no),
        model_version=decision.model_version, engine_version=decision.engine_version, input_hash=decision.input_hash,
        result_hash=decision.result_hash,
        input_snapshot=redact_snapshot(decision.input_snapshot) if redact else dict(decision.input_snapshot),
        rule_trace=[RuleTraceItem.model_validate(t) for t in decision.rule_trace], probabilities=dict(decision.probabilities),
        p_ok=decision.p_ok, cost_matrix=costs, expected_costs=dict(decision.expected_costs), thresholds=dict(thresholds),
        reasons=list(decision.reasons), guards=list(decision.guards), guardrails=dict(decision.guardrails or {}), handoff=handoff,
        human_reviews=[{"action": r.action, "reason": r.reason, "reviewer_user_id": str(r.reviewer_user_id), "overrode_ai": r.overrode_ai,
                        "at": r.created_at.isoformat()} for r in reviews],
        latency_ms=decision.latency_ms, request_id=decision.request_id, decided_at=_decided_at(decision),
    )  # fmt: skip
