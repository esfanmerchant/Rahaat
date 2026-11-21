"""Inline jobs (JOBS_MODE=inline): requests drain what they queued, and the cron endpoint is guarded."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import reset_settings_cache
from app.core.db import system_session
from app.db import models
from app.modules.jobs import inline, service
from app.modules.jobs.service import JobContext


@contextmanager
def env(**values: str) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    reset_settings_cache()
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        reset_settings_cache()


def _status(job_id: uuid.UUID) -> str:
    with system_session() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        return job.status


def _kind(done: list[str]) -> str:
    kind = f"test.inline.{uuid.uuid4().hex[:8]}"

    def handler(db: Session, job: JobContext) -> None:
        done.append(job.kind)

    service.register(kind, handler)
    return kind


def _queue_app(tenant_id: uuid.UUID, kind: str, ids: list[uuid.UUID]) -> TestClient:
    """The real middleware around one route that queues a job and commits, as an endpoint would."""
    from app.main import create_app

    app: FastAPI = create_app()

    @app.post("/test-queue")
    def queue() -> dict[str, str]:
        with system_session() as db:
            ids.append(service.enqueue(db, tenant_id=tenant_id, kind=kind, payload={}).id)
        return {"ok": "queued"}

    return TestClient(app)


def test_drain_runs_due_jobs_within_the_caps(factory: Any) -> None:
    tenant = factory.tenant()
    done: list[str] = []
    kind = _kind(done)
    with system_session() as db:
        ids = [service.enqueue(db, tenant_id=tenant.id, kind=kind).id for _ in range(3)]
    with env(JOBS_MODE="inline"):
        assert inline.drain(max_jobs=2) >= 2
        inline.drain()
    assert {_status(i) for i in ids} == {"done"}


def test_a_request_that_queues_a_job_has_it_done_before_the_response_ends(factory: Any) -> None:
    tenant = factory.tenant()
    done: list[str] = []
    kind = _kind(done)
    ids: list[uuid.UUID] = []
    with env(JOBS_MODE="inline"):
        client = _queue_app(tenant.id, kind, ids)
        assert client.post("/test-queue").status_code == 200
    assert _status(ids[0]) == "done" and done == [kind]


def test_in_thread_mode_the_request_leaves_the_job_for_the_worker(factory: Any) -> None:
    tenant = factory.tenant()
    done: list[str] = []
    kind = _kind(done)
    ids: list[uuid.UUID] = []
    with env(JOBS_MODE="thread"):
        client = _queue_app(tenant.id, kind, ids)
        assert client.post("/test-queue").status_code == 200
    assert _status(ids[0]) == "queued" and done == []
    service.run_pending(tenant_id=tenant.id)  # tidy up


def test_inline_mode_starts_no_worker_thread() -> None:
    from app.modules.jobs import lifecycle

    with env(JOBS_MODE="inline", WORKER_ENABLED="true"):
        lifecycle.startup()
        assert lifecycle._worker is None
    with env(JOBS_MODE="thread", WORKER_ENABLED="false"):
        lifecycle.startup()
        assert lifecycle._worker is None


def test_the_cron_endpoint_needs_the_secret(client: TestClient, factory: Any) -> None:
    url = "/v1/admin/jobs/drain"
    with env(CRON_SECRET=""):
        assert client.get(url, headers={"Authorization": "Bearer anything"}).status_code == 404, "off while no secret is set"
    secret = "cron-secret-for-tests-0123456789"
    tenant = factory.tenant()
    done: list[str] = []
    kind = _kind(done)
    with system_session() as db:
        job_id = service.enqueue(db, tenant_id=tenant.id, kind=kind).id
    with env(CRON_SECRET=secret):
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get(url, headers={"Authorization": secret}).status_code == 401, "the Bearer prefix is required"
        assert _status(job_id) == "queued"
        ok = client.get(url, headers={"Authorization": f"Bearer {secret}"})
        assert ok.status_code == 200 and ok.json()["ran"] >= 1
    assert _status(job_id) == "done"
