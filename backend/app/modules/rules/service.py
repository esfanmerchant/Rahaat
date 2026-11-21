"""Rule versions: draft, validate, dry run, diff, four-eyes publish, rollback. And the active pointer.

A version is immutable once it leaves `draft`: its DSL and content hash never change again. Publishing
needs a second admin who neither wrote the version nor asked for its approval. A rollback is a new version
that copies an old one and goes through the same approval. The active pointer (`rule_sets.active_version_id`)
is read inside each decision's transaction, so a publish takes effect on the very next decision.
Every step writes an audit row in the same transaction; callers commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts.decision import CostMatrix
from app.contracts.engine import DecisionInput, DecisionResult, RuleSetSnapshot
from app.core import audit
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, Unprocessable
from app.db import models
from app.modules.rules import dsl as rule_dsl
from app.modules.rules.schemas import RuleSetOut, RuleVersionOut, ValidationIssue

EDITABLE = "draft"
PENDING = "pending_approval"
PUBLISHED = "published"
RETIRED = "retired"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def snapshot(version: models.RuleVersion) -> RuleSetSnapshot:
    return RuleSetSnapshot(rule_version_id=str(version.id), version_no=version.version_no, dsl=version.dsl,
                           content_hash=version.content_hash)  # fmt: skip


def get_active(db: Session, program_id: uuid.UUID) -> RuleSetSnapshot:
    """The program's active rule version, read in the caller's transaction (no cache, nothing to restart)."""
    rule_set = db.scalar(select(models.RuleSet).where(models.RuleSet.program_id == program_id).order_by(models.RuleSet.created_at))
    if rule_set is None or rule_set.active_version_id is None:
        raise NotFound("This program has no published rules yet.", code="no_active_rules")
    version = db.get(models.RuleVersion, rule_set.active_version_id)
    if version is None:
        raise NotFound("The active rule version is missing.", code="no_active_rules")
    return snapshot(version)


def get_version_snapshot(db: Session, version_id: uuid.UUID) -> RuleSetSnapshot:
    version = db.get(models.RuleVersion, version_id)
    if version is None:
        raise NotFound("Rule version not found.", code="rule_version_not_found")
    return snapshot(version)


# --- reads ---------------------------------------------------------------------------------------------


def _version(db: Session, principal: Principal, version_id: uuid.UUID, *, lock: bool = False) -> models.RuleVersion:
    query = select(models.RuleVersion).where(models.RuleVersion.id == version_id, models.RuleVersion.tenant_id == principal.tenant_id)
    version = db.scalar(query.with_for_update() if lock else query)
    if version is None:
        raise NotFound("Rule version not found.", code="rule_version_not_found")
    return version


def _rule_set(db: Session, rule_set_id: uuid.UUID, *, lock: bool = False) -> models.RuleSet:
    query = select(models.RuleSet).where(models.RuleSet.id == rule_set_id)
    rule_set = db.scalar(query.with_for_update() if lock else query)
    if rule_set is None:
        raise NotFound("Rule set not found.", code="rule_set_not_found")
    return rule_set


def _pending_approval(db: Session, version_id: uuid.UUID) -> models.Approval | None:
    return db.scalar(
        select(models.Approval).where(
            models.Approval.subject_type == "rule_version", models.Approval.subject_id == version_id, models.Approval.status == "pending"
        )
    )


def version_out(db: Session, version: models.RuleVersion, *, active_id: uuid.UUID | None = None) -> RuleVersionOut:
    if active_id is None:
        active_id = _rule_set(db, version.rule_set_id).active_version_id
    errors = rule_dsl.validate(version.dsl)
    pending = _pending_approval(db, version.id) if version.status == PENDING else None
    return RuleVersionOut(
        id=version.id, rule_set_id=version.rule_set_id, version_no=version.version_no, status=version.status,
        is_active=version.id == active_id, dsl=version.dsl, description_en=version.description_en,
        description_ur=version.description_ur, content_hash=version.content_hash, parent_version_id=version.parent_version_id,
        created_by=version.created_by, approved_by=version.approved_by, pending_approval_id=pending.id if pending else None,
        published_at=_iso(version.published_at), created_at=_iso(version.created_at) or "", valid=not errors,
        errors=[ValidationIssue(**e.as_dict()) for e in errors],
    )  # fmt: skip


def list_sets(db: Session, principal: Principal) -> list[RuleSetOut]:
    rows = db.execute(
        select(models.RuleSet, models.Program.slug)
        .join(models.Program, models.Program.id == models.RuleSet.program_id)
        .where(models.RuleSet.tenant_id == principal.tenant_id)
        .order_by(models.RuleSet.created_at)
    ).all()
    out = []
    for rule_set, slug in rows:
        active = db.get(models.RuleVersion, rule_set.active_version_id) if rule_set.active_version_id else None
        out.append(RuleSetOut(id=rule_set.id, program_id=rule_set.program_id, program_slug=slug, name=rule_set.name,
                              active_version_id=rule_set.active_version_id, active_version_no=active.version_no if active else None))  # fmt: skip
    return out


def default_rule_set_id(db: Session, principal: Principal) -> uuid.UUID:
    first = db.scalar(select(models.RuleSet.id).where(models.RuleSet.tenant_id == principal.tenant_id).order_by(models.RuleSet.created_at))
    if first is None:
        raise NotFound("This department has no rule sets.", code="rule_set_not_found")
    return first


def list_versions(db: Session, principal: Principal, rule_set_id: uuid.UUID | None, *, limit: int,
                  before_version_no: int | None) -> tuple[list[RuleVersionOut], str | None]:  # fmt: skip
    set_id = rule_set_id or default_rule_set_id(db, principal)
    rule_set = _rule_set(db, set_id)
    query = select(models.RuleVersion).where(models.RuleVersion.rule_set_id == set_id, models.RuleVersion.tenant_id == principal.tenant_id)
    if before_version_no is not None:
        query = query.where(models.RuleVersion.version_no < before_version_no)
    rows = db.scalars(query.order_by(models.RuleVersion.version_no.desc()).limit(limit + 1)).all()
    items = [version_out(db, v, active_id=rule_set.active_version_id) for v in rows[:limit]]
    return items, str(items[-1].version_no) if len(rows) > limit else None


def get_version(db: Session, principal: Principal, version_id: uuid.UUID) -> RuleVersionOut:
    return version_out(db, _version(db, principal, version_id))


# --- drafts --------------------------------------------------------------------------------------------


def _audit(db: Session, principal: Principal, action: str, version: models.RuleVersion, *, reason: str | None = None,
           details: dict[str, Any] | None = None) -> None:  # fmt: skip
    audit.write(db, tenant_id=principal.tenant_id, action=action, actor_id=principal.user_id, actor_role=principal.role,
                object_type="rule_version", object_id=version.id, rule_version_id=version.id, reason=reason,
                details={"version_no": version.version_no, "status": version.status, **(details or {})})  # fmt: skip


def _next_version_no(db: Session, rule_set_id: uuid.UUID) -> int:
    _rule_set(db, rule_set_id, lock=True)  # serialise numbering within the rule set
    current = db.scalar(select(func.max(models.RuleVersion.version_no)).where(models.RuleVersion.rule_set_id == rule_set_id))
    return int(current or 0) + 1


def create_draft(db: Session, principal: Principal, *, parent_version_id: uuid.UUID, dsl: dict[str, Any] | None,
                 description_en: str | None, description_ur: str | None) -> RuleVersionOut:  # fmt: skip
    parent = _version(db, principal, parent_version_id)
    version = models.RuleVersion(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, rule_set_id=parent.rule_set_id,
        version_no=_next_version_no(db, parent.rule_set_id), status=EDITABLE, dsl=dsl if dsl is not None else dict(parent.dsl),
        description_en=description_en if description_en is not None else parent.description_en,
        description_ur=description_ur if description_ur is not None else parent.description_ur,
        parent_version_id=parent.id, created_by=principal.user_id, high_impact=True,
    )  # fmt: skip
    db.add(version)
    db.flush()
    _audit(db, principal, "rules.draft_created", version, details={"parent_version_id": str(parent.id), "valid": not rule_dsl.validate(version.dsl)})
    return version_out(db, version)


def update_draft(db: Session, principal: Principal, version_id: uuid.UUID, *, dsl: dict[str, Any] | None,
                 description_en: str | None, description_ur: str | None) -> RuleVersionOut:  # fmt: skip
    version = _version(db, principal, version_id, lock=True)
    if version.status != EDITABLE:
        raise Conflict("Only a draft can be edited. Published versions never change; create a new draft instead.", code="version_immutable")
    if dsl is not None:
        version.dsl = dict(dsl)
    if description_en is not None:
        version.description_en = description_en
    if description_ur is not None:
        version.description_ur = description_ur
    db.flush()
    _audit(db, principal, "rules.draft_updated", version, details={"valid": not rule_dsl.validate(version.dsl)})
    return version_out(db, version)


def validate_version(db: Session, principal: Principal, version_id: uuid.UUID) -> list[rule_dsl.DslError]:
    version = _version(db, principal, version_id)
    errors = rule_dsl.validate(version.dsl)
    _audit(db, principal, "rules.validated", version, details={"valid": not errors, "error_count": len(errors)})
    return errors


def dry_run(db: Session, principal: Principal, version_id: uuid.UUID, inp: DecisionInput) -> DecisionResult:
    """Decide one supplied input with this version. Nothing is stored except the audit row."""
    from app.modules.decision.engine import decide
    from app.modules.decision.model import get_model

    version = _version(db, principal, version_id)
    tenant = db.get(models.Tenant, principal.tenant_id)
    costs = CostMatrix.model_validate((tenant.cost_matrix if tenant else None) or {})
    result = decide(inp, snapshot(version), costs, get_model())
    _audit(db, principal, "rules.dry_run", version, details={"route": result.route, "outcome": result.outcome, "input_hash": result.input_hash})
    return result


def diff_version(
    db: Session, principal: Principal, version_id: uuid.UUID, against_id: uuid.UUID | None
) -> tuple[uuid.UUID | None, list[dict[str, Any]]]:
    version = _version(db, principal, version_id)
    if against_id is None:
        against_id = _rule_set(db, version.rule_set_id).active_version_id
    against = _version(db, principal, against_id) if against_id else None
    return (against.id if against else None), rule_dsl.diff(against.dsl if against else {}, version.dsl)


# --- approval and publication ---------------------------------------------------------------------------


def _require_valid(version: models.RuleVersion) -> None:
    errors = rule_dsl.validate(version.dsl)
    if errors:
        raise Unprocessable("The rules have errors. Fix them before asking for approval.", code="rules_invalid",
                            extra={"errors": [e.as_dict() for e in errors]})  # fmt: skip


def _open_approval(db: Session, principal: Principal, version: models.RuleVersion, reason: str, kind: str) -> models.Approval:
    approval = models.Approval(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, kind="rule_publish", subject_type="rule_version", subject_id=version.id,
        status="pending", requested_by=principal.user_id, reason=reason,
        data={"version_no": version.version_no, "content_hash": version.content_hash, "request": kind},
    )  # fmt: skip
    db.add(approval)
    db.flush()
    return approval


def request_approval(db: Session, principal: Principal, version_id: uuid.UUID, reason: str) -> RuleVersionOut:
    version = _version(db, principal, version_id, lock=True)
    if version.status != EDITABLE:
        raise Conflict(f"This version is {version.status}; only a draft can be sent for approval.", code="not_a_draft")
    _require_valid(version)
    version.status = PENDING
    version.content_hash = audit.hash_payload(version.dsl)  # frozen from here on
    db.flush()
    approval = _open_approval(db, principal, version, reason, "publish")
    _audit(db, principal, "rules.approval_requested", version, reason=reason,
           details={"approval_id": str(approval.id), "content_hash": version.content_hash})  # fmt: skip
    return version_out(db, version)


def _check_second_admin(principal: Principal, version: models.RuleVersion, approval: models.Approval | None) -> None:
    if principal.user_id in (version.created_by, approval.requested_by if approval else None):
        audit.write_independent(
            tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id, actor_role=principal.role,
            object_type="rule_version", object_id=version.id, result="denied", reason="four_eyes_required",
            details={"version_no": version.version_no},
        )  # fmt: skip
        raise Forbidden("A second admin must approve this. You wrote it or asked for its approval.", code="four_eyes_required")


def publish(db: Session, principal: Principal, version_id: uuid.UUID, reason: str) -> RuleVersionOut:
    version = _version(db, principal, version_id, lock=True)
    if version.status != PENDING:
        raise Conflict(f"This version is {version.status}; ask for approval before publishing.", code="not_pending_approval")
    approval = _pending_approval(db, version.id)
    _check_second_admin(principal, version, approval)
    _require_valid(version)
    if version.content_hash != audit.hash_payload(version.dsl):
        raise Conflict("The rules changed after approval was requested.", code="content_changed")
    rule_set = _rule_set(db, version.rule_set_id, lock=True)
    previous_id = rule_set.active_version_id
    now = datetime.now(UTC)
    if previous_id and previous_id != version.id:
        previous = db.get(models.RuleVersion, previous_id)
        if previous is not None:
            previous.status = RETIRED
    version.status = PUBLISHED
    version.approved_by = principal.user_id
    version.published_at = now
    version.effective_from = now
    rule_set.active_version_id = version.id
    if approval is not None:
        approval.status = "approved"
        approval.approver_id = principal.user_id
        approval.decided_at = now
    db.flush()
    _audit(db, principal, "rules.version_published", version, reason=reason, details={
        "content_hash": version.content_hash, "previous_version_id": str(previous_id) if previous_id else None,
        "approval_id": str(approval.id) if approval else None, "author": str(version.created_by) if version.created_by else None,
    })  # fmt: skip
    return version_out(db, version, active_id=version.id)


def reject(db: Session, principal: Principal, version_id: uuid.UUID, reason: str) -> RuleVersionOut:
    """A second admin sends a pending version back to draft."""
    version = _version(db, principal, version_id, lock=True)
    if version.status != PENDING:
        raise Conflict(f"This version is {version.status}; only a pending version can be sent back.", code="not_pending_approval")
    approval = _pending_approval(db, version.id)
    _check_second_admin(principal, version, approval)
    version.status = EDITABLE
    version.content_hash = None
    if approval is not None:
        approval.status = "rejected"
        approval.approver_id = principal.user_id
        approval.decided_at = datetime.now(UTC)
    db.flush()
    _audit(db, principal, "rules.approval_rejected", version, reason=reason)
    return version_out(db, version)


def rollback(db: Session, principal: Principal, target_version_id: uuid.UUID, reason: str) -> RuleVersionOut:
    """A new version with the rules of an earlier published one. It needs a second admin like any other."""
    target = _version(db, principal, target_version_id)
    if target.status not in (PUBLISHED, RETIRED):
        raise Conflict("You can only roll back to a version that was published before.", code="not_published_before")
    version = models.RuleVersion(
        id=uuid.uuid4(), tenant_id=principal.tenant_id, rule_set_id=target.rule_set_id,
        version_no=_next_version_no(db, target.rule_set_id), status=PENDING, dsl=dict(target.dsl),
        description_en=target.description_en, description_ur=target.description_ur, parent_version_id=target.id,
        created_by=principal.user_id, high_impact=True, content_hash=audit.hash_payload(target.dsl),
    )  # fmt: skip
    db.add(version)
    db.flush()
    approval = _open_approval(db, principal, version, reason, "rollback")
    _audit(db, principal, "rules.rollback_requested", version, reason=reason,
           details={"rollback_of": str(target.id), "rollback_of_version_no": target.version_no, "approval_id": str(approval.id)})  # fmt: skip
    return version_out(db, version)
