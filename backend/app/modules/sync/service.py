"""`POST /v1/sync`: apply operations that one device queued while it had no signal (PLAN 6.9).

* Ops are applied in order. Each op runs in its own transaction together with its `sync_ops` row, so an op
  and the record that it was applied are committed or rolled back together.
* `(device_id, op_id)` is applied at most once. A repeat returns the stored result as `duplicate`, so the
  same batch sent twice over a flaky connection creates nothing twice. An advisory lock per op serialises
  two copies of one op that arrive at the same moment, and the unique index on `sync_ops` backs it up.
* Each op is authorised again under the permissions and consent that hold when it is applied, not when it
  was queued: the person context (delegation, scope and, for a helper, the switch ticket) and the consent
  are checked for every op, so a withdrawn consent rejects ops still waiting on the phone.
* A rejection the device can clear by itself (a helper's ticket ran out, the op names another family) is
  not recorded and comes back `retryable`. Every other result is final and stored.
* An edit made against an old version is merged field by field (`merge.py`).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.api import ApplicationCreate
from app.core import audit
from app.core.deps import Principal
from app.core.errors import AppError, Conflict, Unprocessable
from app.core.logging import get_logger
from app.core.mockdata import normalise_mock_phone
from app.db import models
from app.modules.applications import pipeline
from app.modules.applications import service as applications
from app.modules.applications.forms import check_client_patch, merge_client_patch, raise_if_errors, scopes_needed
from app.modules.applications.status import EDITABLE
from app.modules.consent.rules import active_consent, require_consent
from app.modules.helpers.tickets import TICKET_DENIALS
from app.modules.people.context import PersonContext, resolve_person
from app.modules.sync import merge
from app.modules.sync.schemas import FieldConflictOut, SyncIn, SyncOpIn, SyncOpResult, SyncOut

log = get_logger("rahat.sync")

# Refusals the device can clear itself; nothing is recorded, so the same op can be sent again later.
RETRYABLE: Final[frozenset[str]] = frozenset(TICKET_DENIALS | {"wrong_person", "service_unavailable", "internal_error"})
_OP_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('sync:' || :tenant_id || ':' || :device_id || ':' || :op_id, 0))")
_CREATE_KEYS: Final = frozenset({"program_id", "form"})


def device_ref(device_id: str) -> str:
    """The device as it appears in the audit log: a short hash, not the client's own id."""
    return hashlib.sha256(f"device:{device_id}".encode()).hexdigest()[:16]


# --- stored results -----------------------------------------------------------------------------------------


def _stored(db: Session, tenant_id: UUID, device_id: str, op_id: str) -> models.SyncOp | None:
    return db.scalars(
        select(models.SyncOp).where(models.SyncOp.tenant_id == tenant_id, models.SyncOp.device_id == device_id,
                                    models.SyncOp.op_id == op_id)  # fmt: skip
    ).first()


def _lock(db: Session, tenant_id: UUID, device_id: str, op_id: str) -> None:
    db.execute(_OP_LOCK, {"tenant_id": str(tenant_id), "device_id": device_id, "op_id": op_id})


def _duplicate(op: SyncOpIn, stored: models.SyncOp, principal: Principal, person_id: UUID, *, reveal: bool = True) -> SyncOpResult:
    """The stored answer to an op sent again. `reveal` False drops what the server held (conflict values)."""
    if stored.created_by != principal.user_id:
        # Someone else's op id on the same device id: never show another person's result.
        return SyncOpResult(op_id=op.op_id, status="rejected", reason="op_id_taken", detail="Use a new op_id for this change.")
    if stored.person_id != person_id:
        # The helper's own op, sent while switched to another family: switch back to that family and send it again.
        return SyncOpResult(op_id=op.op_id, status="rejected", reason="wrong_person", retryable=True,
                            detail="This change belongs to another family. Switch to that family, then sync again.")  # fmt: skip
    result = dict(stored.result or {})
    result.pop("op_id", None)
    result.pop("status", None)
    if not reveal:
        result.pop("conflicts", None)
        result.pop("extra", None)
    return SyncOpResult(op_id=op.op_id, status="duplicate", original_status=stored.status, **result)


def _payload(op: SyncOpIn) -> dict[str, Any]:
    return op.model_dump(mode="json", exclude={"op_id"})


def _rejected(op: SyncOpIn, exc: AppError) -> SyncOpResult:
    code = exc.code
    extra = {k: v for k, v in (exc.extra or {}).items() if k not in ("form",)}  # the full form is not repeated here
    return SyncOpResult(op_id=op.op_id, status="rejected", reason=code, detail=exc.detail, retryable=code in RETRYABLE,
                        entity_id=op.entity_id, extra=extra)  # fmt: skip


def _store(db: Session, principal: Principal, device_id: str, op: SyncOpIn, person_id: UUID | None, result: SyncOpResult) -> None:
    db.add(models.SyncOp(
        tenant_id=principal.tenant_id, device_id=device_id, op_id=op.op_id, person_id=person_id, kind=op.kind,
        entity_id=result.entity_id or op.entity_id, payload=_payload(op), status=result.status,
        result=result.model_dump(mode="json", exclude={"op_id", "status", "original_status"}), created_by=principal.user_id,
    ))  # fmt: skip


def _store_rejection(db: Session, principal: Principal, device_id: str, op: SyncOpIn, person_id: UUID | None,
                     result: SyncOpResult) -> SyncOpResult:  # fmt: skip
    """A final rejection is recorded, so a repeat gets the same answer. Runs in a fresh transaction."""
    if result.retryable:
        return result
    try:
        _lock(db, principal.tenant_id, device_id, op.op_id)
        stored = _stored(db, principal.tenant_id, device_id, op.op_id)
        if stored is not None:  # another copy of this op finished first
            db.commit()
            return _duplicate(op, stored, principal, person_id) if person_id else result
        _store(db, principal, device_id, op, person_id, result)
        db.commit()
    except IntegrityError:
        db.rollback()
    return result


# --- the three kinds of op ---------------------------------------------------------------------------------


def _create(db: Session, ctx: PersonContext, op: SyncOpIn) -> SyncOpResult:
    unknown = sorted(set(op.patch) - _CREATE_KEYS)
    if unknown or "program_id" not in op.patch:
        errors = [{"field": f"patch.{k}", "message": "not allowed", "code": "unknown_field"} for k in unknown]
        raise Unprocessable("A create needs patch.program_id and may carry patch.form, nothing else.", code="invalid_op",
                            extra={"errors": errors})  # fmt: skip
    try:
        body = ApplicationCreate(program_id=op.patch["program_id"], client_op_id=op.op_id, form=op.patch.get("form"))
    except ValidationError as exc:
        errors = [{"field": "patch." + ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "invalid"),
                   "code": e.get("type", "invalid")} for e in exc.errors()]  # fmt: skip
        raise Unprocessable("Check the fields listed in 'errors'.", code="invalid_form", extra={"errors": errors}) from None
    application, created = applications.create_core(db, ctx, body, application_id=op.entity_id, audit_extra={"via": "sync"})
    return SyncOpResult(op_id=op.op_id, status="applied", entity_id=application.id, version=application.version,
                        application_status=application.status, tracking_code=application.tracking_code,
                        extra={} if created else {"already_existed": True})  # fmt: skip


def _normalise(name: str, value: Any) -> Any:
    if name in ("phone", "payout_account") and isinstance(value, str):
        return normalise_mock_phone(value) or value
    return value


def changed_fields(db: Session, application: models.Application, base_version: int) -> set[str]:
    """Fields that edits after `base_version` changed, from the application's own audit rows."""
    rows = db.scalars(
        select(models.AuditLog.details).where(
            models.AuditLog.tenant_id == application.tenant_id, models.AuditLog.object_type == "application",
            models.AuditLog.object_id == str(application.id), models.AuditLog.action.in_(merge.FIELD_CHANGE_ACTIONS),
        )
    ).all()  # fmt: skip
    return merge.fields_changed_after(rows, base_version)


def _patch(db: Session, ctx: PersonContext, op: SyncOpIn) -> SyncOpResult:
    if op.entity_id is None or op.base_version is None:
        raise Unprocessable("An edit needs entity_id and base_version.", code="invalid_op")
    application = applications.load_owned(db, ctx, op.entity_id, lock=True)
    require_consent(db, ctx, action="application.update", scopes=scopes_needed([n for n in op.patch if n != "language"]))
    if application.status not in EDITABLE:
        raise Conflict("This application can no longer be changed.", code="not_editable", extra={"status": application.status})
    if op.base_version > application.version:
        raise Unprocessable("base_version is newer than the application.", code="bad_base_version",
                            extra={"current_version": application.version})  # fmt: skip
    current = applications.form_of(application)
    # Locked (verified) fields become conflicts below; every other problem is a repairable rejection of the whole op.
    raise_if_errors([e for e in check_client_patch(op.patch, current) if e.code != "field_locked"])
    changed = set() if op.base_version == application.version else changed_fields(db, application, op.base_version)
    locked = {name for name in op.patch if name != "language" and getattr(current, name).verified}
    plan = merge.plan_patch(current.model_dump(mode="json"), op.patch, changed=changed, locked=locked, normalise=_normalise)
    if plan.accepted:
        application.form = merge_client_patch(current, plan.accepted).model_dump(mode="json")
        application.version += 1
        audit.write(
            db, tenant_id=ctx.tenant_id, action="application.updated", object_type="application", object_id=application.id,
            details={"fields": sorted(plan.accepted), "version": application.version, "via": "sync", "base_version": op.base_version,
                     "conflicts": sorted(c.field for c in plan.conflicts)},  # fmt: skip
            **ctx.audit_fields(),
        )  # fmt: skip
    return SyncOpResult(
        op_id=op.op_id, status="conflict" if plan.conflicts else "applied", entity_id=application.id, version=application.version,
        application_status=application.status, tracking_code=application.tracking_code, applied_fields=sorted(plan.accepted),
        unchanged_fields=sorted(plan.unchanged), conflicts=[FieldConflictOut(**c.as_dict()) for c in plan.conflicts],
    )  # fmt: skip


def _submit(db: Session, ctx: PersonContext, op: SyncOpIn) -> SyncOpResult:
    if op.entity_id is None:
        raise Unprocessable("A submit needs entity_id.", code="invalid_op")
    out = pipeline.submit(db, ctx, op.entity_id)  # commits when it submits; a repeat returns the first result
    return SyncOpResult(op_id=op.op_id, status="applied", entity_id=out.application.id, version=out.application.version,
                        application_status=out.application.status, tracking_code=out.application.tracking_code,
                        extra={"decision_outcome": out.decision.outcome} if out.decision else {})  # fmt: skip


_HANDLERS = {"create_application": _create, "patch_application": _patch, "submit_application": _submit}


# --- one op, then the batch ---------------------------------------------------------------------------------


def apply_op(db: Session, principal: Principal, device_id: str, op: SyncOpIn, *, acting_for: str | None,
             ticket: str | None) -> SyncOpResult:  # fmt: skip
    _lock(db, principal.tenant_id, device_id, op.op_id)
    try:
        ctx = resolve_person(db, principal, acting_for, "apply", ticket)  # authorised again, now, even for a repeat
    except AppError as exc:
        db.rollback()
        return _rejected(op, exc)  # not recorded: authorisation is checked again on every attempt
    stored = _stored(db, principal.tenant_id, device_id, op.op_id)
    if stored is not None:
        # A helper whose family has taken back its consent learns the op's fate, not what the server holds.
        reveal = not ctx.via_helper or active_consent(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id) is not None
        db.commit()  # releases the op lock
        return _duplicate(op, stored, principal, ctx.person_id, reveal=reveal)
    if op.person_id is not None and op.person_id != ctx.person_id:
        db.rollback()
        if not ctx.via_helper:  # a citizen can only ever act for themself: final
            result = SyncOpResult(op_id=op.op_id, status="rejected", reason="wrong_person", entity_id=op.entity_id,
                                  detail="You can only send your own changes.")  # fmt: skip
            return _store_rejection(db, principal, device_id, op, ctx.person_id, result)
        return SyncOpResult(op_id=op.op_id, status="rejected", reason="wrong_person", retryable=True, entity_id=op.entity_id,
                            detail="This change belongs to another family. Switch to that family, then sync again.")  # fmt: skip

    # The record of the op goes in first, so a handler that commits (submit) commits it together with its work.
    row = models.SyncOp(tenant_id=principal.tenant_id, device_id=device_id, op_id=op.op_id, person_id=ctx.person_id, kind=op.kind,
                        entity_id=op.entity_id, payload=_payload(op), status="applied", result={}, created_by=principal.user_id)  # fmt: skip
    try:
        db.add(row)
        db.flush()
        result = _HANDLERS[op.kind](db, ctx, op)
    except AppError as exc:
        db.rollback()
        return _store_rejection(db, principal, device_id, op, ctx.person_id, _rejected(op, exc))
    except IntegrityError:
        db.rollback()  # the same op was recorded by a request that got there first
        stored = _stored(db, principal.tenant_id, device_id, op.op_id)
        db.commit()
        if stored is not None:
            return _duplicate(op, stored, principal, ctx.person_id)
        raise
    row.status = result.status
    row.entity_id = result.entity_id or op.entity_id
    row.result = result.model_dump(mode="json", exclude={"op_id", "status", "original_status"})
    db.commit()
    return result


def apply_batch(db: Session, ctx: PersonContext, body: SyncIn, *, acting_for: str | None, ticket: str | None) -> SyncOut:
    principal = ctx.principal
    results: list[SyncOpResult] = []
    for op in body.ops:
        try:
            result = apply_op(db, principal, body.device_id, op, acting_for=acting_for, ticket=ticket)
        except Exception:  # noqa: BLE001  (one broken op must not lose the results of the others)
            db.rollback()
            log.exception("sync op failed unexpectedly; it can be sent again")
            result = SyncOpResult(op_id=op.op_id, status="rejected", reason="internal_error", retryable=True, entity_id=op.entity_id,
                                  detail="Something went wrong on our side. This change was not saved; send it again later.")  # fmt: skip
        results.append(result)
    counts = Counter(r.status for r in results)
    audit.write(
        db, tenant_id=principal.tenant_id, action="sync.batch_applied", object_type="device", object_id=device_ref(body.device_id),
        details={"ops": len(results), **{k: counts.get(k, 0) for k in ("applied", "duplicate", "conflict", "rejected")}},
        **ctx.audit_fields(),
    )  # fmt: skip
    db.commit()
    return SyncOut(device_id=body.device_id, person_id=ctx.person_id, results=results,
                   server_time=datetime.now(UTC).isoformat(timespec="seconds"))  # fmt: skip
