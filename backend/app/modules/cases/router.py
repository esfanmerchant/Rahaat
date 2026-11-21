"""The officer's review queue and case actions. One case per request: there are no bulk actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.orm import Session

from app.contracts.api import CaseActionIn, CaseDetail, CaseList, CaseNoteIn
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, CaseKind, Strict
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.cases import service

router = APIRouter(prefix="/v1/cases", tags=["cases"])
# API keys may read the queue, never the case file: that holds detection details meant for staff only.
_queue = Policy("cases:read", ["officer"], api_scopes=["cases:read"], description="The review queue (API keys with cases:read too)")
_read = Policy("cases:read", ["officer"], description="The review queue and a case's handoff package")
_work = Policy("cases:work", ["officer"], description="Take or hand over a case, add notes")
_decide = Policy("cases:decide", ["officer"], description="Approve, reject, request proof, escalate or reopen, with a reason")


class CaseAssignIn(Strict):
    assignee_id: uuid.UUID | None = Field(default=None, description="An officer of this department; omit to take the case yourself")
    reason: str = Field(min_length=5, max_length=1000)


class CaseReopenIn(Strict):
    reason: str = Field(min_length=5, max_length=1000)


@router.get("", response_model=CaseList, summary="Review queue")
def list_cases(
    principal: Principal = Depends(_queue),
    db: Session = Depends(get_db),
    status: service.StatusFilter = Query("active", description="A status, 'active' (default) or 'all'"),
    kind: CaseKind | None = Query(None),
    assignee: str | None = Query(None, max_length=40, description="'me', 'unassigned' or a user id"),
    sort: service.SortKey = Query("priority", description="priority (most urgent first), confidence (least sure first) or age (oldest first)"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=300),
) -> CaseList:
    return service.list_cases(db, principal, status=status, kind=kind, assignee=assignee, sort=sort, limit=limit, cursor=cursor)


@router.get("/{case_id}", response_model=CaseDetail, summary="One case with its handoff package, form, document checks and trace")
def get_case(case_id: uuid.UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> CaseDetail:
    detail = service.get_detail(db, principal, case_id)
    db.commit()  # the view is recorded in the case events and the audit log
    return detail


@router.post("/{case_id}/assign", response_model=CaseDetail, summary="Take a case or give it to another officer")
def assign_case(case_id: uuid.UUID, body: CaseAssignIn, principal: Principal = Depends(_work), db: Session = Depends(get_db)) -> CaseDetail:
    detail = service.assign(db, principal, case_id, assignee_id=body.assignee_id, reason=body.reason)
    db.commit()
    return detail


@router.post("/{case_id}/notes", response_model=CaseDetail, status_code=201, summary="Add a note")
def add_note(case_id: uuid.UUID, body: CaseNoteIn, principal: Principal = Depends(_work), db: Session = Depends(get_db)) -> CaseDetail:
    detail = service.add_note(db, principal, case_id, body=body.body)
    db.commit()
    return detail


@router.post("/{case_id}/actions", response_model=CaseDetail, summary="Approve, reject, request proof or escalate")
def act_on_case(case_id: uuid.UUID, body: CaseActionIn, principal: Principal = Depends(_decide), db: Session = Depends(get_db)) -> CaseDetail:
    detail = service.act(db, principal, case_id, body)
    db.commit()
    return detail


@router.post("/{case_id}/reopen", response_model=CaseDetail, summary="Reopen a resolved case")
def reopen_case(case_id: uuid.UUID, body: CaseReopenIn, principal: Principal = Depends(_decide), db: Session = Depends(get_db)) -> CaseDetail:
    detail = service.reopen(db, principal, case_id, reason=body.reason)
    db.commit()
    return detail
