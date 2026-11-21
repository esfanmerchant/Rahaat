"""Grant, narrow and withdraw consent. Every change writes a `consent_events` row and an audit row.

Withdrawal is one transaction: the consent becomes `withdrawn`, the person's open applications go to
`on_hold_consent`, their queued jobs are cancelled and their memory items are deleted. From the next query
on, `app_can_read_person()` is false for officers, API clients and workers, so the database itself stops
the department reading the person's data.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.contracts.api import ConsentCreate, ConsentNarrow, ConsentOut
from app.core import audit
from app.core.errors import Conflict, NotFound, Unprocessable
from app.core.logging import get_logger
from app.db import models
from app.modules.applications import hooks
from app.modules.applications.status import HOLD_ON_WITHDRAWAL, move, resume_status
from app.modules.consent.rules import ALL_SCOPES, APPLICATION_PURPOSE, active_consent
from app.modules.people.context import PersonContext, deny

log = get_logger("rahat.consent")
_PURPOSE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
ALLOWED_PURPOSES = frozenset({APPLICATION_PURPOSE, "scam_report"})
_PERSON_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('consent:' || :person_id, 0))")


def _lock_person(db: Session, ctx: PersonContext) -> None:
    """Serialise consent changes for one person: no two active consents from a double tap, no half-applied withdrawal.

    Taken before any row lock or audit row, so the lock order is always consent lock, rows, audit lock.
    """
    db.execute(_PERSON_LOCK, {"person_id": str(ctx.person_id)})


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _ordered(scopes: list[str]) -> list[str]:
    wanted = set(scopes)
    return [s for s in ALL_SCOPES if s in wanted]


def effective_status(consent: models.Consent, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if consent.status == "active" and consent.expires_at is not None and consent.expires_at <= now:
        return "expired"
    return consent.status


def _grantee_name(db: Session, consent: models.Consent) -> str:
    if consent.grantee_type == "tenant":
        tenant = db.get(models.Tenant, consent.grantee_id)
        return tenant.name if tenant else "Department"
    if consent.grantee_type == "helper":
        user = db.get(models.User, consent.grantee_id)
        return user.display_name if user else "Helper"
    return consent.grantee_type.replace("_", " ").title()


def consent_out(db: Session, consent: models.Consent) -> ConsentOut:
    return ConsentOut(
        id=consent.id,
        person_id=consent.person_id,
        grantee_type=consent.grantee_type,
        grantee_id=consent.grantee_id,
        grantee_name=_grantee_name(db, consent),
        purpose=consent.purpose,
        field_scopes=list(consent.field_scopes or []),
        status=effective_status(consent),
        version=consent.version,
        granted_at=_iso(consent.granted_at) or "",
        expires_at=_iso(consent.expires_at),
        withdrawn_at=_iso(consent.withdrawn_at),
    )


def _event(db: Session, ctx: PersonContext, consent: models.Consent, event: str, details: dict[str, Any]) -> None:
    db.add(
        models.ConsentEvent(
            tenant_id=ctx.tenant_id, consent_id=consent.id, person_id=consent.person_id, event=event,
            actor_user_id=ctx.user_id, details=details,
        )
    )  # fmt: skip


def list_consents(db: Session, ctx: PersonContext) -> list[ConsentOut]:
    rows = db.scalars(
        select(models.Consent)
        .where(models.Consent.tenant_id == ctx.tenant_id, models.Consent.person_id == ctx.person_id)
        .order_by(models.Consent.granted_at.desc(), models.Consent.id)
    ).all()
    return [consent_out(db, c) for c in rows]


def _owned(db: Session, ctx: PersonContext, consent_id: UUID, *, lock: bool = False) -> models.Consent:
    query = select(models.Consent).where(
        models.Consent.id == consent_id, models.Consent.tenant_id == ctx.tenant_id, models.Consent.person_id == ctx.person_id
    )
    consent = db.scalars(query.with_for_update() if lock else query).first()
    if consent is None:
        raise NotFound("That consent does not exist.")
    return consent


def grant(db: Session, ctx: PersonContext, body: ConsentCreate) -> tuple[ConsentOut, bool]:
    """Returns (consent, created). Granting the same scopes again returns the existing consent."""
    if body.person_id is not None and body.person_id != ctx.person_id:
        # The person comes from the token or X-Acting-For, never from the body.
        raise deny(ctx.principal, "person_mismatch", scope=ctx.scope, person_id=body.person_id)
    if not _PURPOSE.match(body.purpose) or body.purpose not in ALLOWED_PURPOSES:
        raise Unprocessable("Use the purpose relief_application or scam_report.", code="invalid_purpose")
    _lock_person(db, ctx)
    scopes = _ordered(list(body.field_scopes))
    existing = active_consent(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, purpose=body.purpose)
    if existing is not None:
        if set(existing.field_scopes or []) == set(scopes):
            return consent_out(db, existing), False
        raise Conflict(
            "You already share information for this purpose. Narrow it, or take it back and share again.",
            code="consent_exists",
            extra={"consent_id": str(existing.id)},
        )

    now = datetime.now(UTC)
    consent = models.Consent(
        tenant_id=ctx.tenant_id, person_id=ctx.person_id, grantee_type="tenant", grantee_id=ctx.tenant_id,
        purpose=body.purpose, field_scopes=scopes, status="active", version=1, granted_at=now,
        expires_at=now + timedelta(days=body.expires_in_days),
    )  # fmt: skip
    db.add(consent)
    db.flush()
    # Only the consent that withdrawal took away brings paused applications back. Row locks come before audit rows.
    resumed = _resume_held_applications(db, ctx) if body.purpose == APPLICATION_PURPOSE else 0
    _event(db, ctx, consent, "granted", {"field_scopes": scopes, "expires_in_days": body.expires_in_days})
    audit.write(
        db, tenant_id=ctx.tenant_id, action="consent.granted", object_type="consent", object_id=consent.id,
        details={"purpose": body.purpose, "field_scopes": scopes, "person_id": str(ctx.person_id), "resumed": resumed},
        **ctx.audit_fields(),
    )  # fmt: skip
    db.commit()
    if resumed:
        log.info("consent granted; %d application(s) resumed", resumed)
    return consent_out(db, consent), True


def narrow(db: Session, ctx: PersonContext, consent_id: UUID, body: ConsentNarrow) -> ConsentOut:
    _lock_person(db, ctx)
    consent = _owned(db, ctx, consent_id, lock=True)
    if effective_status(consent) != "active":
        raise Conflict("This consent is no longer active.", code="consent_not_active")
    current = list(consent.field_scopes or [])
    wanted = _ordered(list(body.field_scopes))
    widened = sorted(set(wanted) - set(current))
    if widened:
        raise Unprocessable(
            "You can only share less here. To share more, give a new consent.",
            code="consent_widen_not_allowed",
            extra={"errors": [{"field": "field_scopes", "message": f"not in the current consent: {', '.join(widened)}", "code": "widen"}]},
        )
    if set(wanted) == set(current):
        return consent_out(db, consent)
    removed = [s for s in current if s not in wanted]
    consent.field_scopes = wanted
    consent.version += 1
    _event(db, ctx, consent, "narrowed", {"removed": removed, "field_scopes": wanted, "version": consent.version})
    audit.write(
        db, tenant_id=ctx.tenant_id, action="consent.narrowed", object_type="consent", object_id=consent.id,
        details={"removed": removed, "field_scopes": wanted, "version": consent.version}, **ctx.audit_fields(),
    )  # fmt: skip
    db.commit()
    return consent_out(db, consent)


def withdraw(db: Session, ctx: PersonContext, consent_id: UUID) -> ConsentOut:
    _lock_person(db, ctx)
    consent = _owned(db, ctx, consent_id, lock=True)
    if consent.status == "withdrawn":
        return consent_out(db, consent)
    now = datetime.now(UTC)
    consent.status = "withdrawn"
    consent.withdrawn_at = now
    consent.version += 1

    effects: dict[str, Any] = {"held": {}, "jobs_cancelled": 0, "memory_items_deleted": 0}
    if consent.grantee_type == "tenant" and active_consent(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id) is None:
        effects = withdrawal_side_effects(db, ctx, now)

    _event(db, ctx, consent, "withdrawn", effects)
    audit.write(
        db, tenant_id=ctx.tenant_id, action="consent.withdrawn", object_type="consent", object_id=consent.id,
        details={
            "purpose": consent.purpose, "person_id": str(ctx.person_id), "applications_held": len(effects["held"]),
            "jobs_cancelled": effects["jobs_cancelled"], "memory_items_deleted": effects["memory_items_deleted"],
        },
        **ctx.audit_fields(),
    )  # fmt: skip
    _emit_webhook(db, ctx, consent)
    db.commit()
    return consent_out(db, consent)


def withdrawal_side_effects(db: Session, ctx: PersonContext, now: datetime) -> dict[str, Any]:
    """Pause open applications, cancel queued jobs, purge memory. Runs inside the withdrawal transaction."""
    held: dict[str, str] = {}
    applications = db.scalars(
        select(models.Application)
        .where(
            models.Application.tenant_id == ctx.tenant_id,
            models.Application.person_id == ctx.person_id,
            models.Application.status.in_(sorted(HOLD_ON_WITHDRAWAL)),
        )
        .order_by(models.Application.created_at, models.Application.id)
        .with_for_update()
    ).all()
    for application in applications:
        held[str(application.id)] = move(application, "on_hold_consent")
        application.version += 1

    jobs = db.execute(
        update(models.Job)
        .where(models.Job.tenant_id == ctx.tenant_id, models.Job.person_id == ctx.person_id, models.Job.status == "queued")
        .values(status="cancelled", finished_at=now, last_error="consent_withdrawn")
        .execution_options(synchronize_session=False)
    )
    memory = db.execute(
        delete(models.MemoryItem)
        .where(models.MemoryItem.tenant_id == ctx.tenant_id, models.MemoryItem.person_id == ctx.person_id)
        .execution_options(synchronize_session=False)
    )
    for application_id, previous in held.items():
        audit.write(
            db, tenant_id=ctx.tenant_id, action="application.on_hold_consent", object_type="application",
            object_id=application_id, details={"from_status": previous}, **ctx.audit_fields(),
        )  # fmt: skip
    return {"held": held, "jobs_cancelled": int(jobs.rowcount or 0), "memory_items_deleted": int(memory.rowcount or 0)}  # type: ignore[attr-defined]


def _resume_held_applications(db: Session, ctx: PersonContext) -> int:
    """After a new grant, put applications that were paused by a withdrawal back where they were."""
    held = db.scalars(
        select(models.Application)
        .where(
            models.Application.tenant_id == ctx.tenant_id,
            models.Application.person_id == ctx.person_id,
            models.Application.status == "on_hold_consent",
        )
        .with_for_update()
    ).all()
    if not held:
        return 0
    history: dict[str, str] = {}
    events = db.scalars(
        select(models.ConsentEvent)
        .where(
            models.ConsentEvent.tenant_id == ctx.tenant_id,
            models.ConsentEvent.person_id == ctx.person_id,
            models.ConsentEvent.event == "withdrawn",
        )
        .order_by(models.ConsentEvent.created_at, models.ConsentEvent.id)
    ).all()
    for event in events:  # oldest first, so the latest withdrawal wins
        history.update((event.details or {}).get("held") or {})
    targets: dict[UUID, str] = {}
    for application in held:
        targets[application.id] = resume_status(history.get(str(application.id)), submitted=application.submitted_at is not None)
        move(application, targets[application.id])
        application.version += 1
    for application_id, target in targets.items():
        audit.write(
            db, tenant_id=ctx.tenant_id, action="application.resumed", object_type="application",
            object_id=application_id, details={"to_status": target}, **ctx.audit_fields(),
        )  # fmt: skip
    return len(held)


def _emit_webhook(db: Session, ctx: PersonContext, consent: models.Consent) -> None:
    """`consent.withdrawn` for partners, when the webhooks module is present. Never blocks the withdrawal."""
    emit = hooks.optional(("app.modules.webhooks.service", "emit"))
    if emit is None:
        return
    try:
        with db.begin_nested():
            emit(db, tenant_id=ctx.tenant_id, event="consent.withdrawn",
                 payload={"consent_id": str(consent.id), "person_ref": audit.hash_payload(str(ctx.person_id))[:16]})  # fmt: skip
    except Exception:  # noqa: BLE001
        log.exception("could not queue the consent.withdrawn webhook")
