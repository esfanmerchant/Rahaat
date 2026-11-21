"""Mock payments: created only for an approved decision, at most once per application, four-eyes above a limit.

    request_payment(db, tenant_id=..., application_id=..., person_id=..., decision_id=..., amount_pkr=12000)

Concurrency: the application row is locked (`SELECT ... FOR UPDATE`) before the existing payment is looked
up, so two simultaneous requests are serialised and the second one returns the first one's payment. The
unique idempotency key is the backstop. The rail call carries the same key, so a retry never pays twice.

At or below the tenant's `payment_four_eyes_limit_pkr` the payment is released at once. Above it an
`approvals` row waits for a second officer who is neither the one who approved the case nor the requester.
A rail outage leaves the payment `failed` with a `payment.release` job that retries it with backoff.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.logging import get_logger
from app.db import models
from app.modules.jobs.service import JobContext, PermanentJobError, RetryLater, enqueue
from app.modules.payments import rules
from app.modules.webhooks.emit import emit as emit_webhook

log = get_logger("rahat.payments")

RELEASE_JOB = "payment.release"
RETRY_FIRST_DELAY = timedelta(seconds=20)


class PaymentRefused(Conflict):
    code = "payment_not_allowed"
    title = "This payment is not allowed"


def _consent_required(detail: str = "The person's consent no longer allows access to this application.") -> Forbidden:
    return Forbidden(detail, code="consent_required")


def _move(payment: models.Payment, wanted: str) -> None:
    try:
        rules.check_move(payment.status, wanted)
    except rules.IllegalPaymentTransition as exc:
        raise Conflict(str(exc), code="illegal_payment_transition") from exc
    payment.status = wanted


def _approvers_of_case(db: Session, application_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.scalars(
        select(models.HumanReview.reviewer_user_id)
        .join(models.Case, models.Case.id == models.HumanReview.case_id)
        .where(models.Case.application_id == application_id, models.HumanReview.action == "approve")
    ).all()
    return list(dict.fromkeys(rows))


def _approval_basis(db: Session, application: models.Application, decision_id: uuid.UUID | None) -> tuple[str, list[uuid.UUID]]:
    """What makes this payment legitimate: an engine approval, or an officer's approval of the case."""
    officers = _approvers_of_case(db, application.id)
    if decision_id is not None:
        decision = db.get(models.Decision, decision_id)
        if decision is None or decision.application_id != application.id:
            raise PaymentRefused("The decision does not belong to this application.")
        if decision.outcome == "approved":
            return "engine", officers
    if officers:
        return "officer", officers
    raise PaymentRefused("A payment needs an approved decision or an officer's approval.")


def request_payment(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    person_id: uuid.UUID,
    decision_id: uuid.UUID | None,
    amount_pkr: int,
    requested_by: uuid.UUID | None = None,
) -> models.Payment:
    """Create (or return the existing) payment for an approved application, in the caller's transaction."""
    if amount_pkr <= 0:
        raise Unprocessable("A payment needs a positive amount.", code="bad_amount")
    application = db.scalar(
        select(models.Application)
        .where(models.Application.id == application_id, models.Application.tenant_id == tenant_id)
        .with_for_update()
    )
    if application is None:
        raise _consent_required()
    if application.person_id != person_id:
        raise PaymentRefused("The person does not match the application.")
    key = rules.idempotency_key(application_id)
    existing = db.scalar(select(models.Payment).where(models.Payment.tenant_id == tenant_id, models.Payment.idempotency_key == key))
    if existing is not None:
        return existing
    if application.status != "approved":
        raise PaymentRefused("Only an approved application can be paid.")
    basis, case_approvers = _approval_basis(db, application, decision_id)
    tenant = db.get(models.Tenant, tenant_id)
    limit = rules.four_eyes_limit(tenant.config if tenant else None)
    four_eyes = rules.needs_second_approver(amount_pkr, limit)
    payment = models.Payment(
        id=uuid.uuid4(), tenant_id=tenant_id, application_id=application_id, decision_id=decision_id, person_id=person_id,
        amount_pkr=amount_pkr, status="pending_approval" if four_eyes else "approved", idempotency_key=key, requested_by=requested_by,
    )  # fmt: skip
    try:
        with db.begin_nested():
            db.add(payment)
            db.flush()
    except IntegrityError:
        found = db.scalar(select(models.Payment).where(models.Payment.tenant_id == tenant_id, models.Payment.idempotency_key == key))
        if found is None:
            raise
        return found
    audit.write(
        db, tenant_id=tenant_id, action="payment.requested", actor_type="user" if requested_by else "system", actor_id=requested_by,
        object_type="payment", object_id=payment.id, acting_for_person_id=person_id,
        details={"application_id": str(application_id), "decision_id": str(decision_id) if decision_id else None, "amount_pkr": amount_pkr,
                 "basis": basis, "four_eyes": four_eyes, "limit_pkr": limit},
    )  # fmt: skip
    if four_eyes:
        approval = models.Approval(
            id=uuid.uuid4(), tenant_id=tenant_id, kind="payment", subject_type="payment", subject_id=payment.id, status="pending",
            requested_by=requested_by,
            data={"amount_pkr": amount_pkr, "limit_pkr": limit, "application_id": str(application_id),
                  "excluded_approvers": [str(u) for u in {*case_approvers, *([requested_by] if requested_by else [])}]},
        )  # fmt: skip
        db.add(approval)
        db.flush()
        payment.approval_id = approval.id
        audit.write(db, tenant_id=tenant_id, action="approval.requested", actor_type="system", object_type="approval",
                    object_id=approval.id, details={"kind": "payment", "payment_id": str(payment.id), "amount_pkr": amount_pkr})  # fmt: skip
        db.flush()
        return payment
    release_payment(db, payment)
    return payment


def _payout_account(application: models.Application) -> str:
    value = ((application.form or {}).get("payout_account") or {}).get("value")
    return str(value) if value else "cash-pickup"


def release_payment(db: Session, payment: models.Payment, *, actor_id: uuid.UUID | None = None, schedule_retry: bool = True) -> str:
    """Send an approved payment on the rail. Returns settled, unavailable or rejected; never raises for an outage."""
    from app.modules.integrations.service import submit_payment
    from app.modules.notifications.service import notify

    locked = db.scalar(select(models.Payment).where(models.Payment.id == payment.id).with_for_update().execution_options(populate_existing=True))
    if locked is None:
        raise NotFound("No such payment.")
    if locked.status == "settled":
        return "settled"
    if locked.status not in rules.RELEASABLE:
        raise Conflict(f"A {locked.status} payment cannot be released.", code="illegal_payment_transition")
    application = db.get(models.Application, locked.application_id)
    if application is None:
        raise _consent_required()
    result = submit_payment(
        idempotency_key=locked.idempotency_key, amount_pkr=locked.amount_pkr, account_ref=_payout_account(application), reference=str(locked.id)
    )
    if result.status == "settled":
        _move(locked, "settled")
        locked.rail_ref = result.rail_ref
        locked.failure_reason = None
        db.add(models.ReconciliationItem(
            id=uuid.uuid4(), tenant_id=locked.tenant_id, payment_id=locked.id, run_date=datetime.now(UTC).date(),
            status=rules.reconciliation_status(locked.amount_pkr, result.settled_pkr), expected_pkr=locked.amount_pkr,
            settled_pkr=result.settled_pkr, note="settled on the mock rail",
        ))  # fmt: skip
        application.status = "paid"
        application.version = (application.version or 1) + 1
        for event in ("payment.sent", "payment.settled"):  # the rail takes and confirms in one call; a real rail would split them
            emit_webhook(db, locked.tenant_id, event, {"payment_id": locked.id, "application_id": locked.application_id, "status": "settled"})
        audit.write(db, tenant_id=locked.tenant_id, action="payment.settled", actor_type="user" if actor_id else "system", actor_id=actor_id,
                    object_type="payment", object_id=locked.id, acting_for_person_id=locked.person_id,
                    details={"amount_pkr": locked.amount_pkr, "rail_ref": result.rail_ref, "settled_pkr": result.settled_pkr})  # fmt: skip
        notify(db, tenant_id=locked.tenant_id, person_id=locked.person_id, template="payment_sent",
               payload={"amount_pkr": locked.amount_pkr, "rail_ref": result.rail_ref, "tracking_code": application.tracking_code,
                        "payment_id": locked.id})  # fmt: skip
        db.flush()
        return "settled"
    first_failure = locked.status != "failed"
    _move(locked, "failed")
    locked.failure_reason = "rail_unavailable" if result.status == "unavailable" else f"rail_rejected:{result.detail}"[:200]
    audit.write(db, tenant_id=locked.tenant_id, action="payment.failed", actor_type="system", object_type="payment", object_id=locked.id,
                result="failed", reason=locked.failure_reason, details={"amount_pkr": locked.amount_pkr})  # fmt: skip
    if result.status == "unavailable" and schedule_retry:
        enqueue(db, tenant_id=locked.tenant_id, kind=RELEASE_JOB, payload={"payment_id": str(locked.id)}, person_id=locked.person_id,
                priority=10, max_attempts=8, run_at=datetime.now(UTC) + RETRY_FIRST_DELAY)  # fmt: skip
        if first_failure:
            notify(db, tenant_id=locked.tenant_id, person_id=locked.person_id, template="payment_delayed",
                   payload={"payment_id": locked.id, "tracking_code": application.tracking_code})  # fmt: skip
    db.flush()
    return result.status


# --- the retry job --------------------------------------------------------------------------------------


def release_job(db: Session, job: JobContext) -> None:
    try:
        payment_id = uuid.UUID(str(job.payload.get("payment_id")))
    except ValueError as exc:
        raise PermanentJobError("bad payment id") from exc
    payment = db.get(models.Payment, payment_id)
    if payment is None:
        raise PermanentJobError("payment not found")
    if payment.status == "settled":
        return
    try:
        outcome = release_payment(db, payment, schedule_retry=False)
    except Forbidden as exc:
        raise PermanentJobError("consent_required") from exc
    if outcome == "unavailable":
        raise RetryLater("payment rail unavailable")
    if outcome == "rejected":
        raise PermanentJobError("payment rail rejected the payment")


def on_release_failure(db: Session, job: JobContext, error: str, dead: bool) -> None:
    if not dead:
        return
    try:
        payment = db.get(models.Payment, uuid.UUID(str(job.payload.get("payment_id"))))
    except ValueError:
        return
    if payment is not None and payment.status != "settled":
        payment.failure_reason = f"retries_exhausted: {error}"[:200]
        audit.write(db, tenant_id=payment.tenant_id, action="payment.retries_exhausted", actor_type="system", actor_role="worker",
                    object_type="payment", object_id=payment.id, result="failed", reason=error[:200])  # fmt: skip


# --- approvals (maker-checker) --------------------------------------------------------------------------


def decide_approval(db: Session, principal: Principal, approval_id: uuid.UUID, *, approve: bool, reason: str) -> models.Approval:
    approval = db.scalar(select(models.Approval).where(models.Approval.id == approval_id).with_for_update())
    if approval is None:
        raise NotFound("No such approval.")
    if approval.kind != "payment":
        raise Conflict("This approval is not a payment.", code="wrong_approval_kind")
    if approval.status != "pending":
        raise Conflict("This approval has already been decided.", code="already_decided")
    excluded: list[Any] = [approval.requested_by, *(approval.data or {}).get("excluded_approvers", [])]
    if not rules.may_release(principal.user_id, excluded):
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="approval", object_id=approval.id, result="denied", reason="four_eyes_same_person",
            details={"kind": approval.kind},
        )  # fmt: skip
        raise Forbidden("A different person must release this payment.", code="four_eyes_same_person")
    payment = db.scalar(select(models.Payment).where(models.Payment.id == approval.subject_id).with_for_update())
    if payment is None:
        raise NotFound("The payment for this approval no longer exists.")
    application = db.get(models.Application, payment.application_id)
    if application is None:
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="application", object_id=payment.application_id, result="denied", reason="consent_required",
        )  # fmt: skip
        raise _consent_required()
    approval.status = "approved" if approve else "rejected"
    approval.approver_id = principal.user_id
    approval.reason = reason
    approval.decided_at = datetime.now(UTC)
    audit.write(db, tenant_id=principal.tenant_id, action=f"approval.{approval.status}", actor_id=principal.user_id, actor_role=principal.role,
                object_type="approval", object_id=approval.id, reason=reason,
                details={"kind": "payment", "payment_id": str(payment.id), "amount_pkr": payment.amount_pkr})  # fmt: skip
    if approve:
        _move(payment, "approved")
        for review in db.scalars(
            select(models.HumanReview).join(models.Case, models.Case.id == models.HumanReview.case_id)
            .where(models.Case.application_id == payment.application_id, models.HumanReview.action == "approve")
        ).all():  # fmt: skip
            review.second_approver_id = principal.user_id
        db.flush()
        release_payment(db, payment, actor_id=principal.user_id)
    else:
        _move(payment, "cancelled")
        payment.failure_reason = "second_approver_rejected"
        application.status = "in_review"
        application.version = (application.version or 1) + 1
        from app.modules.cases.service import reopen_for_application

        reopen_for_application(db, tenant_id=principal.tenant_id, application_id=application.id, actor_id=principal.user_id,
                               reason=f"Payment not released by the second approver: {reason}")  # fmt: skip
    db.flush()
    return approval
