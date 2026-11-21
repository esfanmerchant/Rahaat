"""Export my data: one JSON file with everything this department holds about the person.

The person's own identifiers are shown in full when they export for themselves, and masked when their
helper exports for them; anyone else's identifiers (a helper's phone) are always masked and staff are named
by role only. Detection details (why a document or message was flagged) are staff-only and are not in the
file; the person gets the same citizen view of each document that the app shows.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.crypto import decrypt_field
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier
from app.db import models
from app.modules.applications.service import _timeline, decision_view, latest_checks, latest_decision
from app.modules.consent import access_log
from app.modules.consent.requests import list_requests, masked_value
from app.modules.consent.service import consent_out
from app.modules.documents.views import citizen_view
from app.modules.helpers.service import delegation_status, helper_cards, ordered_scopes
from app.modules.people.context import PersonContext
from app.modules.people.service import get_person

log = get_logger("rahat.consent.export")

NOTICE: Final = "PROTOTYPE. Not an official service. All identity, payment and data services are simulated."
ACCESS_LOG_ROWS: Final = 100


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _reveal(tenant: models.Tenant, token: str | None, *, full: bool) -> str | None:
    if not token:
        return None
    try:
        value = decrypt_field(tenant.wrapped_dek, token)
    except Exception:  # noqa: BLE001
        log.warning("could not decrypt an identifier for the export")
        return None
    return value if full else mask_identifier(value)


def _form(form: dict[str, Any], *, full: bool) -> dict[str, Any]:
    if full:
        return form
    out = dict(form)
    for name, entry in form.items():
        if isinstance(entry, dict) and "value" in entry:
            out[name] = {**entry, "value": masked_value(name, entry.get("value"))}
    return out


def build(db: Session, ctx: PersonContext) -> dict[str, Any]:
    full = not ctx.via_helper
    person = get_person(db, ctx)
    tenant = db.get(models.Tenant, ctx.tenant_id)
    assert tenant is not None
    now = datetime.now(UTC)
    identifiers = db.scalars(select(models.PersonIdentifier).where(models.PersonIdentifier.tenant_id == ctx.tenant_id,
                                                                   models.PersonIdentifier.person_id == ctx.person_id)).all()  # fmt: skip
    consents = db.scalars(select(models.Consent).where(models.Consent.tenant_id == ctx.tenant_id, models.Consent.person_id == ctx.person_id)
                          .order_by(models.Consent.granted_at, models.Consent.id)).all()  # fmt: skip
    events = db.scalars(select(models.ConsentEvent).where(models.ConsentEvent.tenant_id == ctx.tenant_id,
                                                          models.ConsentEvent.person_id == ctx.person_id)
                        .order_by(models.ConsentEvent.created_at, models.ConsentEvent.id)).all()  # fmt: skip
    delegations = db.scalars(select(models.HelperDelegation).where(models.HelperDelegation.tenant_id == ctx.tenant_id,
                                                                   models.HelperDelegation.person_id == ctx.person_id)
                             .order_by(models.HelperDelegation.created_at, models.HelperDelegation.id)).all()  # fmt: skip
    cards = helper_cards({d.helper_user_id for d in delegations})
    applications = db.scalars(select(models.Application).where(models.Application.tenant_id == ctx.tenant_id,
                                                               models.Application.person_id == ctx.person_id)
                              .order_by(models.Application.created_at, models.Application.id)).all()  # fmt: skip
    programs = dict(db.execute(select(models.Program.id, models.Program.name).where(models.Program.tenant_id == ctx.tenant_id)).all())
    payments = db.scalars(select(models.Payment).where(models.Payment.tenant_id == ctx.tenant_id, models.Payment.person_id == ctx.person_id)
                          .order_by(models.Payment.created_at, models.Payment.id)).all()  # fmt: skip
    messages = db.scalars(select(models.Notification).where(models.Notification.tenant_id == ctx.tenant_id,
                                                            models.Notification.person_id == ctx.person_id)
                          .order_by(models.Notification.created_at, models.Notification.id)).all()  # fmt: skip
    reviews = db.scalars(select(models.Case).where(models.Case.tenant_id == ctx.tenant_id, models.Case.subject_person_id == ctx.person_id)
                         .order_by(models.Case.created_at, models.Case.id)).all()  # fmt: skip

    app_items = []
    for application in applications:
        decision = latest_decision(db, application.id)
        view = decision_view(db, decision)
        app_items.append({
            "id": str(application.id), "program": programs.get(application.program_id), "status": application.status,
            "tracking_code": application.tracking_code, "version": application.version, "created_at": _iso(application.created_at),
            "submitted_at": _iso(application.submitted_at), "answers": _form(dict(application.form or {}), full=full),
            "timeline": [t.model_dump(mode="json") for t in _timeline(db, application)],
            "decision": view.model_dump(mode="json") if view else None,
            "documents": [
                {**citizen_view(str(doc.id), doc.kind, check, identity_mismatch=doc.status in ("mismatch", "unbound")).model_dump(mode="json"),  # type: ignore[arg-type]
                 "uploaded_at": _iso(doc.created_at), "mime": doc.mime, "size_bytes": doc.size_bytes}
                for doc, check, _ in latest_checks(db, application.id)
            ],
        })  # fmt: skip
    log_page = access_log.access_log(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, own_user_id=person.user_id,
                                     limit=ACCESS_LOG_ROWS)  # fmt: skip
    return {
        "notice": NOTICE,
        "generated_at": _iso(now),
        "department": tenant.name,
        "requested_by": "you" if full else "your helper",
        "person": {
            "id": str(person.id), "full_name": person.full_name, "full_name_ur": person.full_name_ur,
            "dob": person.dob.isoformat() if person.dob else None, "gender": person.gender, "district": person.district,
            "language": person.lang, "national_id": _reveal(tenant, person.national_id_enc, full=full),
            "phone": _reveal(tenant, person.phone_enc, full=full), "registered_at": _iso(person.created_at),
        },
        "identifiers": [{"kind": i.kind, "value": _reveal(tenant, i.value_enc, full=full), "verified": i.verified, "source": i.source}
                        for i in identifiers],  # fmt: skip
        "consents": [consent_out(db, c).model_dump(mode="json") for c in consents],
        "consent_history": [{"consent_id": str(e.consent_id), "event": e.event, "at": _iso(e.created_at)} for e in events],
        "helpers": [{"name": cards.get(d.helper_user_id, ("Community helper", None))[0],
                     "phone": cards.get(d.helper_user_id, ("", None))[1], "scopes": ordered_scopes(list(d.scopes or [])),
                     "status": delegation_status(d, now), "granted_at": _iso(d.created_at), "expires_at": _iso(d.expires_at),
                     "revoked_at": _iso(d.revoked_at)} for d in delegations],  # fmt: skip
        "applications": app_items,
        "payments": [{"id": str(p.id), "application_id": str(p.application_id), "amount_pkr": p.amount_pkr, "status": p.status,
                      "reference": p.rail_ref, "created_at": _iso(p.created_at)} for p in payments],  # fmt: skip
        "messages": [{"channel": m.channel, "template": m.template, "lang": m.lang, "body": m.body, "verify_code": m.verify_code,
                      "status": m.status, "created_at": _iso(m.created_at)} for m in messages],  # fmt: skip
        "reviews": [{"kind": c.kind, "status": c.status, "opened_at": _iso(c.created_at), "resolved_at": _iso(c.resolved_at),
                     "resolution": c.resolution} for c in reviews],  # fmt: skip
        "data_requests": [r.model_dump(mode="json") for r in list_requests(db, ctx)],
        "access_log": [e.model_dump(mode="json") for e in log_page.items],
        "kept_after_erasure": "Payments, decisions and the audit trail are kept as financial and audit records.",
    }


def export(db: Session, ctx: PersonContext) -> dict[str, Any]:
    """Build the file and record that it was made (and by whom)."""
    data = build(db, ctx)
    audit.write(db, tenant_id=ctx.tenant_id, action="person.data_exported", object_type="person", object_id=ctx.person_id,
                details={"sections": sorted(data), "identifiers_masked": ctx.via_helper}, **ctx.audit_fields())  # fmt: skip
    db.commit()
    return data
