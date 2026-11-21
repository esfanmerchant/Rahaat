"""Appeals and complaints.

An appeal asks for a second look at a rejection. It opens an `appeal` case in the officer queue with a handoff
package that says what is contested. It must be decided by an officer who had no part in the first decision
(`rules.may_decide`, checked on the server; a refusal is audited in its own committed transaction). `overturned`
runs the normal approval path (a rejected application becomes approved, a notification goes out, and the payment
service creates the payment, once, with four-eyes above the limit); `upheld` tells the citizen with a keyed message.

A complaint is a case too (`complaint`, or `scam_review` for scam reports). Both are person data: officers read
the application behind an appeal through Row Level Security, so a withdrawn consent stops them on the next request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.decision import HandoffPackage
from app.core import audit, metrics
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.logging import redact
from app.db import models
from app.modules.appeals import rules
from app.modules.appeals.schemas import (
    AppealCreate,
    AppealDecide,
    AppealList,
    AppealOut,
    AppealStaffDetail,
    AppealStaffList,
    AppealStaffOut,
    ComplaintCreate,
    ComplaintList,
    ComplaintOut,
    ComplaintResolve,
    ComplaintStaffList,
    ComplaintStaffOut,
    KeyedText,
)
from app.modules.applications.service import latest_decision, load_owned
from app.modules.cases import paging
from app.modules.cases import service as cases
from app.modules.consent.access_log import record_view
from app.modules.consent.rules import require_consent, require_consent_for_helper_read
from app.modules.notifications import templates
from app.modules.notifications.service import notify
from app.modules.payments.service import request_payment
from app.modules.people.context import PersonContext
from app.modules.webhooks.emit import emit as emit_webhook

MAX_PAGE = 100


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def _keyed(key: str, template: str, payload: dict[str, Any]) -> KeyedText:
    return KeyedText(key=key, en=templates.render(template, "en", payload), ur=templates.render(template, "ur", payload))


# --- citizen: appeals ----------------------------------------------------------------------------------------

_APPEAL_MESSAGE = {"open": "appeal_received", "upheld": "appeal_upheld", "overturned": "appeal_overturned"}


def _appeal_out(appeal: models.Appeal, tracking_code: str | None, amount: int | None = None) -> AppealOut:
    status_key = rules.appeal_citizen_status(appeal.status)
    template = _APPEAL_MESSAGE.get(appeal.status, "appeal_received")
    payload = {"tracking_code": tracking_code, "amount_pkr": amount}
    return AppealOut(
        id=appeal.id, application_id=appeal.application_id, tracking_code=tracking_code, status=appeal.status,  # type: ignore[arg-type]
        status_key=status_key,  # type: ignore[arg-type]
        message=_keyed(f"appeal.{status_key}", template, payload), reason=appeal.reason, created_at=_iso(appeal.created_at) or "",
        due_at=_iso(appeal.due_at), resolved_at=_iso(appeal.resolved_at),
    )  # fmt: skip


def _key_of(case: models.Case | None) -> str | None:
    value = ((case.handoff or {}).get("evidence") or {}).get("idempotency_key") if case else None
    return str(value) if value else None


def _decided_at(db: Session, application: models.Application, decision: models.Decision | None) -> datetime | None:
    """When the answer the person disagrees with was given: the later of the engine's decision and an officer's rejection."""
    times = [decision.created_at] if decision is not None else []
    review = db.scalar(
        select(models.HumanReview.created_at).join(models.Case, models.Case.id == models.HumanReview.case_id)
        .where(models.Case.application_id == application.id, models.Case.kind != "appeal", models.HumanReview.action == "reject")
        .order_by(models.HumanReview.created_at.desc()).limit(1)
    )  # fmt: skip
    if review is not None:
        times.append(review)
    return max(times) if times else application.updated_at


def create_appeal(db: Session, ctx: PersonContext, body: AppealCreate, idempotency_key: str | None) -> tuple[AppealOut, bool]:
    """Returns (appeal, created). A repeat with the same Idempotency-Key returns the first appeal."""
    application = load_owned(db, ctx, body.application_id, lock=True)
    require_consent(db, ctx, action="appeal.create")
    existing = list(db.scalars(select(models.Appeal).where(models.Appeal.tenant_id == ctx.tenant_id,
                                                           models.Appeal.application_id == application.id)).all())  # fmt: skip
    if idempotency_key:
        for appeal in existing:
            if appeal.case_id and _key_of(db.get(models.Case, appeal.case_id)) == idempotency_key:
                return _appeal_out(appeal, application.tracking_code), False
    decision = latest_decision(db, application.id)
    now = _now()
    refused = rules.ineligible_reason(
        application_status=application.status, decided_at=_decided_at(db, application, decision), now=now,
        decision_id=decision.id if decision else None, earlier=[(a.status, a.decision_id) for a in existing],
    )  # fmt: skip
    if refused is not None:
        raise Conflict(_REFUSALS[refused], code=refused, extra={"window_days": rules.WINDOW_DAYS, "application_status": application.status})

    original = {"outcome": decision.outcome if decision else "rejected", "route": decision.route if decision else None,
                "reasons": [str(r) for r in (decision.reasons if decision else []) or []][:6]}  # fmt: skip
    appeal_id = uuid.uuid4()
    package = HandoffPackage(
        question="Should the earlier decision on this application stand?",
        understanding=f"The citizen disagrees with the earlier decision ({original['outcome']}) and asks for a second look. "
                      "A different officer than the one who made the first decision must decide.",
        rule_fired=original["reasons"][0] if original["reasons"] else None,
        evidence={"appeal_id": str(appeal_id), "application_id": str(application.id), "decision_id": str(decision.id) if decision else None,
                  "original_outcome": original["outcome"], "original_route": original["route"], "original_reasons": original["reasons"],
                  "contested": "the whole decision", "citizen_reason": redact(body.reason), "idempotency_key": idempotency_key,
                  "filed_by": "helper" if ctx.via_helper else "citizen"},
    )  # fmt: skip
    case = cases.open_case(db, tenant_id=ctx.tenant_id, kind="appeal", opened_reason="citizen_appeal", application_id=application.id,
                           person_id=ctx.person_id, decision_id=decision.id if decision else None, handoff=package, priority=30)  # fmt: skip
    appeal = models.Appeal(
        id=appeal_id, tenant_id=ctx.tenant_id, application_id=application.id, decision_id=decision.id if decision else None,
        person_id=ctx.person_id, reason=redact(body.reason), status="open", due_at=now + timedelta(days=rules.SLA_DAYS), case_id=case.id,
        created_at=now,
    )  # fmt: skip
    db.add(appeal)
    db.flush()
    audit.write(db, tenant_id=ctx.tenant_id, action="appeal.opened", object_type="appeal", object_id=appeal.id,
                details={"application_id": str(application.id), "case_id": str(case.id), "decision_id": str(decision.id) if decision else None,
                         "original_outcome": original["outcome"]}, **ctx.audit_fields())  # fmt: skip
    notify(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, template="appeal_received",
           payload={"tracking_code": application.tracking_code, "application_id": application.id, "case_id": case.id})  # fmt: skip
    emit_webhook(db, ctx.tenant_id, "appeal.opened", {"appeal_id": appeal.id, "application_id": application.id, "case_id": case.id, "status": "open"})
    db.commit()
    return _appeal_out(appeal, application.tracking_code), True


_REFUSALS = {
    "appeal_not_applicable": "Only an application that was rejected can be appealed.",
    "appeal_window_closed": f"The {rules.WINDOW_DAYS} days to appeal this decision have passed.",
    "appeal_already_open": "This application already has an appeal that a person is looking at.",
    "appeal_already_decided": "This decision was already appealed and decided.",
}


def list_my_appeals(db: Session, ctx: PersonContext, *, limit: int, cursor: str | None) -> AppealList:
    require_consent_for_helper_read(db, ctx, action="appeal.list")
    query = select(models.Appeal, models.Application.tracking_code)\
        .outerjoin(models.Application, models.Application.id == models.Appeal.application_id)\
        .where(models.Appeal.tenant_id == ctx.tenant_id, models.Appeal.person_id == ctx.person_id)  # fmt: skip
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Appeal.created_at, models.Appeal.id) < tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    rows = db.execute(query.order_by(models.Appeal.created_at.desc(), models.Appeal.id.desc()).limit(min(limit, MAX_PAGE) + 1)).all()
    page = rows[: min(limit, MAX_PAGE)]
    nxt = paging.encode(page[-1][0].created_at, page[-1][0].id) if len(rows) > len(page) and page else None
    amounts = _amounts(db, [a.application_id for a, _ in page if a.status == "overturned"])
    return AppealList(items=[_appeal_out(a, code, amounts.get(a.application_id)) for a, code in page], next_cursor=nxt)


def _amounts(db: Session, application_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not application_ids:
        return {}
    return dict(db.execute(select(models.Payment.application_id, models.Payment.amount_pkr)
                           .where(models.Payment.application_id.in_(application_ids))).all())  # type: ignore[arg-type]


# --- staff: appeals --------------------------------------------------------------------------------------------


def original_deciders(db: Session, application_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone who reviewed, decided or second-approved the first decision on this application (appeal cases excluded)."""
    rows = db.execute(
        select(models.HumanReview.reviewer_user_id, models.HumanReview.second_approver_id)
        .join(models.Case, models.Case.id == models.HumanReview.case_id)
        .where(models.Case.application_id == application_id, models.Case.kind != "appeal")
    ).all()  # fmt: skip
    return rules.collect_deciders((r[0], r[1]) for r in rows)


def _staff_out(appeal: models.Appeal, tracking_code: str | None, now: datetime) -> AppealStaffOut:
    return AppealStaffOut(
        id=appeal.id, application_id=appeal.application_id, case_id=appeal.case_id, tracking_code=tracking_code,
        status=appeal.status, created_at=_iso(appeal.created_at) or "", due_at=_iso(appeal.due_at),  # type: ignore[arg-type]
        resolved_at=_iso(appeal.resolved_at), age_days=max(0, (now - appeal.created_at).days),
    )  # fmt: skip


def list_staff(db: Session, principal: Principal, *, status: str, limit: int, cursor: str | None) -> AppealStaffList:
    query = select(models.Appeal, models.Application.tracking_code)\
        .outerjoin(models.Application, models.Application.id == models.Appeal.application_id)\
        .where(models.Appeal.tenant_id == principal.tenant_id)  # fmt: skip
    if status != "all":
        query = query.where(models.Appeal.status == status)
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Appeal.created_at, models.Appeal.id) > tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    # Oldest first: the queue is worked from the top.
    rows = db.execute(query.order_by(models.Appeal.created_at, models.Appeal.id).limit(min(limit, MAX_PAGE) + 1)).all()
    page = rows[: min(limit, MAX_PAGE)]
    nxt = paging.encode(page[-1][0].created_at, page[-1][0].id) if len(rows) > len(page) and page else None
    now = _now()
    return AppealStaffList(items=[_staff_out(a, code, now) for a, code in page], next_cursor=nxt)


def _load_appeal(db: Session, principal: Principal, appeal_id: uuid.UUID, *, lock: bool = False) -> models.Appeal:
    query = select(models.Appeal).where(models.Appeal.id == appeal_id, models.Appeal.tenant_id == principal.tenant_id)
    appeal = db.scalar(query.with_for_update() if lock else query)
    if appeal is None:
        raise NotFound("No such appeal.", code="appeal_not_found")
    return appeal


def get_staff(db: Session, principal: Principal, appeal_id: uuid.UUID) -> AppealStaffDetail:
    """Reading the appeal reads the person's application, so it needs their consent and is recorded in their access log."""
    appeal = _load_appeal(db, principal, appeal_id)
    case = db.get(models.Case, appeal.case_id) if appeal.case_id else None
    application = cases._readable_application(db, principal, case) if case is not None else db.get(models.Application, appeal.application_id)
    if application is None:
        raise cases._deny_consent(principal, case, "application", appeal.application_id) if case else NotFound("No such appeal.")
    record_view(db, principal, appeal.person_id, what="appeal_detail", ref_id=appeal.id, details={})
    audit.write(db, tenant_id=principal.tenant_id, action="appeal.viewed", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=appeal.person_id, object_type="appeal", object_id=appeal.id)  # fmt: skip
    detail = _detail(db, principal, appeal, case, application)
    db.flush()
    return detail


def _detail(db: Session, principal: Principal, appeal: models.Appeal, case: models.Case | None, application: models.Application) -> AppealStaffDetail:
    evidence = ((case.handoff or {}).get("evidence") or {}) if case else {}
    deciders = original_deciders(db, appeal.application_id)
    allowed = rules.may_decide(principal.user_id, deciders)
    base = _staff_out(appeal, application.tracking_code, _now())
    return AppealStaffDetail(
        **base.model_dump(), reason=appeal.reason, outcome=appeal.outcome, decision_id=appeal.decision_id,
        original_outcome=evidence.get("original_outcome"), original_reasons=list(evidence.get("original_reasons") or []),
        can_decide=allowed and appeal.status == "open",
        cannot_decide_reason=None if allowed else "You took part in the first decision, so a different officer must decide this appeal.",
    )  # fmt: skip


def decide(db: Session, principal: Principal, appeal_id: uuid.UUID, body: AppealDecide) -> AppealStaffDetail:
    appeal = _load_appeal(db, principal, appeal_id, lock=True)
    if appeal.status != "open":
        raise Conflict("This appeal has already been decided.", code="already_decided", extra={"status": appeal.status})
    if appeal.case_id is None:
        raise NotFound("This appeal has no case.", code="appeal_not_found")
    case = cases._load(db, principal.tenant_id, appeal.case_id, lock=True)
    deciders = original_deciders(db, appeal.application_id)
    if not rules.may_decide(principal.user_id, deciders):
        metrics.ACCESS_DENIED.labels("four_eyes").inc()
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            acting_for_person_id=appeal.person_id, object_type="appeal", object_id=appeal.id, result="denied", reason="appeal_same_officer",
            details={"case_id": str(case.id)},
        )  # fmt: skip
        raise Forbidden("You took part in the first decision, so a different officer must decide this appeal.", code="appeal_same_officer")
    application = cases._readable_application(db, principal, case)  # 403 consent_required (audited) when consent no longer allows it
    assert application is not None
    now = _now()
    original = db.get(models.Decision, appeal.decision_id) if appeal.decision_id else None
    first_seen = db.scalar(select(models.CaseEvent.created_at).where(models.CaseEvent.case_id == case.id, models.CaseEvent.event == "viewed",
                                                                     models.CaseEvent.actor_user_id == principal.user_id).limit(1))  # fmt: skip

    overturn = body.outcome == "overturned"
    tracking = {"tracking_code": application.tracking_code, "application_id": application.id, "case_id": case.id}
    amount: int | None = None
    if overturn:
        if application.status != "rejected":
            raise Conflict(f"The application is {application.status}; only a rejected application can be approved on appeal.",
                           code="application_not_rejected")  # fmt: skip
        amount = cases._payment_amount(db, original, application)
    db.add(models.HumanReview(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, decision_id=appeal.decision_id, case_id=case.id, reviewer_user_id=principal.user_id,
        action="approve" if overturn else "reject", reason=body.reason,
        review_seconds=None if first_seen is None else max(0, int((now - first_seen).total_seconds())),
        overrode_ai=overturn, created_at=now,
    ))  # fmt: skip
    appeal.status, appeal.outcome, appeal.resolved_at = body.outcome, body.reason, now
    cases.resolve_with_outcome(db, principal, case, resolution=body.outcome, reason=body.reason, details={"appeal_id": str(appeal.id)})
    audit.write(db, tenant_id=principal.tenant_id, action="appeal.decided", actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=appeal.person_id, object_type="appeal", object_id=appeal.id, reason=body.reason,
                details={"outcome": body.outcome, "case_id": str(case.id), "application_id": str(application.id),
                         "original_deciders": len(deciders)})  # fmt: skip
    if overturn:
        # The normal approval path: status, message, and the payment service (once per application; four-eyes above the limit).
        try:
            with db.begin_nested():
                application.status = "approved"
                application.version = (application.version or 1) + 1
                db.flush()
        except IntegrityError as exc:  # the person has a newer open application for the same program
            raise Conflict("This person has a newer application for the same program, so this one cannot be approved.",
                           code="newer_application_open") from exc  # fmt: skip
        notify(db, tenant_id=principal.tenant_id, person_id=appeal.person_id, template="appeal_overturned",
               payload={**tracking, "amount_pkr": amount})  # fmt: skip
        request_payment(db, tenant_id=principal.tenant_id, application_id=application.id, person_id=appeal.person_id, decision_id=None,
                        amount_pkr=amount or 0, requested_by=principal.user_id)  # fmt: skip
    else:
        notify(db, tenant_id=principal.tenant_id, person_id=appeal.person_id, template="appeal_upheld", payload=tracking)
    emit_webhook(db, principal.tenant_id, "decision.made", {"application_id": application.id, "case_id": case.id,
                                                            "outcome": "approved" if overturn else "rejected", "route": "appeal"})  # fmt: skip
    emit_webhook(db, principal.tenant_id, "appeal.resolved", {"appeal_id": appeal.id, "application_id": application.id, "case_id": case.id,
                                                              "status": body.outcome})  # fmt: skip
    db.flush()
    detail = _detail(db, principal, appeal, case, application)
    db.commit()
    return detail


# --- complaints ------------------------------------------------------------------------------------------------


def _complaint_out(case: models.Case) -> ComplaintOut:
    status = rules.complaint_citizen_status(case.status)
    outcome = None
    if status == "resolved":
        outcome = "resolved" if case.resolution == "resolved" else "closed"
    template = {"received": "complaint_received", "being_checked": "complaint_received", "resolved": "complaint_resolved"}[status]
    if outcome == "closed":
        template = "complaint_closed"
    return ComplaintOut(
        id=case.id, category=rules.category_of(case.opened_reason),  # type: ignore[arg-type]
        status=status, outcome=outcome, message=_keyed(f"complaint.{status if outcome != 'closed' else 'closed'}", template, {}),  # type: ignore[arg-type]
        created_at=_iso(case.created_at) or "", resolved_at=_iso(case.resolved_at),
    )  # fmt: skip


def _complaint_filter() -> Any:
    return models.Case.opened_reason.like(rules.COMPLAINT_REASON_PREFIX.replace("_", "!_") + "%", escape="!")


def create_complaint(db: Session, ctx: PersonContext, body: ComplaintCreate, idempotency_key: str | None) -> tuple[ComplaintOut, bool]:
    require_consent(db, ctx, action="complaint.create")
    if idempotency_key:
        recent = db.scalars(select(models.Case).where(models.Case.tenant_id == ctx.tenant_id, models.Case.subject_person_id == ctx.person_id,
                                                      _complaint_filter()).order_by(models.Case.created_at.desc()).limit(50)).all()  # fmt: skip
        for case in recent:
            if _key_of(case) == idempotency_key:
                return _complaint_out(case), False
    kind, priority = rules.complaint_route(body.category)
    package = HandoffPackage(
        question="How should this complaint be handled?",
        understanding=f"A citizen filed a complaint about: {body.category.replace('_', ' ')}.",
        evidence={"category": body.category, "details": redact(body.details) if body.details else None, "idempotency_key": idempotency_key,
                  "filed_by": "helper" if ctx.via_helper else "citizen"},
    )  # fmt: skip
    case = cases.open_case(db, tenant_id=ctx.tenant_id, kind=kind, opened_reason=rules.complaint_reason(body.category), person_id=ctx.person_id,
                           handoff=package, priority=priority)  # fmt: skip
    audit.write(db, tenant_id=ctx.tenant_id, action="complaint.filed", object_type="case", object_id=case.id,
                details={"category": body.category, "case_kind": kind}, **ctx.audit_fields())  # fmt: skip
    notify(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, template="complaint_received", payload={"case_id": case.id})
    db.commit()
    return _complaint_out(case), True


def list_my_complaints(db: Session, ctx: PersonContext, *, limit: int, cursor: str | None) -> ComplaintList:
    require_consent_for_helper_read(db, ctx, action="complaint.list")
    query = select(models.Case).where(models.Case.tenant_id == ctx.tenant_id, models.Case.subject_person_id == ctx.person_id, _complaint_filter())
    if cursor:
        created, row_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Case.created_at, models.Case.id) < tuple_(paging.as_datetime(created), paging.as_uuid(row_id)))
    rows = db.scalars(query.order_by(models.Case.created_at.desc(), models.Case.id.desc()).limit(min(limit, MAX_PAGE) + 1)).all()
    page = rows[: min(limit, MAX_PAGE)]
    nxt = paging.encode(page[-1].created_at, page[-1].id) if len(rows) > len(page) and page else None
    return ComplaintList(items=[_complaint_out(c) for c in page], next_cursor=nxt)


def _staff_complaint(case: models.Case, readable: bool) -> ComplaintStaffOut:
    evidence = (case.handoff or {}).get("evidence") or {}
    return ComplaintStaffOut(
        id=case.id, category=rules.category_of(case.opened_reason),  # type: ignore[arg-type]
        case_kind=case.kind,  # type: ignore[arg-type]
        status=case.status, priority=case.priority, details=evidence.get("details") if readable else None,
        created_at=_iso(case.created_at) or "", resolved_at=_iso(case.resolved_at), resolution=case.resolution,
    )  # fmt: skip


def list_staff_complaints(db: Session, principal: Principal, *, status: str, limit: int, cursor: str | None) -> ComplaintStaffList:
    query = select(models.Case, models.Person.id).outerjoin(models.Person, models.Person.id == models.Case.subject_person_id)\
        .where(models.Case.tenant_id == principal.tenant_id, _complaint_filter())  # fmt: skip
    if status == "active":
        query = query.where(models.Case.status.in_(("open", "assigned", "in_review", "waiting_proof", "escalated")))
    elif status == "resolved":
        query = query.where(models.Case.status.in_(("resolved", "closed")))
    if cursor:
        priority, created, row_id = paging.decode(cursor, size=3)
        query = query.where(tuple_(models.Case.priority, models.Case.created_at, models.Case.id)
                            > tuple_(int(priority), paging.as_datetime(created), paging.as_uuid(row_id)))  # fmt: skip
    rows = db.execute(query.order_by(models.Case.priority, models.Case.created_at, models.Case.id).limit(min(limit, MAX_PAGE) + 1)).all()
    page = rows[: min(limit, MAX_PAGE)]  # a null person id means consent hides the person, and so the complaint's text
    nxt = paging.encode(page[-1][0].priority, page[-1][0].created_at, page[-1][0].id) if len(rows) > len(page) and page else None
    return ComplaintStaffList(items=[_staff_complaint(c, pid is not None) for c, pid in page], next_cursor=nxt)


def resolve_complaint(db: Session, principal: Principal, case_id: uuid.UUID, body: ComplaintResolve) -> ComplaintStaffOut:
    case = db.scalar(select(models.Case).where(models.Case.id == case_id, models.Case.tenant_id == principal.tenant_id, _complaint_filter())
                     .with_for_update())  # fmt: skip
    if case is None:
        raise NotFound("No such complaint.", code="complaint_not_found")
    cases._readable_application(db, principal, case)  # consent: 403 `consent_required`, audited, when the person's consent is gone
    cases.resolve_with_outcome(db, principal, case, resolution=body.outcome, reason=body.reason,
                               details={"category": rules.category_of(case.opened_reason)})  # fmt: skip
    notify(db, tenant_id=principal.tenant_id, person_id=case.subject_person_id,
           template="complaint_resolved" if body.outcome == "resolved" else "complaint_closed", payload={"case_id": case.id})  # fmt: skip
    out = _staff_complaint(case, True)
    db.commit()
    return out
