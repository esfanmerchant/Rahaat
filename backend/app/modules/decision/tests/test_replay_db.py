"""Replay of stored decisions and the decision list (B11). Uses Postgres."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.contracts.engine import DecisionInput, IdentityCheck
from app.core.db import SYSTEM, open_session
from app.db import models
from app.modules.decision import replay as replay_module
from app.modules.decision import service
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program, withdraw_consent
from app.synth.golden import base_input, registry


def _record(citizen: Any, setup: Any, inp: DecisionInput) -> models.Decision:
    application_id = make_application(citizen.tenant_id, citizen.person_id, setup.program_id)
    inp = inp.model_copy(update={"application_id": str(application_id)})
    with citizen_session(citizen) as db:
        decision = service.decide_and_record(db, tenant_id=citizen.tenant_id, application_id=application_id, person_id=citizen.person_id, inp=inp)
        db.expunge(decision)
    return decision


def _rows(model: Any, *where: Any) -> list[Any]:
    with open_session(SYSTEM) as db:
        return list(db.scalars(select(model).where(*where)).all())


def test_replay_of_a_stored_decision_matches_bit_for_bit(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    decisions = [
        _record(factory.account(tenant, "citizen"), setup, base_input()),
        _record(factory.account(tenant, "citizen"), setup, base_input(registry=registry(verified_income_pkr=None, income_as_of=None))),
        _record(factory.account(tenant, "citizen"), setup, base_input(identity=IdentityCheck(status="partial", name_score=0.74))),
    ]
    auditor = factory.headers(client, factory.account(tenant, "auditor"))
    for decision in decisions:
        response = client.post(f"/v1/decisions/{decision.id}/replay", headers=auditor)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["match"] is True and body["differences"] == [], body
        assert body["stored_result_hash"] == body["replayed_result_hash"] == decision.result_hash
    rows = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "decision.replayed")
    assert len(rows) == 3 and all(json.loads(r.details)["match"] for r in rows) and rows[0].actor_type == "user"

    view = client.get(f"/v1/decisions/{decisions[0].id}", headers=auditor).json()
    assert view["replay_available"] is True and "case_id" in view and view["trace"]["result_hash"] == decisions[0].result_hash


def test_replay_reports_differences_instead_of_matching_when_the_model_changed(factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.decision import model as model_module
    from app.synth.world import build_world

    tenant = factory.tenant()
    setup = make_program(tenant.id)
    decision = _record(factory.account(tenant, "citizen"), setup, base_input())
    other_model = model_module.train(build_world(seed=11, households=120))
    monkeypatch.setattr(replay_module, "get_model", lambda: other_model)
    with open_session(SYSTEM) as db:
        stored = db.get(models.Decision, decision.id)
        assert stored is not None
        result = replay_module.replay(db, stored)
    assert result.match is False and result.replayed_result_hash != result.stored_result_hash
    assert result.differences[0].startswith("model_version: stored ") and "cannot be loaded" in result.differences[0]


def test_officers_need_consent_to_replay_and_citizens_cannot(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    citizen = factory.account(tenant, "citizen")
    decision = _record(citizen, setup, base_input())
    officer = factory.headers(client, factory.account(tenant, "officer"))
    assert client.post(f"/v1/decisions/{decision.id}/replay", headers=officer).json()["match"] is True
    assert client.post(f"/v1/decisions/{decision.id}/replay", headers=factory.headers(client, citizen)).status_code == 403
    withdraw_consent(tenant.id, citizen.person_id)
    assert client.post(f"/v1/decisions/{decision.id}/replay", headers=officer).status_code == 403
    outsider = factory.headers(client, factory.account(factory.tenant(), "auditor"))
    assert client.post(f"/v1/decisions/{decision.id}/replay", headers=outsider).status_code == 404


def test_decision_list_filters_and_pages_without_personal_data(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    approved = _record(factory.account(tenant, "citizen"), setup, base_input())
    asked = _record(factory.account(tenant, "citizen"), setup, base_input(registry=registry(verified_income_pkr=None, income_as_of=None)))
    human = _record(factory.account(tenant, "citizen"), setup, base_input(identity=IdentityCheck(status="partial", name_score=0.74)))
    auditor = factory.headers(client, factory.account(tenant, "auditor"))

    def ids(query: str) -> list[str]:
        response = client.get(f"/v1/decisions{query}", headers=auditor)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    everything = client.get("/v1/decisions", headers=auditor).json()
    assert {i["id"] for i in everything["items"]} == {str(approved.id), str(asked.id), str(human.id)}
    assert "Zainab" not in json.dumps(everything), "the list carries no names or snapshots"
    first = next(i for i in everything["items"] if i["id"] == str(approved.id))
    assert first["rule_version_no"] == 1 and first["expected_cost"] is not None and first["main_reason"] == "rules.all_hard_verified_pass"
    assert ids("?route=auto") == [str(approved.id)]
    assert ids("?outcome=needs_proof") == [str(asked.id)]
    assert ids("?route=human") == [str(human.id)]
    assert len(ids("?rule_version_no=1")) == 3 and ids("?rule_version_no=2") == []
    assert len(ids(f"?rule_version_id={setup.v1_id}")) == 3
    today = datetime.now(UTC).date()
    assert len(ids(f"?decided_from={today}&decided_to={today}")) == 3
    assert ids(f"?decided_to={today - timedelta(days=2)}") == []
    page = client.get("/v1/decisions?limit=2", headers=auditor).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = client.get(f"/v1/decisions?limit=2&cursor={page['next_cursor']}", headers=auditor).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    assert {i["id"] for i in page["items"]} | {i["id"] for i in rest["items"]} == {str(approved.id), str(asked.id), str(human.id)}
    assert client.get("/v1/decisions?route=sideways", headers=auditor).status_code == 422
    assert client.get("/v1/decisions", headers=factory.headers(client, factory.account(tenant, "admin"))).status_code == 403
