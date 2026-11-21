"""notify(), SMS delivery through the job queue, retries and dead letter, consent, and the read endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.db import RlsContext, session_scope, system_session
from app.db import models
from app.mocks.state import STATE
from app.modules.integrations.testing import fresh_mocks
from app.modules.jobs.service import run_pending
from app.modules.notifications.service import SMS_JOB, notify

LATER = datetime.now(UTC) + timedelta(days=1)


@pytest.fixture()
def mocks() -> Iterator[None]:
    with fresh_mocks():
        yield


def _notify(tenant_id: Any, person_id: Any, template: str = "approved", **payload: Any) -> list[Any]:
    with session_scope(RlsContext(role="worker", tenant_id=tenant_id)) as db:
        rows = notify(db, tenant_id=tenant_id, person_id=person_id, template=template, payload=payload or {"amount_pkr": 12000})
        return [row.id for row in rows]


def _rows(tenant_id: Any) -> dict[str, models.Notification]:
    with system_session() as db:
        rows = db.scalars(select(models.Notification).where(models.Notification.tenant_id == tenant_id)).all()
        for row in rows:
            db.expunge(row)
        return {row.channel: row for row in rows}


def test_notify_delivers_in_app_and_sms_with_verify_codes(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _notify(tenant.id, citizen.person_id, tracking_code="R-10001", amount_pkr=12000)
    rows = _rows(tenant.id)
    assert rows["in_app"].status == "sent" and rows["sms"].status == "queued"
    assert rows["in_app"].verify_code != rows["sms"].verify_code
    assert rows["sms"].body.endswith(f"کوڈ {rows['sms'].verify_code}") and "12,000" in rows["sms"].body

    assert run_pending(tenant_id=tenant.id, kinds=[SMS_JOB]) == 1
    assert _rows(tenant.id)["sms"].status == "sent"
    assert [m["body"] for m in STATE.sms_outbox] == [rows["sms"].body]
    assert STATE.sms_outbox[0]["to"] == citizen.identifier

    mine = client.get("/v1/notifications", headers=factory.headers(client, citizen)).json()["items"]
    assert [m["template"] for m in mine] == ["approved"] and mine[0]["verify_code"] == rows["in_app"].verify_code

    admin = factory.headers(client, factory.account(tenant, "admin"))
    outbox = {item["channel"]: item for item in client.get("/v1/outbox", headers=admin).json()["items"]}
    assert outbox["sms"]["destination"] == "•" * 9 + citizen.identifier[-3:] and citizen.identifier not in str(outbox)
    assert client.get("/v1/outbox", headers=factory.headers(client, citizen)).status_code == 403

    genuine = client.post("/v1/notifications/verify", json={"code": str(rows["sms"].verify_code).lower()}).json()
    assert genuine["genuine"] is True and genuine["template"] == "approved" and genuine["department"] == tenant.name
    assert client.post("/v1/notifications/verify", json={"code": "ZZZZZZ"}).json() == {
        "genuine": False, "template": None, "channel": None, "department": None, "sent_at": None}  # fmt: skip


def test_sms_failure_is_retried_then_dead_lettered_and_in_app_still_arrives(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    STATE.set_control("sms", latency_ms=None, failure_rate=None, down=True)
    _notify(tenant.id, citizen.person_id, "proof_needed", proof_kind="income_proof")

    assert run_pending(tenant_id=tenant.id, kinds=[SMS_JOB]) == 1
    sms = _rows(tenant.id)["sms"]
    assert sms.status == "queued" and sms.attempts == 1 and "unavailable" in (sms.last_error or "")
    with system_session() as db:
        job = db.scalar(select(models.Job).where(models.Job.tenant_id == tenant.id, models.Job.kind == SMS_JOB))
        assert job is not None and job.status == "queued" and job.run_at is not None

    run_pending(tenant_id=tenant.id, kinds=[SMS_JOB], now=LATER)  # the remaining attempts, all failing
    rows = _rows(tenant.id)
    assert rows["sms"].status == "failed" and rows["sms"].attempts == 4
    assert rows["in_app"].status == "sent"
    with system_session() as db:
        job = db.scalar(select(models.Job).where(models.Job.tenant_id == tenant.id, models.Job.kind == SMS_JOB))
        assert job is not None and job.status == "dead" and job.attempts == 4
        failed = db.scalar(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "notification.failed"))
        assert failed is not None
    assert len(STATE.sms_outbox) == 0


def test_a_queued_sms_is_not_sent_after_consent_is_withdrawn(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _notify(tenant.id, citizen.person_id, "person_will_check", tracking_code="R-2")
    with system_session() as db:
        db.execute(update(models.Consent).where(models.Consent.person_id == citizen.person_id)
                   .values(status="withdrawn", withdrawn_at=datetime.now(UTC)))  # fmt: skip
    run_pending(tenant_id=tenant.id, kinds=[SMS_JOB])
    sms = _rows(tenant.id)["sms"]
    assert sms.status == "failed" and "person_not_readable" in (sms.last_error or "")
    assert len(STATE.sms_outbox) == 0, "the worker runs under RLS, so it cannot read a person who took consent back"
