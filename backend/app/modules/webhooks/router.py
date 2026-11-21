"""Webhooks for a department's admin: subscribe a server to events, see every delivery, send a test, redeliver."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.webhooks import rules, service
from app.modules.webhooks.schemas import (
    DeliveryList,
    DeliveryOut,
    EventOut,
    MockReceived,
    WebhookCreate,
    WebhookCreated,
    WebhookOut,
    WebhookUpdate,
)

router = APIRouter(prefix="/v1/admin/webhooks", tags=["admin: webhooks"])
_manage = Policy("webhooks:manage", ["admin"], description="Create, change, test and delete this department's webhooks; read their deliveries")


@router.get("", response_model=list[WebhookOut], summary="This department's webhooks (never the secrets)")
def list_webhooks(principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> list[WebhookOut]:
    return service.list_webhooks(db, principal)


@router.post("", response_model=WebhookCreated, status_code=201,
             summary="Create a webhook; the response is the only time the signing secret is shown")  # fmt: skip
def create_webhook(
    body: WebhookCreate,
    principal: Principal = Depends(_manage),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=80,
                                         description="Accepted; a repeat for the same address is a 409 `webhook_exists`"),
) -> WebhookCreated:
    out = service.create_webhook(db, principal, body)
    db.commit()
    return out


@router.get("/events", response_model=list[EventOut], summary="The events a webhook can subscribe to")
def list_events(_: Principal = Depends(_manage)) -> list[EventOut]:
    return [EventOut(name=name, description=text) for name, text in rules.EVENTS.items()]


@router.get("/mock-receiver/received", response_model=MockReceived,
            summary="What the built-in mock receiver (url `mock://receiver`) got, with whether each signature verified")  # fmt: skip
def mock_received(
    webhook_id: UUID | None = Query(None), limit: int = Query(50, ge=1, le=300),
    principal: Principal = Depends(_manage), db: Session = Depends(get_db),
) -> MockReceived:  # fmt: skip
    return MockReceived.model_validate(service.mock_received(db, principal, webhook_id, limit))


@router.get("/{webhook_id}", response_model=WebhookOut, summary="One webhook (never the secret)")
def get_webhook(webhook_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> WebhookOut:
    return service.get_webhook(db, principal, webhook_id)


@router.patch("/{webhook_id}", response_model=WebhookOut, summary="Change the address or events, or disable it")
def update_webhook(webhook_id: UUID, body: WebhookUpdate, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> WebhookOut:
    out = service.update_webhook(db, principal, webhook_id, body)
    db.commit()
    return out


@router.delete("/{webhook_id}", status_code=204, summary="Delete a webhook and its delivery log")
def delete_webhook(webhook_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> Response:
    service.delete_webhook(db, principal, webhook_id)
    db.commit()
    return Response(status_code=204)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreated, summary="Make a new signing secret; shown once, the old one stops")
def rotate_secret(webhook_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> WebhookCreated:
    out = service.rotate_secret(db, principal, webhook_id)
    db.commit()
    return out


@router.post("/{webhook_id}/test", response_model=DeliveryOut, status_code=201,
             summary="Send a `webhook.test` event now and return how it went")  # fmt: skip
def test_webhook(webhook_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> DeliveryOut:
    out = service.send_test(db, principal, webhook_id)
    db.commit()
    return out


@router.get("/{webhook_id}/deliveries", response_model=DeliveryList, summary="The delivery log, newest first")
def list_deliveries(
    webhook_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(pending|delivered|failed|dead)$"),
    cursor: str | None = Query(None, max_length=200), limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> DeliveryList:  # fmt: skip
    return service.list_deliveries(db, principal, webhook_id, status=status, limit=limit, cursor=cursor)


@router.post("/{webhook_id}/deliveries/{delivery_id}/redeliver", response_model=DeliveryOut, status_code=201,
             summary="Send an earlier event again (a new delivery; the old one stays in the log)")  # fmt: skip
def redeliver(webhook_id: UUID, delivery_id: UUID, principal: Principal = Depends(_manage), db: Session = Depends(get_db)) -> DeliveryOut:
    out = service.redeliver(db, principal, webhook_id, delivery_id)
    db.commit()
    return out
