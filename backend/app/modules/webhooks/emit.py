"""The outbox side of webhooks: one small function the rest of the code calls when something happens.

    from app.modules.webhooks.emit import emit
    emit(db, tenant_id, "case.opened", {"case_id": case.id, "kind": case.kind, "status": case.status})

It writes a `webhook_deliveries` row for every active webhook of the department that subscribes to the event,
and queues a `webhook.deliver` job, in the caller's transaction (the outbox pattern): the delivery exists
exactly when the change that caused it was committed. It never sends anything itself, never raises, and keeps
only ids and statuses from `data` (rules.clean_payload), so no name, phone number or national ID can leave.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import models
from app.modules.jobs.service import enqueue
from app.modules.webhooks import rules

log = get_logger("rahat.webhooks")
DELIVER_JOB = "webhook.deliver"


def queue_delivery(
    db: Session, webhook: models.Webhook, event: str, payload: dict[str, str], *, run_at: datetime | None = None
) -> models.WebhookDelivery:
    delivery = models.WebhookDelivery(
        id=uuid.uuid4(), tenant_id=webhook.tenant_id, webhook_id=webhook.id, event=event, payload=payload, status="pending",
        attempts=0, next_attempt_at=run_at or datetime.now(UTC), created_at=datetime.now(UTC),
    )  # fmt: skip
    db.add(delivery)
    db.flush()
    enqueue(db, tenant_id=webhook.tenant_id, kind=DELIVER_JOB, payload={"delivery_id": str(delivery.id)}, priority=60, max_attempts=3, run_at=run_at)
    return delivery


def emit(db: Session, tenant_id: uuid.UUID, event: str, data: dict[str, Any]) -> int:
    """Queue `event` for the department's subscribers. Returns how many deliveries were queued; failures are logged, not raised."""
    if event not in rules.EVENTS:
        log.error("unknown webhook event %r was not queued", event)
        return 0
    payload = rules.clean_payload(data)
    try:
        with db.begin_nested():  # a failure here must not undo or fail the change that raised the event
            hooks = db.scalars(select(models.Webhook).where(models.Webhook.tenant_id == tenant_id, models.Webhook.active.is_(True))).all()
            queued = [queue_delivery(db, hook, event, payload) for hook in hooks if rules.subscribed(hook.events, event)]
        return len(queued)
    except Exception:  # noqa: BLE001
        log.exception("could not queue webhook event %s", event)
        return 0
