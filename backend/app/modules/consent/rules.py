"""Consent checks used by every person-facing write.

The database already refuses officer, API-client and worker reads without an active consent
(`app_can_read_person`). These checks add the application-level rules on top: no application can be
created, changed, uploaded to or submitted without an active consent for this department, and a field
can be written only when the consent covers its scope.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, metrics
from app.core.errors import Conflict, Forbidden
from app.db import models
from app.modules.people.context import PersonContext

APPLICATION_PURPOSE: Final = "relief_application"
ALL_SCOPES: Final = ("identity", "contact", "household", "income", "documents")


def active_consent(db: Session, *, tenant_id: UUID, person_id: UUID, purpose: str = APPLICATION_PURPOSE) -> models.Consent | None:
    """The department's live consent from this person for `purpose`, if any."""
    now = datetime.now(UTC)
    return db.scalars(
        select(models.Consent)
        .where(
            models.Consent.tenant_id == tenant_id,
            models.Consent.person_id == person_id,
            models.Consent.grantee_type == "tenant",
            models.Consent.grantee_id == tenant_id,
            models.Consent.purpose == purpose,
            models.Consent.status == "active",
            or_(models.Consent.expires_at.is_(None), models.Consent.expires_at > now),
        )
        .order_by(models.Consent.granted_at.desc(), models.Consent.id)
        .limit(1)
    ).first()


def people_with_active_consent(db: Session, *, tenant_id: UUID, person_ids: Iterable[UUID],
                               purpose: str = APPLICATION_PURPOSE) -> set[UUID]:  # fmt: skip
    """Of `person_ids`, those with a live department consent for `purpose`: `active_consent` for a list, in one query."""
    wanted = list(dict.fromkeys(person_ids))
    if not wanted:
        return set()
    now = datetime.now(UTC)
    return set(
        db.scalars(
            select(models.Consent.person_id).where(
                models.Consent.tenant_id == tenant_id,
                models.Consent.person_id.in_(wanted),
                models.Consent.grantee_type == "tenant",
                models.Consent.grantee_id == tenant_id,
                models.Consent.purpose == purpose,
                models.Consent.status == "active",
                or_(models.Consent.expires_at.is_(None), models.Consent.expires_at > now),
            )
        ).all()
    )


def _refuse(ctx: PersonContext, code: str, action: str, details: dict[str, object]) -> None:
    metrics.ACCESS_DENIED.labels("consent").inc()
    audit.write_independent(
        tenant_id=ctx.tenant_id,
        action="access.denied",
        object_type="person",
        object_id=ctx.person_id,
        result="denied",
        reason=code,
        details={"attempted": action, **details},
        **ctx.audit_fields(),
    )


def require_consent(db: Session, ctx: PersonContext, *, action: str, scopes: Iterable[str] = ()) -> models.Consent:
    """409 `consent_required` without an active consent; 409 `consent_scope_missing` when a needed scope is not covered."""
    consent = active_consent(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id)
    if consent is None:
        _refuse(ctx, "consent_required", action, {})
        raise Conflict(
            "Please agree to share your information with the department first.",
            code="consent_required",
        )
    missing = sorted(set(scopes) - set(consent.field_scopes or []))
    if missing:
        _refuse(ctx, "consent_scope_missing", action, {"missing_scopes": missing})
        raise Conflict(
            "You have not agreed to share this kind of information.",
            code="consent_scope_missing",
            extra={"missing_scopes": missing, "consent_id": str(consent.id)},
        )
    return consent


def require_consent_for_helper_read(db: Session, ctx: PersonContext, *, action: str) -> None:
    """A helper reads a person's case data only while the person's consent is active.

    The person themself can always see their own record; that is what lets them take the consent back.
    """
    if not ctx.via_helper:
        return
    if active_consent(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id) is None:
        _refuse(ctx, "consent_required", action, {})
        raise Forbidden("This person has not agreed to share their information.", code="consent_required")
