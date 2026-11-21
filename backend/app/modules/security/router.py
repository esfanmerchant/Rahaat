"""Security self-checks for the Challenge Lab and the department's security events (admins and auditors)."""

from __future__ import annotations

from datetime import UTC
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core import audit
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.db import models
from app.modules.security import probes

router = APIRouter(prefix="/v1/admin/security", tags=["admin: security"])
_probe = Policy("security:probe", ["admin", "auditor"], cost=5,
                description="Run the read-only database security probes; every run is audited")  # fmt: skip
_events = Policy("security:events", ["admin", "auditor"], description="Security events of this department")


class ProbeOut(BaseModel):
    name: str
    claim: str
    passed: bool
    sql: str = Field(description="The exact statement the database was asked to run, as the API's own role")
    evidence: dict[str, Any]


class ProbeRunOut(BaseModel):
    passed: bool
    audit_seq: int = Field(description="The audit row that records this run")
    probes: list[ProbeOut]


class SecurityEventOut(BaseModel):
    id: UUID
    kind: str
    severity: str
    created_at: str
    details: dict[str, Any]


@router.post("/probes", response_model=ProbeRunOut, summary="Try to get around Row Level Security with raw SQL, and show the refusals")
def run_probes(principal: Principal = Depends(_probe), db: Session = Depends(get_db)) -> ProbeRunOut:
    results = probes.run_all(tenant_id=principal.tenant_id, user_id=principal.user_id, role=principal.role)
    passed = all(r.passed for r in results)
    row = audit.write(db, tenant_id=principal.tenant_id, action="security.probes_run", actor_id=principal.user_id, actor_role=principal.role,
                      result="ok" if passed else "failed", details={r.name: r.passed for r in results})  # fmt: skip
    db.commit()
    return ProbeRunOut(passed=passed, audit_seq=row.seq, probes=[ProbeOut(name=r.name, claim=r.claim, passed=r.passed, sql=r.sql,
                                                                         evidence=r.evidence) for r in results])  # fmt: skip


@router.get("/events", response_model=list[SecurityEventOut], summary="Refused key use, refresh-token reuse and rejected uploads")
def list_events(
    principal: Principal = Depends(_events),
    db: Session = Depends(get_db),
    kind: str | None = Query(None, max_length=48),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> list[SecurityEventOut]:
    query = select(models.SecurityEvent).where(models.SecurityEvent.tenant_id == principal.tenant_id)
    if kind:
        query = query.where(models.SecurityEvent.kind == kind)
    rows = db.scalars(query.order_by(models.SecurityEvent.created_at.desc(), models.SecurityEvent.id).limit(limit)).all()
    return [SecurityEventOut(id=r.id, kind=r.kind, severity=r.severity, created_at=r.created_at.astimezone(UTC).isoformat(timespec="seconds"),
                             details=dict(r.details or {})) for r in rows]  # fmt: skip
