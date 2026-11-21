"""Appeals and complaints: citizens (or their helpers) file them and follow them; officers decide them."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.appeals import service
from app.modules.appeals.schemas import (
    AppealCreate,
    AppealDecide,
    AppealList,
    AppealOut,
    AppealStaffDetail,
    AppealStaffList,
    ComplaintCreate,
    ComplaintList,
    ComplaintOut,
    ComplaintResolve,
    ComplaintStaffList,
    ComplaintStaffOut,
)
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1", tags=["appeals and complaints"])

_file_appeal = acting_person("appeals:write-own", "apply", description="A citizen, or a helper with the apply scope, appeals a rejection")
_my_appeals = acting_person("appeals:read-own", "track", description="A citizen's own appeals, or a helper's delegated person's")
_file_complaint = acting_person("complaints:write-own", "apply", description="A citizen, or a helper with the apply scope, files a complaint")
_my_complaints = acting_person("complaints:read-own", "track", description="A citizen's own complaints, or a helper's delegated person's")
_queue = Policy("appeals:read", ["officer", "auditor"], description="The appeals queue (tracking code only, and only with consent)")
_review = Policy("appeals:review", ["officer"], description="Read one appeal with the citizen's reason and the original decision")
_decide = Policy("appeals:decide", ["officer"], description="Decide an appeal; never the officer who took part in the first decision")
_complaint_queue = Policy("complaints:read", ["officer"], description="The complaints queue")
_complaint_resolve = Policy("complaints:resolve", ["officer"], description="Resolve or dismiss a complaint")

IDEMPOTENCY = Header(None, alias="Idempotency-Key", max_length=80, description="A repeat with the same key returns the first result")


@router.post("/appeals", response_model=AppealOut, status_code=201,
             summary="Appeal a rejection (within 30 days, once per decision); opens a case for a different officer")  # fmt: skip
def create_appeal(body: AppealCreate, response: Response, ctx: PersonContext = Depends(_file_appeal), db: Session = Depends(get_db),
                  idempotency_key: str | None = IDEMPOTENCY) -> AppealOut:  # fmt: skip
    out, created = service.create_appeal(db, ctx, body, idempotency_key)
    if not created:
        response.status_code = 200
    return out


@router.get("/me/appeals", response_model=AppealList, summary="My appeals, newest first, with keyed text in English and Urdu")
def my_appeals(ctx: PersonContext = Depends(_my_appeals), db: Session = Depends(get_db), cursor: str | None = Query(None, max_length=200),
               limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)) -> AppealList:  # fmt: skip
    return service.list_my_appeals(db, ctx, limit=limit, cursor=cursor)


@router.get("/appeals", response_model=AppealStaffList, summary="The appeals queue, oldest first")
def staff_appeals(
    principal: Principal = Depends(_queue), db: Session = Depends(get_db),
    status: Literal["open", "upheld", "overturned", "withdrawn", "all"] = Query("open"),
    cursor: str | None = Query(None, max_length=200), limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> AppealStaffList:  # fmt: skip
    return service.list_staff(db, principal, status=status, limit=limit, cursor=cursor)


@router.get("/appeals/{appeal_id}", response_model=AppealStaffDetail,
            summary="One appeal: the citizen's reason, the original decision, and whether you may decide it")  # fmt: skip
def staff_appeal(appeal_id: UUID, principal: Principal = Depends(_review), db: Session = Depends(get_db)) -> AppealStaffDetail:
    out = service.get_staff(db, principal, appeal_id)
    db.commit()
    return out


@router.post("/appeals/{appeal_id}/decide", response_model=AppealStaffDetail,
             summary="Uphold or overturn (a different officer than the first decision; a reason is required)")  # fmt: skip
def decide_appeal(appeal_id: UUID, body: AppealDecide, principal: Principal = Depends(_decide), db: Session = Depends(get_db)) -> AppealStaffDetail:
    return service.decide(db, principal, appeal_id, body)


@router.post("/complaints", response_model=ComplaintOut, status_code=201,
             summary="File a complaint about service, staff, a payment or a scam attempt; opens a case")  # fmt: skip
def create_complaint(body: ComplaintCreate, response: Response, ctx: PersonContext = Depends(_file_complaint), db: Session = Depends(get_db),
                     idempotency_key: str | None = IDEMPOTENCY) -> ComplaintOut:  # fmt: skip
    out, created = service.create_complaint(db, ctx, body, idempotency_key)
    if not created:
        response.status_code = 200
    return out


@router.get("/me/complaints", response_model=ComplaintList, summary="My complaints and where each one stands")
def my_complaints(ctx: PersonContext = Depends(_my_complaints), db: Session = Depends(get_db), cursor: str | None = Query(None, max_length=200),
                  limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)) -> ComplaintList:  # fmt: skip
    return service.list_my_complaints(db, ctx, limit=limit, cursor=cursor)


@router.get("/complaints", response_model=ComplaintStaffList, summary="The complaints queue (scam reports included)")
def staff_complaints(
    principal: Principal = Depends(_complaint_queue), db: Session = Depends(get_db),
    status: Literal["active", "resolved", "all"] = Query("active"),
    cursor: str | None = Query(None, max_length=200), limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ComplaintStaffList:  # fmt: skip
    return service.list_staff_complaints(db, principal, status=status, limit=limit, cursor=cursor)


@router.post("/complaints/{case_id}/resolve", response_model=ComplaintStaffOut, summary="Resolve or dismiss a complaint; the citizen is told")
def resolve_complaint(case_id: UUID, body: ComplaintResolve, principal: Principal = Depends(_complaint_resolve),
                      db: Session = Depends(get_db)) -> ComplaintStaffOut:  # fmt: skip
    return service.resolve_complaint(db, principal, case_id, body)
