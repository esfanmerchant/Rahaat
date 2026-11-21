"""Jobs dashboard for admins: what is queued, running, retrying or dead, and a retry for dead jobs."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, Strict
from app.core import audit
from app.core.deps import Principal, get_db
from app.core.errors import Conflict, NotFound
from app.core.policy import Policy
from app.db import models
from app.modules.cases import paging
from app.modules.jobs import service

router = APIRouter(prefix="/v1/admin/jobs", tags=["admin: jobs"])
_read = Policy("jobs:read", ["admin"], description="The background job queue of this department")
_retry = Policy("jobs:retry", ["admin"], description="Give a dead job a fresh set of attempts (audited)")

JobStatus = Literal["queued", "running", "done", "failed", "dead", "cancelled"]


class JobOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    run_at: str | None = None
    last_error: str | None = None
    created_at: str
    finished_at: str | None = None


class JobList(Page):
    items: list[JobOut]
    counts: dict[str, int] = Field(default_factory=dict, description="Jobs per status in this department")


class JobRetryIn(Strict):
    reason: str = Field(min_length=5, max_length=500)


def _out(job: models.Job) -> JobOut:
    return JobOut(
        id=job.id, kind=job.kind, status=job.status, priority=job.priority, attempts=job.attempts, max_attempts=job.max_attempts,
        run_at=paging.iso(job.run_at), last_error=job.last_error, created_at=paging.iso(job.created_at) or "",
        finished_at=paging.iso(job.finished_at),
    )  # fmt: skip


@router.get("", response_model=JobList, summary="Background jobs, newest first")
def list_jobs(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    status: JobStatus | None = Query(None),
    kind: str | None = Query(None, max_length=48),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=200),
) -> JobList:
    query = select(models.Job).where(models.Job.tenant_id == principal.tenant_id)
    if status:
        query = query.where(models.Job.status == status)
    if kind:
        query = query.where(models.Job.kind == kind)
    if cursor:
        created, job_id = paging.decode(cursor, size=2)
        query = query.where(tuple_(models.Job.created_at, models.Job.id) < tuple_(paging.as_datetime(created), paging.as_uuid(job_id)))
    rows = db.scalars(query.order_by(models.Job.created_at.desc(), models.Job.id.desc()).limit(limit + 1)).all()
    counts: dict[str, Any] = dict(
        db.execute(select(models.Job.status, func.count()).where(models.Job.tenant_id == principal.tenant_id).group_by(models.Job.status)).all()  # type: ignore[arg-type,unused-ignore]
    )
    page = rows[:limit]
    next_cursor = paging.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return JobList(items=[_out(j) for j in page], counts={k: int(v) for k, v in counts.items()}, next_cursor=next_cursor)


@router.post("/{job_id}/retry", response_model=JobOut, summary="Retry a dead job")
def retry_job(job_id: uuid.UUID, body: JobRetryIn, principal: Principal = Depends(_retry), db: Session = Depends(get_db)) -> JobOut:
    job = db.scalar(select(models.Job).where(models.Job.id == job_id, models.Job.tenant_id == principal.tenant_id).with_for_update())
    if job is None:
        raise NotFound("No such job.")
    if job.status != "dead":
        raise Conflict("Only a dead job can be retried.", code="job_not_dead")
    service.requeue_dead(db, job)
    audit.write(db, tenant_id=principal.tenant_id, action="job.requeued", actor_id=principal.user_id, actor_role=principal.role,
                object_type="job", object_id=job.id, reason=body.reason, details={"kind": job.kind})  # fmt: skip
    db.commit()
    return _out(job)
