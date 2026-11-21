"""The agent for case review. An officer starts a run, the agent proposes one action, and an officer approves or rejects it.

Starting a run and approving a step need an officer: only an officer can open the person's file (consent and Row Level Security
apply to the agent exactly as to the officer), and the approving officer is the one the payment and audit rows name. Admins and
auditors can read runs (without the case text) but cannot start, approve or reject anything.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.agent import service
from app.modules.agent.schemas import RunList, RunOut, StepDecisionIn

router = APIRouter(tags=["agent"])
_run = Policy("agent:run", ["officer"], description="Start an agent run on a case; the agent proposes, nothing happens yet")
_decide = Policy("agent:approve", ["officer"], description="Approve or reject one proposed agent action; approval runs it, as that officer")
_read = Policy("agent:read", ["officer", "admin", "auditor"], description="Read agent runs and steps (case text is shown to officers only)")


@router.post("/v1/cases/{case_id}/agent/runs", response_model=RunOut, status_code=201, summary="Start an agent run on a case")
def start_run(case_id: uuid.UUID, principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> RunOut:
    out = service.start_run(db, principal, case_id)
    db.commit()
    return out


@router.get("/v1/cases/{case_id}/agent/runs", response_model=RunList, summary="Agent runs for a case, newest first")
def list_runs(
    case_id: uuid.UUID, limit: int = Query(10, ge=1, le=25), principal: Principal = Depends(_read), db: Session = Depends(get_db)
) -> RunList:
    return RunList(items=service.list_runs(db, principal, case_id, limit))


@router.get("/v1/agent/runs/{agent_run_id}", response_model=RunOut, summary="One agent run with its steps")
def get_run(agent_run_id: uuid.UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> RunOut:
    return service.get_run(db, principal, agent_run_id)


@router.post(
    "/v1/agent/steps/{step_id}/approve", response_model=RunOut, summary="Approve a proposed action: the guard checks again, then it runs once"
)
def approve_step(step_id: uuid.UUID, body: StepDecisionIn, principal: Principal = Depends(_decide), db: Session = Depends(get_db)) -> RunOut:
    out = service.approve_step(db, principal, step_id, reason=body.reason)
    db.commit()
    return out


@router.post("/v1/agent/steps/{step_id}/reject", response_model=RunOut, summary="Reject a proposed action: nothing runs")
def reject_step(step_id: uuid.UUID, body: StepDecisionIn, principal: Principal = Depends(_decide), db: Session = Depends(get_db)) -> RunOut:
    out = service.reject_step(db, principal, step_id, reason=body.reason)
    db.commit()
    return out
