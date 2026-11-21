"""The notification outbox: in-app messages and mock SMS, each with a verify code.

    notify(db, tenant_id=..., person_id=..., template="approved", payload={"amount_pkr": 12000})

In-app rows are delivered at once. SMS rows are queued and sent by a `notification.sms` job, which runs
as `worker` in the tenant, so a person who has withdrawn consent is not contacted. A gateway outage is
retried with backoff and dead-lettered after the last attempt; the in-app copy is always there.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.crypto import blind_index, decrypt_field
from app.core.db import system_session
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier
from app.db import models
from app.modules.jobs.service import JobContext, PermanentJobError, RetryLater, enqueue
from app.modules.notifications import templates
from app.modules.plans import service as plans

log = get_logger("rahat.notifications")

SMS_JOB = "notification.sms"
CHANNELS = ("in_app", "sms")
_PAYLOAD_KEYS = ("tracking_code", "amount_pkr", "rail_ref", "proof_kind", "application_id", "payment_id", "case_id")


@lru_cache
def _verify_key() -> bytes:
    # A secret derived from the master key through the keyed blind index (HMAC-SHA256); no custom crypto.
    return bytes.fromhex(blind_index("notification-verify-code-key", scope="notification-verify"))


def make_verify_code(notification_id: uuid.UUID, body_hash: str) -> str:
    return templates.verify_code(notification_id, body_hash, _verify_key())


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in payload.items() if k in _PAYLOAD_KEYS}


def _phone(db: Session, tenant_id: uuid.UUID, person: models.Person) -> str | None:
    if not person.phone_enc:
        return None
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return None
    try:
        return decrypt_field(tenant.wrapped_dek, person.phone_enc)
    except Exception:  # noqa: BLE001
        log.exception("could not decrypt a phone number for a notification")
        return None


def notify(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID | None,
    template: str,
    payload: dict[str, Any] | None = None,
    lang: str | None = None,
    channels: Iterable[str] = CHANNELS,
) -> list[models.Notification]:
    """Write outbox rows for one message in the caller's transaction; SMS goes out through a job.

    Sign-up messages (`templates.ONE_TIME_TEMPLATES`) are the exception: see `_send_one_time`.
    """
    if template in templates.ONE_TIME_TEMPLATES:
        sent = _send_one_time(db, tenant_id=tenant_id, person_id=person_id, template=template, payload=dict(payload or {}), lang=lang)
        return [sent] if sent is not None else []
    payload = _clean_payload(dict(payload or {}))
    wanted = [c for c in dict.fromkeys(channels) if c in CHANNELS]
    person = db.get(models.Person, person_id) if person_id else None  # RLS: None when this caller may not read them
    chosen = templates.choose_lang(lang, person.lang if person else None)
    text = templates.render(template, chosen, payload)
    text_hash = templates.body_hash(text)
    phone = _phone(db, tenant_id, person) if person is not None and "sms" in wanted else None
    now = datetime.now(UTC)
    created: list[models.Notification] = []
    for channel in wanted:
        if channel == "sms" and phone is None:
            log.info("no SMS for template %s: no readable phone number", template)
            continue
        if channel == "sms" and not plans.try_consume(db, tenant_id, "sms"):
            log.warning("sms plan limit reached; template %s stays in the app only", template)  # the in-app copy is always there
            continue
        notification_id = uuid.uuid4()
        code = make_verify_code(notification_id, text_hash)
        row_payload = dict(payload)
        if channel == "sms" and phone:
            row_payload["_to"] = mask_identifier(phone)
        row = models.Notification(
            id=notification_id, tenant_id=tenant_id, person_id=person_id, user_id=person.user_id if person else None,
            channel=channel, template=template, lang=chosen, payload=row_payload, body=templates.with_code(text, code, chosen),
            body_hash=text_hash, verify_code=code, attempts=0,
            destination_hash=blind_index(phone, scope=str(tenant_id)) if channel == "sms" and phone else None,
            status="sent" if channel == "in_app" else "queued", sent_at=now if channel == "in_app" else None, created_at=now,
        )  # fmt: skip
        db.add(row)
        created.append(row)
    db.flush()
    for row in created:
        if row.channel == "sms":
            enqueue(db, tenant_id=tenant_id, kind=SMS_JOB, payload={"notification_id": str(row.id)}, person_id=person_id,
                    priority=20, max_attempts=4)  # fmt: skip
    if created:
        audit.write(
            db, tenant_id=tenant_id, action="notification.queued", actor_type="system", object_type="notification",
            object_id=created[0].id, acting_for_person_id=person_id,
            details={"template": template, "lang": chosen, "channels": [r.channel for r in created], "ids": [str(r.id) for r in created]},
        )  # fmt: skip
    return created


def _send_one_time(
    db: Session, *, tenant_id: uuid.UUID, person_id: uuid.UUID | None, template: str, payload: dict[str, Any], lang: str | None
) -> models.Notification | None:
    """A sign-up message, sent now to the number the person typed.

    The person asked for it, and a worker could not send it later: workers need a consent that a person who is
    still signing up cannot have yet. No verify code is appended, so the message carries one code only, and the
    stored copy hides the code.
    """
    person = db.get(models.Person, person_id) if person_id else None
    phone = _phone(db, tenant_id, person) if person is not None else None
    if phone is None:
        log.info("no sign-up message %s: no readable phone number", template)
        return None
    chosen = templates.choose_lang(lang, person.lang if person else None)
    text = templates.render(template, chosen, payload)
    code = templates.render(template, chosen, {**payload, "code": ""})
    stored = text if code == text else templates.render(template, chosen, {**payload, "code": "000000"}).replace("000000", "••••••")
    from app.modules.integrations.service import send_sms

    result = send_sms(phone, text)
    now = datetime.now(UTC)
    row = models.Notification(
        id=uuid.uuid4(), tenant_id=tenant_id, person_id=person_id, user_id=person.user_id if person else None, channel="sms",
        template=template, lang=chosen, payload={"_to": mask_identifier(phone)}, body=stored, body_hash=templates.body_hash(text),
        verify_code=None, attempts=1, destination_hash=blind_index(phone, scope=str(tenant_id)),
        status="sent" if result.status == "sent" else "failed", last_error=None if result.status == "sent" else result.status,
        sent_at=now if result.status == "sent" else None, created_at=now,
    )  # fmt: skip
    db.add(row)
    db.flush()
    audit.write(db, tenant_id=tenant_id, action="notification.sent_one_time", actor_type="system", object_type="notification",
                object_id=row.id, result="ok" if result.status == "sent" else "failed", details={"template": template})  # fmt: skip
    return row


# --- SMS delivery job -----------------------------------------------------------------------------------


def deliver_sms(db: Session, job: JobContext) -> None:
    from app.modules.integrations.service import send_sms

    try:
        notification_id = uuid.UUID(str(job.payload.get("notification_id")))
    except ValueError as exc:
        raise PermanentJobError("bad notification id") from exc
    row = db.scalar(select(models.Notification).where(models.Notification.id == notification_id).with_for_update())
    if row is None:
        raise PermanentJobError("notification not found")
    if row.status in ("sent", "read"):
        return  # already delivered: running twice must not text the person twice
    person = db.get(models.Person, row.person_id) if row.person_id else None
    if person is None:
        raise PermanentJobError("person_not_readable: consent withdrawn or record removed")
    phone = _phone(db, row.tenant_id, person)
    if phone is None:
        raise PermanentJobError("no phone number")
    tenant = db.get(models.Tenant, row.tenant_id)
    sender = str((tenant.config or {}).get("official_sender", "RAHAT")) if tenant else "RAHAT"
    result = send_sms(phone, row.body, sender=sender)
    if result.status == "unavailable":
        raise RetryLater("sms gateway unavailable")
    if result.status != "sent":
        raise PermanentJobError(f"sms rejected: {result.detail}")
    row.status = "sent"
    row.sent_at = datetime.now(UTC)
    row.attempts = job.attempts
    row.last_error = None
    row.payload = {**(row.payload or {}), "_gateway_id": result.message_id}
    audit.write(db, tenant_id=row.tenant_id, action="notification.sent", actor_type="system", actor_role="worker",
                object_type="notification", object_id=row.id, details={"channel": "sms", "attempts": job.attempts})  # fmt: skip


def on_sms_failure(db: Session, job: JobContext, error: str, dead: bool) -> None:
    try:
        notification_id = uuid.UUID(str(job.payload.get("notification_id")))
    except ValueError:
        return
    row = db.get(models.Notification, notification_id)
    if row is None:
        return
    row.attempts = job.attempts
    row.last_error = error[:300]
    if dead:
        row.status = "failed"
        audit.write(db, tenant_id=row.tenant_id, action="notification.failed", actor_type="system", actor_role="worker",
                    object_type="notification", object_id=row.id, result="failed", reason=error[:200],
                    details={"channel": row.channel, "attempts": job.attempts})  # fmt: skip


# --- verify codes ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VerifyResult:
    genuine: bool
    template: str | None = None
    channel: str | None = None
    department: str | None = None
    sent_at: str | None = None


def lookup_verify_code(code: str) -> VerifyResult:
    """Is this code on a message we really sent? Reveals the kind of message and the sender, never the person."""
    wanted = templates.normalise_code(code)
    if len(wanted) != templates.CODE_LENGTH:
        return VerifyResult(genuine=False)
    with system_session() as db:  # narrow: one indexed lookup by code; no person data is read or returned
        row = db.execute(
            select(models.Notification.id, models.Notification.body_hash, models.Notification.body, models.Notification.lang,
                   models.Notification.template, models.Notification.channel, models.Notification.created_at, models.Notification.tenant_id)
            .where(models.Notification.verify_code == wanted)
            .limit(1)
        ).first()  # fmt: skip
        if row is None or not row.body_hash:
            return VerifyResult(genuine=False)
        text = templates.text_without_code(row.body, wanted, row.lang)
        genuine = make_verify_code(row.id, row.body_hash) == wanted and text is not None and templates.body_hash(text) == row.body_hash
        if not genuine:
            return VerifyResult(genuine=False)
        tenant = db.get(models.Tenant, row.tenant_id)
        return VerifyResult(genuine=True, template=row.template, channel=row.channel, department=tenant.name if tenant else None,
                            sent_at=row.created_at.isoformat(timespec="minutes"))  # fmt: skip
