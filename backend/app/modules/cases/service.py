"""Cases: the one system for every human handoff (application review, duplicates, documents, appeals ...).

    open_case(db, tenant_id=..., kind="application_review", opened_reason="income_unverified",
              application_id=..., person_id=..., decision_id=..., handoff=package, confidence=0.81)

Person data comes through Row Level Security. The case row is tenant data, but the application, form and
document checks behind it are person data: when the person's consent is gone the officer gets 403
`consent_required` and an `access.denied` row is committed on its own, so the attempt stays on record.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.contracts.api import CaseActionIn, CaseDetail, CaseEventOut, CaseList, CaseNoteOut, CaseSummary
from app.contracts.application import ApplicationFormV1
from app.contracts.common import CaseKind
from app.contracts.decision import DecisionTrace, HandoffPackage
from app.contracts.documents import DocumentCheck
from app.core import audit, metrics
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.core.logging import get_logger
from app.db import models
from app.modules.cases import paging, rules
from app.modules.consent.access_log import record_view

log = get_logger("rahat.cases")

CASE_KINDS: frozenset[str] = frozenset(CaseKind.__args__)  # type: ignore[attr-defined]
REVIEWABLE_APPLICATION = frozenset({"submitted", "in_review", "needs_proof"})
DEFAULT_PAYMENT_PKR = 12_000
SortKey = Literal["priority", "confidence", "age"]
StatusFilter = Literal["open", "assigned", "in_review", "waiting_proof", "escalated", "resolved", "closed", "active", "all"]


def _now() -> datetime:
    return datetime.now(UTC)


def _event(db: Session, case: models.Case, event: str, *, from_status: str | None, to_status: str | None,
           actor_id: uuid.UUID | None, details: dict[str, Any] | None = None) -> None:  # fmt: skip
    db.add(models.CaseEvent(id=uuid.uuid4(), tenant_id=case.tenant_id, case_id=case.id, event=event, from_status=from_status,
                            to_status=to_status, actor_user_id=actor_id, details=dict(details or {}), created_at=_now()))  # fmt: skip


def _illegal(exc: rules.IllegalCaseTransition) -> Conflict:
    return Conflict(f"This case is {exc.current}; it cannot {exc.event.replace('_', ' ')}.", code="illegal_transition",
                    extra={"status": exc.current, "action": exc.event})  # fmt: skip


# --- opening and system transitions (called by the pipeline and other modules) --------------------------


def open_case(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    opened_reason: str,
    application_id: uuid.UUID | None = None,
    person_id: uuid.UUID | None = None,
    decision_id: uuid.UUID | None = None,
    handoff: HandoffPackage | dict[str, Any] | None = None,
    confidence: float | None = None,
    priority: int = 50,
) -> models.Case:
    """Open a case, or refresh the active one of the same kind for the same application (never two at once)."""
    if kind not in CASE_KINDS:
        raise ValueError(f"unknown case kind {kind!r}")
    package = handoff.model_dump(mode="json") if isinstance(handoff, BaseModel) else dict(handoff or {})
    now = _now()
    if application_id is not None:
        existing = db.scalar(
            select(models.Case)
            .where(models.Case.tenant_id == tenant_id, models.Case.application_id == application_id, models.Case.kind == kind,
                   models.Case.status.in_(rules.ACTIVE))
            .order_by(models.Case.created_at.desc(), models.Case.id.desc()).limit(1).with_for_update()
        )  # fmt: skip
        if existing is not None:
            old = existing.status
            existing.decision_id = decision_id or existing.decision_id
            if package:
                existing.handoff = package
            if confidence is not None:
                existing.confidence = confidence
            existing.priority = min(existing.priority, priority)
            existing.opened_reason = opened_reason[:64]
            if existing.status == "waiting_proof":
                existing.status = rules.next_status(existing.status, "proof_received")
            _event(db, existing, "updated" if old == existing.status else "proof_received", from_status=old, to_status=existing.status,
                   actor_id=None, details={"reason": opened_reason[:64], "decision_id": str(decision_id) if decision_id else None})  # fmt: skip
            _link_decision(db, decision_id, existing.id)
            audit.write(db, tenant_id=tenant_id, action="case.updated", actor_type="system", object_type="case", object_id=existing.id,
                        acting_for_person_id=person_id, details={"reason": opened_reason[:64], "status": existing.status})  # fmt: skip
            db.flush()
            return existing
    case = models.Case(
        id=uuid.uuid4(), tenant_id=tenant_id, kind=kind, status="open", priority=priority, confidence=confidence,
        subject_person_id=person_id, application_id=application_id, decision_id=decision_id, opened_reason=opened_reason[:64],
        handoff=package, sla_due_at=rules.sla_due(kind, priority, now), created_at=now, updated_at=now,
    )  # fmt: skip
    db.add(case)
    db.flush()
    _event(db, case, "created", from_status=None, to_status="open", actor_id=None, details={"reason": opened_reason[:64]})
    _link_decision(db, decision_id, case.id)
    audit.write(db, tenant_id=tenant_id, action="case.opened", actor_type="system", object_type="case", object_id=case.id,
                acting_for_person_id=person_id,
                details={"kind": kind, "reason": opened_reason[:64], "priority": priority, "confidence": confidence,
                         "decision_id": str(decision_id) if decision_id else None})  # fmt: skip
    db.flush()
    return case


def _link_decision(db: Session, decision_id: uuid.UUID | None, case_id: uuid.UUID) -> None:
    if decision_id is None:
        return
    decision = db.get(models.Decision, decision_id)
    if decision is not None and decision.case_id is None:
        decision.case_id = case_id


def reopen_for_application(db: Session, *, tenant_id: uuid.UUID, application_id: uuid.UUID, actor_id: uuid.UUID | None, reason: str) -> int:
    """Reopen the resolved cases of an application (for example when a second approver stops the payment)."""
    reopened = 0
    for case in db.scalars(
        select(models.Case).where(models.Case.tenant_id == tenant_id, models.Case.application_id == application_id,
                                  models.Case.status == "resolved").with_for_update()
    ).all():  # fmt: skip
        old = case.status
        case.status = rules.next_status(old, "reopen")
        case.resolved_at = None
        case.resolution = None
        _event(db, case, "reopened", from_status=old, to_status=case.status, actor_id=actor_id, details={"reason": reason[:300]})
        audit.write(db, tenant_id=tenant_id, action="case.reopened", actor_id=actor_id, actor_type="user" if actor_id else "system",
                    object_type="case", object_id=case.id, reason=reason[:300])  # fmt: skip
        reopened += 1
    return reopened


def proof_received(db: Session, *, tenant_id: uuid.UUID, application_id: uuid.UUID) -> int:
    """New proof arrived for an application: its waiting cases go back to a person."""
    moved = 0
    for case in db.scalars(
        select(models.Case).where(models.Case.tenant_id == tenant_id, models.Case.application_id == application_id,
                                  models.Case.status == "waiting_proof").with_for_update()
    ).all():  # fmt: skip
        case.status = rules.next_status(case.status, "proof_received")
        _event(db, case, "proof_received", from_status="waiting_proof", to_status=case.status, actor_id=None)
        audit.write(db, tenant_id=tenant_id, action="case.proof_received", actor_type="system", object_type="case", object_id=case.id)
        moved += 1
    return moved


# --- reading --------------------------------------------------------------------------------------------


def _load(db: Session, case_id: uuid.UUID, *, lock: bool = False) -> models.Case:
    query = select(models.Case).where(models.Case.id == case_id)
    if lock:
        query = query.with_for_update()
    case = db.scalar(query)
    if case is None:  # another tenant's case is invisible under RLS, so it is simply not found
        raise NotFound("No such case.")
    return case


def _deny_consent(principal: Principal, case: models.Case, object_type: str, object_id: uuid.UUID) -> Forbidden:
    metrics.ACCESS_DENIED.labels("consent").inc()
    audit.write_independent(
        tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
        acting_for_person_id=case.subject_person_id, object_type=object_type, object_id=object_id, result="denied",
        reason="consent_required", details={"case_id": str(case.id)},
    )  # fmt: skip
    return Forbidden("This person's consent no longer allows us to show their application.", code="consent_required")


def _readable_application(db: Session, principal: Principal, case: models.Case) -> models.Application | None:
    """The case's application through RLS. 403 when it exists but consent hides it."""
    if case.application_id is not None:
        application = db.get(models.Application, case.application_id)
        if application is None:
            raise _deny_consent(principal, case, "application", case.application_id)
        return application
    if case.subject_person_id is not None and db.get(models.Person, case.subject_person_id) is None:
        raise _deny_consent(principal, case, "person", case.subject_person_id)
    return None


def _names(db: Session, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    return dict(db.execute(select(models.User.id, models.User.display_name).where(models.User.id.in_(user_ids))).all())  # type: ignore[arg-type,unused-ignore]


def _summary(case: models.Case, subject_name: str | None, now: datetime) -> dict[str, Any]:
    return {
        "id": case.id, "kind": case.kind, "status": case.status, "priority": case.priority, "confidence": case.confidence,
        "opened_reason": case.opened_reason, "subject_name": subject_name, "application_id": case.application_id,
        "assigned_to": case.assigned_to, "sla_due_at": paging.iso(case.sla_due_at),
        "age_minutes": max(0, int((now - case.created_at).total_seconds() // 60)), "created_at": paging.iso(case.created_at) or "",
    }  # fmt: skip


def _trace(db: Session, case: models.Case) -> DecisionTrace | None:
    if case.decision_id is None:
        return None
    decision = db.get(models.Decision, case.decision_id)
    if decision is None:
        return None
    try:
        from app.modules.decision.service import trace_view  # Track B; absent until merged
    except ImportError:
        return None
    try:
        trace = trace_view(db, decision, redact=False)
        return trace if isinstance(trace, DecisionTrace) else DecisionTrace.model_validate(trace)
    except Exception:  # noqa: BLE001  (a broken trace must not hide the case from the officer)
        log.exception("could not build the decision trace for case %s", case.id)
        return None


def _document_checks(db: Session, application: models.Application | None) -> list[DocumentCheck]:
    if application is None:
        return []
    rows = db.scalars(
        select(models.DocumentCheck).join(models.Document, models.Document.id == models.DocumentCheck.document_id)
        .where(models.Document.application_id == application.id)
        .order_by(models.DocumentCheck.created_at, models.DocumentCheck.id)
    ).all()  # fmt: skip
    checks = []
    for row in rows:
        try:
            checks.append(DocumentCheck.model_validate(row.result))
        except ValidationError:
            log.warning("stored document check %s does not match the contract", row.id)
    return checks


def build_detail(db: Session, case: models.Case, application: models.Application | None) -> CaseDetail:
    now = _now()
    subject = db.get(models.Person, case.subject_person_id) if case.subject_person_id else None
    handoff = None
    if case.handoff:
        try:
            handoff = HandoffPackage.model_validate(case.handoff)
        except ValidationError:
            log.warning("handoff package of case %s does not match the contract", case.id)
    form = None
    if application is not None and application.form:
        try:
            form = ApplicationFormV1.model_validate(application.form)
        except ValidationError:
            log.warning("form of application %s does not match the contract", application.id)
    notes = db.scalars(select(models.CaseNote).where(models.CaseNote.case_id == case.id)
                       .order_by(models.CaseNote.created_at, models.CaseNote.id)).all()  # fmt: skip
    events = db.scalars(select(models.CaseEvent).where(models.CaseEvent.case_id == case.id, models.CaseEvent.event != "viewed")
                        .order_by(models.CaseEvent.created_at, models.CaseEvent.id)).all()  # fmt: skip
    names = _names(db, {n.author_user_id for n in notes if n.author_user_id} | {e.actor_user_id for e in events if e.actor_user_id})
    return CaseDetail(
        **_summary(case, subject.full_name if subject else None, now),
        handoff=handoff, form=form, document_checks=_document_checks(db, application), decision=_trace(db, case),
        notes=[CaseNoteOut(id=n.id, author_kind=n.author_kind, author_name=names.get(n.author_user_id) if n.author_user_id else None,
                           body=n.body, created_at=paging.iso(n.created_at) or "") for n in notes],
        events=[CaseEventOut(event=e.event, from_status=e.from_status, to_status=e.to_status,
                             actor_name=names.get(e.actor_user_id) if e.actor_user_id else None, at=paging.iso(e.created_at) or "")
                for e in events],
        allowed_actions=rules.allowed_actions(case.status),
    )  # fmt: skip


def list_cases(
    db: Session, principal: Principal, *, status: StatusFilter = "active", kind: str | None = None, assignee: str | None = None,
    sort: SortKey = "priority", limit: int = 25, cursor: str | None = None,
) -> CaseList:  # fmt: skip
    query = (
        select(models.Case, models.Person.full_name)
        .outerjoin(models.Person, models.Person.id == models.Case.subject_person_id)  # RLS: no consent, no name
        .where(models.Case.tenant_id == principal.tenant_id)
    )
    if status == "active":
        query = query.where(models.Case.status.in_(rules.ACTIVE))
    elif status != "all":
        query = query.where(models.Case.status == status)
    if kind:
        query = query.where(models.Case.kind == kind)
    if assignee == "me":
        query = query.where(models.Case.assigned_to == principal.user_id)
    elif assignee == "unassigned":
        query = query.where(models.Case.assigned_to.is_(None))
    elif assignee:
        try:
            query = query.where(models.Case.assigned_to == uuid.UUID(assignee))
        except ValueError as exc:
            raise Unprocessable("assignee must be 'me', 'unassigned' or a user id.", code="bad_assignee") from exc

    confidence = func.coalesce(models.Case.confidence, -1.0)
    key_options: dict[str, list[Any]] = {
        "priority": [models.Case.priority, models.Case.created_at, models.Case.id],
        "confidence": [confidence, models.Case.created_at, models.Case.id],  # least sure first
        "age": [models.Case.created_at, models.Case.id],  # oldest first
    }
    keys = key_options[sort]
    if cursor:
        values = paging.decode(cursor, size=len(keys) + 1)
        if values[0] != sort:
            raise Unprocessable("This page link belongs to a different sort order.", code="bad_cursor")
        raw = values[1:]
        typed: list[Any] = []
        for key, value in zip(keys, raw, strict=True):
            if key is models.Case.id:
                typed.append(paging.as_uuid(value))
            elif key is models.Case.created_at:
                typed.append(paging.as_datetime(value))
            else:
                typed.append(value)
        query = query.where(tuple_(*keys) > tuple_(*typed))
    rows = db.execute(query.order_by(*keys).limit(limit + 1)).all()
    now = _now()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last: models.Case = page[-1][0]
        sort_options: dict[str, list[Any]] = {
            "priority": [last.priority, last.created_at, last.id],
            "confidence": [last.confidence if last.confidence is not None else -1.0, last.created_at, last.id],
            "age": [last.created_at, last.id],
        }
        next_cursor = paging.encode(sort, *sort_options[sort])
    return CaseList(items=[CaseSummary(**_summary(case, name, now)) for case, name in page], next_cursor=next_cursor)


def get_detail(db: Session, principal: Principal, case_id: uuid.UUID) -> CaseDetail:
    """The officer's review screen. Opening it is recorded: who looked at whose file, and when."""
    case = _load(db, case_id)
    application = _readable_application(db, principal, case)
    seen = db.scalar(select(models.CaseEvent.id).where(models.CaseEvent.case_id == case.id, models.CaseEvent.event == "viewed",
                                                       models.CaseEvent.actor_user_id == principal.user_id).limit(1))  # fmt: skip
    if seen is None:
        _event(db, case, "viewed", from_status=case.status, to_status=case.status, actor_id=principal.user_id)
    audit.write(db, tenant_id=principal.tenant_id, action="case.viewed", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=case.subject_person_id, object_type="case", object_id=case.id)  # fmt: skip
    if case.subject_person_id is not None:  # the person's access log shows this read (consent centre)
        record_view(db, principal, case.subject_person_id, what="case_detail", ref_id=case.id, details={"case_kind": case.kind})
    db.flush()
    return build_detail(db, case, application)


# --- officer actions ------------------------------------------------------------------------------------


def _active_officer(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.scalar(
        select(models.Membership.id).where(models.Membership.tenant_id == tenant_id, models.Membership.user_id == user_id,
                                           models.Membership.role == "officer", models.Membership.status == "active").limit(1)
    ) is not None  # fmt: skip


def assign(db: Session, principal: Principal, case_id: uuid.UUID, *, assignee_id: uuid.UUID | None, reason: str) -> CaseDetail:
    case = _load(db, case_id, lock=True)
    application = _readable_application(db, principal, case)
    target = assignee_id or principal.user_id
    if not _active_officer(db, principal.tenant_id, target):
        raise Unprocessable("Cases can only be given to an officer of this department.", code="bad_assignee")
    try:
        new_status = rules.next_status(case.status, "assign")
    except rules.IllegalCaseTransition as exc:
        raise _illegal(exc) from exc
    old = case.status
    case.status, case.assigned_to = new_status, target
    _event(db, case, "assigned", from_status=old, to_status=new_status, actor_id=principal.user_id,
           details={"assignee": str(target), "reason": reason[:300]})  # fmt: skip
    audit.write(db, tenant_id=principal.tenant_id, action="case.assigned", actor_id=principal.user_id, actor_role=principal.role,
                object_type="case", object_id=case.id, reason=reason, details={"assignee": str(target)})  # fmt: skip
    db.flush()
    return build_detail(db, case, application)


def add_note(db: Session, principal: Principal, case_id: uuid.UUID, *, body: str) -> CaseDetail:
    case = _load(db, case_id, lock=True)
    application = _readable_application(db, principal, case)
    note = models.CaseNote(id=uuid.uuid4(), tenant_id=case.tenant_id, case_id=case.id, author_user_id=principal.user_id,
                           author_kind="user", body=body, created_at=_now())  # fmt: skip
    db.add(note)
    _event(db, case, "note_added", from_status=case.status, to_status=case.status, actor_id=principal.user_id)
    audit.write(db, tenant_id=principal.tenant_id, action="case.note_added", actor_id=principal.user_id, actor_role=principal.role,
                object_type="case", object_id=case.id, details={"note_id": str(note.id), "length": len(body)})  # fmt: skip
    db.flush()
    return build_detail(db, case, application)


def _payment_amount(db: Session, decision: models.Decision | None, application: models.Application) -> int:
    version: models.RuleVersion | None = None
    if decision is not None:
        version = db.get(models.RuleVersion, decision.rule_version_id)
    if version is None:
        rule_set = db.scalar(select(models.RuleSet).where(models.RuleSet.program_id == application.program_id).limit(1))
        if rule_set is not None and rule_set.active_version_id is not None:
            version = db.get(models.RuleVersion, rule_set.active_version_id)
    try:
        return int((version.dsl if version else {}).get("payment_pkr") or DEFAULT_PAYMENT_PKR)
    except (TypeError, ValueError):
        return DEFAULT_PAYMENT_PKR


def _proof_kind(body: CaseActionIn, case: models.Case) -> str:
    if body.proof_kind:
        return body.proof_kind
    suggested = (case.handoff or {}).get("resolving_proof")
    return suggested if suggested in ("rahat_id", "income_proof") else "other"


def act(db: Session, principal: Principal, case_id: uuid.UUID, body: CaseActionIn) -> CaseDetail:
    """Approve, reject, request proof or escalate one case, with a reason. Applies the effect on the application."""
    from app.modules.notifications.service import notify
    from app.modules.payments.service import request_payment

    case = _load(db, case_id, lock=True)
    application = _readable_application(db, principal, case)
    try:
        new_status = rules.next_status(case.status, body.action)
    except rules.IllegalCaseTransition as exc:
        raise _illegal(exc) from exc
    on_application = case.kind == "application_review" and application is not None
    if on_application and body.action != "escalate":
        assert application is not None
        if application.status not in REVIEWABLE_APPLICATION:
            raise Conflict(f"The application is {application.status}; it cannot be changed from this case.", code="application_not_reviewable")

    now = _now()
    decision = db.get(models.Decision, case.decision_id) if case.decision_id else None
    hypotheses = (case.handoff or {}).get("hypotheses") or []
    lean = rules.engine_lean(decision.outcome if decision else None, decision.p_ok if decision else None, hypotheses)
    first_seen = db.scalar(
        select(func.min(models.CaseEvent.created_at)).where(models.CaseEvent.case_id == case.id, models.CaseEvent.event == "viewed",
                                                            models.CaseEvent.actor_user_id == principal.user_id)
    )  # fmt: skip
    seconds = rules.review_seconds(first_seen, now)
    overrode = rules.overrode_engine(body.action, lean)
    db.add(models.HumanReview(id=uuid.uuid4(), tenant_id=case.tenant_id, decision_id=case.decision_id, case_id=case.id,
                              reviewer_user_id=principal.user_id, action=body.action, reason=body.reason, review_seconds=seconds,
                              overrode_ai=overrode, created_at=now))  # fmt: skip

    old = case.status
    case.status = new_status
    details: dict[str, Any] = {"engine_lean": lean, "overrode_ai": overrode, "review_seconds": seconds}
    if body.action in ("approve", "reject"):
        case.resolved_at = now
        case.resolution = "approved" if body.action == "approve" else "rejected"
        case.resolution_reason = body.reason
    elif body.action == "request_proof":
        details["proof_kind"] = _proof_kind(body, case)
    elif body.action == "escalate":
        case.priority = rules.escalated_priority(case.priority)
        case.sla_due_at = rules.escalated_sla(case.sla_due_at, now)
        case.assigned_to = None  # back to the top of the queue for a senior officer
        details["priority"] = case.priority
    if case.assigned_to is None and body.action != "escalate":
        case.assigned_to = principal.user_id
    if case.kind == "correction" and body.action in ("approve", "reject"):
        # A correction or erasure request from the consent centre: apply it or close it with the case. This runs
        # before this transaction's first audit row: an erasure commits in its own transaction and needs the
        # tenant's audit lock, which this one would otherwise hold until it ends.
        from app.modules.consent.requests import on_case_decided

        on_case_decided(db, principal, case, approve=body.action == "approve", reason=body.reason)
    _event(db, case, body.action, from_status=old, to_status=new_status, actor_id=principal.user_id, details={**details, "reason": body.reason[:300]})
    audit.write(db, tenant_id=principal.tenant_id, action=f"case.{body.action}", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=case.subject_person_id, object_type="case", object_id=case.id, reason=body.reason,
                rule_version_id=decision.rule_version_id if decision else None, details=details)  # fmt: skip
    db.flush()

    if on_application:
        assert application is not None
        tracking = {"tracking_code": application.tracking_code, "application_id": application.id, "case_id": case.id}
        if body.action == "approve":
            amount = _payment_amount(db, decision, application)
            application.status = "approved"
            application.version = (application.version or 1) + 1
            db.flush()
            notify(db, tenant_id=case.tenant_id, person_id=application.person_id, template="approved", payload={**tracking, "amount_pkr": amount})
            request_payment(db, tenant_id=case.tenant_id, application_id=application.id, person_id=application.person_id,
                            decision_id=case.decision_id, amount_pkr=amount, requested_by=principal.user_id)  # fmt: skip
        elif body.action == "reject":
            application.status = "rejected"
            application.version = (application.version or 1) + 1
            notify(db, tenant_id=case.tenant_id, person_id=application.person_id, template="rejected", payload=tracking)
        elif body.action == "request_proof":
            application.status = "needs_proof"
            application.version = (application.version or 1) + 1
            notify(db, tenant_id=case.tenant_id, person_id=application.person_id, template="proof_needed",
                   payload={**tracking, "proof_kind": details["proof_kind"]})  # fmt: skip
        db.flush()
    return build_detail(db, case, application)


def reopen(db: Session, principal: Principal, case_id: uuid.UUID, *, reason: str) -> CaseDetail:
    case = _load(db, case_id, lock=True)
    application = _readable_application(db, principal, case)
    try:
        new_status = rules.next_status(case.status, "reopen")
    except rules.IllegalCaseTransition as exc:
        raise _illegal(exc) from exc
    if case.kind == "application_review" and application is not None:
        if application.status in ("approved", "paid"):
            raise Conflict("An approved application cannot be reopened here; stop the payment instead.", code="application_already_approved")
        application.status = "in_review"
        application.version = (application.version or 1) + 1
    old = case.status
    case.status = new_status
    case.resolved_at = None
    case.resolution = None
    _event(db, case, "reopened", from_status=old, to_status=new_status, actor_id=principal.user_id, details={"reason": reason[:300]})
    audit.write(db, tenant_id=principal.tenant_id, action="case.reopened", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=case.subject_person_id, object_type="case", object_id=case.id, reason=reason)  # fmt: skip
    db.flush()
    return build_detail(db, case, application)
