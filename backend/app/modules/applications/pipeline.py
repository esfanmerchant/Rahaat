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

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.api import SubmitOut
from app.contracts.application import ApplicationFormV1
from app.contracts.decision import HandoffPackage, UncertainField
from app.contracts.documents import DocumentCheck
from app.contracts.engine import DecisionInput, DuplicateEvidence, IdentityCheck, RegistryRecord, RegistryStatus
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
from app.modules.webhooks.emit import emit as emit_webhook

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


def _duplicates(db: Session, ctx: PersonContext, application: models.Application) -> DuplicateEvidence | None:
    """Track B's dedupe (B8), run when the engine decides: a possible duplicate is a guard that sends the case
    to a person (and opens a duplicate_review case). A failure leaves no evidence; it never invents one."""
    try:
        from app.modules.matching.service import check_duplicates
    except ImportError:
        return None
    try:
        with db.begin_nested():
            return check_duplicates(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, application_id=application.id)
    except Exception:  # noqa: BLE001
        log.exception("duplicate check failed; deciding without dedupe evidence")
        return None


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
        "identity_unbound": "This person has no registered ID yet, so the ID on the form or card must be checked by a person.",
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
    amount = _amount(rule_version)
    request_payment = hooks.optional(hooks.REQUEST_PAYMENT)
    if request_payment is None or amount is None:
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


# Templates that Track A2's `notify` knows, and the only payload keys it keeps.
TEMPLATE_FOR_STATUS: dict[str, str] = {
    "approved": "approved",
    "in_review": "person_will_check",
    "needs_proof": "proof_needed",
    "rejected": "rejected",
}
UNDECIDED_TEMPLATE = "application_received"  # the pipeline could not decide at once
PROOF_KINDS = ("rahat_id", "income_proof", "other")


def notification_for(target: str, *, decided: bool, tracking_code: str | None, amount_pkr: int | None,
                     proof_kind: str | None) -> tuple[str, dict[str, Any]]:  # fmt: skip
    """Pure: the template and payload for the outcome of a submission."""
    payload: dict[str, Any] = {"tracking_code": tracking_code}
    if not decided:
        return UNDECIDED_TEMPLATE, payload
    template = TEMPLATE_FOR_STATUS.get(target, "person_will_check")
    if template == "approved" and amount_pkr:
        payload["amount_pkr"] = amount_pkr
    if template == "proof_needed":
        payload["proof_kind"] = proof_kind if proof_kind in PROOF_KINDS else "other"
    return template, payload


def _notify(db: Session, ctx: PersonContext, form: ApplicationFormV1, template: str, payload: dict[str, Any]) -> None:
    notify = hooks.optional(hooks.NOTIFY)
    if notify is None:
        return
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


def _amount(rule_version: models.RuleVersion | None) -> int | None:
    amount = (rule_version.dsl or {}).get("payment_pkr") if rule_version else None
    return amount if isinstance(amount, int) and not isinstance(amount, bool) and amount > 0 else None


def run(db: Session, ctx: PersonContext, application: models.Application) -> SubmitOut:
    """Submit a locked application that is in a submittable state, decide, apply, commit.

    Audit rows are written after the other tracks' functions have run, so this transaction does not hold
    the tenant's audit lock while they work (a `write_independent` from inside them would wait for it).
    """
    form = form_of(application)
    program = db.get(models.Program, application.program_id)
    rule_version = active_rule_version(db, application.program_id)
    if program is None:
        raise RuntimeError("application without a program")
    person = get_person(db, ctx)

    previous = move(application, "submitted")
    application.submitted_at = datetime.now(UTC)
    application.version += 1

    evidence = gather_evidence(db, ctx, application, form)
    inp = build_input(application, program, form, evidence)

    decision: models.Decision | None = None
    if evidence.unchecked_documents:
        reason = "document_unchecked"
    elif not person.national_id_hash:
        # Nothing ties this person to an ID yet (self-registered), so a card or a typed ID cannot be trusted
        # to be theirs. A person checks the identity; the engine is not asked.
        reason = "identity_unbound"
    else:
        inp = inp.model_copy(update={"duplicate": _duplicates(db, ctx, application)})
        decision, reason = _decide(db, ctx, application, inp)

    if decision is None:
        target = "in_review"
        metrics.DECISIONS.labels("human").inc()
        move(application, target)
        dsl = rule_version.dsl if rule_version else None
        _open_case(db, ctx, application, reason=reason, decision=None, handoff=_fallback_handoff(form, dsl, evidence, reason))
    else:
        target = OUTCOME_STATUS.get(decision.outcome, "in_review")
        if target == "approved" and (decision.route != "auto" or decision.guards or evidence.identity_mismatch):
            # Backstop: money moves only on an automatic approval with no guard raised.
            target, reason = "in_review", "approval_blocked_by_guard"
        move(application, target)
        if target == "approved":
            _request_payment(db, ctx, application, decision, rule_version)
        elif target == "in_review":
            _open_case(db, ctx, application, reason=reason or (decision.reasons or ["needs_human"])[0], decision=decision,
                       handoff=_handoff_of(decision))  # fmt: skip

    if decision is not None:
        emit_webhook(db, ctx.tenant_id, "decision.made", {"decision_id": decision.id, "application_id": application.id,
                                                          "outcome": decision.outcome, "route": decision.route})  # fmt: skip

    template, payload = notification_for(target, decided=decision is not None, tracking_code=application.tracking_code,
                                         amount_pkr=_amount(rule_version), proof_kind=_ask_proof(decision))  # fmt: skip
    _notify(db, ctx, form, template, payload)

    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.submitted", object_type="application", object_id=application.id,
        details={"from_status": previous, "version": application.version}, **ctx.audit_fields(),
    )  # fmt: skip
    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.status_changed", actor_type="system", object_type="application",
        object_id=application.id, reason=reason or None,
        details={"from_status": "submitted", "to_status": target, "decision_id": str(decision.id) if decision else None,
                 "version": application.version},  # fmt: skip
        acting_for_person_id=ctx.person_id if ctx.via_helper else None,
    )  # fmt: skip
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
    value = getattr(decision, "ask_proof", None)
    if not value:
        handoff = decision.handoff or {}
        value = handoff.get("resolving_proof") if isinstance(handoff, dict) else None
    return str(value) if value else None


def submit(db: Session, ctx: PersonContext, application_id: UUID) -> SubmitOut:
    """Submit once. A repeat submit (double tap, retry after a timeout) returns the first result unchanged."""
    application = load_owned(db, ctx, application_id, lock=True)
    require_consent(db, ctx, action="application.submit")
    repeat = application.status == "needs_proof" and not _changed_since_decision(db, application)
    if application.status not in SUBMITTABLE or repeat:
        decision = latest_decision(db, application.id)
        return SubmitOut(application=application_out(db, application, decision=decision), decision=decision_view(db, decision))
    return run(db, ctx, application)


def _changed_since_decision(db: Session, application: models.Application) -> bool:
    """True when new proof or answers arrived after the last decision (a double tap brings nothing new)."""
    row = db.scalars(
        select(models.AuditLog.details)
        .where(models.AuditLog.tenant_id == application.tenant_id, models.AuditLog.object_id == str(application.id),
               models.AuditLog.action == "application.status_changed")  # fmt: skip
        .order_by(models.AuditLog.seq.desc())
        .limit(1)
    ).first()
    try:
        decided_at_version = json.loads(row).get("version") if row else None
    except (TypeError, ValueError, AttributeError):
        decided_at_version = None
    return decided_at_version is None or application.version > int(decided_at_version)
