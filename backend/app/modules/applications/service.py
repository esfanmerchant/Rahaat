"""Applications: create (idempotent on client_op_id), read, patch with an optimistic lock, submit.

Ownership is checked twice: the query filters on the request's person, and Row Level Security only returns
rows that person (or their delegated helper) may read. Another person's application is a 404, never a 403,
so ids cannot be probed.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.api import (
    ApplicationCreate,
    ApplicationList,
    ApplicationOut,
    ApplicationPatch,
    ApplicationSummary,
    ProgramOut,
    RuleVersionBrief,
)
from app.contracts.application import ApplicationFormV1
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.contracts.decision import DecisionUserView, Explanation
from app.contracts.documents import DocumentCheck, DocumentCitizenView
from app.core import audit
from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import Conflict, NotFound, ServiceUnavailable, Unprocessable
from app.core.logging import get_logger
from app.core.mockdata import normalise_mock_phone
from app.db import models
from app.modules.applications import hooks
from app.modules.applications.forms import (
    check_client_form,
    merge_client_patch,
    missing_fields,
    raise_if_errors,
    scopes_needed,
    set_fields,
)
from app.modules.applications.status import EDITABLE
from app.modules.applications.timeline import DecisionEvent, PaymentEvent, build_timeline, format_tracking, new_tracking_number, symbols_for
from app.modules.consent.access_log import record_view
from app.modules.consent.rules import require_consent, require_consent_for_helper_read
from app.modules.documents.views import citizen_view
from app.modules.people.context import PersonContext
from app.modules.plans import service as plans

log = get_logger("rahat.applications")


def _iso(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else ""


# --- programs and rules ---------------------------------------------------------------------------------


def active_rule_version(db: Session, program_id: UUID) -> models.RuleVersion | None:
    rule_set = db.scalars(
        select(models.RuleSet).where(models.RuleSet.program_id == program_id).order_by(models.RuleSet.created_at, models.RuleSet.id)
    ).first()
    if rule_set is None or rule_set.active_version_id is None:
        return None
    return db.get(models.RuleVersion, rule_set.active_version_id)


def _brief(version: models.RuleVersion | None) -> RuleVersionBrief | None:
    if version is None:
        return None
    dsl = version.dsl or {}
    payment = dsl.get("payment_pkr")
    return RuleVersionBrief(
        id=version.id, version_no=version.version_no, description_en=version.description_en, description_ur=version.description_ur,
        required_docs=[str(d) for d in dsl.get("required_docs") or []], payment_pkr=payment if isinstance(payment, int) else None,
    )  # fmt: skip


def list_programs(db: Session, principal: Principal) -> list[ProgramOut]:
    programs = db.scalars(
        select(models.Program)
        .where(models.Program.tenant_id == principal.tenant_id, models.Program.active.is_(True))
        .order_by(models.Program.created_at, models.Program.id)
    ).all()
    return [
        ProgramOut(id=p.id, slug=p.slug, name=p.name, name_ur=p.name_ur, active=p.active, rule_version=_brief(active_rule_version(db, p.id)))
        for p in programs
    ]


# --- reading ---------------------------------------------------------------------------------------------


def load_owned(db: Session, ctx: PersonContext, application_id: UUID, *, lock: bool = False) -> models.Application:
    query = select(models.Application).where(
        models.Application.id == application_id,
        models.Application.tenant_id == ctx.tenant_id,
        models.Application.person_id == ctx.person_id,
    )
    application = db.scalars(query.with_for_update() if lock else query).first()
    if application is None:
        raise NotFound("We could not find that application.")
    return application


def form_of(application: models.Application) -> ApplicationFormV1:
    return ApplicationFormV1.model_validate(application.form or {})


def latest_checks(db: Session, application_id: UUID) -> list[tuple[models.Document, DocumentCheck | None, bool]]:
    """Each document of the application with its newest check (None when unchecked) and whether it is an ID mismatch."""
    documents = db.scalars(
        select(models.Document)
        .where(models.Document.application_id == application_id)
        .order_by(models.Document.created_at, models.Document.id)
    ).all()
    out: list[tuple[models.Document, DocumentCheck | None, bool]] = []
    for document in documents:
        row = db.scalars(
            select(models.DocumentCheck)
            .where(models.DocumentCheck.document_id == document.id)
            .order_by(models.DocumentCheck.created_at.desc(), models.DocumentCheck.id)
            .limit(1)
        ).first()
        check: DocumentCheck | None = None
        if row is not None:
            try:
                check = DocumentCheck.model_validate(row.result)
            except ValidationError:
                log.warning("stored document check does not match the contract; treating it as unchecked")
        out.append((document, check, document.status == "mismatch"))
    return out


def latest_decision(db: Session, application_id: UUID) -> models.Decision | None:
    return db.scalars(
        select(models.Decision)
        .where(models.Decision.application_id == application_id)
        .order_by(models.Decision.created_at.desc(), models.Decision.id.desc())
        .limit(1)
    ).first()


def decision_view(db: Session, decision: models.Decision | None) -> DecisionUserView | None:
    """Track B's citizen view of a stored decision; without Track B, the same fields read from the row."""
    if decision is None:
        return None
    user_view = hooks.optional(hooks.USER_VIEW)
    if user_view is not None:
        try:
            view = user_view(decision)
            return view if isinstance(view, DecisionUserView) else DecisionUserView.model_validate(view)
        except Exception:  # noqa: BLE001
            log.exception("user_view failed; reading the stored explanation instead")
    version = db.get(models.RuleVersion, decision.rule_version_id)
    try:
        return DecisionUserView(
            decision_id=str(decision.id), outcome=decision.outcome, route=decision.route,
            explanation=Explanation.model_validate(decision.explanation), rule_version_no=version.version_no if version else 0,
            decided_at=_iso(decision.created_at),
        )  # fmt: skip
    except ValidationError:
        log.warning("stored decision explanation does not match the contract")
        return None


def _timeline(db: Session, application: models.Application) -> list[Any]:
    decisions = db.execute(
        select(models.Decision.created_at, models.Decision.outcome)
        .where(models.Decision.application_id == application.id)
        .order_by(models.Decision.created_at, models.Decision.id)
    ).all()
    payments = db.execute(
        select(models.Payment.updated_at, models.Payment.status)
        .where(models.Payment.application_id == application.id)
        .order_by(models.Payment.created_at, models.Payment.id)
    ).all()
    return build_timeline(
        created_at=application.created_at, submitted_at=application.submitted_at, status=application.status,
        updated_at=application.updated_at, decisions=[DecisionEvent(at=d.created_at, outcome=d.outcome) for d in decisions],
        payments=[PaymentEvent(at=p.updated_at, status=p.status) for p in payments],
        in_review_without_decision=application.status == "in_review" and not decisions,
    )  # fmt: skip


def _program_names(db: Session, program_ids: set[UUID]) -> dict[UUID, str]:
    if not program_ids:
        return {}
    rows = db.execute(select(models.Program.id, models.Program.name).where(models.Program.id.in_(program_ids))).all()
    return {r.id: r.name for r in rows}


def _summary_fields(application: models.Application, program_name: str) -> dict[str, Any]:
    return {
        "id": application.id,
        "person_id": application.person_id,
        "program_id": application.program_id,
        "program_name": program_name,
        "status": application.status,
        "tracking_code": application.tracking_code,
        "tracking_symbols": symbols_for(application.tracking_code),
        "version": application.version,
        "updated_at": _iso(application.updated_at),
    }


def application_out(db: Session, application: models.Application, *, decision: models.Decision | None = None) -> ApplicationOut:
    form = form_of(application)
    version = active_rule_version(db, application.program_id)
    documents: list[DocumentCitizenView] = [
        citizen_view(str(doc.id), doc.kind, check, identity_mismatch=doc.status in ("mismatch", "unbound"))  # type: ignore[arg-type]
        for doc, check, _ in latest_checks(db, application.id)
    ]
    names = _program_names(db, {application.program_id})
    return ApplicationOut(
        **_summary_fields(application, names.get(application.program_id, "")),
        form=form,
        missing_fields=missing_fields(form, version.dsl if version else None),
        documents=documents,
        decision=decision_view(db, decision or latest_decision(db, application.id)),
        timeline=_timeline(db, application),
    )


def _encode_cursor(application: models.Application) -> str:
    raw = f"{application.created_at.astimezone(UTC).isoformat()}|{application.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, _, ident = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        return datetime.fromisoformat(at), UUID(ident)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Unprocessable("The page cursor is not valid. Start from the first page.", code="invalid_cursor") from exc


def list_applications(db: Session, ctx: PersonContext, *, cursor: str | None, limit: int) -> ApplicationList:
    require_consent_for_helper_read(db, ctx, action="application.list")
    limit = max(1, min(limit or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE))
    query = select(models.Application).where(
        models.Application.tenant_id == ctx.tenant_id, models.Application.person_id == ctx.person_id
    )
    if cursor:
        at, ident = _decode_cursor(cursor)
        query = query.where(tuple_(models.Application.created_at, models.Application.id) < tuple_(at, ident))
    rows = db.scalars(query.order_by(models.Application.created_at.desc(), models.Application.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    names = _program_names(db, {a.program_id for a in page})
    items = [ApplicationSummary(**_summary_fields(a, names.get(a.program_id, ""))) for a in page]
    if ctx.via_helper:  # a helper's read shows in the person's access log
        record_view(db, ctx.principal, ctx.person_id, what="applications_list")
        db.commit()
    return ApplicationList(items=items, next_cursor=_encode_cursor(page[-1]) if len(rows) > limit else None)


def get_application(db: Session, ctx: PersonContext, application_id: UUID) -> ApplicationOut:
    application = load_owned(db, ctx, application_id)
    require_consent_for_helper_read(db, ctx, action="application.read")
    out = application_out(db, application)
    if ctx.via_helper:
        record_view(db, ctx.principal, ctx.person_id, what="application", ref_id=application.id)
        db.commit()
    return out


# --- writing ---------------------------------------------------------------------------------------------


def _allocate_tracking_code(tenant_id: UUID) -> str:
    """A tracking code no other application in the department uses.

    The caller's own context cannot see other people's applications, so this one narrow existence check
    runs in the system context. It reads a count and nothing else.
    """
    with system_session() as sdb:
        for _ in range(25):
            code = format_tracking(new_tracking_number())
            taken = sdb.scalar(
                select(func.count())
                .select_from(models.Application)
                .where(models.Application.tenant_id == tenant_id, models.Application.tracking_code == code)
            )
            if not taken:
                return code
    raise ServiceUnavailable("Could not give this application a tracking code. Try again.", code="tracking_code_exhausted")


def _by_client_op(db: Session, ctx: PersonContext, client_op_id: str) -> models.Application | None:
    return db.scalars(
        select(models.Application).where(
            models.Application.tenant_id == ctx.tenant_id,
            models.Application.person_id == ctx.person_id,
            models.Application.client_op_id == client_op_id,
        )
    ).first()


CLOSED_STATUSES = ("rejected", "withdrawn")


def _refuse_second_open_application(db: Session, ctx: PersonContext, program_id: UUID) -> None:
    """One open application per person and program: a second one could be paid twice.

    A person may apply again after a rejection or a withdrawal. The database enforces the same rule with a
    partial unique index (migration 0004), so two requests racing each other cannot both succeed.
    """
    open_one = db.scalar(
        select(models.Application).where(
            models.Application.tenant_id == ctx.tenant_id, models.Application.person_id == ctx.person_id,
            models.Application.program_id == program_id, models.Application.status.notin_(CLOSED_STATUSES),
        ).limit(1)
    )  # fmt: skip
    if open_one is not None:
        raise Conflict(
            "You already have an application for this program.", code="application_exists",
            extra={"application_id": str(open_one.id), "application_status": open_one.status},
        )  # fmt: skip


def _constraint(exc: IntegrityError) -> str:
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    return str(getattr(diag, "constraint_name", "") or "")


def create_core(db: Session, ctx: PersonContext, body: ApplicationCreate, *, application_id: UUID | None = None,
                audit_extra: dict[str, Any] | None = None) -> tuple[models.Application, bool]:  # fmt: skip
    """Create without committing (the caller commits). Returns (application, created).

    The same client_op_id always returns the application it first created. Offline clients may choose the
    application id (`application_id`), so later queued edits can refer to it; an id that is already taken
    by someone else is refused, never reused.
    """
    form = body.form or ApplicationFormV1()
    require_consent(db, ctx, action="application.create", scopes=scopes_needed(set_fields(form)))
    existing = _by_client_op(db, ctx, body.client_op_id)
    if existing is not None:
        return existing, False
    if application_id is not None:
        same = db.get(models.Application, application_id)  # RLS: only rows this person may read are visible
        if same is not None and same.tenant_id == ctx.tenant_id and same.person_id == ctx.person_id:
            return same, False

    program = db.get(models.Program, body.program_id)
    if program is None or program.tenant_id != ctx.tenant_id or not program.active:
        raise NotFound("That program is not open in this department.", code="program_not_found")
    raise_if_errors(check_client_form(form))
    _refuse_second_open_application(db, ctx, program.id)
    form.form_version = "v1"  # the server owns the schema version
    if form.phone.value:
        form.phone.value = normalise_mock_phone(form.phone.value)
    plans.consume(db, ctx.tenant_id, "applications")  # 429 plan_limit_reached at the creation point; nothing the person typed is lost

    application = models.Application(
        id=application_id or uuid.uuid4(), tenant_id=ctx.tenant_id, program_id=program.id, person_id=ctx.person_id,
        status="draft", form=form.model_dump(mode="json"), form_version=form.form_version, version=1,
        client_op_id=body.client_op_id, submitted_via="helper" if ctx.via_helper else "web",
        tracking_code=_allocate_tracking_code(ctx.tenant_id), created_by=ctx.user_id,
    )  # fmt: skip
    try:
        with db.begin_nested():  # a savepoint: losing a race must not undo the caller's other work
            db.add(application)
            db.flush()
    except IntegrityError as exc:
        existing = _by_client_op(db, ctx, body.client_op_id)
        if existing is not None:  # a concurrent retry of the same create won the race
            return existing, False
        _refuse_second_open_application(db, ctx, program.id)  # another create for this person and program won
        if application_id is not None and "pkey" in _constraint(exc):
            raise Conflict("That application id is already used. Generate a new one.", code="entity_id_taken") from None
        raise Conflict("That client_op_id is already used. Generate a new one.", code="client_op_id_conflict") from None
    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.created", object_type="application", object_id=application.id,
        details={"program_id": str(program.id), "tracking_code": application.tracking_code, "fields": set_fields(form),
                 **(audit_extra or {})},
        **ctx.audit_fields(),
    )  # fmt: skip
    return application, True


def create_application(db: Session, ctx: PersonContext, body: ApplicationCreate) -> tuple[ApplicationOut, bool]:
    """Returns (application, created). The same client_op_id always returns the application it first created."""
    application, created = create_core(db, ctx, body)
    if created:
        db.commit()
    return application_out(db, application), created


def patch_core(db: Session, ctx: PersonContext, application_id: UUID, body: ApplicationPatch) -> models.Application:
    """Strict optimistic lock (409 `version_conflict`); does not commit. Offline sync merges field by field instead."""
    application = load_owned(db, ctx, application_id, lock=True)
    fields = [name for name in body.form_patch if name != "language"]
    require_consent(db, ctx, action="application.update", scopes=scopes_needed(fields))
    if application.status not in EDITABLE:
        raise Conflict("This application can no longer be changed.", code="not_editable", extra={"status": application.status})
    current = form_of(application)
    if body.base_version != application.version:
        raise Conflict(
            "Someone saved this application after you opened it. Here is the latest version.",
            code="version_conflict",
            extra={"current_version": application.version, "form": current.model_dump(mode="json")},
        )
    if not body.form_patch:
        return application
    updated = merge_client_patch(current, body.form_patch)
    application.form = updated.model_dump(mode="json")
    application.version += 1
    audit.write(
        db, tenant_id=ctx.tenant_id, action="application.updated", object_type="application", object_id=application.id,
        details={"fields": sorted(body.form_patch), "version": application.version}, **ctx.audit_fields(),
    )  # fmt: skip
    return application


def patch_application(db: Session, ctx: PersonContext, application_id: UUID, body: ApplicationPatch) -> ApplicationOut:
    application = patch_core(db, ctx, application_id, body)
    db.commit()
    return application_out(db, application)
