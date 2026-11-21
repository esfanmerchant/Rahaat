"""The tool registry: typed inputs, typed outputs, and what each tool does.

Read tools change nothing and run at once. Action tools run only from `execute_action`, which the service calls
after an officer has approved the step and the action guard has allowed it again. Every action goes through the
existing service (`cases.service.act`, `notifications.service.notify`), so the case state machine, the four-eyes
rule, idempotent payments and the audit rows are the ones the officer's own buttons use, as the approving officer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.api import CaseActionIn, CaseDetail
from app.core.deps import Principal
from app.db import models
from app.modules.agent import schemas
from app.modules.agent.facts import CaseFacts, approval_blockers, reject_blockers
from app.modules.guardrails.action_guard import ACTION_TOOLS, READ_TOOLS, TOOLS

DUPLICATE_OPEN = ("open", "linked")


@dataclass
class ToolEnv:
    db: Session
    principal: Principal
    case_id: uuid.UUID
    person_id: uuid.UUID | None
    facts: CaseFacts
    detail: CaseDetail


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    kind: str
    description: str
    input_model: type[BaseModel]


DESCRIPTIONS = {
    "get_case": "The case summary: status, application status, which actions are allowed.",
    "get_handoff": "The handoff package: what the system understands, the cheapest question, the top two hypotheses.",
    "explain_decision": "The decision trace in brief: outcome, route, reason codes, guards, thresholds.",
    "check_rules": "Every rule result with whether its inputs were verified, and whether approval or rejection is supported.",
    "find_duplicates": "Stored duplicate candidates for this person (read only; never compares again).",
    "search_policy": "Search the department's approved policy text. Answers only from retrieved text, with citations.",
    "request_proof": "Send the keyed proof-request message for the cheapest question and move the case to waiting for proof.",
    "send_template_message": "Send one fixed, keyed message to the citizen. Never free text.",
    "approve_and_pay": "Approve the case and create the mock payment. The amount comes from the rule version.",
    "reject_with_reason": "Reject the case because a verified hard rule failed. The citizen gets the keyed rejection message.",
    "escalate": "Send the case to a senior officer with higher priority.",
}
REGISTRY: dict[str, ToolDef] = {name: ToolDef(name, TOOLS[name].kind, DESCRIPTIONS[name], schemas.INPUTS[name]) for name in TOOLS}
assert set(REGISTRY) == set(READ_TOOLS) | set(ACTION_TOOLS)


def is_action(tool: str) -> bool:
    return tool in ACTION_TOOLS


# --- read tools -----------------------------------------------------------------------------------------


def _get_case(env: ToolEnv, _: Any) -> BaseModel:
    f = env.facts
    return schemas.GetCaseOut(case_id=f.case_id, kind=f.case_kind, status=f.case_status, opened_reason=f.opened_reason,
                              application_status=f.application_status, allowed_actions=list(f.allowed_actions), note_count=f.note_count)  # fmt: skip


def _get_handoff(env: ToolEnv, _: Any) -> BaseModel:
    f = env.facts
    handoff = env.detail.handoff
    return schemas.GetHandoffOut(
        understanding=f.understanding, rule_fired=handoff.rule_fired if handoff else None,
        hypotheses=[{"label": label, "probability": p} for label, p in f.hypotheses],
        uncertain_fields=[{"field": name, "why": why} for name, why in f.uncertain_fields], resolving_proof=f.resolving_proof,
        suggested_question=f.suggested_question, expected_costs=dict(f.expected_costs),
    )  # fmt: skip


def _explain(env: ToolEnv, _: Any) -> BaseModel:
    f = env.facts
    return schemas.ExplainDecisionOut(outcome=f.decision_outcome, route=f.decision_route, reasons=list(f.reasons), guards=list(f.guards),
                                      p_ok=f.p_ok, thresholds={"approve": f.approve_threshold, "reject": f.reject_threshold},
                                      rule_version_no=f.rule_version_no)  # fmt: skip


def _check_rules(env: ToolEnv, _: Any) -> BaseModel:
    f = env.facts
    approve, reject = approval_blockers(f), reject_blockers(f)
    return schemas.CheckRulesOut(
        rules=[{"rule_id": r.rule_id, "hard": r.hard, "result": r.result, "verified": r.verified} for r in f.rules],
        hard_failed=[r.rule_id for r in f.rules if r.hard and r.result == "fail"],
        hard_unknown=[r.rule_id for r in f.rules if r.hard and r.result == "unknown"],
        approval_supported=not approve, approval_blockers=approve, reject_supported=not reject, payment_pkr=f.payment_pkr,
    )  # fmt: skip


def duplicate_rows(db: Session, tenant_id: uuid.UUID, person_id: uuid.UUID | None) -> list[models.DuplicateCandidate]:
    if person_id is None:
        return []
    return list(db.scalars(
        select(models.DuplicateCandidate).where(
            models.DuplicateCandidate.tenant_id == tenant_id,
            (models.DuplicateCandidate.person_a_id == person_id) | (models.DuplicateCandidate.person_b_id == person_id),
        ).order_by(models.DuplicateCandidate.score.desc(), models.DuplicateCandidate.id)
    ).all())  # fmt: skip


def worst_band(rows: list[models.DuplicateCandidate]) -> str | None:
    if not rows:
        return None
    live = [r.band for r in rows if r.status in DUPLICATE_OPEN]
    for band in ("same", "possible"):
        if band in live:
            return band
    return "distinct"


def _find_duplicates(env: ToolEnv, _: Any) -> BaseModel:
    rows = duplicate_rows(env.db, env.principal.tenant_id, env.person_id)
    return schemas.FindDuplicatesOut(
        worst_band=worst_band(rows),
        candidates=[{"id": str(r.id), "band": r.band, "score": round(r.score, 3), "status": r.status} for r in rows[:5]],
    )  # fmt: skip


def _search_policy(env: ToolEnv, args: Any) -> BaseModel:
    from app.modules.rag import service as rag
    from app.modules.rag.answer import compose

    tenant_id = env.principal.tenant_id
    result = compose(rag.indexes_for(env.db, tenant_id), args.query, None)
    if result.answered:
        rag._verify_citations(env.db, tenant_id, result)  # every cited chunk must exist, be approved and still hold the sentence
    if not result.answered:
        return schemas.SearchPolicyOut(answered=False, reason=result.reason)
    passages = result.passages
    position = {p.chunk_id: i for i, p in enumerate(passages)}
    return schemas.SearchPolicyOut(
        answered=True, reason=result.reason,
        sentences=[{"text": s.text, "citation": position[s.passage.chunk_id]} for s in result.sentences],
        citations=[schemas.PolicyCitation(document_id=p.document_id, doc_key=p.doc_key, title=p.title, version=p.version, section_id=p.section_id,
                                          section=p.heading, chunk_id=p.chunk_id) for p in passages],
    )  # fmt: skip


_READERS = {"get_case": _get_case, "get_handoff": _get_handoff, "explain_decision": _explain, "check_rules": _check_rules,
            "find_duplicates": _find_duplicates, "search_policy": _search_policy}  # fmt: skip


def run_read(env: ToolEnv, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    parsed = schemas.INPUTS[tool].model_validate(args)
    return _READERS[tool](env, parsed).model_dump(mode="json")


# --- action tools (only after approval) -----------------------------------------------------------------


def _reason(text: str, ordinal: int, tool: str) -> str:
    return f"{text.strip()} (agent step {ordinal}: {tool}, approved by an officer)"[:1000]


def execute_action(env: ToolEnv, tool: str, args: dict[str, Any], officer_reason: str, ordinal: int) -> dict[str, Any]:
    """Run one approved action as the approving officer. Raises the service's own errors (illegal transition, consent)."""
    from app.modules.cases import service as cases

    parsed = schemas.INPUTS[tool].model_validate(args)
    reason = _reason(officer_reason, ordinal, tool)
    notification: str | None = None
    if tool == "request_proof":
        assert isinstance(parsed, schemas.RequestProofIn)
        detail = cases.act(env.db, env.principal, env.case_id, CaseActionIn(action="request_proof", reason=reason, proof_kind=parsed.proof_kind))
        notification = "proof_needed"
    elif tool == "approve_and_pay":
        detail = cases.act(env.db, env.principal, env.case_id, CaseActionIn(action="approve", reason=reason))
        notification = "approved"
    elif tool == "reject_with_reason":
        assert isinstance(parsed, schemas.RejectIn)
        detail = cases.act(env.db, env.principal, env.case_id,
                           CaseActionIn(action="reject", reason=f"{parsed.reason_code}:{parsed.rule_id}. {reason}"[:1000]))  # fmt: skip
        notification = "rejected"
    elif tool == "escalate":
        detail = cases.act(env.db, env.principal, env.case_id, CaseActionIn(action="escalate", reason=reason))
    elif tool == "send_template_message":
        assert isinstance(parsed, schemas.SendTemplateIn)
        detail = env.detail
        notification = _send_template(env, parsed)
    else:  # the guard refuses unknown tools first; this is the backstop
        raise ValueError(f"not an action tool: {tool}")
    application = env.db.get(models.Application, uuid.UUID(env.facts.application_id)) if env.facts.application_id else None
    payment = None
    if tool == "approve_and_pay" and application is not None:
        payment = env.db.scalar(select(models.Payment).where(models.Payment.application_id == application.id,
                                                              models.Payment.tenant_id == env.principal.tenant_id))  # fmt: skip
    return schemas.ActionOut(
        case_status=detail.status, application_status=application.status if application else None,
        payment_status=payment.status if payment else None, payment_pkr=payment.amount_pkr if payment else None,
        pending_second_approver=bool(payment and payment.status == "pending_approval"), notification_template=notification,
    ).model_dump(mode="json")  # fmt: skip


def _send_template(env: ToolEnv, args: schemas.SendTemplateIn) -> str:
    from app.modules.notifications.service import notify

    application = env.db.get(models.Application, uuid.UUID(env.facts.application_id)) if env.facts.application_id else None
    if application is None:
        raise ValueError("no readable application")
    notify(env.db, tenant_id=env.principal.tenant_id, person_id=application.person_id, template=args.template,
           payload={"tracking_code": application.tracking_code, "application_id": application.id, "case_id": env.case_id,
                    "proof_kind": args.proof_kind or env.facts.resolving_proof or "other"})  # fmt: skip
    return args.template
