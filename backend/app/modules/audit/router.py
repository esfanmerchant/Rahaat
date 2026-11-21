"""Read the audit log and verify its hash chain. Auditors and admins only; nobody can write through here."""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core import audit
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.db import models

router = APIRouter(prefix="/v1/audit", tags=["audit"])
_read = Policy("audit:read", ["auditor", "admin"], description="Read-only access to the tenant's audit trail")


class AuditEntry(BaseModel):
    seq: int
    ts: str
    actor_type: str
    actor_id: str | None
    actor_role: str | None
    acting_for_person_id: str | None
    action: str
    object_type: str | None
    object_id: str | None
    result: str
    reason: str | None
    input_hash: str | None
    model_version: str | None
    rule_version_id: str | None
    request_id: str | None
    details: dict[str, Any]
    prev_hash: str
    hash: str


class AuditPage(BaseModel):
    items: list[AuditEntry]
    next_cursor: str | None = None


class ChainOut(BaseModel):
    ok: bool
    checked: int
    head_seq: int
    head_hash: str
    first_broken_seq: int | None = None
    problem: str | None = None


def _entry(row: models.AuditLog) -> AuditEntry:
    return AuditEntry(
        seq=row.seq, ts=row.ts.astimezone(UTC).isoformat(timespec="milliseconds"), actor_type=row.actor_type,
        actor_id=row.actor_id, actor_role=row.actor_role,
        acting_for_person_id=str(row.acting_for_person_id) if row.acting_for_person_id else None,
        action=row.action, object_type=row.object_type, object_id=row.object_id, result=row.result, reason=row.reason,
        input_hash=row.input_hash, model_version=row.model_version,
        rule_version_id=str(row.rule_version_id) if row.rule_version_id else None, request_id=row.request_id,
        details=json.loads(row.details or "{}"), prev_hash=row.prev_hash, hash=row.hash,
    )  # fmt: skip


@router.get("", response_model=AuditPage, summary="Audit trail, newest first")
def list_audit(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: int | None = Query(None, ge=1, description="Return entries with seq below this"),
    action: str | None = Query(None, max_length=64, description="Exact action, or a prefix ending in '.'"),
    result: str | None = Query(None, pattern="^(ok|denied|failed|abstained|refused|blocked|flag|flagged|mask)$"),
    actor_id: str | None = Query(None, max_length=64),
    object_id: str | None = Query(None, max_length=64),
) -> AuditPage:
    query = select(models.AuditLog).where(models.AuditLog.tenant_id == principal.tenant_id)
    if cursor:
        query = query.where(models.AuditLog.seq < cursor)
    if action:
        query = query.where(models.AuditLog.action.startswith(action, autoescape=True) if action.endswith(".")
                            else models.AuditLog.action == action)  # fmt: skip
    if result:
        query = query.where(models.AuditLog.result == result)
    if actor_id:
        query = query.where(models.AuditLog.actor_id == actor_id)
    if object_id:
        query = query.where(models.AuditLog.object_id == object_id)
    rows = db.scalars(query.order_by(models.AuditLog.seq.desc()).limit(limit + 1)).all()
    items = [_entry(r) for r in rows[:limit]]
    return AuditPage(items=items, next_cursor=str(items[-1].seq) if len(rows) > limit else None)


@router.get("/verify", response_model=ChainOut, summary="Recompute the hash chain and report the first broken row")
def verify(principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> ChainOut:
    report = audit.verify_chain(db, principal.tenant_id)
    audit.write(
        db, tenant_id=principal.tenant_id, action="audit.chain_verified", actor_id=principal.user_id,
        actor_role=principal.role, result="ok" if report.ok else "failed",
        details={"checked": report.checked, "first_broken_seq": report.first_broken_seq},
    )  # fmt: skip
    db.commit()
    return ChainOut(
        ok=report.ok, checked=report.checked, head_seq=report.head_seq, head_hash=report.head_hash,
        first_broken_seq=report.first_broken_seq, problem=report.problem,
    )  # fmt: skip
