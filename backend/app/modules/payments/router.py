"""Payments and the maker-checker approvals queue, for officers."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.contracts.api import ApprovalDecideIn, ApprovalOut, PaymentOut
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.db import models
from app.modules.cases import paging
from app.modules.payments import service

router = APIRouter(prefix="/v1", tags=["payments"])
_read = Policy("payments:read", ["officer"], api_scopes=["payments:read"], description="Payments of this department")
_approvals_read = Policy("approvals:read", ["officer"], description="Payments waiting for a second person")
_approvals_decide = Policy("approvals:decide", ["officer"], description="Release or stop a payment above the limit (four-eyes)")


class PaymentList(Page):
    items: list[PaymentOut]


class ApprovalList(Page):
    items: list[ApprovalOut]


def payment_out(p: models.Payment) -> PaymentOut:
    return PaymentOut(id=p.id, application_id=p.application_id, amount_pkr=p.amount_pkr, status=p.status, rail_ref=p.rail_ref,
                      approval_id=p.approval_id, created_at=paging.iso(p.created_at) or "")  # fmt: skip


def approval_out(a: models.Approval) -> ApprovalOut:
    return ApprovalOut(id=a.id, kind=a.kind, subject_type=a.subject_type, subject_id=a.subject_id, status=a.status,
                       requested_by=a.requested_by, approver_id=a.approver_id, reason=a.reason,
                       created_at=paging.iso(a.created_at) or "")  # fmt: skip


@router.get("/payments", response_model=PaymentList, summary="Payments, newest first")
def list_payments(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    status: Literal["pending_approval", "approved", "submitted", "settled", "failed", "reversed", "cancelled"] | None = Query(None),
    application_id: uuid.UUID | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=200),
) -> PaymentList:
    query = select(models.Payment).where(models.Payment.tenant_id == principal.tenant_id)
    if status:
        query = query.where(models.Payment.status == status)
    if application_id:
        query = query.where(models.Payment.application_id == application_id)
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Payment.created_at, models.Payment.id) < tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    rows = db.scalars(query.order_by(models.Payment.created_at.desc(), models.Payment.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    return PaymentList(items=[payment_out(p) for p in page],
                       next_cursor=paging.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None)  # fmt: skip


@router.get("/approvals", response_model=ApprovalList, summary="Approvals waiting for a second person")
def list_approvals(
    principal: Principal = Depends(_approvals_read),
    db: Session = Depends(get_db),
    status: Literal["pending", "approved", "rejected", "expired"] = Query("pending"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=200),
) -> ApprovalList:
    query = select(models.Approval).where(models.Approval.tenant_id == principal.tenant_id, models.Approval.kind == "payment",
                                          models.Approval.status == status)  # fmt: skip
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Approval.created_at, models.Approval.id) > tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    rows = db.scalars(query.order_by(models.Approval.created_at, models.Approval.id).limit(limit + 1)).all()  # oldest waits first
    page = rows[:limit]
    return ApprovalList(items=[approval_out(a) for a in page],
                        next_cursor=paging.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None)  # fmt: skip


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalOut, summary="Release or stop a payment (second person)")
def decide(
    approval_id: uuid.UUID, body: ApprovalDecideIn, principal: Principal = Depends(_approvals_decide), db: Session = Depends(get_db)
) -> ApprovalOut:
    approval = service.decide_approval(db, principal, approval_id, approve=body.approve, reason=body.reason)
    db.commit()
    return approval_out(approval)


from app.modules.payments.settings_router import router as _settings_router  # noqa: E402

router.include_router(_settings_router)
