"""The evaluation summary (B13): live numbers per rule version, labelled numbers from eval runs. Uses Postgres."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.contracts.engine import IdentityCheck
from app.core.db import system_session
from app.db import models
from app.modules.decision import service as decision_service
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program
from app.modules.evals.summary import percentile
from app.synth.golden import base_input, registry


def _decide(factory: Any, tenant: Any, setup: Any, inp: Any) -> models.Decision:
    citizen = factory.account(tenant, "citizen")
    application_id = make_application(tenant.id, citizen.person_id, setup.program_id)
    with citizen_session(citizen) as db:
        decision = decision_service.decide_and_record(db, tenant_id=tenant.id, application_id=application_id, person_id=citizen.person_id,
                                                      inp=inp.model_copy(update={"application_id": str(application_id)}))  # fmt: skip
        db.expunge(decision)
    return decision


def test_summary_reports_live_and_labelled_numbers_and_counts_a_real_silent_guess(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    approved = _decide(factory, tenant, setup, base_input())
    _decide(factory, tenant, setup, base_input(registry=registry(verified_income_pkr=None, income_as_of=None)))
    human = _decide(factory, tenant, setup, base_input(identity=IdentityCheck(status="partial", name_score=0.74)))
    admin = factory.headers(client, factory.account(tenant, "admin"))
    assert client.post("/v1/evals/decisions/runs", headers=admin).status_code == 201
    officer = factory.account(tenant, "officer")
    with system_session() as db:
        case = models.Case(id=uuid.uuid4(), tenant_id=tenant.id, kind="application_review", status="resolved", priority=50,
                           application_id=human.application_id, decision_id=human.id)  # fmt: skip
        db.add(case)
        db.flush()
        db.add(models.HumanReview(tenant_id=tenant.id, decision_id=human.id, case_id=case.id, reviewer_user_id=officer.user_id,
                                  action="reject", reason="Not the card holder", overrode_ai=True))  # fmt: skip

    body = client.get("/v1/evals/summary", headers=factory.headers(client, factory.account(tenant, "auditor"))).json()
    live = body["live_overall"]
    assert live["decisions"] == 3 and live["routes"] == {"auto": 1, "ask_more": 1, "human": 1}
    assert live["silent_guesses"] == 0 and live["engine_fallbacks"] == 0 and live["abstention_rate"] == round(2 / 3, 4)
    assert live["latency_ms_p50"] is not None and live["latency_ms_p95"] is not None and live["expected_cost_per_decision"] is not None
    assert live["officer_reviews"] == 1 and live["officer_overrides"] == 1 and live["override_rate"] == 1.0
    (v1,) = body["live_by_rule_version"]
    assert v1["rule_version_no"] == 1 and v1["decisions"] == 3
    labelled = body["labelled"]
    assert labelled["stored"] and labelled["cases"] >= 1000 and labelled["accuracy_of_automatic"] > 0.95 and labelled["silent_guesses"] == 0
    assert body["labelled_by_rule_version"][0]["rule_version_no"] == 1
    assert body["names"]["wrong_links"] == 0 and body["names"]["fixtures"] >= 200
    assert body["silent_guesses_total"] == 0

    # A stored automatic approval with an active guard is a silent guess: the metric must see it.
    with system_session() as db:
        stored = db.get(models.Decision, approved.id)
        assert stored is not None
        bad = models.Decision(
            tenant_id=tenant.id, application_id=stored.application_id, person_id=stored.person_id, rule_version_id=stored.rule_version_id,
            model_version=stored.model_version, engine_version=stored.engine_version, cost_matrix=dict(stored.cost_matrix),
            input_snapshot=dict(stored.input_snapshot), input_hash=stored.input_hash, rule_trace=list(stored.rule_trace),
            probabilities=dict(stored.probabilities), p_ok=stored.p_ok, expected_costs=dict(stored.expected_costs), route="auto",
            outcome="approved", reasons=["test_tampered"], guards=["possible_duplicate"], explanation=dict(stored.explanation), latency_ms=1,
        )  # fmt: skip
        db.add(bad)
    again = client.get("/v1/evals/summary", headers=admin).json()
    assert again["live_overall"]["silent_guesses"] == 1 and again["silent_guesses_total"] == 1
    assert client.get("/v1/evals/summary", headers=factory.headers(client, factory.account(tenant, "officer"))).status_code == 403


def test_percentiles() -> None:
    assert percentile([], 50) is None
    assert percentile([5, 1, 3], 50) == 3 and percentile([1, 2, 3, 4], 95) == 4 and percentile([7], 95) == 7
