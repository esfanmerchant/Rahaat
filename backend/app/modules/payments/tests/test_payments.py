"""request_payment, concurrency, four-eyes approvals and rail failures, against Postgres and the mock rail."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.db import RlsContext, session_scope
from app.db import models
from app.mocks.state import STATE
from app.modules.cases import testing as t
from app.modules.integrations.testing import fresh_mocks
from app.modules.jobs.service import run_pending
from app.modules.payments.service import RELEASE_JOB, PaymentRefused, request_payment

LATER = datetime.now(UTC) + timedelta(days=1)


@pytest.fixture()
def mocks() -> Iterator[None]:
    with fresh_mocks():
        yield


def _engine_approved(tenant_id: uuid.UUID, person_id: uuid.UUID) -> dict[str, uuid.UUID]:
    program_id, version_id = t.program(tenant_id)
    application_id = t.application(tenant_id, person_id, program_id, status="approved")
    decision_id = t.decision(tenant_id, application_id, person_id, version_id, outcome="approved", route="auto")
    return {"application_id": application_id, "decision_id": decision_id}


def _request(tenant_id: uuid.UUID, person_id: uuid.UUID, ids: dict[str, uuid.UUID], amount: int = 12_000) -> uuid.UUID:
    with session_scope(RlsContext(role="worker", tenant_id=tenant_id)) as db:
        payment = request_payment(db, tenant_id=tenant_id, application_id=ids["application_id"], person_id=person_id,
                                  decision_id=ids["decision_id"], amount_pkr=amount)  # fmt: skip
        return payment.id


def test_an_engine_approval_at_or_below_the_limit_is_paid_at_once(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    ids = _engine_approved(tenant.id, citizen.person_id)
    payment_id = _request(tenant.id, citizen.person_id, ids)

    payment = t.get(models.Payment, payment_id)
    assert payment.status == "settled" and payment.rail_ref and payment.approval_id is None
    assert t.get(models.Application, ids["application_id"]).status == "paid"
    (recon,) = t.rows(models.ReconciliationItem, models.ReconciliationItem.payment_id == payment_id)
    assert recon.status == "matched" and recon.settled_pkr == 12_000
    templates = sorted(n.template for n in t.rows(models.Notification, models.Notification.tenant_id == tenant.id))
    assert templates == ["payment_sent", "payment_sent"]  # in-app and SMS
    assert _request(tenant.id, citizen.person_id, ids) == payment_id, "asking again returns the same payment"
    assert len(t.rows(models.Payment, models.Payment.application_id == ids["application_id"])) == 1
    assert len(STATE.payments) == 1


def test_two_concurrent_requests_create_one_payment(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    ids = _engine_approved(tenant.id, citizen.person_id)
    STATE.set_control("payment", latency_ms=150, failure_rate=None, down=None)  # hold the first request open
    start = threading.Barrier(2)
    results: list[uuid.UUID] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            start.wait()
            results.append(_request(tenant.id, citizen.person_id, ids))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == [] and len(results) == 2 and results[0] == results[1]
    assert len(t.rows(models.Payment, models.Payment.application_id == ids["application_id"])) == 1
    assert len(STATE.payments) == 1, "the rail was paid once"


def test_no_payment_without_an_approved_decision(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    program_id, version_id = t.program(tenant.id)
    in_review = t.application(tenant.id, citizen.person_id, program_id, status="in_review")
    decision_id = t.decision(tenant.id, in_review, citizen.person_id, version_id, outcome="approved")
    with pytest.raises(PaymentRefused):
        _request(tenant.id, citizen.person_id, {"application_id": in_review, "decision_id": decision_id})
    other = factory.account(tenant, "citizen")  # one open application per person and program
    approved_but_human = t.application(tenant.id, other.person_id, program_id, status="approved")
    needs_human = t.decision(tenant.id, approved_but_human, other.person_id, version_id, outcome="needs_human")
    with pytest.raises(PaymentRefused):
        _request(tenant.id, other.person_id, {"application_id": approved_but_human, "decision_id": needs_human})
    assert t.rows(models.Payment, models.Payment.tenant_id == tenant.id) == []


def test_above_the_limit_a_different_officer_must_release_it(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    t.set_limit(tenant.id, 10_000)
    citizen = factory.account(tenant, "citizen")
    first, second = factory.account(tenant, "officer"), factory.account(tenant, "officer")
    first_h, second_h = factory.headers(client, first), factory.headers(client, second)
    ids = t.review_case(tenant.id, citizen.person_id, payment_pkr=12_000)

    client.get(f"/v1/cases/{ids['case_id']}", headers=first_h)
    approved = client.post(f"/v1/cases/{ids['case_id']}/actions", headers=first_h,
                           json={"action": "approve", "reason": "Salary slip checked by phone with the employer"})  # fmt: skip
    assert approved.status_code == 200, approved.text
    (payment,) = t.rows(models.Payment, models.Payment.application_id == ids["application_id"])
    assert payment.status == "pending_approval" and payment.approval_id is not None
    assert t.get(models.Application, ids["application_id"]).status == "approved"
    assert len(STATE.payments) == 0, "nothing reaches the rail before the second person"

    pending = client.get("/v1/approvals", headers=second_h).json()["items"]
    assert [a["id"] for a in pending] == [str(payment.approval_id)]
    own = client.post(f"/v1/approvals/{payment.approval_id}/decide", headers=first_h, json={"approve": True, "reason": "looks fine to me"})
    assert own.status_code == 403 and own.json()["code"] == "four_eyes_same_person"
    denied = t.rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "access.denied")
    assert [d.reason for d in denied] == ["four_eyes_same_person"], "the refused attempt is on record"

    outsider = factory.headers(client, factory.account(factory.tenant(), "officer"))
    assert client.post(f"/v1/approvals/{payment.approval_id}/decide", headers=outsider,
                       json={"approve": True, "reason": "other department"}).status_code == 404  # fmt: skip
    released = client.post(f"/v1/approvals/{payment.approval_id}/decide", headers=second_h,
                           json={"approve": True, "reason": "Second check of the slip done"})  # fmt: skip
    assert released.status_code == 200 and released.json()["status"] == "approved"
    assert t.get(models.Payment, payment.id).status == "settled"
    assert t.get(models.Application, ids["application_id"]).status == "paid"
    (review,) = t.rows(models.HumanReview, models.HumanReview.case_id == ids["case_id"])
    assert review.reviewer_user_id == first.user_id and review.second_approver_id == second.user_id
    again = client.post(f"/v1/approvals/{payment.approval_id}/decide", headers=second_h, json={"approve": True, "reason": "double click"})
    assert again.status_code == 409
    listed = client.get("/v1/payments", headers=second_h).json()["items"]
    assert [(p["id"], p["status"]) for p in listed] == [(str(payment.id), "settled")]


def test_a_rail_outage_leaves_the_payment_retryable(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    ids = _engine_approved(tenant.id, citizen.person_id)
    STATE.set_control("payment", latency_ms=None, failure_rate=None, down=True)
    payment_id = _request(tenant.id, citizen.person_id, ids)
    payment = t.get(models.Payment, payment_id)
    assert payment.status == "failed" and payment.failure_reason == "rail_unavailable"
    assert t.get(models.Application, ids["application_id"]).status == "approved"
    (job,) = t.rows(models.Job, models.Job.tenant_id == tenant.id, models.Job.kind == RELEASE_JOB)
    assert job.status == "queued"
    delayed = [n.template for n in t.rows(models.Notification, models.Notification.tenant_id == tenant.id)]
    assert set(delayed) == {"payment_delayed"}

    STATE.set_control("payment", latency_ms=None, failure_rate=None, down=False)
    run_pending(tenant_id=tenant.id, kinds=[RELEASE_JOB], now=LATER)
    assert t.get(models.Payment, payment_id).status == "settled"
    assert t.get(models.Application, ids["application_id"]).status == "paid"
    assert t.get(models.Job, job.id).status == "done"


def test_the_submit_pipeline_can_pay_from_the_citizens_own_session(factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    ids = _engine_approved(tenant.id, citizen.person_id)
    ctx = RlsContext(role="citizen", tenant_id=tenant.id, user_id=citizen.user_id, person_id=citizen.person_id)
    with session_scope(ctx) as db:  # what POST /v1/applications/{id}/submit does after an auto approval
        payment = request_payment(db, tenant_id=tenant.id, application_id=ids["application_id"], person_id=citizen.person_id,
                                  decision_id=ids["decision_id"], amount_pkr=12_000)  # fmt: skip
        payment_id = payment.id
    assert t.get(models.Payment, payment_id).status == "settled"
    assert t.get(models.Application, ids["application_id"]).status == "paid"


def test_a_second_approver_can_stop_the_payment_and_the_case_reopens(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    t.set_limit(tenant.id, 5_000)
    citizen = factory.account(tenant, "citizen")
    first, second = factory.headers(client, factory.account(tenant, "officer")), factory.headers(client, factory.account(tenant, "officer"))
    ids = t.review_case(tenant.id, citizen.person_id)
    assert client.post(f"/v1/cases/{ids['case_id']}/actions", headers=first,
                       json={"action": "approve", "reason": "Looks eligible from the letter"}).status_code == 200  # fmt: skip
    (payment,) = t.rows(models.Payment, models.Payment.application_id == ids["application_id"])
    stopped = client.post(f"/v1/approvals/{payment.approval_id}/decide", headers=second,
                          json={"approve": False, "reason": "The letter is unsigned; check again"})  # fmt: skip
    assert stopped.status_code == 200 and stopped.json()["status"] == "rejected"
    assert t.get(models.Payment, payment.id).status == "cancelled"
    assert t.get(models.Application, ids["application_id"]).status == "in_review"
    assert t.get(models.Case, ids["case_id"]).status == "open"
    assert len(STATE.payments) == 0
