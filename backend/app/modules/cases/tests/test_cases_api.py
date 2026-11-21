"""The officer's case API: queue, detail with handoff, actions and their effects, isolation, consent."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.contracts.decision import TypedDecision
from app.contracts.documents import DocumentCheck, OcrResult, QrResult
from app.core.db import system_session
from app.db import models
from app.modules.cases import testing as t
from app.modules.cases.service import open_case
from app.modules.integrations.testing import fresh_mocks


@pytest.fixture()
def mocks() -> Iterator[None]:
    with fresh_mocks():
        yield


def _document_check(tenant_id: uuid.UUID, person_id: uuid.UUID, application_id: uuid.UUID) -> None:
    with system_session() as db:
        document = models.Document(id=uuid.uuid4(), tenant_id=tenant_id, application_id=application_id, person_id=person_id, kind="rahat_id",
                                   storage_key=uuid.uuid4().hex, sha256="0" * 64, mime="image/png", size_bytes=1000)  # fmt: skip
        db.add(document)
        db.flush()
        check = DocumentCheck(
            document_id=str(document.id), kind="rahat_id", quality="ok", qr=QrResult(found=True, signature_valid=True),
            ocr=OcrResult(available=False), model_version="test",
            authenticity=TypedDecision(choice="genuine", confidence=0.97, route="auto", model_version="test"),
        )  # fmt: skip
        db.add(models.DocumentCheck(id=uuid.uuid4(), tenant_id=tenant_id, document_id=document.id, person_id=person_id, quality="ok",
                                    authenticity="genuine", confidence=0.97, result=check.model_dump(mode="json")))  # fmt: skip


def _act(client: Any, headers: dict[str, str], case_id: Any, action: str, reason: str = "Checked the documents carefully", **extra: Any) -> Any:
    return client.post(f"/v1/cases/{case_id}/actions", headers=headers, json={"action": action, "reason": reason, **extra})


def test_queue_detail_and_who_may_see_it(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.headers(client, factory.account(tenant, "officer"))
    ids = t.review_case(tenant.id, citizen.person_id)
    _document_check(tenant.id, citizen.person_id, ids["application_id"])
    with system_session() as db:  # a second, more urgent and less sure case
        urgent = open_case(db, tenant_id=tenant.id, kind="document_review", opened_reason="forgery_suspected", person_id=citizen.person_id,
                           confidence=0.4, priority=10).id  # fmt: skip

    by_priority = client.get("/v1/cases", headers=officer).json()["items"]
    assert [c["id"] for c in by_priority] == [str(urgent), str(ids["case_id"])]
    assert by_priority[1]["subject_name"] == "Test Citizen" and by_priority[1]["sla_due_at"]
    by_age = client.get("/v1/cases", headers=officer, params={"sort": "age", "limit": 1}).json()
    assert [c["id"] for c in by_age["items"]] == [str(ids["case_id"])] and by_age["next_cursor"]
    second_page = client.get("/v1/cases", headers=officer, params={"sort": "age", "limit": 1, "cursor": by_age["next_cursor"]}).json()
    assert [c["id"] for c in second_page["items"]] == [str(urgent)] and second_page["next_cursor"] is None
    assert client.get("/v1/cases", headers=officer, params={"kind": "document_review"}).json()["items"][0]["id"] == str(urgent)
    assert client.get("/v1/cases", headers=officer, params={"cursor": "garbage!"}).status_code == 422

    detail = client.get(f"/v1/cases/{ids['case_id']}", headers=officer).json()
    assert detail["handoff"]["resolving_proof"] == "income_proof" and detail["form"]["household_size"]["value"] == 5
    assert [c["quality"] for c in detail["document_checks"]] == ["ok"]
    assert detail["decision"] is None  # Track B's trace_view is not in this tree yet: null, never a fake
    assert detail["allowed_actions"] == ["approve", "reject", "request_proof", "escalate"]
    assert [e["event"] for e in detail["events"]] == ["created"]

    citizen_h = factory.headers(client, citizen)
    assert client.get("/v1/cases", headers=citizen_h).status_code == 403
    assert client.get(f"/v1/cases/{ids['case_id']}", headers=citizen_h).status_code == 403
    outsider = factory.headers(client, factory.account(factory.tenant(), "officer"))
    assert client.get(f"/v1/cases/{ids['case_id']}", headers=outsider).status_code == 404
    assert _act(client, outsider, ids["case_id"], "approve").status_code == 404
    assert client.get("/v1/cases", headers=outsider).json()["items"] == []


def test_approve_pays_and_records_the_review(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer_account = factory.account(tenant, "officer")
    officer = factory.headers(client, officer_account)
    ids = t.review_case(tenant.id, citizen.person_id)

    assert _act(client, officer, ids["case_id"], "approve", reason="ok").status_code == 422  # a real reason is required
    assert client.post(f"/v1/cases/{ids['case_id']}/actions", headers=officer,
                       json={"action": "approve", "reason": "fine by me", "case_ids": ["x"]}).status_code == 422  # no bulk, no extras
    client.get(f"/v1/cases/{ids['case_id']}", headers=officer)
    done = _act(client, officer, ids["case_id"], "approve", reason="Income confirmed by the union council letter")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "resolved" and done.json()["allowed_actions"] == []
    assert t.get(models.Application, ids["application_id"]).status == "paid"
    (payment,) = t.rows(models.Payment, models.Payment.application_id == ids["application_id"])
    assert payment.status == "settled" and payment.amount_pkr == 12_000 and payment.requested_by == officer_account.user_id
    (review,) = t.rows(models.HumanReview, models.HumanReview.case_id == ids["case_id"])
    assert review.action == "approve" and review.overrode_ai is False and review.review_seconds is not None
    assert review.decision_id == ids["decision_id"]
    sent = sorted({n.template for n in t.rows(models.Notification, models.Notification.tenant_id == tenant.id)})
    assert sent == ["approved", "payment_sent"]

    again = _act(client, officer, ids["case_id"], "approve", reason="Approving a second time")
    assert again.status_code == 409 and again.json()["code"] == "illegal_transition"
    assert len(t.rows(models.Payment, models.Payment.application_id == ids["application_id"])) == 1


def test_request_proof_waits_then_comes_back_and_reject_is_an_override(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.headers(client, factory.account(tenant, "officer"))
    ids = t.review_case(tenant.id, citizen.person_id)

    waiting = _act(client, officer, ids["case_id"], "request_proof", reason="Need a salary slip for this month")
    assert waiting.status_code == 200 and waiting.json()["status"] == "waiting_proof"
    assert t.get(models.Application, ids["application_id"]).status == "needs_proof"
    (note,) = [n for n in t.rows(models.Notification, models.Notification.tenant_id == tenant.id) if n.channel == "in_app"]
    assert note.template == "proof_needed" and "آمدنی" in note.body and note.lang == "ur"
    assert _act(client, officer, ids["case_id"], "request_proof").status_code == 409

    with system_session() as db:  # the citizen sent proof and the pipeline decided again: same case, back to a person
        again = open_case(db, tenant_id=tenant.id, kind="application_review", opened_reason="proof_received",
                          application_id=ids["application_id"], person_id=citizen.person_id, decision_id=ids["decision_id"])  # fmt: skip
        assert again.id == ids["case_id"] and again.status == "in_review"
        t_app = db.get(models.Application, ids["application_id"])
        assert t_app is not None
        t_app.status = "in_review"

    rejected = _act(client, officer, ids["case_id"], "reject", reason="The slip shows Rs 45,000 a month")
    assert rejected.status_code == 200 and rejected.json()["status"] == "resolved"
    assert t.get(models.Application, ids["application_id"]).status == "rejected"
    reviews = {r.action: r for r in t.rows(models.HumanReview, models.HumanReview.case_id == ids["case_id"])}
    assert reviews["reject"].overrode_ai is True  # the engine leaned to "eligible"
    events = [e["event"] for e in rejected.json()["events"]]
    assert events == ["created", "request_proof", "proof_received", "reject"]

    reopened = client.post(f"/v1/cases/{ids['case_id']}/reopen", headers=officer, json={"reason": "Citizen appealed in person"})
    assert reopened.status_code == 200 and reopened.json()["status"] == "open"
    assert t.get(models.Application, ids["application_id"]).status == "in_review"


def test_escalate_assign_and_notes(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.headers(client, factory.account(tenant, "officer"))
    senior = factory.account(tenant, "officer")
    admin = factory.account(tenant, "admin")
    ids = t.review_case(tenant.id, citizen.person_id)

    escalated = _act(client, officer, ids["case_id"], "escalate", reason="Possible fraud ring, needs a senior")
    assert escalated.json()["status"] == "escalated" and escalated.json()["priority"] == 20 and escalated.json()["assigned_to"] is None
    bad = client.post(f"/v1/cases/{ids['case_id']}/assign", headers=officer, json={"assignee_id": str(admin.user_id), "reason": "admin look"})
    assert bad.status_code == 422 and bad.json()["code"] == "bad_assignee"
    given = client.post(f"/v1/cases/{ids['case_id']}/assign", headers=officer, json={"assignee_id": str(senior.user_id), "reason": "senior on duty"})
    assert given.status_code == 200 and given.json()["status"] == "assigned" and given.json()["assigned_to"] == str(senior.user_id)
    noted = client.post(f"/v1/cases/{ids['case_id']}/notes", headers=officer, json={"body": "Called the citizen; phone was off."})
    assert noted.status_code == 201 and noted.json()["notes"][0]["body"] == "Called the citizen; phone was off."
    mine = client.get("/v1/cases", headers=factory.headers(client, senior), params={"assignee": "me"}).json()["items"]
    assert [c["id"] for c in mine] == [str(ids["case_id"])]


def test_withdrawn_consent_blocks_the_officer_and_the_attempt_is_audited(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.headers(client, factory.account(tenant, "officer"))
    ids = t.review_case(tenant.id, citizen.person_id)
    assert client.get(f"/v1/cases/{ids['case_id']}", headers=officer).status_code == 200

    t.set_consent(citizen.person_id, "withdrawn")
    blocked = client.get(f"/v1/cases/{ids['case_id']}", headers=officer)
    assert blocked.status_code == 403 and blocked.json()["code"] == "consent_required"
    assert _act(client, officer, ids["case_id"], "approve", reason="Trying to approve anyway").status_code == 403
    denied = t.rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "access.denied")
    assert len(denied) == 2 and {d.reason for d in denied} == {"consent_required"} and {d.object_type for d in denied} == {"application"}
    assert t.rows(models.Payment, models.Payment.application_id == ids["application_id"]) == []
    listed = client.get("/v1/cases", headers=officer).json()["items"]
    assert listed[0]["id"] == str(ids["case_id"]) and listed[0]["subject_name"] is None  # the queue keeps the case, not the name
