"""Digital Twin (B12): what a draft changes, with no side effects; then publish through four-eyes or discard."""

from __future__ import annotations

import copy
import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.contracts.decision import CostMatrix
from app.contracts.engine import IdentityCheck
from app.core.db import SYSTEM, open_session
from app.db import models
from app.modules.decision import service as decision_service
from app.modules.decision.model import get_model
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program
from app.modules.evals import decision_eval as E
from app.modules.twin import simulate as S
from app.seed import RULES_V1
from app.synth.golden import base_input, registry

STALE_RULE = {**RULES_V1, "params": {**RULES_V1["params"], "stale_income_settles_below": 0.5}}
LOWER_CAP = {**RULES_V1, "params": {**RULES_V1["params"], "income_cap": 20000}}


def test_the_twin_counts_changes_costs_and_slices_on_labelled_cases() -> None:
    model = get_model()
    cases = S.synthetic_cases(E.cached_scores(RULES_V1, model), E.cached_scores(LOWER_CAP, model))
    summary = S.summarise(cases, CostMatrix(), payment_before=12000, payment_after=12000)
    print(f"\ntwin cap 30k -> 20k on {summary['n']} labelled cases: change {summary['change']}, flagged {summary['flagged_slices']}, "
          f"labelled {summary['labelled']}")  # fmt: skip
    assert summary["n"] >= 1000 and summary["changed"] > 0
    assert sum(sum(row.values()) for row in summary["transitions"].values()) == summary["n"]
    assert sum(summary["change"].values()) == 0, "every case moves from one outcome to another"
    assert summary["outcomes_after"]["approved"] < summary["outcomes_before"]["approved"], "a lower cap approves fewer"
    assert summary["labelled"]["eligible_after"] < summary["labelled"]["eligible_before"]
    assert summary["payout_after_pkr"] == 12000 * summary["outcomes_after"]["approved"]
    for key in S.SLICE_KEYS:
        assert sum(row["n"] for row in summary["slices"][key]) == summary["n"]
    unchanged = S.summarise(S.synthetic_cases(E.cached_scores(RULES_V1, model), E.cached_scores(RULES_V1, model)), CostMatrix(),
                            payment_before=12000, payment_after=12000)  # fmt: skip
    assert unchanged["changed"] == 0 and unchanged["flagged_slices"] == [] and unchanged["expected_cost_change"] == 0


def _counts(tenant_id: Any) -> dict[str, int]:
    tables = (models.Notification, models.Payment, models.Case, models.Decision, models.Job, models.Application, models.Approval,
              models.RuleVersion, models.EvalRun, models.DuplicateCandidate, models.TwinRun, models.AuditLog)  # fmt: skip
    with open_session(SYSTEM) as db:
        return {t.__tablename__: int(db.scalar(select(func.count()).select_from(t).where(t.tenant_id == tenant_id)) or 0) for t in tables}


def _draft(client: TestClient, headers: dict[str, str], parent: Any, dsl: dict[str, Any]) -> str:
    response = client.post("/v1/rules/versions", json={"parent_version_id": str(parent), "dsl": dsl}, headers=headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_a_twin_run_writes_nothing_but_its_own_row(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    for inp in (base_input(), base_input(registry=registry(income_as_of="2024-05-01", verified_income_pkr=9000)),
                base_input(identity=IdentityCheck(status="partial", name_score=0.74))):  # fmt: skip
        citizen = factory.account(tenant, "citizen")
        application_id = make_application(tenant.id, citizen.person_id, setup.program_id)
        with citizen_session(citizen) as db:
            decision_service.decide_and_record(db, tenant_id=tenant.id, application_id=application_id, person_id=citizen.person_id,
                                               inp=inp.model_copy(update={"application_id": str(application_id)}))  # fmt: skip
    admin = factory.headers(client, factory.account(tenant, "admin"))
    draft_id = _draft(client, admin, setup.v1_id, copy.deepcopy(STALE_RULE))
    before = _counts(tenant.id)

    response = client.post("/v1/twin/runs", json={"draft_version_id": draft_id}, headers=admin)
    assert response.status_code == 201, response.text
    after = _counts(tenant.id)
    assert after.pop("twin_runs") == before.pop("twin_runs") + 1
    assert after.pop("audit_log") == before.pop("audit_log") + 1, "one audit entry records the run"
    assert after == before, "no notification, payment, case, decision, job, application, approval or eval run was written"

    body = response.json()
    live = body["live"]
    assert live["n"] == 3 and live["base_differs_from_stored"] == 0, "the base version recomputes the stored decisions"
    assert live["changed"] == 1 and live["transitions"]["needs_proof"]["approved"] == 1, "the stale but low income is now enough"
    assert body["synthetic"]["n"] >= 1000 and body["synthetic"]["labelled"] is not None
    assert any(c["path"] == "params.stale_income_settles_below" for c in body["rule_changes"])
    changed_live = [s for s in body["sample"] if s["dataset"] == "live"]
    assert len(changed_live) == 1 and changed_live[0]["before"]["outcome"] == "needs_proof" and changed_live[0]["after"]["outcome"] == "approved"
    assert "Zainab" not in json.dumps(body), "the sample carries no names"
    assert body["side_effects"].startswith("None.")
    (row,) = [r for r in client.get("/v1/twin/runs", headers=admin).json()["items"] if r["id"] == body["id"]]
    assert row["changed_live"] == 1
    auditor = factory.headers(client, factory.account(tenant, "auditor"))
    assert client.get(f"/v1/twin/runs/{body['id']}", headers=auditor).status_code == 200
    assert client.post("/v1/twin/runs", json={"draft_version_id": draft_id}, headers=auditor).status_code == 403


def test_publish_goes_through_four_eyes_and_discard_is_recorded(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    setup = make_program(tenant.id)
    first, second = factory.account(tenant, "admin"), factory.account(tenant, "admin")
    admin, approver = factory.headers(client, first), factory.headers(client, second)

    draft_id = _draft(client, admin, setup.v1_id, copy.deepcopy(LOWER_CAP))
    run = client.post("/v1/twin/runs", json={"draft_version_id": draft_id, "include_live": False}, headers=admin).json()
    assert run["live"] is None and run["synthetic"]["change"]["approved"] < 0
    asked = client.post(f"/v1/twin/runs/{run['id']}/request-publish", json={"reason": "Twin checked: budget cut"}, headers=admin)
    assert asked.status_code == 200 and asked.json()["status"] == "publishing" and asked.json()["draft_status"] == "pending_approval"
    assert client.post(f"/v1/rules/versions/{draft_id}/publish", json={"reason": "I wrote it"}, headers=admin).status_code == 403
    published = client.post(f"/v1/rules/versions/{draft_id}/publish", json={"reason": "Second admin agrees"}, headers=approver)
    assert published.status_code == 200 and published.json()["is_active"] is True
    assert client.post(f"/v1/twin/runs/{run['id']}/discard", json={"reason": "too late now"}, headers=admin).status_code == 409

    other_id = _draft(client, admin, draft_id, copy.deepcopy(STALE_RULE))
    other = client.post("/v1/twin/runs", json={"draft_version_id": other_id, "include_live": False}, headers=admin).json()
    assert other["base_version_no"] == 2, "the base is the version that is active now"
    dropped = client.post(f"/v1/twin/runs/{other['id']}/discard", json={"reason": "Not this quarter"}, headers=admin)
    assert dropped.status_code == 200 and dropped.json()["status"] == "discarded" and dropped.json()["decided_reason"] == "Not this quarter"
    with open_session(SYSTEM) as db:
        actions = set(db.scalars(select(models.AuditLog.action).where(models.AuditLog.tenant_id == tenant.id)).all())
    assert {"twin.run", "twin.publish_requested", "twin.discarded", "rules.version_published"} <= actions
    assert client.post("/v1/twin/runs", json={"draft_version_id": str(setup.v1_id), "base_version_id": other_id}, headers=admin).status_code == 201
