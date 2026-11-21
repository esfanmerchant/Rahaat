"""The impact report on a small seeded scenario: one automatic approval, one ask-for-proof, one human case, payments, a scam and anomaly cases."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.contracts.engine import IdentityCheck
from app.core.db import system_session
from app.db import models
from app.modules.decision import service as decision_service
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program
from app.synth.golden import base_input, registry


def _decide(factory: Any, tenant: Any, setup: Any, inp: Any) -> tuple[models.Decision, Any]:
    citizen = factory.account(tenant, "citizen")
    application_id = make_application(tenant.id, citizen.person_id, setup.program_id)
    with citizen_session(citizen) as db:
        decision = decision_service.decide_and_record(
            db,
            tenant_id=tenant.id,
            application_id=application_id,
            person_id=citizen.person_id,
            inp=inp.model_copy(update={"application_id": str(application_id)}),
        )
        db.expunge(decision)
    return decision, citizen


def test_impact_numbers_match_a_small_seeded_scenario(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant("Test Relief Department")
    setup = make_program(tenant.id)
    approved, c1 = _decide(factory, tenant, setup, base_input())
    _decide(factory, tenant, setup, base_input(registry=registry(verified_income_pkr=None, income_as_of=None)))
    human, c3 = _decide(factory, tenant, setup, base_input(identity=IdentityCheck(status="partial", name_score=0.74)))
    officer = factory.account(tenant, "officer")
    opened = datetime.now(UTC) - timedelta(hours=2)
    with system_session() as db:
        submitted = db.get(models.Application, approved.application_id)
        assert submitted is not None
        submitted.submitted_at = approved.created_at - timedelta(seconds=4)
        case = models.Case(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            kind="application_review",
            status="resolved",
            priority=50,
            application_id=human.application_id,
            decision_id=human.id,
            created_at=opened,
            resolved_at=opened + timedelta(hours=1),
            resolution="approved",
        )
        db.add(case)
        db.flush()
        db.add(models.HumanReview(tenant_id=tenant.id, decision_id=human.id, case_id=case.id, reviewer_user_id=officer.user_id, action="approve",
                                  reason="Checked the card in person", review_seconds=240, overrode_ai=False))  # fmt: skip
        for status, amount in (("settled", 12_000), ("settled", 12_000), ("cancelled", 12_000)):
            db.add(models.Payment(id=uuid.uuid4(), tenant_id=tenant.id, application_id=approved.application_id, person_id=c1.person_id,
                                  amount_pkr=amount, status=status, idempotency_key=uuid.uuid4().hex))  # fmt: skip
        for label, confirmed in (("relief_scam", "relief_scam"), ("phishing_link", None), ("legit_program_message", None)):
            db.add(models.ScamReport(id=uuid.uuid4(), tenant_id=tenant.id, text_redacted="x", text_hash=uuid.uuid4().hex, label=label, confidence=0.9,
                                     route="auto", confirmed_label=confirmed))  # fmt: skip
        for resolution in (None, "rejected", "approved"):
            db.add(models.Case(id=uuid.uuid4(), tenant_id=tenant.id, kind="anomaly_review", status="resolved" if resolution else "open", priority=30,
                               resolution=resolution))  # fmt: skip
        db.add(models.DuplicateCandidate(tenant_id=tenant.id, person_a_id=c1.person_id, person_b_id=c3.person_id, score=0.9, band="possible",
                                         status="linked"))  # fmt: skip

    admin = factory.headers(client, factory.account(tenant, "admin"))
    body = client.get("/v1/admin/impact", headers=admin, params={"assumed_minutes_per_manual_review": 15}).json()

    assert body["department"] == "Test Relief Department" and body["window_days"] == 90
    h = body["handoff"]
    assert h["decisions"] == 3 and h["by_route"] == {"auto": 1, "ask_more": 1, "human": 1} and h["handoff_rate"] == round(1 / 3, 4)
    assert h["not_automatic_rate"] == round(2 / 3, 4) and h["silent_guesses"] == 0
    t = body["time_to_decision"]
    assert t["automatic"]["n"] == 1 and 3.9 <= t["automatic"]["median_seconds"] <= 4.1, "submission to decision, from the stored timestamps"
    assert t["human_case"] == {"n": 1, "median_seconds": 3600.0, "p90_seconds": 3600.0}
    assert t["human_review_hands_on"]["median_seconds"] == 240.0 and t["human_case_by_kind"]["application_review"]["n"] == 1
    p = body["payments"]
    assert p["count"] == 3 and p["amount_pkr"] == 36_000 and p["settled_pkr"] == 24_000
    assert p["by_status"]["cancelled"] == {"count": 1, "amount_pkr": 12_000}
    f = body["fraud_stopped"]
    assert f["scams_flagged"] == 2 and f["scams_confirmed_by_a_person"] == 1 and f["payments_stopped"] == 1 and f["payments_stopped_pkr"] == 12_000
    assert f["anomaly_cases"] == {"total": 3, "active": 1, "confirmed": 1, "dismissed": 1}
    assert f["duplicate_candidates"] == 1 and f["duplicates_linked_by_a_person"] == 1
    c = body["cost_per_claim"]
    assert c["decisions"] == 3 and c["per_claim_units"] is not None and c["all_to_a_person_per_claim_units"] is not None
    s = body["time_saved"]
    assert s["automatic_decisions"] == 1 and s["hands_on_source"] == "measured_median_review_seconds" and s["minutes_per_manual_review_used"] == 4.0
    assert {a["name"] for a in body["assumptions"]} == {"assumed_minutes_per_manual_review", "assumed_pkr_per_cost_unit"}
    assert next(a for a in body["assumptions"] if a["name"] == "assumed_minutes_per_manual_review")["value"] == 15
    r = body["replay"]
    assert r["synthetic"] is True and "Synthetic" in r["label"] and r["cases"] >= 1000 and r["false_approvals"] is not None
    assert body["measured_from"]["decisions"] == 3 and body["measured_from"]["timed_officer_reviews"] == 1


def test_impact_without_any_data_is_empty_not_invented(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    body = client.get("/v1/admin/impact", headers=factory.headers(client, factory.account(tenant, "officer"))).json()
    assert body["handoff"]["decisions"] == 0 and body["handoff"]["handoff_rate"] is None
    assert body["time_to_decision"]["automatic"]["median_seconds"] is None and body["cost_per_claim"]["per_claim_units"] is None
    assert body["time_saved"]["hands_on_hours_saved"] == 0 and body["time_saved"]["hands_on_source"] == "assumed_minutes_per_manual_review"
    assert body["payments"]["count"] == 0 and body["payments"]["average_pkr"] is None


def test_impact_policy_and_isolation(client: TestClient, factory: Any) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    setup = make_program(tenant.id)
    _decide(factory, tenant, setup, base_input())
    for role, status in (("admin", 200), ("officer", 200), ("auditor", 403), ("citizen", 403), ("helper", 403)):
        assert client.get("/v1/admin/impact", headers=factory.headers(client, factory.account(tenant, role))).status_code == status, role
    assert client.get("/v1/admin/impact").status_code == 401
    mine = client.get("/v1/admin/impact", headers=factory.headers(client, factory.account(tenant, "admin"))).json()
    theirs = client.get("/v1/admin/impact", headers=factory.headers(client, factory.account(other, "admin"))).json()
    assert mine["handoff"]["decisions"] == 1 and theirs["handoff"]["decisions"] == 0
    bad = client.get("/v1/admin/impact", headers=factory.headers(client, factory.account(tenant, "admin")), params={"days": 0})
    assert bad.status_code == 422
