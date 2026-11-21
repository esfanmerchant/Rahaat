"""Agent runs: plan, run the read steps, park the action for an officer, and execute it only after approval.

State machine of a run (persisted in `agent_runs.status` and `agent_runs.state`, so it resumes after a restart):

    running -> waiting_approval -> done            (officer approved and the action ran, or the officer rejected it)
    running -> done                                (the planner abstained, or its proposal was refused by the guard)
    waiting_approval -> done (failed)              (the guard refused at execution because the case changed, or the action failed)

Every step is a row in `agent_steps` and an audit row. The action guard runs when a step is proposed and again when it is
approved, with the case read afresh. Nothing in this module sends a model's text anywhere: tool arguments are enums and ids.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.decision import TypedDecision
from app.core import audit
from app.core.deps import Principal
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.db import models
from app.modules.agent import gate, tools
from app.modules.agent.facts import CaseFacts, from_detail
from app.modules.agent.planner import Planner, PlanProposal, get_planner, provider_status
from app.modules.agent.schemas import AgentDecisionOut, ApprovalOut, PlannerOut, RunOut, StepOut
from app.modules.agent.settings import agent_settings
from app.modules.guardrails import service as guard_service
from app.modules.guardrails.input_guard import check_input
from app.modules.guardrails.verdict import GuardVerdict, Surface
from app.modules.payments import rules as payment_rules

log = get_logger("rahat.agent")

CORE_READS = ("get_case", "get_handoff", "explain_decision", "check_rules", "find_duplicates")
STAFF_DETAIL_ROLES = frozenset({"officer"})
# A refusal about who is approving leaves the step waiting (another officer may approve); any other refusal ends the step.
APPROVER_CODES = frozenset({"four_eyes_same_person", "self_approval", "tool_not_allowed_for_role"})


class AgentActionBlocked(Conflict):
    code = "agent_action_blocked"
    title = "The action guard refused this step"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str:
    return (value or _now()).isoformat()


# --- facts ----------------------------------------------------------------------------------------------


def _case_row(db: Session, tenant_id: uuid.UUID, case_id: uuid.UUID) -> models.Case:
    case = db.scalar(select(models.Case).where(models.Case.id == case_id, models.Case.tenant_id == tenant_id))
    if case is None:
        raise NotFound("No such case.")
    return case


def _approvers_of_case(db: Session, tenant_id: uuid.UUID, application_id: uuid.UUID | None) -> tuple[str, ...]:
    if application_id is None:
        return ()
    rows = db.scalars(
        select(models.HumanReview.reviewer_user_id).join(models.Case, models.Case.id == models.HumanReview.case_id)
        .where(models.Case.tenant_id == tenant_id, models.Case.application_id == application_id, models.HumanReview.action == "approve")
    ).all()  # fmt: skip
    return tuple(dict.fromkeys(str(u) for u in rows))


def build_facts(db: Session, principal: Principal, case_id: uuid.UUID) -> tuple[CaseFacts, Any, models.Case]:
    """Read the case as the signed-in officer (so consent and RLS apply and the view is recorded), then derive the facts."""
    from app.modules.cases import service as cases

    detail = cases.get_detail(db, principal, case_id)
    case = _case_row(db, principal.tenant_id, case_id)
    application = db.get(models.Application, case.application_id) if case.application_id else None
    rows = tools.duplicate_rows(db, principal.tenant_id, case.subject_person_id)
    payment_exists = False
    amount: int | None = None
    if application is not None:
        paid = select(models.Payment.id).where(models.Payment.application_id == application.id, models.Payment.tenant_id == principal.tenant_id)
        payment_exists = db.scalar(paid.limit(1)) is not None
        decision = db.get(models.Decision, case.decision_id) if case.decision_id else None
        amount = cases._payment_amount(db, decision, application)  # the same function that sets the paid amount: rules, never a model
    facts = from_detail(detail, application_status=application.status if application else None,
                        application_id=str(application.id) if application else None, duplicate_band=tools.worst_band(rows),
                        payment_pkr=amount, payment_exists=payment_exists)  # fmt: skip
    return facts, detail, case


def _scan_untrusted(db: Session, principal: Principal, facts: CaseFacts, run_id: uuid.UUID) -> list[str]:
    """The input guard looks at every piece of case text. Findings are stored; the text is still only data."""
    flags: list[str] = []
    for item in facts.untrusted:
        surface: Surface = "ocr" if item.source in ("ocr", "evidence") else "message"
        verdict = check_input(item.text, surface)
        if verdict.verdict in ("flag", "block"):
            flags += [f"{item.source}:{code}" for code in verdict.codes]
            guard_service.record(db, verdict, tenant_id=principal.tenant_id, actor_type="user", actor_id=principal.user_id,
                                 actor_role=principal.role, object_type="agent_run", object_id=run_id, context={"source": item.source})  # fmt: skip
    return list(dict.fromkeys(flags))[:20]


# --- writing --------------------------------------------------------------------------------------------


def _digest(run_id: uuid.UUID, ordinal: int, tool: str, args: dict[str, Any]) -> str:
    return hashlib.sha256(f"{run_id}:{ordinal}:{tool}:{json.dumps(args, sort_keys=True)}".encode()).hexdigest()[:32]


def _audit(db: Session, principal: Principal | None, run: models.AgentRun, action: str, *, step: models.AgentStep | None = None,
           result: str = "ok", reason: str | None = None, details: dict[str, Any] | None = None) -> None:  # fmt: skip
    planner = (run.state or {}).get("planner", {})
    audit.write(
        db, tenant_id=run.tenant_id, action=action, actor_type="user" if principal else "ai",
        actor_id=principal.user_id if principal else f"agent:{planner.get('type', 'local')}", actor_role=principal.role if principal else "agent",
        acting_for_person_id=run.person_id, object_type="agent_step" if step else "agent_run", object_id=step.id if step else run.id,
        result=result, reason=reason, model_version=(planner.get("model_version") if planner else None),
        details={"run_id": str(run.id), "ordinal": step.ordinal if step else None, "tool": step.tool if step else None, **(details or {})},
    )  # fmt: skip


def _add_step(db: Session, run: models.AgentRun, tool: str, args: dict[str, Any], *, status: str, rationale: str | None = None,
              output: dict[str, Any] | None = None) -> models.AgentStep:  # fmt: skip
    ordinal = (db.scalar(select(func.max(models.AgentStep.ordinal)).where(models.AgentStep.run_id == run.id)) or 0) + 1
    if status != "blocked":
        run.steps_used += 1  # a refused step is on record but does not count against the budget
    step = models.AgentStep(id=uuid.uuid4(), tenant_id=run.tenant_id, run_id=run.id, ordinal=ordinal, tool=tool,
                            input={"args": args, "rationale": rationale, "key": _digest(run.id, ordinal, tool, args)},
                            output=output or {}, status=status, created_at=_now())  # fmt: skip
    db.add(step)
    db.flush()
    return step


def _state(run: models.AgentRun, **changes: Any) -> None:
    run.state = {**(run.state or {}), **changes}  # JSON columns are not mutation-tracked: always assign a new dict


def _decision_json(decision: TypedDecision[str]) -> dict[str, Any]:
    return decision.model_dump(mode="json")


# --- start ----------------------------------------------------------------------------------------------


def _goal(case_id: uuid.UUID) -> str:
    return f"case_review:{case_id}"


def _open_run(db: Session, tenant_id: uuid.UUID, case_id: uuid.UUID) -> models.AgentRun | None:
    return db.scalar(select(models.AgentRun).where(models.AgentRun.tenant_id == tenant_id, models.AgentRun.goal == _goal(case_id),
                                                    models.AgentRun.status == "waiting_approval")
                     .order_by(models.AgentRun.created_at.desc(), models.AgentRun.id).limit(1))  # fmt: skip


def start_run(db: Session, principal: Principal, case_id: uuid.UUID, *, planner: Planner | None = None,
              http_client: httpx.Client | None = None) -> RunOut:  # fmt: skip
    """Plan one action for a case, run the read steps, and park the action for an officer's approval. Does not commit."""
    facts, detail, case = build_facts(db, principal, case_id)
    existing = _open_run(db, principal.tenant_id, case_id)
    if existing is not None:
        return run_out(db, existing, principal.role, reused=True)
    budget = max(3, agent_settings().agent_step_budget)
    run = models.AgentRun(id=uuid.uuid4(), tenant_id=principal.tenant_id, goal=_goal(case_id), status="running", application_id=case.application_id,
                          person_id=case.subject_person_id, started_by=principal.user_id, acting_role=principal.role, step_budget=budget,
                          steps_used=0, state={}, created_at=_now(), updated_at=_now())  # fmt: skip
    db.add(run)
    db.flush()
    flags = _scan_untrusted(db, principal, facts, run.id)
    proposal: PlanProposal = (planner or get_planner(http_client)).plan(facts)
    _state(run, case_id=str(case_id), planner={"type": proposal.planner_type, "model_version": proposal.model_version,
                                                "fallback_reason": proposal.fallback_reason}, decision=_decision_json(proposal.decision),
           rationale=proposal.rationale, flags=flags, outcome="abstained" if proposal.action is None else "proposed", phase="planned")  # fmt: skip
    _audit(db, principal, run, "agent.run_started", details={"planner": proposal.planner_type, "model_version": proposal.model_version,
                                                             "choice": proposal.decision.choice, "confidence": proposal.decision.confidence,
                                                             "abstained": proposal.decision.abstained, "reasons": proposal.decision.reasons,
                                                             "flags": len(flags), "fallback": proposal.fallback_reason})  # fmt: skip

    env = tools.ToolEnv(db=db, principal=principal, case_id=case_id, person_id=case.subject_person_id, facts=facts, detail=detail)
    plan: list[tuple[str, dict[str, Any]]] = [(tool, {}) for tool in CORE_READS]
    if proposal.search_query:
        plan.append(("search_policy", {"query": proposal.search_query}))
    refused: GuardVerdict | None = None
    for tool, args in plan:
        refused = _run_read(db, principal, run, env, tool, args)
        if refused is not None:
            break
    if refused is not None:
        _stop_blocked(run, proposal, refused)
    else:
        _propose_action(db, principal, run, facts, proposal)
    run.updated_at = _now()
    db.flush()
    return run_out(db, run, principal.role)


def _run_read(db: Session, principal: Principal, run: models.AgentRun, env: tools.ToolEnv, tool: str, args: dict[str, Any]) -> GuardVerdict | None:
    """Run one read step. Returns the refusing verdict when the guard stopped it, else None."""
    verdict = gate.check("propose", tool, args, env.facts, role=principal.role, steps_used=run.steps_used, step_budget=run.step_budget)
    if verdict.blocked:
        step = _add_step(db, run, tool, args, status="blocked", output={"codes": verdict.codes})
        _record_refusal(db, principal, run, step, verdict)
        return verdict
    try:
        output = tools.run_read(env, tool, args)
        status = "done"
    except Exception as exc:  # noqa: BLE001  (a failing read must not stop the officer from seeing the rest)
        log.warning("read tool %s failed: %s", tool, type(exc).__name__)
        output, status = {"error": "tool_failed"}, "failed"
    step = _add_step(db, run, tool, args, status=status, output=output)
    _audit(db, None, run, "agent.step_executed", step=step, result="ok" if status == "done" else "failed")
    return None


def _record_refusal(db: Session, principal: Principal | None, run: models.AgentRun, step: models.AgentStep, verdict: GuardVerdict) -> None:
    guard_service.record(db, verdict, tenant_id=run.tenant_id, actor_type="user" if principal else "ai",
                         actor_id=principal.user_id if principal else "agent", actor_role=principal.role if principal else "agent",
                         object_type="agent_step", object_id=step.id, context={"tool": step.tool, "stage": "agent"})  # fmt: skip
    _audit(db, principal, run, "agent.step_blocked", step=step, result="blocked", reason=",".join(verdict.codes)[:200],
           details={"codes": verdict.codes})  # fmt: skip


def _stop_blocked(run: models.AgentRun, proposal: PlanProposal, verdict: GuardVerdict) -> None:
    """The guard refused a step: the run ends without an action, and says so as an abstention."""
    abstained = TypedDecision[str](choice=None, confidence=0.0, route="human", reasons=["proposal_blocked", *verdict.codes],
                                   model_version=proposal.model_version, abstained=True)  # fmt: skip
    run.status = "done"
    _state(run, phase="finished", outcome="proposal_blocked", decision=_decision_json(abstained),
           rationale="I am not sure; please review. The action guard refused a step.")  # fmt: skip


def _propose_action(db: Session, principal: Principal, run: models.AgentRun, facts: CaseFacts, proposal: PlanProposal) -> None:
    if proposal.action is None:
        run.status = "done"
        _state(run, phase="finished")
        return
    call = proposal.action
    verdict = gate.check("propose", call.tool, call.args, facts, role=principal.role, steps_used=run.steps_used, step_budget=run.step_budget)
    if verdict.blocked:
        step = _add_step(db, run, call.tool, call.args, status="blocked", rationale=proposal.rationale, output={"codes": verdict.codes})
        _record_refusal(db, principal, run, step, verdict)
        _stop_blocked(run, proposal, verdict)
        return
    step = _add_step(db, run, call.tool, call.args, status="waiting_approval", rationale=proposal.rationale)
    run.status = "waiting_approval"
    _state(run, phase="awaiting_officer")
    _audit(db, None, run, "agent.step_proposed", step=step, result="pending", details={"args": call.args, "confidence": proposal.decision.confidence})


# --- reading --------------------------------------------------------------------------------------------


def _steps(db: Session, run_id: uuid.UUID) -> list[models.AgentStep]:
    return list(db.scalars(select(models.AgentStep).where(models.AgentStep.run_id == run_id).order_by(models.AgentStep.ordinal)).all())


def _step_out(step: models.AgentStep, staff: bool) -> StepOut:
    output = dict(step.output or {})
    approval = output.pop("_approval", None)
    codes = list(output.get("codes") or []) if step.status == "blocked" else []
    action = tools.is_action(step.tool)
    return StepOut(
        id=step.id, ordinal=step.ordinal, tool=step.tool, kind="action" if action else "read", status=step.status, requires_approval=action,
        args=dict((step.input or {}).get("args") or {}), rationale=(step.input or {}).get("rationale") if staff else None,
        output=output if staff or action else {}, approval=ApprovalOut.model_validate(approval) if approval else None, block_codes=codes,
        created_at=_iso(step.created_at),
    )  # fmt: skip


def run_out(db: Session, run: models.AgentRun, role: str, *, reused: bool = False) -> RunOut:
    state = run.state or {}
    staff = role in STAFF_DETAIL_ROLES
    decision = state.get("decision") or {
        "choice": None,
        "confidence": 0.0,
        "route": "human",
        "reasons": [],
        "model_version": "none",
        "abstained": True,
    }
    return RunOut(
        id=run.id, case_id=uuid.UUID(state["case_id"]), status=run.status, outcome=state.get("outcome", "abstained"),
        planner=PlannerOut.model_validate(state.get("planner") or {"type": "local", "model_version": "none"}),
        decision=AgentDecisionOut(**{k: decision.get(k) for k in ("choice", "confidence", "abstained", "route", "reasons", "model_version")}),
        rationale=state.get("rationale") if staff else None, flags=list(state.get("flags") or []), step_budget=run.step_budget,
        steps_used=run.steps_used, steps=[_step_out(s, staff) for s in _steps(db, run.id)], reused=reused, created_at=_iso(run.created_at),
        updated_at=_iso(run.updated_at),
    )  # fmt: skip


def get_run(db: Session, principal: Principal, run_id: uuid.UUID) -> RunOut:
    run = db.scalar(select(models.AgentRun).where(models.AgentRun.id == run_id, models.AgentRun.tenant_id == principal.tenant_id))
    if run is None:
        raise NotFound("No such agent run.")
    return run_out(db, run, principal.role)


def list_runs(db: Session, principal: Principal, case_id: uuid.UUID, limit: int = 10) -> list[RunOut]:
    _case_row(db, principal.tenant_id, case_id)
    rows = db.scalars(select(models.AgentRun).where(models.AgentRun.tenant_id == principal.tenant_id, models.AgentRun.goal == _goal(case_id))
                      .order_by(models.AgentRun.created_at.desc(), models.AgentRun.id.desc()).limit(limit)).all()  # fmt: skip
    return [run_out(db, r, principal.role) for r in rows]


# --- approve and reject ---------------------------------------------------------------------------------


def _locked(db: Session, principal: Principal, step_id: uuid.UUID) -> tuple[models.AgentStep, models.AgentRun]:
    step = db.scalar(select(models.AgentStep).where(models.AgentStep.id == step_id, models.AgentStep.tenant_id == principal.tenant_id)
                     .with_for_update())  # fmt: skip
    if step is None:
        raise NotFound("No such agent step.")
    run = db.scalar(select(models.AgentRun).where(models.AgentRun.id == step.run_id, models.AgentRun.tenant_id == principal.tenant_id)
                    .with_for_update())  # fmt: skip
    if run is None:
        raise NotFound("No such agent run.")
    return step, run


def _approval(principal: Principal, kind: str, reason: str) -> dict[str, Any]:
    return {"action": kind, "by_user_id": str(principal.user_id), "at": _now().isoformat(), "reason": reason}


def reject_step(db: Session, principal: Principal, step_id: uuid.UUID, *, reason: str) -> RunOut:
    """The officer says no. Nothing runs. Repeating the call changes nothing. Does not commit."""
    step, run = _locked(db, principal, step_id)
    if not tools.is_action(step.tool):
        raise Conflict("Read steps are not approved or rejected.", code="step_not_actionable")
    if step.status == "rejected":
        return run_out(db, run, principal.role)
    if step.status != "waiting_approval":
        raise Conflict(f"This step is {step.status}; it can no longer be rejected.", code="step_not_pending")
    step.status = "rejected"
    step.output = {**(step.output or {}), "_approval": _approval(principal, "rejected", reason)}
    run.status = "done"
    run.updated_at = _now()
    _state(run, phase="finished", outcome="rejected")
    _audit(db, principal, run, "agent.step_rejected", step=step, reason=reason)
    db.flush()
    return run_out(db, run, principal.role)


def approve_step(db: Session, principal: Principal, step_id: uuid.UUID, *, reason: str) -> RunOut:
    """An officer approves one proposed action: the guard looks again with fresh facts, then the action runs once, as that officer.

    A repeat of an approval that already ran returns the same result and does nothing. Commits on a refusal or a failure so
    that the record of it stays; the caller commits a success.
    """
    step, run = _locked(db, principal, step_id)
    if not tools.is_action(step.tool):
        raise Conflict("Read steps are not approved or rejected.", code="step_not_actionable")
    if step.status == "done":
        return run_out(db, run, principal.role)  # idempotent: the action already ran
    if step.status != "waiting_approval":
        raise Conflict(f"This step is {step.status}; it cannot be approved.", code="step_not_pending")
    case_id = uuid.UUID((run.state or {})["case_id"])
    facts, detail, case = build_facts(db, principal, case_id)
    args = dict((step.input or {}).get("args") or {})
    tenant = db.get(models.Tenant, principal.tenant_id)
    limit = payment_rules.four_eyes_limit(tenant.config if tenant else None)
    verdict = gate.check("execute", step.tool, args, facts, role=principal.role, steps_used=run.steps_used, step_budget=run.step_budget,
                         step_status=step.status, approval_source="officer_request", approver_user_id=str(principal.user_id),
                         approver_role=principal.role, four_eyes_limit_pkr=limit,
                         prior_case_approvers=_approvers_of_case(db, principal.tenant_id, case.application_id))  # fmt: skip
    if verdict.blocked:
        _refuse(db, principal, run, step, verdict)
    _audit(db, principal, run, "agent.step_approved", step=step, reason=reason, details={"args": args})
    env = tools.ToolEnv(db=db, principal=principal, case_id=case_id, person_id=case.subject_person_id, facts=facts, detail=detail)
    try:
        output = tools.execute_action(env, step.tool, args, reason, step.ordinal)
    except AppError as exc:
        db.rollback()
        _fail(db, principal, step_id, exc.code)
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _fail(db, principal, step_id, f"error:{type(exc).__name__}")
        raise
    step.status = "done"
    step.output = {**output, "_approval": _approval(principal, "approved", reason)}
    run.status = "done"
    run.updated_at = _now()
    _state(run, phase="finished", outcome="approved")
    _audit(db, None, run, "agent.step_done", step=step, details={"result": {k: v for k, v in output.items() if k != "notification_template"}})
    db.flush()
    return run_out(db, run, principal.role)


def _refuse(db: Session, principal: Principal, run: models.AgentRun, step: models.AgentStep, verdict: GuardVerdict) -> None:
    """Record a refusal at execution, keep it (commit), and raise. The step ends unless only the approver was the problem."""
    terminal = not set(verdict.codes) <= APPROVER_CODES
    _record_refusal(db, principal, run, step, verdict)
    if terminal:
        step.status = "blocked"
        step.output = {**(step.output or {}), "codes": verdict.codes}
        run.status = "done"
        _state(run, phase="finished", outcome="failed")
    run.updated_at = _now()
    db.commit()
    err_cls = Forbidden if set(verdict.codes) <= APPROVER_CODES else AgentActionBlocked
    raise err_cls("The action guard refused this step.", code=verdict.codes[0], extra={"codes": verdict.codes})


def _fail(db: Session, principal: Principal, step_id: uuid.UUID, code: str) -> None:
    """After a rollback: store that the approved action failed, in a fresh transaction, so the record stays."""
    step, run = _locked(db, principal, step_id)
    step.status = "failed"
    step.output = {**(step.output or {}), "error": code}
    run.status = "done"
    run.updated_at = _now()
    _state(run, phase="finished", outcome="failed")
    _audit(db, principal, run, "agent.step_failed", step=step, result="failed", reason=code[:200])
    db.commit()


def providers() -> dict[str, str]:
    return provider_status()
