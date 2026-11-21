"""Appeals and complaints end to end: eligibility, the different-officer rule, overturn through payments, consent, isolation."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.db import system_session
from app.db import models
from app.modules.cases import testing as t
from app.modules.integrations.testing import fresh_mocks
from app.modules.jobs.service import run_pending
from app.modules.webhooks import rules as webhook_rules

REASON = "I disagree: my income is lower than the record says."


@pytest.fixture(autouse=True)
def _mocks() -> Iterator[None]:
    with fresh_mocks():
        yield


class Dept:
    """A department with a citizen, three officers, an auditor and an admin."""

    def __init__(self, client: Any, factory: Any) -> None:
        self.client, self.factory = client, factory
        self.tenant = factory.tenant()
        self.citizen = factory.account(self.tenant, "citizen")
        self.cit = factory.headers(client, self.citizen)
        self.officers = [factory.account(self.tenant, "officer") for _ in range(3)]
        self.o1, self.o2, self.o3 = (factory.headers(client, a) for a in self.officers)
        self.auditor = factory.headers(client, factory.account(self.tenant, "auditor"))
        self.admin = factory.headers(client, factory.account(self.tenant, "admin"))

    def rejected_by_officer(self) -> dict[str, uuid.UUID]:
        """A review case that officer 1 rejects: the application ends `rejected`."""
        ids = t.review_case(self.tenant.id, self.citizen.person_id)
        done = self.client.post(f"/v1/cases/{ids['case_id']}/actions", headers=self.o1, json={"action": "reject", "reason": "Income is above the cap"})  # noqa: E501
        assert done.status_code == 200, done.text
        return ids

    def rejected_by_engine(self) -> dict[str, uuid.UUID]:
        program_id, version_id = t.program(self.tenant.id)
        application_id = t.application(self.tenant.id, self.citizen.person_id, program_id, status="rejected")
        decision_id = t.decision(self.tenant.id, application_id, self.citizen.person_id, version_id, outcome="rejected", route="auto")
        return {"application_id": application_id, "decision_id": decision_id}

    def appeal(self, application_id: uuid.UUID, key: str | None = None, reason: str = REASON) -> Any:
        headers = {**self.cit, **({"Idempotency-Key": key} if key else {})}
        return self.client.post("/v1/appeals", headers=headers, json={"application_id": str(application_id), "reason": reason})

    def decide(self, who: dict[str, str], appeal_id: str, outcome: str, reason: str = "Looked at the papers again") -> Any:
        return self.client.post(f"/v1/appeals/{appeal_id}/decide", headers=who, json={"outcome": outcome, "reason": reason})


@pytest.fixture()
def dept(client: Any, factory: Any) -> Dept:
    return Dept(client, factory)


def _audit(tenant_id: uuid.UUID, action: str) -> list[models.AuditLog]:
    with system_session() as db:
        rows = list(db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant_id, models.AuditLog.action == action)).all())
        for row in rows:
            db.expunge(row)
        return rows


def _application(application_id: uuid.UUID) -> models.Application:
    return t.get(models.Application, application_id)


def test_the_citizen_appeals_a_rejection_and_a_different_officer_overturns_it_through_the_normal_payment_path(client: Any, dept: Dept) -> None:
    hook = client.post("/v1/admin/webhooks", headers=dept.admin, json={"url": webhook_rules.MOCK_RECEIVER_URL, "events": ["*"]}).json()
    ids = dept.rejected_by_officer()
    assert _application(ids["application_id"]).status == "rejected"

    created = dept.appeal(ids["application_id"], key="appeal-key-0001")
    assert created.status_code == 201, created.text
    appeal = created.json()
    assert appeal["status"] == "open" and appeal["status_key"] == "being_checked" and appeal["reason"] == REASON
    assert appeal["message"]["key"] == "appeal.being_checked" and "different officer" in appeal["message"]["en"] and appeal["message"]["ur"].startswith("راحت")  # noqa: E501
    replay = dept.appeal(ids["application_id"], key="appeal-key-0001")
    assert replay.status_code == 200 and replay.json()["id"] == appeal["id"], "the same Idempotency-Key returns the first appeal"
    second = dept.appeal(ids["application_id"], key="another-key-0002")
    assert second.status_code == 409 and second.json()["code"] == "appeal_already_open"

    # The officer queue: an appeal case with a handoff that says what is contested.
    with system_session() as db:
        stored = db.get(models.Appeal, uuid.UUID(appeal["id"]))
        assert stored is not None and stored.case_id is not None
        case = db.get(models.Case, stored.case_id)
        assert case is not None and case.kind == "appeal" and case.status == "open" and case.application_id == ids["application_id"]
        assert case.handoff["question"] and case.handoff["evidence"]["contested"] and case.handoff["evidence"]["citizen_reason"] == REASON
        assert case.handoff["evidence"]["original_outcome"] == "needs_human"
    queue = client.get("/v1/appeals", headers=dept.o2).json()["items"]
    assert [a["id"] for a in queue] == [appeal["id"]] and queue[0]["tracking_code"] and queue[0]["age_days"] == 0
    assert [c["kind"] for c in client.get("/v1/cases", headers=dept.o2, params={"kind": "appeal"}).json()["items"]] == ["appeal"]
    assert client.get("/v1/appeals", headers=dept.auditor).json()["items"][0]["tracking_code"] is None, "an auditor reads no person data"

    # The generic case screen cannot decide it: only the appeals endpoint, which also tells the citizen.
    generic = client.post(f"/v1/cases/{queue[0]['case_id']}/actions", headers=dept.o2, json={"action": "approve", "reason": "Skipping the check"})
    assert generic.status_code == 409 and generic.json()["code"] == "use_dedicated_endpoint"

    # Officer 1 made the first decision: the server refuses them, and the refusal stays on record.
    detail_1 = client.get(f"/v1/appeals/{appeal['id']}", headers=dept.o1).json()
    assert detail_1["can_decide"] is False and "different officer" in detail_1["cannot_decide_reason"] and detail_1["reason"] == REASON
    refused = dept.decide(dept.o1, appeal["id"], "overturned")
    assert refused.status_code == 403 and refused.json()["code"] == "appeal_same_officer"
    denied = [r for r in _audit(dept.tenant.id, "access.denied") if r.reason == "appeal_same_officer"]
    assert len(denied) == 1 and denied[0].object_id == appeal["id"] and denied[0].result == "denied"
    assert t.get(models.Appeal, uuid.UUID(appeal["id"])).status == "open" and _application(ids["application_id"]).status == "rejected"

    detail_2 = client.get(f"/v1/appeals/{appeal['id']}", headers=dept.o2).json()
    assert detail_2["can_decide"] is True and detail_2["original_outcome"] == "needs_human"
    assert dept.decide(dept.o2, appeal["id"], "overturned", reason="no").status_code == 422
    assert client.post(f"/v1/appeals/{appeal['id']}/decide", headers=dept.o2, json={"outcome": "upheld", "reason": "Fine reason here", "x": 1}).status_code == 422  # noqa: E501
    assert client.post(f"/v1/appeals/{appeal['id']}/decide", headers=dept.o2, json={"outcome": "maybe", "reason": "Fine reason here"}).status_code == 422  # noqa: E501
    decided = dept.decide(dept.o2, appeal["id"], "overturned", reason="The income paper shows she is under the cap")
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "overturned" and decided.json()["outcome"].startswith("The income paper") and decided.json()["can_decide"] is False  # noqa: E501
    assert dept.decide(dept.o3, appeal["id"], "upheld").status_code == 409, "an appeal is decided once"

    # Approval, payment and the message came from the existing services, once.
    assert _application(ids["application_id"]).status == "paid"
    payments = t.rows(models.Payment, models.Payment.application_id == ids["application_id"])
    assert len(payments) == 1 and payments[0].status == "settled" and payments[0].amount_pkr == 12_000 and payments[0].decision_id is None
    templates_sent = {n.template for n in t.rows(models.Notification, models.Notification.person_id == dept.citizen.person_id)}
    assert {"appeal_received", "appeal_overturned", "payment_sent"} <= templates_sent
    mine = client.get("/v1/me/appeals", headers=dept.cit).json()["items"][0]
    assert mine["status"] == "overturned" and mine["status_key"] == "approved_after_appeal" and "12,000" in mine["message"]["en"] and "12,000" in mine["message"]["ur"]  # noqa: E501
    assert t.get(models.Case, uuid.UUID(queue[0]["case_id"])).resolution == "overturned"
    assert len(_audit(dept.tenant.id, "appeal.opened")) == 1 and len(_audit(dept.tenant.id, "appeal.decided")) == 1
    assert _audit(dept.tenant.id, "appeal.decided")[0].reason == "The income paper shows she is under the cap"

    # Webhooks fired for the whole story, with ids and statuses only.
    run_pending(tenant_id=dept.tenant.id, kinds=["webhook.deliver"], max_jobs=200)
    deliveries = t.rows(models.WebhookDelivery, models.WebhookDelivery.webhook_id == uuid.UUID(hook["id"]))
    events = {d.event for d in deliveries}
    assert {"appeal.opened", "appeal.resolved", "case.opened", "case.resolved", "decision.made", "payment.sent", "payment.settled"} <= events
    assert all(d.status == "delivered" for d in deliveries) and all(set(d.payload) <= webhook_rules.ALLOWED_KEYS for d in deliveries)
    resolved = next(d for d in deliveries if d.event == "appeal.resolved")
    assert resolved.payload == {"appeal_id": appeal["id"], "application_id": str(ids["application_id"]), "case_id": queue[0]["case_id"], "status": "overturned"}  # noqa: E501
    assert "Test Citizen" not in json.dumps([d.payload for d in deliveries])


def test_an_overturned_appeal_above_the_limit_waits_for_a_second_approver_who_is_not_the_appeal_officer(client: Any, dept: Dept) -> None:
    t.set_limit(dept.tenant.id, 5_000)
    ids = dept.rejected_by_officer()
    appeal = dept.appeal(ids["application_id"]).json()
    assert dept.decide(dept.o2, appeal["id"], "overturned").status_code == 200
    payment = t.rows(models.Payment, models.Payment.application_id == ids["application_id"])[0]
    assert payment.status == "pending_approval" and _application(ids["application_id"]).status == "approved"
    approval = t.rows(models.Approval, models.Approval.subject_id == payment.id)[0]
    # The officer who overturned the rejection is the approver, so they cannot also release the money.
    refused = client.post(f"/v1/approvals/{approval.id}/decide", headers=dept.o2, json={"approve": True, "reason": "Releasing it now"})
    assert refused.status_code == 403 and refused.json()["code"] == "four_eyes_same_person"
    assert approval.data["excluded_approvers"].count(str(dept.officers[1].user_id)) >= 1
    released = client.post(f"/v1/approvals/{approval.id}/decide", headers=dept.o3, json={"approve": True, "reason": "Second person agrees"})
    assert released.status_code == 200
    assert _application(ids["application_id"]).status == "paid"


def test_an_upheld_appeal_keeps_the_rejection_tells_the_citizen_and_cannot_be_repeated(client: Any, dept: Dept) -> None:
    ids = dept.rejected_by_engine()
    appeal = dept.appeal(ids["application_id"]).json()
    # An engine-only decision has no officer to exclude: any officer may decide it.
    assert client.get(f"/v1/appeals/{appeal['id']}", headers=dept.o1).json()["can_decide"] is True
    assert dept.decide(dept.o1, appeal["id"], "upheld", reason="The record still shows income above the cap").status_code == 200
    assert _application(ids["application_id"]).status == "rejected" and t.rows(models.Payment, models.Payment.application_id == ids["application_id"]) == []  # noqa: E501
    assert "appeal_upheld" in {n.template for n in t.rows(models.Notification, models.Notification.person_id == dept.citizen.person_id)}
    mine = client.get("/v1/me/appeals", headers=dept.cit).json()["items"][0]
    assert mine["status"] == "upheld" and mine["status_key"] == "first_answer_stays" and "first answer stays" in mine["message"]["en"]
    assert "income above the cap" not in json.dumps(mine), "the officer's notes are not shown to the citizen"
    again = dept.appeal(ids["application_id"])
    assert again.status_code == 409 and again.json()["code"] == "appeal_already_decided"


def test_who_may_appeal_and_when(client: Any, dept: Dept, factory: Any) -> None:
    program_id, _ = t.program(dept.tenant.id)
    for status in ("in_review", "approved", "needs_proof"):
        pending = t.application(dept.tenant.id, dept.citizen.person_id, t.program(dept.tenant.id)[0], status=status)
        refused = dept.appeal(pending)
        assert refused.status_code == 409 and refused.json()["code"] == "appeal_not_applicable", status

    old = t.application(dept.tenant.id, dept.citizen.person_id, program_id, status="rejected")
    with system_session() as db:  # no engine decision on file: the window runs from the rejection (the row's last change)
        db.execute(update(models.Application).where(models.Application.id == old).values(updated_at=datetime.now(UTC) - timedelta(days=40)))
    late = dept.appeal(old)
    assert late.status_code == 409 and late.json()["code"] == "appeal_window_closed" and late.json()["window_days"] == 30

    fresh = t.application(dept.tenant.id, dept.citizen.person_id, t.program(dept.tenant.id)[0], status="rejected")
    assert dept.appeal(fresh, reason="no").status_code == 422
    assert client.post("/v1/appeals", headers=dept.cit, json={"application_id": str(fresh), "reason": REASON, "status": "overturned"}).status_code == 422  # noqa: E501
    stranger = factory.headers(client, factory.account(dept.tenant, "citizen"))
    assert client.post("/v1/appeals", headers=stranger, json={"application_id": str(fresh), "reason": REASON}).status_code == 404, "not their application"  # noqa: E501
    assert client.get("/v1/me/appeals", headers=stranger).json()["items"] == []
    assert client.post("/v1/appeals", headers=dept.o1, json={"application_id": str(fresh), "reason": REASON}).status_code == 403
    assert dept.appeal(fresh).status_code == 201


def test_withdrawn_consent_stops_officers_on_the_very_next_request(client: Any, dept: Dept) -> None:
    ids = dept.rejected_by_engine()
    appeal = dept.appeal(ids["application_id"]).json()
    assert client.get(f"/v1/appeals/{appeal['id']}", headers=dept.o2).status_code == 200
    t.set_consent(dept.citizen.person_id, "withdrawn")

    detail = client.get(f"/v1/appeals/{appeal['id']}", headers=dept.o2)
    assert detail.status_code == 403 and detail.json()["code"] == "consent_required"
    decide = dept.decide(dept.o2, appeal["id"], "overturned")
    assert decide.status_code == 403 and decide.json()["code"] == "consent_required"
    assert t.get(models.Appeal, uuid.UUID(appeal["id"])).status == "open" and _application(ids["application_id"]).status == "rejected"
    assert [r.reason for r in _audit(dept.tenant.id, "access.denied")].count("consent_required") >= 2, "denied attempts are on record"
    assert client.get("/v1/appeals", headers=dept.o2).json()["items"][0]["tracking_code"] is None, "the list no longer shows the code"
    # The person can still see their own appeal, and cannot file a new one without agreeing again.
    assert client.get("/v1/me/appeals", headers=dept.cit).json()["items"][0]["id"] == appeal["id"]
    other = t.application(dept.tenant.id, dept.citizen.person_id, t.program(dept.tenant.id)[0], status="rejected")
    refused = dept.appeal(other)
    assert refused.status_code == 409 and refused.json()["code"] == "consent_required"


def test_another_department_sees_and_changes_nothing(client: Any, dept: Dept, factory: Any) -> None:
    ids = dept.rejected_by_engine()
    appeal = dept.appeal(ids["application_id"]).json()
    case_id = str(t.get(models.Appeal, uuid.UUID(appeal["id"])).case_id)
    outsider = factory.headers(client, factory.account(factory.tenant(), "officer"))
    assert client.get("/v1/appeals", headers=outsider).json()["items"] == []
    assert client.get(f"/v1/appeals/{appeal['id']}", headers=outsider).status_code == 404
    assert dept.decide(outsider, appeal["id"], "overturned").status_code == 404
    assert client.post(f"/v1/complaints/{case_id}/resolve", headers=outsider, json={"outcome": "resolved", "reason": "Not theirs"}).status_code == 404
    assert t.get(models.Appeal, uuid.UUID(appeal["id"])).status == "open"


def test_a_complaint_becomes_a_case_the_citizen_can_follow_and_an_officer_resolves(client: Any, dept: Dept, factory: Any) -> None:
    created = client.post("/v1/complaints", headers={**dept.cit, "Idempotency-Key": "complaint-key-01"},
                          json={"category": "staff", "details": "The counter clerk asked for a fee. Call 0999-1234567."})  # fmt: skip
    assert created.status_code == 201, created.text
    complaint = created.json()
    assert complaint["category"] == "staff" and complaint["status"] == "received" and complaint["outcome"] is None
    assert complaint["message"]["en"].startswith("Rahat:") and complaint["message"]["ur"].startswith("راحت")
    replay = client.post("/v1/complaints", headers={**dept.cit, "Idempotency-Key": "complaint-key-01"}, json={"category": "staff"})
    assert replay.status_code == 200 and replay.json()["id"] == complaint["id"]
    scam = client.post("/v1/complaints", headers=dept.cit, json={"category": "scam_attempt"}).json()
    assert client.post("/v1/complaints", headers=dept.cit, json={"category": "bribery"}).status_code == 422
    assert client.post("/v1/complaints", headers=dept.cit, json={"category": "service", "owner": "x"}).status_code == 422
    assert client.post("/v1/complaints", headers=dept.cit, json={"category": "service", "details": "x" * 501}).status_code == 422

    cases = {c["id"]: c for c in client.get("/v1/cases", headers=dept.o1, params={"status": "all"}).json()["items"]}
    assert cases[complaint["id"]]["kind"] == "complaint" and cases[complaint["id"]]["priority"] == 30
    assert cases[scam["id"]]["kind"] == "scam_review" and cases[scam["id"]]["priority"] == 20, "scam reports go to the scam queue, first"
    queue = client.get("/v1/complaints", headers=dept.o1).json()["items"]
    assert [c["id"] for c in queue] == [scam["id"], complaint["id"]]
    staff_view = next(c for c in queue if c["id"] == complaint["id"])
    assert staff_view["details"].startswith("The counter clerk asked for a fee.") and "1234567" not in staff_view["details"], "phone numbers are redacted"  # noqa: E501
    assert client.get("/v1/complaints", headers=dept.cit).status_code == 403 and client.get("/v1/complaints", headers=dept.auditor).status_code == 403

    generic = client.post(f"/v1/cases/{complaint['id']}/actions", headers=dept.o1, json={"action": "approve", "reason": "Quick close"})
    assert generic.status_code == 409 and generic.json()["code"] == "use_dedicated_endpoint"
    other_citizen = factory.headers(client, factory.account(dept.tenant, "citizen"))
    assert client.get("/v1/me/complaints", headers=other_citizen).json()["items"] == []

    resolved = client.post(f"/v1/complaints/{complaint['id']}/resolve", headers=dept.o2, json={"outcome": "resolved", "reason": "Clerk was spoken to"})  # noqa: E501
    assert resolved.status_code == 200 and resolved.json()["resolution"] == "resolved" and resolved.json()["status"] == "resolved"
    assert client.post(f"/v1/complaints/{complaint['id']}/resolve", headers=dept.o2, json={"outcome": "resolved", "reason": "Again"}).status_code == 409  # noqa: E501
    closed = client.post(f"/v1/complaints/{scam['id']}/resolve", headers=dept.o2, json={"outcome": "dismissed", "reason": "Nothing we can act on"})
    assert closed.status_code == 200

    mine = {c["id"]: c for c in client.get("/v1/me/complaints", headers=dept.cit).json()["items"]}
    assert mine[complaint["id"]]["status"] == "resolved" and mine[complaint["id"]]["outcome"] == "resolved" and "took action" in mine[complaint["id"]]["message"]["en"]  # noqa: E501
    assert mine[scam["id"]]["outcome"] == "closed" and "could not change" in mine[scam["id"]]["message"]["en"]
    assert "Clerk was spoken to" not in json.dumps(mine)
    templates_sent = {n.template for n in t.rows(models.Notification, models.Notification.person_id == dept.citizen.person_id)}
    assert {"complaint_received", "complaint_resolved", "complaint_closed"} <= templates_sent
    assert {r.action for r in t.rows(models.AuditLog, models.AuditLog.tenant_id == dept.tenant.id)} >= {"complaint.filed", "case.resolved"}

    consent_gone = client.post("/v1/complaints", headers=dept.cit, json={"category": "service"}).json()
    t.set_consent(dept.citizen.person_id, "withdrawn")
    blocked = client.post(f"/v1/complaints/{consent_gone['id']}/resolve", headers=dept.o2, json={"outcome": "resolved", "reason": "Done already"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "consent_required"
    assert next(c for c in client.get("/v1/complaints", headers=dept.o1).json()["items"] if c["id"] == consent_gone["id"])["details"] is None
