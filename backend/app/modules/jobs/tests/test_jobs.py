"""The Postgres job queue: worker context, retry and dead letter, SKIP LOCKED, and the admin view."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.db import open_session, system_session
from app.db import models
from app.modules.jobs import service
from app.modules.jobs.service import JobContext, RetryLater

FAR_FUTURE = datetime.now(UTC) + timedelta(days=1)


def _enqueue(tenant_id: uuid.UUID, kind: str, count: int = 1, **kwargs: Any) -> list[uuid.UUID]:
    ids = []
    with system_session() as db:
        for n in range(count):
            ids.append(service.enqueue(db, tenant_id=tenant_id, kind=kind, payload={"n": n}, **kwargs).id)
    return ids


def _job(job_id: uuid.UUID) -> models.Job:
    with system_session() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        db.expunge(job)
        return job


def test_backoff_grows_and_is_capped() -> None:
    assert [service.retry_delay(n).total_seconds() for n in (1, 2, 3)] == [5, 10, 20]
    assert service.retry_delay(30).total_seconds() == service.BACKOFF_MAX_SECONDS


def test_a_job_runs_in_its_own_tenant_as_worker(factory: Any) -> None:
    tenant = factory.tenant()
    kind = f"test.ctx.{uuid.uuid4().hex[:8]}"
    seen: dict[str, Any] = {}

    def handler(db: Session, job: JobContext) -> None:
        row = db.execute(text("SELECT current_setting('app.role', true), current_setting('app.tenant_id', true)")).one()
        seen.update(role=row[0], tenant=row[1], payload=job.payload)

    service.register(kind, handler)
    (job_id,) = _enqueue(tenant.id, kind)
    assert service.run_pending(tenant_id=tenant.id) == 1
    assert seen == {"role": "worker", "tenant": str(tenant.id), "payload": {"n": 0}}
    job = _job(job_id)
    assert job.status == "done" and job.attempts == 1 and job.finished_at is not None


def test_a_failing_job_is_retried_with_backoff_then_dead_lettered(factory: Any) -> None:
    tenant = factory.tenant()
    kind = f"test.fail.{uuid.uuid4().hex[:8]}"
    failures: list[tuple[int, bool]] = []

    def handler(db: Session, job: JobContext) -> None:
        raise RetryLater("the service is down")

    def on_failure(db: Session, job: JobContext, error: str, dead: bool) -> None:
        failures.append((job.attempts, dead))

    service.register(kind, handler, on_failure=on_failure)
    (job_id,) = _enqueue(tenant.id, kind, max_attempts=3)
    assert service.run_pending(tenant_id=tenant.id) == 1
    job = _job(job_id)
    assert job.status == "queued" and job.attempts == 1 and job.run_at is not None and job.run_at > datetime.now(UTC)
    assert service.run_pending(tenant_id=tenant.id) == 0, "not due yet: the backoff must be respected"
    assert service.run_pending(tenant_id=tenant.id, now=FAR_FUTURE) == 2  # attempts 2 and 3
    job = _job(job_id)
    assert job.status == "dead" and job.attempts == 3 and "service is down" in (job.last_error or "")
    assert failures == [(1, False), (2, False), (3, True)]


def test_unknown_kind_goes_straight_to_the_dead_letter(factory: Any) -> None:
    tenant = factory.tenant()
    (job_id,) = _enqueue(tenant.id, f"test.unknown.{uuid.uuid4().hex[:8]}")
    service.run_pending(tenant_id=tenant.id)
    assert _job(job_id).status == "dead"


def test_skip_locked_never_hands_out_a_row_another_worker_holds(factory: Any) -> None:
    tenant = factory.tenant()
    kind = f"test.lock.{uuid.uuid4().hex[:8]}"
    first, second = _enqueue(tenant.id, kind, count=2)
    holder = open_session(service.RlsContext(role="system"))
    try:
        held = holder.scalars(
            select(models.Job).where(models.Job.id == first).with_for_update(skip_locked=True)
        ).all()  # worker A is in the middle of claiming the first job
        assert [j.id for j in held] == [first]
        taken = service.claim(worker_id="worker-b", limit=5, tenant_id=tenant.id, kinds=[kind])
        assert [j.id for j in taken] == [second]
    finally:
        holder.rollback()
        holder.close()


def test_two_workers_never_process_the_same_job(factory: Any) -> None:
    tenant = factory.tenant()
    kind = f"test.race.{uuid.uuid4().hex[:8]}"
    processed: list[tuple[str, uuid.UUID]] = []
    lock = threading.Lock()

    def handler(db: Session, job: JobContext) -> None:
        time.sleep(0.02)  # long enough for the other worker to try the same rows
        with lock:
            processed.append((threading.current_thread().name, job.id))

    service.register(kind, handler)
    ids = _enqueue(tenant.id, kind, count=12)
    threads = [threading.Thread(target=service.run_pending, kwargs={"tenant_id": tenant.id, "kinds": [kind], "worker_id": f"w{n}"},
                                name=f"w{n}") for n in range(2)]  # fmt: skip
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    done_ids = [job_id for _, job_id in processed]
    assert sorted(done_ids) == sorted(ids) and len(set(done_ids)) == len(done_ids)
    assert {name for name, _ in processed} == {"w0", "w1"}, "both workers should have taken part"
    assert all(_job(job_id).attempts == 1 for job_id in ids)


def test_admin_sees_the_queue_and_can_retry_a_dead_job(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    officer = factory.headers(client, factory.account(tenant, "officer"))
    (job_id,) = _enqueue(tenant.id, f"test.unknown.{uuid.uuid4().hex[:8]}")
    service.run_pending(tenant_id=tenant.id)

    assert client.get("/v1/admin/jobs", headers=officer).status_code == 403
    listing = client.get("/v1/admin/jobs", headers=admin, params={"status": "dead"}).json()
    assert [item["id"] for item in listing["items"]] == [str(job_id)] and listing["counts"] == {"dead": 1}
    assert client.post(f"/v1/admin/jobs/{job_id}/retry", headers=admin, json={}).status_code == 422  # a reason is required
    retried = client.post(f"/v1/admin/jobs/{job_id}/retry", headers=admin, json={"reason": "handler deployed now"})
    assert retried.status_code == 200 and retried.json()["status"] == "queued" and retried.json()["attempts"] == 0
    assert client.post(f"/v1/admin/jobs/{job_id}/retry", headers=admin, json={"reason": "again please"}).status_code == 409

    other_admin = factory.headers(client, factory.account(factory.tenant(), "admin"))
    assert client.post(f"/v1/admin/jobs/{job_id}/retry", headers=other_admin, json={"reason": "not mine"}).status_code == 404
