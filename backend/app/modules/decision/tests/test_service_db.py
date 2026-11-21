"""decide_and_record, the decision API, and a rule change taking effect on the next decision. Uses Postgres."""

from __future__ import annotations

import copy
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.contracts.decision import CostMatrix
from app.contracts.engine import DecisionInput
from app.core import metrics
from app.core.db import SYSTEM, open_session, system_session
from app.db import models
from app.modules.decision import service
from app.modules.decision.engine import decide
from app.modules.decision.model import get_model
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program, withdraw_consent
from app.modules.rules.service import get_version_snapshot
from app.synth.golden import base_input, registry


def _record(citizen: Any, setup: Any, inp: DecisionInput) -> models.Decision:
    application_id = make_application(citizen.tenant_id, citizen.person_id, setup.program_id)
    inp = inp.model_copy(update={"application_id": str(application_id)})
    with citizen_session(citizen) as db:
        decision = service.decide_and_record(db, tenant_id=citizen.tenant_id, application_id=application_id, person_id=citizen.person_id,
                                             inp=inp, actor_user_id=citizen.user_id)  # fmt: skip
        db.expunge(decision)
    return decision


def _audit_rows(tenant_id: Any, action: str) -> list[models.AuditLog]:
    with open_session(SYSTEM) as db:
        return list(db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant_id, models.AuditLog.action == action)).all())


def test_decide_and_record_stores_everything_needed_to_replay(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    setup = make_program(tenant.id)
    before = metrics.DECISIONS.labels("auto")._value.get()
    decision = _record(citizen, setup, base_input())
    assert (decision.route, decision.outcome) == ("auto", "approved")
    assert decision.rule_version_id == setup.v1_id and decision.model_version == get_model().version
    assert metrics.DECISIONS.labels("auto")._value.get() == before + 1
    assert service.engine_extras(decision)["payment_pkr"] == 12000

    rows = _audit_rows(tenant.id, "decision.made")
    assert len(rows) == 1
    row = rows[0]
    assert row.actor_type == "ai" and row.model_version == decision.model_version and row.rule_version_id == setup.v1_id
    assert row.input_hash == decision.input_hash and json.loads(row.details)["result_hash"] == decision.result_hash

    with open_session(SYSTEM) as db:  # replay from the stored snapshot and pinned versions
        rules = get_version_snapshot(db, decision.rule_version_id)
        stored = db.get(models.Decision, decision.id)
        assert stored is not None
        replayed = decide(DecisionInput.model_validate(stored.input_snapshot), rules, CostMatrix.model_validate(stored.cost_matrix), get_model())
        assert replayed.result_hash == stored.result_hash
        registered = db.scalars(select(models.ModelRegistry).where(models.ModelRegistry.tenant_id == tenant.id)).all()
        assert [r.version for r in registered] == [decision.model_version]


def test_user_view_and_trace_views(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    setup = make_program(tenant.id)
    decision = _record(citizen, setup, base_input(registry=registry(verified_income_pkr=None, income_as_of=None)))
    view = service.user_view(decision)
    assert view.route == "ask_more" and view.rule_version_no == 1
    assert view.explanation.reason_codes == ["ask_income_proof"] and len(view.explanation.sentences) <= 3
    with open_session(SYSTEM) as db:
        raw = service.trace_view(db, decision, redact=False)
        masked = service.trace_view(db, decision, redact=True)
    assert raw.input_snapshot["form"]["full_name"]["value"] == "Zainab Bibi"
    assert masked.input_snapshot["form"]["full_name"]["value"] == "Z••• B•••"
    assert masked.input_snapshot["form"]["national_id"]["value"].endswith(raw.input_snapshot["form"]["national_id"]["value"][-3:])
    assert "•" in masked.input_snapshot["form"]["national_id"]["value"]
    assert masked.input_snapshot["documents"][0]["ocr"]["raw_text"] is None
    assert masked.input_snapshot["registry"]["dob"] == "1978-••-••"
    assert raw.thresholds["approve"] == 0.968 and raw.handoff and raw.handoff.resolving_proof == "income_proof"
    assert masked.handoff and "ocr_text" not in masked.handoff.evidence


def test_decision_api_officer_auditor_and_consent(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.account(tenant, "officer")
    auditor = factory.account(tenant, "auditor")
    setup = make_program(tenant.id)
    decision = _record(citizen, setup, base_input())

    as_officer = client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, officer))
    assert as_officer.status_code == 200, as_officer.text
    assert "x-rahat-stub" not in as_officer.headers
    body = as_officer.json()
    assert body["user_view"]["outcome"] == "approved" and body["trace"]["input_snapshot"]["form"]["full_name"]["value"] == "Zainab Bibi"

    as_auditor = client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, auditor))
    assert as_auditor.status_code == 200
    assert as_auditor.json()["trace"]["input_snapshot"]["form"]["full_name"]["value"] == "Z••• B•••"

    assert client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, citizen)).status_code == 403

    other = factory.tenant()
    stranger = factory.account(other, "officer")
    assert client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, stranger)).status_code == 404

    withdraw_consent(tenant.id, citizen.person_id)
    blocked = client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, officer))
    assert blocked.status_code == 403 and blocked.json()["code"] == "consent_required"
    denied = [r for r in _audit_rows(tenant.id, "access.denied") if r.object_type == "decision"]
    assert len(denied) == 1 and denied[0].actor_id == str(officer.user_id)
    assert client.get(f"/v1/decisions/{decision.id}", headers=factory.headers(client, auditor)).status_code == 200  # masked view


def _publish_cap(client: TestClient, factory: Any, setup: Any, author: Any, approver: Any, cap: int) -> str:
    dsl = copy.deepcopy(get_version_dsl(setup.v1_id))
    dsl["params"]["income_cap"] = cap
    created = client.post("/v1/rules/versions", json={"parent_version_id": str(setup.v1_id), "dsl": dsl}, headers=factory.headers(client, author))
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    asked = client.post(f"/v1/rules/versions/{version_id}/request-approval", json={"reason": "Lower the income cap"},
                        headers=factory.headers(client, author))  # fmt: skip
    assert asked.status_code == 200, asked.text
    own = client.post(f"/v1/rules/versions/{version_id}/publish", json={"reason": "Publishing my own"}, headers=factory.headers(client, author))
    assert own.status_code == 403 and own.json()["code"] == "four_eyes_required"
    published = client.post(f"/v1/rules/versions/{version_id}/publish", json={"reason": "Checked the diff"},
                            headers=factory.headers(client, approver))  # fmt: skip
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published" and published.json()["is_active"]
    return str(version_id)


def get_version_dsl(version_id: Any) -> dict[str, Any]:
    with system_session() as db:
        version = db.get(models.RuleVersion, version_id)
        assert version is not None
        return dict(version.dsl)


def test_rule_change_applies_to_the_next_decision_and_old_decisions_keep_their_version(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    author, approver = factory.account(tenant, "admin"), factory.account(tenant, "admin")
    setup = make_program(tenant.id)
    case = base_input(registry=registry(verified_income_pkr=25_000))

    first = _record(citizen, setup, case)
    assert first.outcome == "approved" and first.rule_version_id == setup.v1_id

    v2 = _publish_cap(client, factory, setup, author, approver, cap=20_000)
    neighbour = factory.account(tenant, "citizen")  # one open application per person and program
    second = _record(neighbour, setup, case)  # same evidence, nothing restarted
    assert str(second.rule_version_id) == v2
    assert second.outcome != "approved"
    assert {t["rule_id"]: t["result"] for t in second.rule_trace}["income_cap"] == "fail"

    with open_session(SYSTEM) as db:
        old = db.get(models.Decision, first.id)
        assert old is not None and old.rule_version_id == setup.v1_id and old.outcome == "approved"
        replay = decide(DecisionInput.model_validate(old.input_snapshot), get_version_snapshot(db, old.rule_version_id),
                        CostMatrix.model_validate(old.cost_matrix), get_model())  # fmt: skip
        assert replay.result_hash == old.result_hash
        v1 = db.get(models.RuleVersion, setup.v1_id)
        assert v1 is not None and v1.status == "retired" and v1.dsl["params"]["income_cap"] == 30000
    actions = [r.action for r in _audit_rows(tenant.id, "rules.version_published")]
    assert actions == ["rules.version_published"]


def test_tenant_cost_matrix_moves_the_thresholds(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    setup = make_program(tenant.id)
    with system_session() as db:
        row = db.get(models.Tenant, tenant.id)
        assert row is not None
        row.cost_matrix = CostMatrix(wrong_approve=1000.0).model_dump()
    decision = _record(citizen, setup, base_input())
    assert service.engine_extras(decision)["thresholds"]["approve"] == round(CostMatrix(wrong_approve=1000.0).approve_threshold(1.0), 4)
    assert decision.cost_matrix["wrong_approve"] == 1000.0


def test_seed_step_registers_the_model_once(factory: Any) -> None:
    from app.modules.decision.seed_step import seed

    tenant = factory.tenant()
    for _ in range(2):
        with system_session() as db:
            seed(db)
    with open_session(SYSTEM) as db:
        rows = db.scalars(select(models.ModelRegistry).where(models.ModelRegistry.tenant_id == tenant.id)).all()
    assert len(rows) == 1 and rows[0].version == get_model().version and rows[0].metrics["test"]["p_ok"]["ece"] is not None
