"""My messages, the department's outbox (destinations masked), and the public verify-code check."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import false, or_, select, tuple_
from sqlalchemy.orm import Session

from app.contracts.api import NotificationList, NotificationOut
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, Strict
from app.core.deps import Principal, get_db
from app.core.policy import Policy, Public, any_authenticated
from app.db import models
from app.modules.cases import paging
from app.modules.notifications import service

router = APIRouter(prefix="/v1", tags=["notifications"])
_mine = any_authenticated("notifications:read-own")
_outbox = Policy("notifications:outbox", ["officer", "admin"], description="Every message the department sent; destinations masked")


class OutboxItem(BaseModel):
    id: uuid.UUID
    channel: str
    template: str
    lang: str
    body: str
    status: str
    attempts: int
    destination: str | None = Field(default=None, description="Masked: only the last three digits")
    verify_code: str | None = None
    last_error: str | None = None
    created_at: str
    sent_at: str | None = None


class OutboxList(Page):
    items: list[OutboxItem]


class VerifyIn(Strict):
    code: str = Field(min_length=4, max_length=16, description="The code at the end of a message")


class VerifyOut(BaseModel):
    genuine: bool = Field(description="True only for a message this platform really sent")
    template: str | None = None
    channel: str | None = None
    department: str | None = None
    sent_at: str | None = None


def _page(query, limit: int, cursor: str | None):  # type: ignore[no-untyped-def]
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(
            tuple_(models.Notification.created_at, models.Notification.id) < tuple_(paging.as_datetime(created), paging.as_uuid(row_id))
        )
    return query.order_by(models.Notification.created_at.desc(), models.Notification.id.desc()).limit(limit + 1)


def _next(rows: list[models.Notification], limit: int) -> str | None:
    return paging.encode(rows[limit - 1].created_at, rows[limit - 1].id) if len(rows) > limit else None


@router.get("/notifications", response_model=NotificationList, summary="My messages, newest first")
def my_notifications(
    principal: Principal = Depends(_mine),
    db: Session = Depends(get_db),
    channel: Literal["in_app", "sms", "all"] = Query("in_app"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=200),
) -> NotificationList:
    mine = or_(
        models.Notification.user_id == principal.user_id,
        models.Notification.person_id == principal.person_id if principal.person_id else false(),
    )
    query = select(models.Notification).where(models.Notification.tenant_id == principal.tenant_id, mine)
    if channel != "all":
        query = query.where(models.Notification.channel == channel)
    rows = list(db.scalars(_page(query, limit, cursor)).all())
    items = [
        NotificationOut(id=r.id, channel=r.channel, template=r.template, lang=r.lang, body=r.body, status=r.status,
                        verify_code=r.verify_code, created_at=paging.iso(r.created_at) or "")  # fmt: skip
        for r in rows[:limit]
    ]
    return NotificationList(items=items, next_cursor=_next(rows, limit))


@router.get("/outbox", response_model=OutboxList, summary="Every message this department sent (destinations masked)")
def outbox(
    principal: Principal = Depends(_outbox),
    db: Session = Depends(get_db),
    status: Literal["queued", "sent", "failed", "read"] | None = Query(None),
    channel: Literal["in_app", "sms"] | None = Query(None),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=200),
) -> OutboxList:
    query = select(models.Notification).where(models.Notification.tenant_id == principal.tenant_id)
    if status:
        query = query.where(models.Notification.status == status)
    if channel:
        query = query.where(models.Notification.channel == channel)
    rows = list(db.scalars(_page(query, limit, cursor)).all())
    items = [
        OutboxItem(id=r.id, channel=r.channel, template=r.template, lang=r.lang, body=r.body, status=r.status, attempts=r.attempts,
                   destination=(r.payload or {}).get("_to") if r.channel == "sms" else "in-app",
                   verify_code=r.verify_code, last_error=r.last_error, created_at=paging.iso(r.created_at) or "",
                   sent_at=paging.iso(r.sent_at))  # fmt: skip
        for r in rows[:limit]
    ]
    return OutboxList(items=items, next_cursor=_next(rows, limit))


@router.post("/notifications/verify", response_model=VerifyOut, summary="Check the code at the end of a message")
def verify_message(body: VerifyIn, _: None = Depends(Public("anyone can check whether a message really came from Rahat"))) -> VerifyOut:
    result = service.lookup_verify_code(body.code)
    return VerifyOut(genuine=result.genuine, template=result.template, channel=result.channel, department=result.department,
                     sent_at=result.sent_at)  # fmt: skip
