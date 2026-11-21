"""The submit pipeline (docs/CONTRACTS.md, "The decision pipeline").

1. Gather evidence: the form, the stored DocumentChecks, an IdentityCheck and a RegistryRecord.
2. Build a DecisionInput and hand it to Track B's `decide_and_record`.
3. Apply the result: approve requests the payment, ask_more sets needs_proof, human opens a case.
   Every outcome sends a notification.

Every other track's function is imported when it is needed. When one is missing or fails, the pipeline
degrades to the safe side and never invents a result: no engine or an unchecked upload means a person
reviews the application; an unreachable registry is passed on as `registry_status="unavailable"`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.contracts.api import SubmitOut
from app.contracts.application import ApplicationFormV1
from app.contracts.decision import HandoffPackage, UncertainField
from app.contracts.documents import DocumentCheck
from app.contracts.engine import DecisionInput, IdentityCheck, RegistryRecord, RegistryStatus
from app.core import audit, metrics
from app.core.crypto import blind_index
from app.core.logging import get_logger
from app.db import models
from app.modules.applications import hooks
from app.modules.applications.forms import missing_fields, signed_fields
from app.modules.applications.service import (
    active_rule_version,
    application_out,
    decision_view,
    form_of,
    latest_checks,
    latest_decision,
    load_owned,
)
from app.modules.applications.status import OUTCOME_STATUS, SUBMITTABLE, move
from app.modules.consent.rules import require_consent
from app.modules.people.context import PersonContext
from app.modules.people.service import get_person, registered_national_id

log = get_logger("rahat.pipeline")

_QUESTION = "Is this household eligible for the Rahat payment?"


@dataclass
class Evidence:
    documents: list[DocumentCheck] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    unchecked_documents: list[str] = field(default_factory=list)
    identity: IdentityCheck | None = None
    registry_status: RegistryStatus = "unavailable"
    registry: RegistryRecord | None = None
    identity_mismatch: bool = False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def id_differs(candidate: str | None, registered_hash: str | None, tenant_id: UUID) -> bool:
    """True when a value is present, the person has a registered ID, and the two are not the same."""
    if not candidate or not registered_hash:
        return False
    return blind_index(candidate, scope=str(tenant_id)) != registered_hash


def _identity(national_id: str | None, form: ApplicationFormV1) -> IdentityCheck | None:
    if not (national_id and form.full_name.value and form.dob.value):
        return None  # not attempted: something it needs is unknown
    verify = hooks.optional(hooks.VERIFY_IDENTITY)
    if verify is None:
        return None
    try:
        result = verify(national_id, form.full_name.value, form.dob.value)
        return result if isinstance(result, IdentityCheck) else IdentityCheck.model_validate(result)
    except Exception:  # noqa: BLE001
        log.warning("identity service failed; passing it on as unavailable")
        return IdentityCheck(status="unavailable", checked_at=_now_iso())


def _registry(national_id: str | None) -> tuple[RegistryStatus, RegistryRecord | None]:
    if not national_id:
        return "unavailable", None
    lookup = hooks.optional(hooks.LOOKUP_REGISTRY)
    if lookup is None:
        return "unavailable", None
    try:
        status, record = lookup(national_id)
        if status not in ("found", "not_found", "unavailable"):
            return "unavailable", None
        if record is not None and not isinstance(record, RegistryRecord):
            record = RegistryRecord.model_validate(record)
        return status, record if status == "found" else None
    except Exception:  # noqa: BLE001
        log.warning("registry lookup failed; passing it on as unavailable")
        return "unavailable", None


def gather_evidence(db: Session, ctx: PersonContext, application: models.Application, form: ApplicationFormV1) -> Evidence:
    person = get_person(db, ctx)
    evidence = Evidence()
    for document, check, mismatch in latest_checks(db, application.id):
        evidence.document_ids.append(str(document.id))
        if check is None:
            evidence.unchecked_documents.append(str(document.id))
            continue
        evidence.documents.append(check)
        if mismatch:
            evidence.identity_mismatch = True
        elif check.qr.found and check.qr.signature_valid is True:
            signed_id = signed_fields(check.qr.payload).get("national_id")
            evidence.identity_mismatch |= id_differs(signed_id, person.national_id_hash, ctx.tenant_id)

    # A typed ID that is not the person's own registered ID is treated exactly like a mismatched card.
    evidence.identity_mismatch |= id_differs(form.national_id.value, person.national_id_hash, ctx.tenant_id)
    national_id = form.national_id.value or registered_national_id(db, person)
    if evidence.identity_mismatch:
        evidence.identity = IdentityCheck(status="mismatch", checked_at=_now_iso())
    else:
        evidence.identity = _identity(national_id, form)
    evidence.registry_status, evidence.registry = _registry(national_id)
    return evidence


def build_input(application: models.Application, program: models.Program, form: ApplicationFormV1, evidence: Evidence) -> DecisionInput:
    return DecisionInput(
        application_id=str(application.id),
        program_slug=program.slug,
        lang=form.language,
        form=form,
        documents=evidence.documents,
        identity=evidence.identity,
        registry_status=evidence.registry_status,
        registry=evidence.registry,
        consent_ok=True,  # checked before the pipeline starts; without it there is no submission
        queue_days=1.0,
        decided_at=_now_iso(),
    )


def _safe_call(db: Session, what: str, fn: Any, /, **kwargs: Any) -> Any:
    """Run another track's function in a savepoint. A failure rolls back only its own writes."""
    try:
        with db.begin_nested():
            return fn(**kwargs)
    except Exception:  # noqa: BLE001
        log.exception("%s failed; continuing on the safe path", what)
        return None


def _fallback_handoff(form: ApplicationFormV1, dsl: dict[str, Any] | None, evidence: Evidence, reason: str) -> HandoffPackage:
    """What the officer needs when no automatic decision was made. It states facts; it does not decide."""
    why = {
        "engine_unavailable": "The decision engine was not available, so nothing was decided automatically.",
        "engine_failed": "The decision engine could not finish, so nothing was decided automatically.",
        "document_unchecked": "An uploaded document could not be checked automatically, so a person must look at it.",
    }.get(reason, "The application needs a person to review it.")
    return HandoffPackage(
        question=_QUESTION,
        understanding=why,
        uncertain_fields=[UncertainField(field=name, value=None, confidence=0.0, why="missing") for name in missing_fields(form, dsl)],
        rule_fired=None,
        resolving_proof=None,
        evidence={"document_ids": evidence.document_ids, "unchecked_document_ids": evidence.unchecked_documents,
                  "registry_status": evidence.registry_status, "identity": evidence.identity.status if evidence.identity else None},  # fmt: skip
        guards=["identity_mismatch"] if evidence.identity_mismatch else [],
    )


def _open_case(db: Session, ctx: PersonContext, application: models.Application, *, reason: str,
               decision: models.Decision | None, handoff: HandoffPackage | None) -> None:  # fmt: skip
    open_case = hooks.optional(hooks.OPEN_CASE)
    if open_case is None:
        log.warning("cases module not available; the application waits in_review without a case")
        return
    guarded = bool(decision is not None and decision.guards)
    _safe_call(
        db, "open_case", open_case, db=db, tenant_id=ctx.tenant_id, kind="application_review", opened_reason=reason,
        application_id=application.id, person_id=ctx.person_id, decision_id=decision.id if decision else None,
        handoff=handoff, confidence=decision.p_ok if decision else None, priority=20 if guarded else 50,
    )  # fmt: skip


def _request_payment(db: Session, ctx: PersonContext, application: models.Application, decision: models.Decision,
                     rule_version: models.RuleVersion | None) -> None:  # fmt: skip
    amount = (rule_version.dsl or {}).get("payment_pkr") if rule_version else None
    request_payment = hooks.optional(hooks.REQUEST_PAYMENT)
    if request_payment is None or not isinstance(amount, int) or amount <= 0:
        audit.write(
            db, tenant_id=ctx.tenant_id, action="payment.not_requested", actor_type="system", object_type="application",
            object_id=application.id, result="failed",
            reason="payments_unavailable" if request_payment is None else "no_amount_in_rule_version",
            details={"decision_id": str(decision.id)},
        )  # fmt: skip
        return
    _safe_call(
        db, "request_payment", request_payment, db=db, tenant_id=ctx.tenant_id, application_id=application.id,
        person_id=ctx.person_id, decision_id=decision.id, amount_pkr=amount, requested_by=None,
    )  # fmt: skip


def _notify(db: Session, ctx: PersonContext, application: models.Application, form: ApplicationFormV1, template: str,
            extra: dict[str, Any]) -> None:  # fmt: skip
    notify = hooks.optional(hooks.NOTIFY)
    if notify is None:
        return
    payload = {"tracking_code": application.tracking_code, "application_id": str(application.id), **extra}
    _safe_call(db, "notify", notify, db=db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, template=template,
               payload=payload, lang=form.language)  # fmt: skip


def _decide(db: Session, ctx: PersonContext, application: models.Application, inp: DecisionInput) -> tuple[models.Decision | None, str]:
    decide_and_record = hooks.optional(hooks.DECIDE_AND_RECORD)
    if decide_and_record is None:
        return None, "engine_unavailable"
    decision = _safe_call(
        db, "decide_and_record", decide_and_record, db=db, tenant_id=ctx.tenant_id, application_id=application.id,
        person_id=ctx.person_id, inp=inp, actor_user_id=ctx.user_id,
    )  # fmt: skip
    if not isinstance(decision, models.Decision):
        return None, "engine_failed"
    return decision, ""


def run(db: Session, ctx: PersonContext, application: models.Application) -> SubmitOut:
    """Submit a locked application that is in a submittable state, decide, apply, commit."""
    form = form_of(application)
    program = db.get(models.Program, application.program_id)
    rule_version = active_rule_version(db, application.program_id)
    if program is None:
        raise RuntimeError("application without a program")

    previous = move(application, "submitted")
    application.submitted_at = datetime.now(UTC)
    application.version += 1
    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.submitted", object_type="application", object_id=application.id,
        details={"from_status": previous, "version": application.version}, **ctx.audit_fields(),
    )  # fmt: skip

    evidence = gather_evidence(db, ctx, application, form)
    inp = build_input(application, program, form, evidence)

    decision: models.Decision | None = None
    reason = "document_unchecked" if evidence.unchecked_documents else ""
    if not reason:
        decision, reason = _decide(db, ctx, application, inp)

    if decision is None:
        target = "in_review"
        metrics.DECISIONS.labels("human").inc()
        move(application, target)
        dsl = rule_version.dsl if rule_version else None
        _open_case(db, ctx, application, reason=reason, decision=None, handoff=_fallback_handoff(form, dsl, evidence, reason))
    else:
        target = OUTCOME_STATUS.get(decision.outcome, "in_review")
        move(application, target)
        if decision.outcome == "approved":
            _request_payment(db, ctx, application, decision, rule_version)
        elif target == "in_review":
            handoff = _handoff_of(decision)
            _open_case(db, ctx, application, reason=(decision.reasons or ["needs_human"])[0], decision=decision, handoff=handoff)

    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.status_changed", actor_type="system", object_type="application",
        object_id=application.id, reason=reason or None,
        details={"from_status": "submitted", "to_status": target, "decision_id": str(decision.id) if decision else None},
        acting_for_person_id=ctx.person_id if ctx.via_helper else None,
    )  # fmt: skip
    _notify(db, ctx, application, form, f"application_{target}",
            {"outcome": decision.outcome if decision else "needs_human", "ask_proof": _ask_proof(decision)})  # fmt: skip
    db.commit()
    return SubmitOut(application=application_out(db, application, decision=decision), decision=decision_view(db, decision))


def _handoff_of(decision: models.Decision) -> HandoffPackage | None:
    if not decision.handoff:
        return None
    try:
        return HandoffPackage.model_validate(decision.handoff)
    except ValidationError:
        log.warning("stored handoff package does not match the contract")
        return None


def _ask_proof(decision: models.Decision | None) -> str | None:
    if decision is None or decision.outcome != "needs_proof":
        return None
    handoff = decision.handoff or {}
    value = handoff.get("resolving_proof") if isinstance(handoff, dict) else None
    return str(value) if value else None


def submit(db: Session, ctx: PersonContext, application_id: UUID) -> SubmitOut:
    """Submit once. A repeat submit (double tap, retry after a timeout) returns the first result unchanged."""
    application = load_owned(db, ctx, application_id, lock=True)
    require_consent(db, ctx, action="application.submit")
    if application.status not in SUBMITTABLE:
        decision = latest_decision(db, application.id)
        return SubmitOut(application=application_out(db, application, decision=decision), decision=decision_view(db, decision))
    return run(db, ctx, application)
