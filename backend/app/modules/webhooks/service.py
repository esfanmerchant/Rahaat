"""Webhook administration and delivery.

Delivery state lives in `webhook_deliveries`; the job queue only wakes the sender. Each `webhook.deliver` job makes
one attempt. A failed attempt records `response_code`, `last_error` and `next_attempt_at` (exponential backoff with
jitter) and queues the next job for that time, until `MAX_ATTEMPTS`, after which the delivery is `dead` and an
audit row says so. An admin can redeliver any delivery: that makes a new row and leaves the history alone.
"""

from __future__ import annotations

import json
import random
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.core import audit, webhook_signing
from app.core.crypto import decrypt_field, encrypt_field
from app.core.deps import Principal
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.logging import get_logger
from app.db import models
from app.modules.cases import paging
from app.modules.jobs.service import JobContext, PermanentJobError
from app.modules.webhooks import rules, sender
from app.modules.webhooks.emit import DELIVER_JOB, queue_delivery
from app.modules.webhooks.schemas import DeliveryList, DeliveryOut, WebhookCreate, WebhookCreated, WebhookOut, WebhookUpdate

log = get_logger("rahat.webhooks")
MAX_WEBHOOKS_PER_TENANT = 20
MAX_PAGE = 100


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _tenant(db: Session, tenant_id: uuid.UUID) -> models.Tenant:
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        raise NotFound("No such department.")
    return tenant


def _secret_of(db: Session, hook: models.Webhook) -> str:
    return decrypt_field(_tenant(db, hook.tenant_id).wrapped_dek, hook.secret_enc)


def _load(db: Session, principal: Principal, webhook_id: uuid.UUID, *, lock: bool = False) -> models.Webhook:
    query = select(models.Webhook).where(models.Webhook.id == webhook_id, models.Webhook.tenant_id == principal.tenant_id)
    hook = db.scalar(query.with_for_update() if lock else query)
    if hook is None:
        raise NotFound("No such webhook.", code="webhook_not_found")
    return hook


def _validated_url(url: str) -> str:
    try:
        sender.validate_url(url)
    except rules.BlockedTarget as exc:
        raise Unprocessable(exc.detail, code="webhook_url_refused", extra={"reason": exc.reason}) from exc
    return url


def _out(db: Session, hook: models.Webhook, counts: dict[str, int] | None = None) -> WebhookOut:
    secret = _secret_of(db, hook)
    counts = counts or {}
    return WebhookOut(
        id=hook.id, url=hook.url, events=[str(e) for e in hook.events or []], active=hook.active, secret_hint=secret[-4:],
        created_at=_iso(hook.created_at) or "", created_by=hook.created_by, is_mock_receiver=hook.url == rules.MOCK_RECEIVER_URL,
        deliveries_pending=counts.get("pending", 0) + counts.get("failed", 0), deliveries_dead=counts.get("dead", 0),
    )  # fmt: skip


def _status_counts(db: Session, tenant_id: uuid.UUID, webhook_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    result: dict[uuid.UUID, dict[str, int]] = {}
    if not webhook_ids:
        return result
    rows = db.execute(
        select(models.WebhookDelivery.webhook_id, models.WebhookDelivery.status, func.count())
        .where(models.WebhookDelivery.tenant_id == tenant_id, models.WebhookDelivery.webhook_id.in_(webhook_ids))
        .group_by(models.WebhookDelivery.webhook_id, models.WebhookDelivery.status)
    ).all()  # fmt: skip
    for webhook_id, status, count in rows:
        result.setdefault(webhook_id, {})[status] = int(count)
    return result


def list_webhooks(db: Session, principal: Principal) -> list[WebhookOut]:
    hooks = db.scalars(select(models.Webhook).where(models.Webhook.tenant_id == principal.tenant_id)
                       .order_by(models.Webhook.created_at, models.Webhook.id)).all()  # fmt: skip
    counts = _status_counts(db, principal.tenant_id, [h.id for h in hooks])
    return [_out(db, h, counts.get(h.id)) for h in hooks]


def get_webhook(db: Session, principal: Principal, webhook_id: uuid.UUID) -> WebhookOut:
    hook = _load(db, principal, webhook_id)
    return _out(db, hook, _status_counts(db, principal.tenant_id, [hook.id]).get(hook.id))


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def create_webhook(db: Session, principal: Principal, body: WebhookCreate) -> WebhookCreated:
    url = _validated_url(body.url.strip())
    existing = db.scalars(select(models.Webhook).where(models.Webhook.tenant_id == principal.tenant_id)).all()
    if len(existing) >= MAX_WEBHOOKS_PER_TENANT:
        raise Conflict("This department already has the most webhooks it can have. Delete one first.", code="too_many_webhooks")
    if any(h.url == url for h in existing):
        # The secret is shown once, so a repeat create cannot hand it out again: it is a conflict, not a replay.
        raise Conflict("A webhook for this address already exists. Update it, or rotate its secret.", code="webhook_exists")
    secret = new_secret()
    hook = models.Webhook(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, url=url, secret_enc=encrypt_field(_tenant(db, principal.tenant_id).wrapped_dek, secret),
        events=list(body.events), active=True, created_by=principal.user_id, created_at=datetime.now(UTC),
    )  # fmt: skip
    db.add(hook)
    db.flush()
    audit.write(db, tenant_id=principal.tenant_id, action="webhook.created", actor_id=principal.user_id, actor_role=principal.role,
                object_type="webhook", object_id=hook.id,
                details={"events": hook.events, "mock_receiver": url == rules.MOCK_RECEIVER_URL})  # fmt: skip
    out = _out(db, hook)
    if url == rules.MOCK_RECEIVER_URL:
        sender.register_mock_secret(str(hook.id), secret)
    return WebhookCreated(**out.model_dump(), secret=secret)


def update_webhook(db: Session, principal: Principal, webhook_id: uuid.UUID, body: WebhookUpdate) -> WebhookOut:
    hook = _load(db, principal, webhook_id, lock=True)
    changed: dict[str, Any] = {}
    if body.url is not None and body.url.strip() != hook.url:
        hook.url = _validated_url(body.url.strip())
        changed["url"] = True
    if body.events is not None:
        hook.events = list(body.events)
        changed["events"] = hook.events
    if body.active is not None and body.active != hook.active:
        hook.active = body.active
        changed["active"] = body.active
    if changed:
        audit.write(db, tenant_id=principal.tenant_id, action="webhook.updated", actor_id=principal.user_id, actor_role=principal.role,
                    object_type="webhook", object_id=hook.id, details=changed)  # fmt: skip
    db.flush()
    return _out(db, hook, _status_counts(db, principal.tenant_id, [hook.id]).get(hook.id))


def rotate_secret(db: Session, principal: Principal, webhook_id: uuid.UUID) -> WebhookCreated:
    hook = _load(db, principal, webhook_id, lock=True)
    secret = new_secret()
    hook.secret_enc = encrypt_field(_tenant(db, principal.tenant_id).wrapped_dek, secret)
    audit.write(db, tenant_id=principal.tenant_id, action="webhook.secret_rotated", actor_id=principal.user_id, actor_role=principal.role,
                object_type="webhook", object_id=hook.id)  # fmt: skip
    db.flush()
    if hook.url == rules.MOCK_RECEIVER_URL:
        sender.register_mock_secret(str(hook.id), secret)
    return WebhookCreated(**_out(db, hook).model_dump(), secret=secret)


def delete_webhook(db: Session, principal: Principal, webhook_id: uuid.UUID) -> None:
    hook = _load(db, principal, webhook_id, lock=True)
    audit.write(db, tenant_id=principal.tenant_id, action="webhook.deleted", actor_id=principal.user_id, actor_role=principal.role,
                object_type="webhook", object_id=hook.id, details={"mock_receiver": hook.url == rules.MOCK_RECEIVER_URL})  # fmt: skip
    db.delete(hook)
    db.flush()


# --- deliveries -------------------------------------------------------------------------------------------


def _delivery_out(row: models.WebhookDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=row.id, webhook_id=row.webhook_id, event=row.event, status=row.status, attempts=row.attempts, max_attempts=rules.MAX_ATTEMPTS,  # type: ignore[arg-type]
        response_code=row.response_code, last_error=row.last_error, next_attempt_at=_iso(row.next_attempt_at),
        delivered_at=_iso(row.delivered_at), created_at=_iso(row.created_at) or "", payload=dict(row.payload or {}),
    )  # fmt: skip


def list_deliveries(db: Session, principal: Principal, webhook_id: uuid.UUID, *, status: str | None, limit: int, cursor: str | None) -> DeliveryList:
    _load(db, principal, webhook_id)
    query = select(models.WebhookDelivery).where(models.WebhookDelivery.tenant_id == principal.tenant_id,
                                                 models.WebhookDelivery.webhook_id == webhook_id)  # fmt: skip
    if status:
        query = query.where(models.WebhookDelivery.status == status)
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        before = tuple_(paging.as_datetime(created), paging.as_uuid(row_id))
        query = query.where(tuple_(models.WebhookDelivery.created_at, models.WebhookDelivery.id) < before)
    newest_first = (models.WebhookDelivery.created_at.desc(), models.WebhookDelivery.id.desc())
    rows = db.scalars(query.order_by(*newest_first).limit(min(limit, MAX_PAGE) + 1)).all()
    page = rows[: min(limit, MAX_PAGE)]
    nxt = paging.encode(page[-1].created_at, page[-1].id) if len(rows) > len(page) and page else None
    return DeliveryList(items=[_delivery_out(r) for r in page], next_cursor=nxt)


def redeliver(db: Session, principal: Principal, webhook_id: uuid.UUID, delivery_id: uuid.UUID) -> DeliveryOut:
    hook = _load(db, principal, webhook_id)
    old = db.scalar(select(models.WebhookDelivery).where(models.WebhookDelivery.id == delivery_id, models.WebhookDelivery.webhook_id == hook.id,
                                                         models.WebhookDelivery.tenant_id == principal.tenant_id))  # fmt: skip
    if old is None:
        raise NotFound("No such delivery.", code="delivery_not_found")
    new = queue_delivery(db, hook, old.event, dict(old.payload or {}))
    audit.write(db, tenant_id=principal.tenant_id, action="webhook.redelivered", actor_id=principal.user_id, actor_role=principal.role,
                object_type="webhook", object_id=hook.id,
                details={"delivery_id": str(new.id), "redelivery_of": str(old.id), "event": old.event})  # fmt: skip
    return _delivery_out(new)


def send_test(db: Session, principal: Principal, webhook_id: uuid.UUID) -> DeliveryOut:
    """Make a `webhook.test` delivery and try it at once, so the admin sees the answer. A failure retries like any other."""
    hook = _load(db, principal, webhook_id, lock=True)
    delivery = queue_delivery(db, hook, rules.TEST_EVENT, {"webhook_id": str(hook.id), "status": "test"})
    audit.write(db, tenant_id=principal.tenant_id, action="webhook.test_sent", actor_id=principal.user_id, actor_role=principal.role,
                object_type="webhook", object_id=hook.id, details={"delivery_id": str(delivery.id)})  # fmt: skip
    attempt(db, delivery, hook)
    return _delivery_out(delivery)


def mock_received(db: Session, principal: Principal, webhook_id: uuid.UUID | None, limit: int) -> dict[str, Any]:
    if webhook_id is not None:
        _load(db, principal, webhook_id)
    mine = {str(h.id) for h in db.scalars(select(models.Webhook).where(models.Webhook.tenant_id == principal.tenant_id,
                                                                       models.Webhook.url == rules.MOCK_RECEIVER_URL))}  # fmt: skip
    received = sender.mock_received(str(webhook_id) if webhook_id else None, 300 if webhook_id is None else limit)
    items = [i for i in received.get("items", []) if i.get("webhook_id") in mine][:limit]  # one department never sees another's
    return {"reachable": bool(received.get("reachable", True)), "items": items}


# --- sending ---------------------------------------------------------------------------------------------


def body_for(delivery: models.WebhookDelivery) -> bytes:
    document = {"id": str(delivery.id), "event": delivery.event, "created_at": _iso(delivery.created_at), "data": dict(delivery.payload or {})}
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def attempt(db: Session, delivery: models.WebhookDelivery, hook: models.Webhook, *, now: datetime | None = None,
            rand: float | None = None, send: Any = None) -> str:  # fmt: skip
    """One delivery attempt. Updates the row and, when it failed and may retry, queues the next job. Returns the new status."""
    now = now or datetime.now(UTC)
    body = body_for(delivery)
    timestamp = int(time.time())
    headers = {
        "X-Rahat-Event": delivery.event, "X-Rahat-Delivery": str(delivery.id), "X-Rahat-Timestamp": str(timestamp),
        "X-Rahat-Signature": webhook_signing.sign(_secret_of(db, hook), timestamp, body), "X-Rahat-Webhook": str(hook.id),
        "User-Agent": "Rahat-Webhooks/1 (prototype)",
    }  # fmt: skip
    if hook.url == rules.MOCK_RECEIVER_URL:
        sender.register_mock_secret(str(hook.id), _secret_of(db, hook))  # keeps the mock receiver in step (it forgets on restart)
    result = (send or sender.send_signed)(hook.url, body, headers)
    delivery.attempts = (delivery.attempts or 0) + 1
    delivery.response_code = result.status_code
    if result.ok:
        delivery.status, delivery.last_error, delivery.next_attempt_at, delivery.delivered_at = "delivered", None, None, now
        db.flush()
        return "delivered"
    delivery.last_error = (result.error or "failed")[:300]
    if delivery.attempts >= rules.MAX_ATTEMPTS or not rules.retryable(result.error):
        delivery.status, delivery.next_attempt_at = "dead", None
        audit.write(db, tenant_id=delivery.tenant_id, action="webhook.delivery_dead", actor_type="system", actor_role="worker",
                    object_type="webhook", object_id=hook.id, result="failed", reason=delivery.last_error,
                    details={"delivery_id": str(delivery.id), "event": delivery.event, "attempts": delivery.attempts})  # fmt: skip
        db.flush()
        return "dead"
    wait = rules.backoff_seconds(delivery.attempts, random.random() if rand is None else rand)  # noqa: S311  (jitter, not security)
    delivery.status, delivery.next_attempt_at = "failed", now + timedelta(seconds=wait)
    db.flush()
    from app.modules.jobs.service import enqueue

    enqueue(db, tenant_id=delivery.tenant_id, kind=DELIVER_JOB, payload={"delivery_id": str(delivery.id)}, priority=60, max_attempts=3,
            run_at=delivery.next_attempt_at)  # fmt: skip
    return "failed"


def deliver_job(db: Session, job: JobContext) -> None:
    try:
        delivery_id = uuid.UUID(str(job.payload.get("delivery_id")))
    except ValueError as exc:
        raise PermanentJobError("bad delivery id") from exc
    delivery = db.scalar(select(models.WebhookDelivery).where(models.WebhookDelivery.id == delivery_id).with_for_update())
    if delivery is None:
        raise PermanentJobError("delivery not found")
    if delivery.status in ("delivered", "dead"):
        return  # a job that runs twice must not send twice
    hook = db.get(models.Webhook, delivery.webhook_id)
    if hook is None or not hook.active:
        delivery.status, delivery.next_attempt_at, delivery.last_error = "dead", None, "webhook_disabled_or_deleted"
        return
    attempt(db, delivery, hook)
