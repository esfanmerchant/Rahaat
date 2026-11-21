"""The Postgres job queue (DECISIONS 3): enqueue, claim with SKIP LOCKED, run, retry with backoff, dead-letter.

    enqueue(db, tenant_id=..., kind="notification.sms", payload={...}, person_id=...)

Handlers are registered by kind. A module adds its own in `app/modules/<name>/job_handlers.py`, defining
`HANDLERS = {"kind": fn}` and optionally `ON_FAILURE = {"kind": fn}`; they are discovered on first use.

Claiming is the only step that uses the system context (the dispatcher must see every tenant's queue).
The job itself runs in its own tenant with role `worker`, so Row Level Security and consent still apply:
a job for a person who has withdrawn consent cannot read that person. The handler's work and the "done"
mark commit in one transaction, so a job's effects happen once even if the worker dies in between.
"""

from __future__ import annotations

import importlib
import pkgutil
import socket
import threading
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.context import note_job_enqueued
from app.core.db import RlsContext, session_scope, system_session
from app.core.logging import get_logger, redact
from app.db import models

log = get_logger("rahat.jobs")


@dataclass(frozen=True)
class JobContext:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1
    max_attempts: int = 5
    person_id: uuid.UUID | None = None


Handler = Callable[[Session, JobContext], None]
FailureHook = Callable[[Session, JobContext, str, bool], None]  # (db, job, error, dead)


class RetryLater(Exception):  # noqa: N818  (a signal, not an error)
    """An expected, temporary problem (a service is down). The job is retried with backoff."""


class PermanentJobError(Exception):
    """Retrying cannot help (bad payload, consent withdrawn). The job goes straight to the dead letter."""


BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 600.0
LEASE = timedelta(minutes=5)  # a job still "running" after this is assumed abandoned and is claimed again

_handlers: dict[str, Handler] = {}
_on_failure: dict[str, FailureHook] = {}
_discovered = False
_discover_lock = threading.Lock()


def register(kind: str, handler: Handler, *, on_failure: FailureHook | None = None) -> None:
    _handlers[kind] = handler
    if on_failure is not None:
        _on_failure[kind] = on_failure


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    with _discover_lock:
        if _discovered:
            return
        import app.modules as modules_pkg

        for module in sorted(pkgutil.iter_modules(modules_pkg.__path__), key=lambda m: m.name):
            name = f"app.modules.{module.name}.job_handlers"
            try:
                found = importlib.import_module(name)
            except ModuleNotFoundError as exc:
                if exc.name == name:
                    continue
                raise
            for kind, handler in getattr(found, "HANDLERS", {}).items():
                _handlers.setdefault(kind, handler)
            for kind, hook in getattr(found, "ON_FAILURE", {}).items():
                _on_failure.setdefault(kind, hook)
        _discovered = True


def known_kinds() -> list[str]:
    _discover()
    return sorted(_handlers)


def retry_delay(attempts: int) -> timedelta:
    """5 s, 10 s, 20 s ... capped at 10 minutes."""
    return timedelta(seconds=min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1))))


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    kind: str,
    payload: dict[str, Any] | None = None,
    person_id: uuid.UUID | None = None,
    priority: int = 50,
    run_at: datetime | None = None,
    max_attempts: int = 5,
) -> models.Job:
    """Add a job in the caller's transaction: it becomes visible to workers when the caller commits."""
    job = models.Job(
        id=uuid.uuid4(), tenant_id=tenant_id, kind=kind, payload=dict(payload or {}), status="queued", priority=priority,
        attempts=0, max_attempts=max(1, max_attempts), run_at=run_at, person_id=person_id,
    )  # fmt: skip
    db.add(job)
    db.flush()
    note_job_enqueued()  # inline mode: the request drains due jobs once it has committed
    return job


def default_worker_id() -> str:
    return f"{socket.gethostname()[:40]}-{threading.get_ident() % 100000}"


def claim(
    *,
    worker_id: str,
    limit: int = 1,
    now: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
    kinds: Iterable[str] | None = None,
) -> list[JobContext]:
    """Take up to `limit` due jobs. SKIP LOCKED means two workers never take the same row."""
    now = now or _now()
    due = or_(
        and_(models.Job.status == "queued", or_(models.Job.run_at.is_(None), models.Job.run_at <= now)),
        and_(models.Job.status == "running", models.Job.locked_at < now - LEASE),
    )
    query = select(models.Job).where(due)
    if tenant_id is not None:
        query = query.where(models.Job.tenant_id == tenant_id)
    if kinds is not None:
        query = query.where(models.Job.kind.in_(list(kinds)))
    query = query.order_by(models.Job.priority, models.Job.created_at, models.Job.id).limit(limit).with_for_update(skip_locked=True)
    with system_session() as db:  # the dispatcher: the one place that looks across tenants
        jobs = db.scalars(query).all()
        claimed = []
        for job in jobs:
            job.status = "running"
            job.attempts = (job.attempts or 0) + 1
            job.locked_at = _now()
            job.locked_by = worker_id
            claimed.append(
                JobContext(id=job.id, tenant_id=job.tenant_id, kind=job.kind, payload=dict(job.payload or {}), attempts=job.attempts,
                           max_attempts=job.max_attempts, person_id=job.person_id)  # fmt: skip
            )
    return claimed


def _worker_ctx(job: JobContext) -> RlsContext:
    return RlsContext(role="worker", tenant_id=job.tenant_id)


def run_one(job: JobContext, *, worker_id: str) -> str:
    """Run one claimed job. Returns done, retry or dead."""
    _discover()
    handler = _handlers.get(job.kind)
    try:
        with session_scope(_worker_ctx(job)) as db:
            if handler is None:
                raise PermanentJobError(f"no handler for job kind {job.kind!r}")
            handler(db, job)
            db.execute(
                update(models.Job)
                .where(models.Job.id == job.id, models.Job.locked_by == worker_id)
                .values(status="done", finished_at=_now(), last_error=None, locked_at=None)
            )
        return "done"
    except Exception as exc:  # noqa: BLE001  (every failure is recorded; none may kill the worker)
        dead = isinstance(exc, PermanentJobError) or job.attempts >= job.max_attempts
        error = redact(f"{type(exc).__name__}: {exc}")[:500]
        if isinstance(exc, RetryLater | PermanentJobError):
            log.info("job %s (%s) attempt %d: %s", job.id, job.kind, job.attempts, error)
        else:
            log.exception("job %s (%s) attempt %d failed", job.id, job.kind, job.attempts)
        _record_failure(job, error, dead=dead, worker_id=worker_id)
        return "dead" if dead else "retry"


def _record_failure(job: JobContext, error: str, *, dead: bool, worker_id: str) -> None:
    now = _now()
    values: dict[str, Any] = {"status": "dead" if dead else "queued", "last_error": error, "locked_at": None, "locked_by": None}
    if dead:
        values["finished_at"] = now
    else:
        values["run_at"] = now + retry_delay(job.attempts)
    try:
        with session_scope(_worker_ctx(job)) as db:
            db.execute(update(models.Job).where(models.Job.id == job.id, models.Job.locked_by == worker_id).values(**values))
            hook = _on_failure.get(job.kind)
            if hook is not None:
                try:
                    with db.begin_nested():
                        hook(db, job, error, dead)
                except Exception:  # noqa: BLE001
                    log.exception("failure hook of job kind %s failed", job.kind)
    except Exception:  # noqa: BLE001
        log.exception("could not record the failure of job %s", job.id)


def run_pending(
    *,
    max_jobs: int = 100,
    now: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
    kinds: Iterable[str] | None = None,
    worker_id: str | None = None,
) -> int:
    """Run due jobs one by one until none is left or `max_jobs` ran. Synchronous: tests call this directly."""
    worker = worker_id or default_worker_id()
    kinds_list = list(kinds) if kinds is not None else None
    processed = 0
    while processed < max_jobs:
        batch = claim(worker_id=worker, limit=1, now=now, tenant_id=tenant_id, kinds=kinds_list)
        if not batch:
            break
        for job in batch:
            run_one(job, worker_id=worker)
            processed += 1
    return processed


def cancel_for_person(db: Session, *, tenant_id: uuid.UUID, person_id: uuid.UUID) -> int:
    """Cancel a person's queued jobs, for example when they withdraw consent. Returns how many."""
    result = db.execute(
        update(models.Job)
        .where(models.Job.tenant_id == tenant_id, models.Job.person_id == person_id, models.Job.status == "queued")
        .values(status="cancelled", finished_at=_now(), last_error="cancelled: consent withdrawn")
    )
    return int(getattr(result, "rowcount", 0) or 0)


def requeue_dead(db: Session, job: models.Job) -> models.Job:
    """An admin gives a dead job a fresh set of attempts."""
    job.status = "queued"
    job.attempts = 0
    job.run_at = None
    job.finished_at = None
    job.locked_at = None
    job.locked_by = None
    db.flush()
    return job
