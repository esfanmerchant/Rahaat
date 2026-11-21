"""The cost-of-being-wrong API: analysis, what-if (slider), stored runs, and the audited cost matrix. Uses Postgres."""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.contracts.engine import AnomalyEvidence
from app.core.db import SYSTEM, open_session
from app.db import models
from app.modules.decision import service as decision_service
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program
from app.synth.golden import base_input


def _rows(model: Any, *where: Any) -> list[Any]:
    with open_session(SYSTEM) as db:
        return list(db.scalars(select(model).where(*where)).all())


def test_latest_analysis_and_a_slider_request_follow_the_cost_matrix(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    make_program(tenant.id)
    admin = factory.headers(client, factory.account(tenant, "admin"))
    latest = client.get("/v1/evals/decisions/latest", headers=admin)
    assert latest.status_code == 200, latest.text
    body = latest.json()
    assert body["thresholds"]["approve"] == 0.968 and body["thresholds"]["reject"] == 0.8933 and body["stored"] is False
    assert body["operating_point"]["n"] >= 1000 and body["dataset"]["held_out"] is True and body["operating_point"]["silent_guesses"] == 0
    assert len(body["reliability"]["bins"]) == 10 and body["roc"] and body["pr"] and body["cost_curve"] and body["explanation"]

    slider = {"wrong_approve": 40, "wrong_reject": 30, "human_review": 3, "ask_proof": 1, "delay_per_day": 0.2}
    client.post("/v1/evals/decisions/what-if", json=slider, headers=admin)  # warm
    started = time.perf_counter()
    response = client.post("/v1/evals/decisions/what-if", json=slider, headers=admin)
    elapsed = time.perf_counter() - started
    print(f"\nwhat-if round trip {elapsed * 1000:.0f} ms (server {response.json()['elapsed_ms']} ms)")
    assert response.status_code == 200 and elapsed < 1.0
    what_if = response.json()
    assert what_if["thresholds"]["approve"] == round(1 - 3.2 / 40, 4) and what_if["costs"]["wrong_approve"] == 40
    assert what_if["operating_point"]["approved"] >= body["operating_point"]["approved"], "a cheaper wrong approval approves more"
    assert not _rows(models.EvalRun, models.EvalRun.tenant_id == tenant.id), "what-if saves nothing"
    assert client.post("/v1/evals/decisions/what-if", json={**slider, "extra": 1}, headers=admin).status_code == 422
    assert client.post("/v1/evals/decisions/what-if", json={**slider, "wrong_approve": 0}, headers=admin).status_code == 422


def test_runs_are_stored_and_listed(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    make_program(tenant.id)
    admin = factory.headers(client, factory.account(tenant, "admin"))
    auditor = factory.headers(client, factory.account(tenant, "auditor"))
    created = client.post("/v1/evals/decisions/runs", json={"note": "after the cap review"}, headers=admin)
    assert created.status_code == 201 and created.json()["stored"] is True
    (run,) = _rows(models.EvalRun, models.EvalRun.tenant_id == tenant.id)
    assert run.kind == "decision" and run.metrics["operating_point"]["n"] >= 1000 and run.artifacts["cost_curve"]
    latest = client.get("/v1/evals/decisions/latest", headers=auditor).json()
    assert latest["run_id"] == str(run.id) and latest["stored"] is True
    listed = client.get("/v1/evals/runs?kind=decision", headers=auditor).json()
    assert [item["id"] for item in listed["items"]] == [str(run.id)]
    assert client.post("/v1/evals/decisions/runs", headers=auditor).status_code == 403, "auditors read, admins run"
    assert _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "eval.run_stored")


def test_saving_the_cost_matrix_is_audited_and_changes_the_next_decision(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    setup = make_program(tenant.id)
    admin_account = factory.account(tenant, "admin")
    admin = factory.headers(client, admin_account)
    officer = factory.headers(client, factory.account(tenant, "officer"))
    borderline = base_input(anomaly=AnomalyEvidence(score=0.6, flagged=False))  # verified, p_ok about 0.91

    def decide_now(person: Any) -> models.Decision:
        application_id = make_application(tenant.id, person.person_id, setup.program_id)
        inp = borderline.model_copy(update={"application_id": str(application_id)})
        with citizen_session(person) as db:
            decision = decision_service.decide_and_record(db, tenant_id=tenant.id, application_id=application_id, person_id=person.person_id, inp=inp)
            db.expunge(decision)
        return decision

    before = decide_now(citizen)
    assert (before.route, before.outcome) == ("human", "needs_human") and before.cost_matrix["wrong_approve"] == 100

    new = {"wrong_approve": 20, "wrong_reject": 30, "human_review": 3, "ask_proof": 1, "delay_per_day": 0.2}
    assert client.put("/v1/cost-matrix", json={**new, "reason": "x"}, headers=admin).status_code == 422, "a reason is required"
    assert client.put("/v1/cost-matrix", json={**new, "reason": "Pilot: cheaper error"}, headers=officer).status_code == 403
    saved = client.put("/v1/cost-matrix", json={**new, "reason": "Pilot: smaller payments, so a wrong one costs less"}, headers=admin)
    assert saved.status_code == 200, saved.text
    assert saved.json()["thresholds"]["approve"] == 0.84 and saved.json()["eval_run_id"]
    assert client.get("/v1/cost-matrix", headers=officer).json()["costs"]["wrong_approve"] == 20

    (row,) = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "tenant.cost_matrix_changed")
    details = json.loads(row.details)
    assert details["before"]["wrong_approve"] == 100 and details["after"]["wrong_approve"] == 20 and row.actor_id == str(admin_account.user_id)
    assert details["approve_threshold"] == {"before": 0.968, "after": 0.84}

    after = decide_now(factory.account(tenant, "citizen"))  # one open application per person and program
    assert (after.route, after.outcome) == ("auto", "approved"), "the very next decision uses the saved costs"
    assert after.cost_matrix["wrong_approve"] == 20 and decision_service.engine_extras(after)["thresholds"]["approve"] == 0.84
    latest = client.get("/v1/evals/decisions/latest", headers=admin).json()
    assert latest["stored"] and latest["costs"]["wrong_approve"] == 20, "the stored analysis matches the department's costs"


def test_name_fixture_report_is_served(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    auditor = factory.headers(client, factory.account(tenant, "auditor"))
    report = client.get("/v1/evals/names", headers=auditor).json()
    assert report["fixtures"] >= 200 and report["wrong_links"] == 0 and set(report["bands"]) == {"same", "possible", "distinct"}
