"""Data requests from the consent centre: correct a value, or erase my data. An officer decides each one.

Correction: the person names a field, the value it should have and why. The request is stored (the new
value encrypted with the department's key) and a `correction` case opens with a handoff package that shows
the officer the current value, where it came from and the requested value. When the officer approves the
case (`POST /v1/cases/{id}/actions`), the value is written with provenance `typed` (never `verified`), the
application's version goes up, and the audit row names the officer who changed it.

Identity and payout fields (`national_id`, `phone`, `payout_account`) can be corrected only by the person
themself, never by a helper, and never on an application that is already approved or paid: a payment is
released to the payout account on the form, so a late change could send the money somewhere else.

Erasure: the person asks for their data to be deleted. Nothing is deleted when they ask: a case opens and
an officer approves or rejects it. On approval the person's record, documents, answers, identifiers,
consents and the copies held in sync records and case packages are erased in one narrow system-context
transaction, so it works even after consent was taken back. Payments, decisions and the audit trail are
kept: they are financial and audit records, decisions are immutable in the database, and auditors only
ever see them masked.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.contracts.application import FORM_FIELDS, ApplicationFormV1, apply_patch
from app.contracts.common import Strict
from app.contracts.decision import HandoffPackage, UncertainField
from app.core import audit
from app.core.crypto import decrypt_field, encrypt_field
from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, Unprocessable
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier, normalise_mock_phone
from app.db import models
from app.modules.applications.forms import check_client_patch, raise_if_errors, scopes_needed
from app.modules.cases import rules as case_rules
from app.modules.consent.rules import require_consent
from app.modules.people.context import PersonContext

log = get_logger("rahat.consent.requests")

ERASURE_FIELD: Final = "_erasure"
PERSON_FIELDS: Final = ("full_name", "dob", "gender", "district")  # also kept on the person record
MASKED_FIELDS: Final = frozenset({"national_id", "phone", "payout_account"})
CITIZEN_ONLY_FIELDS: Final = MASKED_FIELDS  # who you are and where the money goes: the person only, never a helper
OPEN_APPLICATION: Final = ("draft", "submitted", "needs_proof", "in_review", "on_hold_consent")
KEPT_APPLICATION: Final = ("approved", "paid")  # financial records; their answers are kept
DECIDED_APPLICATION: Final = KEPT_APPLICATION  # their answers no longer change
ERASE_LOCK_TIMEOUT: Final = "5s"


class CorrectionIn(Strict):
    field: str = Field(min_length=2, max_length=64, description="A form field, e.g. full_name, dob, household_size")
    new_value: str | int | bool | None = Field(description="The right value, in the field's own format")
    reason: str = Field(min_length=5, max_length=500, description="Why the current value is wrong")
    application_id: UUID | None = Field(default=None, description="Defaults to my newest application")


class ErasureIn(Strict):
    reason: str | None = Field(default=None, max_length=500)


class DataRequestOut(BaseModel):
    id: UUID
    kind: Literal["correction", "erasure"]
    field: str | None = None
    new_value: Any | None = None
    reason: str | None = None
    status: str = Field(description="open | accepted | rejected")
    requested_at: str
    resolved_at: str | None = None
    case_status: str | None = None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _tenant(db: Session, tenant_id: UUID) -> models.Tenant:
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        raise NotFound("Department not found.")
    return tenant


def _seal(tenant: models.Tenant, value: Any) -> str:
    return encrypt_field(tenant.wrapped_dek, json.dumps({"v": value}))


def _unseal(tenant: models.Tenant, token: str) -> Any:
    if not token:
        return None
    try:
        return json.loads(decrypt_field(tenant.wrapped_dek, token)).get("v")
    except Exception:  # noqa: BLE001
        log.warning("could not read a stored correction value")
        return None


def _value_hash(value: Any) -> str:
    return audit.hash_payload({"v": value})


def _open_case(db: Session, ctx: PersonContext, *, reason: str, application_id: UUID | None, subject: UUID | None,
               handoff: HandoffPackage, priority: int) -> models.Case:  # fmt: skip
    """A new `correction` case. Not `cases.open_case`: that one keeps one active case per application and kind,
    and two requests about one application are two decisions."""
    now = datetime.now(UTC)
    case = models.Case(
        id=uuid.uuid4(), tenant_id=ctx.tenant_id, kind="correction", status="open", priority=priority, subject_person_id=subject,
        application_id=application_id, opened_reason=reason, handoff=handoff.model_dump(mode="json"),
        sla_due_at=case_rules.sla_due("correction", priority, now), created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(case)
    db.flush()
    db.add(models.CaseEvent(id=uuid.uuid4(), tenant_id=ctx.tenant_id, case_id=case.id, event="created", from_status=None, to_status="open",
                            details={"reason": reason}, created_at=now))  # fmt: skip
    audit.write(db, tenant_id=ctx.tenant_id, action="case.opened", actor_type="system", object_type="case", object_id=case.id,
                acting_for_person_id=ctx.person_id, details={"kind": "correction", "reason": reason, "priority": priority})  # fmt: skip
    return case


def _out(db: Session, tenant: models.Tenant, request: models.CorrectionRequest, *, reveal: bool = True) -> DataRequestOut:
    case_status = db.scalar(select(models.Case.status).where(models.Case.id == request.case_id)) if request.case_id else None
    erasure = request.field == ERASURE_FIELD
    value = None if erasure else _unseal(tenant, request.new_value_enc)
    return DataRequestOut(
        id=request.id, kind="erasure" if erasure else "correction", field=None if erasure else request.field,
        new_value=value if reveal else masked_value(request.field, value), reason=request.reason, status=request.status,
        requested_at=_iso(request.created_at) or "", resolved_at=_iso(request.resolved_at), case_status=case_status,
    )  # fmt: skip


def list_requests(db: Session, ctx: PersonContext) -> list[DataRequestOut]:
    """The person's requests. A helper sees identifiers masked, as in the export."""
    tenant = _tenant(db, ctx.tenant_id)
    rows = db.scalars(
        select(models.CorrectionRequest)
        .where(models.CorrectionRequest.tenant_id == ctx.tenant_id, models.CorrectionRequest.person_id == ctx.person_id)
        .order_by(models.CorrectionRequest.created_at.desc(), models.CorrectionRequest.id)
    ).all()
    return [_out(db, tenant, r, reveal=not ctx.via_helper) for r in rows]


# --- correction ------------------------------------------------------------------------------------------


def _target_application(db: Session, ctx: PersonContext, application_id: UUID | None) -> models.Application | None:
    query = select(models.Application).where(models.Application.tenant_id == ctx.tenant_id, models.Application.person_id == ctx.person_id)
    if application_id is not None:
        application = db.scalars(query.where(models.Application.id == application_id)).first()
        if application is None:
            raise NotFound("We could not find that application.")
        return application
    return db.scalars(query.order_by(models.Application.created_at.desc(), models.Application.id.desc()).limit(1)).first()


def _person_value(person: models.Person, field: str) -> Any:
    value = getattr(person, field, None)
    return value.isoformat() if isinstance(value, date) else value


def check_value(field: str, value: Any, current: ApplicationFormV1) -> Any:
    """The same format checks a typed answer gets (mock formats, dates, ranges), minus the lock on verified
    fields: asking for a correction is exactly how a verified value is changed. Returns the normalised value."""
    if field not in FORM_FIELDS:
        raise Unprocessable("That is not a field we hold.", code="unknown_field", extra={"errors": [{"field": "field", "message": "unknown",
                                                                                                     "code": "unknown_field"}]})  # fmt: skip
    if field in ("phone", "payout_account") and isinstance(value, str):
        value = normalise_mock_phone(value) or value
    entry = {"value": value, "provenance": "typed"}
    raise_if_errors([e for e in check_client_patch({field: entry}, current) if e.code != "field_locked"])
    try:
        parsed = apply_patch(current, {field: {**entry, "confidence": 1.0, "verified": False}})
    except (ValidationError, ValueError):
        errors = [{"field": "new_value", "message": "wrong type for this field", "code": "invalid_value"}]
        raise Unprocessable("That value does not fit this field.", code="invalid_value", extra={"errors": errors}) from None
    return getattr(parsed, field).value


def request_correction(db: Session, ctx: PersonContext, body: CorrectionIn) -> DataRequestOut:
    """201 with the open request. 409 `correction_open` while one for the same field waits, `application_decided`
    for an answer on an approved or paid application; 403 `citizen_only_field`; 422 `no_change`."""
    if ctx.via_helper and body.field in CITIZEN_ONLY_FIELDS:
        raise Forbidden("Only the person can ask to change their ID, phone or payout account.", code="citizen_only_field")
    require_consent(db, ctx, action="correction.request", scopes=scopes_needed([body.field]))
    tenant = _tenant(db, ctx.tenant_id)
    person = db.get(models.Person, ctx.person_id)
    if person is None:
        raise NotFound("We could not find your record.")
    application = _target_application(db, ctx, body.application_id)
    if application is not None and application.status in DECIDED_APPLICATION:
        if body.field not in PERSON_FIELDS:
            raise Conflict("This application is already decided, so its answers cannot change. Ask a person at the office.",
                           code="application_decided", extra={"application_status": application.status})  # fmt: skip
        application = None  # the person record is corrected; the decided application keeps its answers
    if application is None and body.field not in PERSON_FIELDS:
        raise Conflict("Start an application first, or correct your name, date of birth, gender or district.", code="no_application")
    form = ApplicationFormV1.model_validate(application.form or {}) if application is not None else ApplicationFormV1()
    value = check_value(body.field, body.new_value, form)
    current_entry = getattr(form, body.field) if application is not None else None
    old = current_entry.value if current_entry is not None else _person_value(person, body.field)
    if old == value:
        raise Unprocessable("That is already the value we hold.", code="no_change")
    waiting = db.scalar(
        select(models.CorrectionRequest.id).where(
            models.CorrectionRequest.tenant_id == ctx.tenant_id, models.CorrectionRequest.person_id == ctx.person_id,
            models.CorrectionRequest.field == body.field, models.CorrectionRequest.status == "open",
        ).limit(1)
    )  # fmt: skip
    if waiting is not None:
        raise Conflict("You already asked to correct this. A person will look at it soon.", code="correction_open",
                       extra={"request_id": str(waiting)})  # fmt: skip

    request = models.CorrectionRequest(id=uuid.uuid4(), tenant_id=ctx.tenant_id, person_id=ctx.person_id, field=body.field,
                                       old_value_hash=_value_hash(old), new_value_enc=_seal(tenant, value), reason=body.reason,
                                       status="open")  # fmt: skip
    db.add(request)
    db.flush()
    source = current_entry.provenance if current_entry is not None else "person_record"
    verified = bool(current_entry.verified) if current_entry is not None else False
    who = "The person's community helper asks, on the person's behalf," if ctx.via_helper else "The person asks"
    shown_new, shown_old = masked_value(body.field, value), masked_value(body.field, old)  # identifiers stay out of case packages
    handoff = HandoffPackage(
        question="Should this correction be accepted?",
        understanding=(f"{who} to change '{body.field}'. The value we hold came from {source}"
                       f"{' and was verified' if verified else ''}. Check the reason and any proof before accepting."),  # fmt: skip
        uncertain_fields=[UncertainField(field=body.field, value=shown_new, confidence=0.0, why="correction_requested")],
        evidence={"correction_id": str(request.id), "field": body.field, "current_value": shown_old, "current_provenance": source,
                  "current_verified": verified, "requested_value": shown_new, "reason": body.reason,
                  "requested_by_role": ctx.principal.role, "applies_to": "application" if application is not None else "person_record",
                  "also_person_record": body.field in PERSON_FIELDS},  # fmt: skip
        suggested_question="If the right value is not clear, ask the person for proof.",
    )
    case = _open_case(db, ctx, reason="correction_request", application_id=application.id if application else None,
                      subject=ctx.person_id, handoff=handoff, priority=50)  # fmt: skip
    request.case_id = case.id
    audit.write(db, tenant_id=ctx.tenant_id, action="correction.requested", object_type="correction_request", object_id=request.id,
                details={"field": body.field, "case_id": str(case.id), "application_id": str(application.id) if application else None},
                **ctx.audit_fields())  # fmt: skip
    db.commit()
    return _out(db, tenant, request)


def _apply_correction(db: Session, principal: Principal, case: models.Case, request: models.CorrectionRequest) -> None:
    tenant = _tenant(db, principal.tenant_id)
    value = _unseal(tenant, request.new_value_enc)
    changed_by = {"changed_by": str(principal.user_id), "changed_by_role": principal.role, "correction_id": str(request.id)}
    application = db.get(models.Application, case.application_id) if case.application_id is not None else None
    if case.application_id is not None and application is None:  # RLS: the officer still needs the person's consent
        raise Conflict("The application is no longer available.", code="application_unavailable")
    if application is not None and application.status in DECIDED_APPLICATION:
        # Decided since the request: its answers (and so its payout) no longer change.
        if request.field not in PERSON_FIELDS:
            raise Conflict("The application was decided after this request. Reject the request and tell the person why.",
                           code="application_decided", extra={"application_status": application.status})  # fmt: skip
        application = None
    if application is not None:
        form = ApplicationFormV1.model_validate(application.form or {})
        updated = apply_patch(form, {request.field: {"value": value, "confidence": 1.0, "provenance": "typed", "verified": False}})
        application.form = updated.model_dump(mode="json")
        application.version += 1
        audit.write(db, tenant_id=principal.tenant_id, action="application.corrected", actor_id=principal.user_id, actor_role=principal.role,
                    acting_for_person_id=request.person_id, object_type="application", object_id=application.id,
                    details={"fields": [request.field], "version": application.version, "provenance": "typed", **changed_by})  # fmt: skip
    if request.field in PERSON_FIELDS:
        person = db.get(models.Person, request.person_id)
        if person is not None:
            setattr(person, request.field, date.fromisoformat(value) if request.field == "dob" and value else value)
            audit.write(db, tenant_id=principal.tenant_id, action="person.corrected", actor_id=principal.user_id, actor_role=principal.role,
                        acting_for_person_id=request.person_id, object_type="person", object_id=request.person_id,
                        details={"fields": [request.field], **changed_by})  # fmt: skip


# --- erasure ----------------------------------------------------------------------------------------------


def request_erasure(db: Session, ctx: PersonContext, body: ErasureIn) -> DataRequestOut:
    """The person asks for their data to be deleted. A case opens; nothing is deleted until an officer approves."""
    tenant = _tenant(db, ctx.tenant_id)
    waiting = db.scalar(
        select(models.CorrectionRequest.id).where(
            models.CorrectionRequest.tenant_id == ctx.tenant_id, models.CorrectionRequest.person_id == ctx.person_id,
            models.CorrectionRequest.field == ERASURE_FIELD, models.CorrectionRequest.status == "open",
        ).limit(1)
    )  # fmt: skip
    if waiting is not None:
        raise Conflict("You already asked us to delete your data. A person will look at it soon.", code="erasure_request_open",
                       extra={"request_id": str(waiting)})  # fmt: skip
    statuses = dict(db.execute(
        select(models.Application.status, func.count()).where(models.Application.tenant_id == ctx.tenant_id,
                                                              models.Application.person_id == ctx.person_id)
        .group_by(models.Application.status)
    ).all())  # fmt: skip
    payments = db.scalar(select(func.count()).select_from(models.Payment).where(models.Payment.tenant_id == ctx.tenant_id,
                                                                               models.Payment.person_id == ctx.person_id)) or 0  # fmt: skip
    request = models.CorrectionRequest(id=uuid.uuid4(), tenant_id=ctx.tenant_id, person_id=ctx.person_id, field=ERASURE_FIELD,
                                       new_value_enc=_seal(tenant, None), reason=body.reason, status="open")  # fmt: skip
    db.add(request)
    db.flush()
    handoff = HandoffPackage(
        question="Should this person's data be erased?",
        understanding=("The person asked for their data to be deleted. Approving erases their record, documents, answers, identifiers "
                       "and consents. Payments, decisions and the audit trail are kept. Reject only for a reason you can state, "
                       "such as an open payment or an investigation."),  # fmt: skip
        evidence={"erasure_request_id": str(request.id), "person_ref": audit.hash_payload(str(ctx.person_id))[:16],
                  "applications_by_status": {str(k): int(v) for k, v in statuses.items()}, "payments": int(payments),
                  "reason": body.reason},  # fmt: skip
    )
    # No subject person on the case: deciding it needs no access to the data itself, so it works after consent is withdrawn.
    case = _open_case(db, ctx, reason="erasure_request", application_id=None, subject=None, handoff=handoff, priority=40)
    request.case_id = case.id
    audit.write(db, tenant_id=ctx.tenant_id, action="person.erasure_requested", object_type="correction_request", object_id=request.id,
                details={"case_id": str(case.id)}, **ctx.audit_fields())  # fmt: skip
    db.commit()
    return _out(db, tenant, request)


def erase_person(*, tenant_id: UUID, person_id: UUID, request_id: UUID, actor_id: UUID, actor_role: str) -> dict[str, int]:
    """Erase one person's data after an officer approved it, in its own system-context transaction.

    Narrow: every statement names this person. It runs before the officer's transaction writes any audit
    row, takes the person's rows first and the tenant's audit lock last (like every other writer), and gives
    up after a few seconds instead of waiting forever. It records `person.erased` itself, so the erasure is on
    record even if the officer's request fails afterwards. Stored photos are removed only after the commit.
    Idempotent: an erased person is left alone.
    """
    from app.modules.documents.service import _path_for  # the storage layout belongs to the documents module

    now = datetime.now(UTC)
    effects: dict[str, int] = {}
    paths = []
    try:
        with system_session() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))  # ERASE_LOCK_TIMEOUT
            person = db.scalars(select(models.Person).where(models.Person.id == person_id, models.Person.tenant_id == tenant_id)
                                .with_for_update()).first()  # fmt: skip
            if person is None or person.status == "deleted":
                return effects
            documents = db.scalars(select(models.Document).where(models.Document.tenant_id == tenant_id,
                                                                 models.Document.person_id == person_id)).all()  # fmt: skip
            paths = [document.storage_key for document in documents]
            effects["documents"] = len(documents)
            db.execute(delete(models.Document).where(models.Document.tenant_id == tenant_id, models.Document.person_id == person_id))
            empty = ApplicationFormV1().model_dump(mode="json")
            applications = db.scalars(select(models.Application)
                                      .where(models.Application.tenant_id == tenant_id, models.Application.person_id == person_id)
                                      .with_for_update()).all()  # fmt: skip
            for application in applications:
                if application.status in KEPT_APPLICATION:
                    continue
                if application.status in OPEN_APPLICATION:
                    application.status = "withdrawn"
                application.form = empty
                application.version += 1
            effects["applications_cleared"] = sum(1 for a in applications if a.status not in KEPT_APPLICATION)
            withdrawn = db.scalars(select(models.Consent).where(models.Consent.tenant_id == tenant_id, models.Consent.person_id == person_id,
                                                                models.Consent.status == "active").with_for_update()).all()  # fmt: skip
            for consent in withdrawn:
                consent.status, consent.withdrawn_at, consent.version = "withdrawn", now, consent.version + 1
                db.add(models.ConsentEvent(tenant_id=tenant_id, consent_id=consent.id, person_id=person_id, event="withdrawn",
                                           actor_user_id=actor_id, details={"reason": "erasure", "request_id": str(request_id)}))  # fmt: skip
            effects["consents_withdrawn"] = len(withdrawn)
            effects["delegations_revoked"] = int(db.execute(
                update(models.HelperDelegation).where(models.HelperDelegation.tenant_id == tenant_id,
                                                      models.HelperDelegation.person_id == person_id,
                                                      models.HelperDelegation.revoked_at.is_(None)).values(revoked_at=now)
            ).rowcount or 0)  # type: ignore[attr-defined]  # fmt: skip
            effects["jobs_cancelled"] = int(db.execute(
                update(models.Job).where(models.Job.tenant_id == tenant_id, models.Job.person_id == person_id, models.Job.status == "queued")
                .values(status="cancelled", finished_at=now, last_error="cancelled: person erased")
            ).rowcount or 0)  # type: ignore[attr-defined]  # fmt: skip
            for model in (models.MemoryItem, models.PersonIdentifier, models.NameVariant, models.HouseholdLink):
                db.execute(delete(model).where(model.tenant_id == tenant_id, model.person_id == person_id))
            db.execute(delete(models.DuplicateCandidate).where(
                models.DuplicateCandidate.tenant_id == tenant_id,
                or_(models.DuplicateCandidate.person_a_id == person_id, models.DuplicateCandidate.person_b_id == person_id)))  # fmt: skip
            # Copies of what the person or their helper sent: queued offline changes and the packages on their cases.
            effects["sync_ops_cleared"] = int(db.execute(
                update(models.SyncOp).where(models.SyncOp.tenant_id == tenant_id, models.SyncOp.person_id == person_id)
                .values(payload={}, result={"reason": "person_erased"})
            ).rowcount or 0)  # type: ignore[attr-defined]  # fmt: skip
            cases = db.scalars(select(models.Case).where(models.Case.tenant_id == tenant_id, models.Case.subject_person_id == person_id)
                               .with_for_update()).all()  # fmt: skip
            for case in cases:
                case.handoff = {}
                if case.status not in ("resolved", "closed"):
                    case.status, case.resolution, case.resolved_at = "resolved", "person_erased", now
            effects["cases_closed"] = len(cases)
            person.full_name, person.full_name_ur, person.name_key = "", None, None
            person.dob = person.gender = person.district = None
            person.phone_enc = person.phone_hash = person.national_id_enc = person.national_id_hash = None
            person.status = "deleted"
            person.data = {"erased_at": now.isoformat(), "erasure_request_id": str(request_id)}
            db.flush()
            audit.write(db, tenant_id=tenant_id, action="person.erased", actor_id=actor_id, actor_role=actor_role, object_type="person",
                        object_id=person_id, acting_for_person_id=person_id, details={"request_id": str(request_id), **effects})  # fmt: skip
    except OperationalError:
        log.warning("erasure could not get its locks in time; nothing was changed")
        raise ServiceUnavailable("This person's record is busy. Try again in a moment.", code="erasure_busy") from None
    for storage_key in paths:  # after the commit: a failure here leaves a file without a row, never a row without its file
        try:
            _path_for(storage_key).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            log.warning("could not remove a stored document file after erasure")
    return effects


# --- the officer's decision (called from the case actions) ---------------------------------------------------


def on_case_decided(db: Session, principal: Principal, case: models.Case, *, approve: bool, reason: str) -> None:
    """An officer approved or rejected a `correction` case: apply or close the request behind it.

    Called from the case action before the officer's transaction writes its audit rows, so the erasure's own
    transaction can take the tenant's audit lock without waiting for this one.
    """
    request = db.scalars(
        select(models.CorrectionRequest)
        .where(models.CorrectionRequest.tenant_id == principal.tenant_id, models.CorrectionRequest.case_id == case.id)
        .with_for_update()
    ).first()
    if request is None:
        return
    if request.status != "open":
        raise Conflict("This request was already decided.", code="request_already_decided")
    erasure = request.field == ERASURE_FIELD
    effects: dict[str, int] = {}
    if approve:
        if erasure:
            effects = erase_person(tenant_id=principal.tenant_id, person_id=request.person_id, request_id=request.id,
                                   actor_id=principal.user_id, actor_role=principal.role)  # fmt: skip
            # The person's other requests: their values go, and the open ones close with the erasure.
            others = (models.CorrectionRequest.tenant_id == principal.tenant_id, models.CorrectionRequest.person_id == request.person_id)
            db.execute(update(models.CorrectionRequest).where(*others).values(new_value_enc="").execution_options(synchronize_session=False))
            db.execute(update(models.CorrectionRequest).where(*others, models.CorrectionRequest.status == "open",
                                                              models.CorrectionRequest.id != request.id)
                       .values(status="rejected", resolved_at=datetime.now(UTC)).execution_options(synchronize_session=False))  # fmt: skip
        else:
            _apply_correction(db, principal, case, request)
    request.status = "accepted" if approve else "rejected"
    request.resolved_at = datetime.now(UTC)
    action = ("person.erasure" if erasure else "correction") + (".accepted" if approve else ".rejected")
    audit.write(db, tenant_id=principal.tenant_id, action=action, actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=request.person_id, object_type="correction_request", object_id=request.id, reason=reason,
                details={"field": None if erasure else request.field, "case_id": str(case.id), **effects})  # fmt: skip


def masked_value(field: str, value: Any) -> Any:
    return mask_identifier(value) if field in MASKED_FIELDS and isinstance(value, str) and value else value
