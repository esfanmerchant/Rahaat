"""Rule versions API: drafts, validation, dry run, diff, four-eyes publish, send back, rollback, isolation."""

from __future__ import annotations

import copy
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import SYSTEM, open_session
from app.db import models
from app.modules.decision.tests.dbsetup import make_program
from app.seed import RULES_V1
from app.synth.golden import base_input, registry


def _setup(factory: Any) -> tuple[Any, Any, Any, Any]:
    tenant = factory.tenant()
    return tenant, factory.account(tenant, "admin"), factory.account(tenant, "admin"), make_program(tenant.id)


def _draft(client: TestClient, factory: Any, admin: Any, parent: Any, dsl: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"parent_version_id": str(parent)}
    if dsl is not None:
        body["dsl"] = dsl
    response = client.post("/v1/rules/versions", json=body, headers=factory.headers(client, admin))
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_draft_lifecycle_and_immutability(client: TestClient, factory: Any) -> None:
    tenant, author, approver, setup = _setup(factory)
    a, b = factory.headers(client, author), factory.headers(client, approver)
    draft = _draft(client, factory, author, setup.v1_id)
    assert draft["version_no"] == 2 and draft["status"] == "draft" and draft["dsl"] == RULES_V1 and draft["valid"]

    changed = copy.deepcopy(RULES_V1)
    changed["params"]["income_cap"] = 35000
    patched = client.patch(f"/v1/rules/versions/{draft['id']}", json={"dsl": changed}, headers=a)
    assert patched.status_code == 200 and patched.json()["dsl"]["params"]["income_cap"] == 35000

    diff = client.get(f"/v1/rules/versions/{draft['id']}/diff", headers=a).json()
    assert diff["against_version_id"] == str(setup.v1_id)
    assert diff["changes"] == [{"path": "params.income_cap", "kind": "changed", "old": 30000, "new": 35000}]

    assert client.post(f"/v1/rules/versions/{draft['id']}/request-approval", json={"reason": "Raise the cap"}, headers=a).status_code == 200
    frozen = client.patch(f"/v1/rules/versions/{draft['id']}", json={"dsl": RULES_V1}, headers=a)
    assert frozen.status_code == 409 and frozen.json()["code"] == "version_immutable"

    sent_back = client.post(f"/v1/rules/versions/{draft['id']}/reject", json={"reason": "Needs a district rule"}, headers=b)
    assert sent_back.status_code == 200 and sent_back.json()["status"] == "draft"
    assert client.post(f"/v1/rules/versions/{draft['id']}/request-approval", json={"reason": "Try again"}, headers=a).status_code == 200
    assert client.post(f"/v1/rules/versions/{draft['id']}/publish", json={"reason": "My own version"}, headers=a).status_code == 403
    published = client.post(f"/v1/rules/versions/{draft['id']}/publish", json={"reason": "Diff checked"}, headers=b)
    assert published.status_code == 200 and published.json()["approved_by"] == str(approver.user_id)
    assert client.patch(f"/v1/rules/versions/{draft['id']}", json={"dsl": RULES_V1}, headers=a).status_code == 409
    assert client.post(f"/v1/rules/versions/{draft['id']}/publish", json={"reason": "Publish again"}, headers=b).status_code == 409

    listed = client.get("/v1/rules/versions", headers=a).json()["items"]
    assert [(v["version_no"], v["status"], v["is_active"]) for v in listed] == [(2, "published", True), (1, "retired", False)]
    sets = client.get("/v1/rules/sets", headers=a).json()
    assert sets[0]["active_version_no"] == 2 and sets[0]["program_slug"] == "rahat"

    with open_session(SYSTEM) as db:
        actions = [r.action for r in db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id)
                                                 .order_by(models.AuditLog.seq)).all()]  # fmt: skip
        approvals = db.scalars(select(models.Approval).where(models.Approval.tenant_id == tenant.id).order_by(models.Approval.created_at)).all()
    assert [x for x in actions if x.startswith("rules.")] == [
        "rules.draft_created", "rules.draft_updated", "rules.approval_requested", "rules.approval_rejected",
        "rules.approval_requested", "rules.version_published",
    ]  # fmt: skip
    assert "access.denied" in actions
    assert sorted(a.status for a in approvals) == ["approved", "rejected"]


def test_invalid_rules_cannot_be_sent_for_approval(client: TestClient, factory: Any) -> None:
    _, author, _, setup = _setup(factory)
    h = factory.headers(client, author)
    bad = copy.deepcopy(RULES_V1)
    bad["all"][1]["expr"] = {"<=": [{"var": "income"}, {"param": "income_cap"}]}
    check = client.post("/v1/rules/validate", json={"dsl": bad}, headers=h).json()
    assert not check["valid"] and check["errors"][0]["code"] == "unknown_variable" and "verified_income_pkr" in check["errors"][0]["message"]
    draft = _draft(client, factory, author, setup.v1_id, bad)
    assert not draft["valid"]
    refused = client.post(f"/v1/rules/versions/{draft['id']}/request-approval", json={"reason": "Ship it"}, headers=h)
    assert refused.status_code == 422 and refused.json()["errors"][0]["path"] == "$.all[1].expr.<=[0].var"
    stored = client.post(f"/v1/rules/versions/{draft['id']}/validate", headers=h).json()
    assert not stored["valid"]


def test_dry_run_decides_without_storing(client: TestClient, factory: Any) -> None:
    tenant, author, _, setup = _setup(factory)
    h = factory.headers(client, author)
    lower = copy.deepcopy(RULES_V1)
    lower["params"]["income_cap"] = 20000
    draft = _draft(client, factory, author, setup.v1_id, lower)
    case = base_input(registry=registry(verified_income_pkr=25_000)).model_dump(mode="json")
    on_draft = client.post(f"/v1/rules/versions/{draft['id']}/dry-run", json={"input": case}, headers=h)
    on_active = client.post(f"/v1/rules/versions/{setup.v1_id}/dry-run", json={"input": case}, headers=h)
    assert on_draft.status_code == 200, on_draft.text
    assert on_active.json()["result"]["outcome"] == "approved"
    assert on_draft.json()["result"]["outcome"] != "approved"
    with open_session(SYSTEM) as db:
        assert db.scalars(select(models.Decision).where(models.Decision.tenant_id == tenant.id)).all() == []


def test_rollback_is_a_new_version_that_needs_a_second_admin(client: TestClient, factory: Any) -> None:
    _, author, approver, setup = _setup(factory)
    a, b = factory.headers(client, author), factory.headers(client, approver)
    changed = copy.deepcopy(RULES_V1)
    changed["payment_pkr"] = 9000
    draft = _draft(client, factory, author, setup.v1_id, changed)
    client.post(f"/v1/rules/versions/{draft['id']}/request-approval", json={"reason": "Smaller payment"}, headers=a)
    assert client.post(f"/v1/rules/versions/{draft['id']}/publish", json={"reason": "Approved"}, headers=b).status_code == 200

    assert client.post(f"/v1/rules/versions/{draft['id']}/rollback", json={"reason": "x" * 5}, headers=a).status_code == 201  # to itself: allowed
    rolled = client.post(f"/v1/rules/versions/{setup.v1_id}/rollback", json={"reason": "Payment cut was a mistake"}, headers=b)
    assert rolled.status_code == 201, rolled.text
    body = rolled.json()
    assert body["version_no"] == 4 and body["status"] == "pending_approval" and body["dsl"] == RULES_V1
    assert body["parent_version_id"] == str(setup.v1_id)
    assert client.post(f"/v1/rules/versions/{body['id']}/publish", json={"reason": "My own rollback"}, headers=b).status_code == 403
    done = client.post(f"/v1/rules/versions/{body['id']}/publish", json={"reason": "Rollback checked"}, headers=a)
    assert done.status_code == 200 and done.json()["is_active"] and done.json()["dsl"]["payment_pkr"] == 12000
    assert client.post(f"/v1/rules/versions/{draft['id']}/rollback", json={"reason": "Not a draft"}, headers=a).status_code == 201


def test_access_is_admin_only_and_per_department(client: TestClient, factory: Any) -> None:
    tenant, author, _, setup = _setup(factory)
    officer, auditor = factory.account(tenant, "officer"), factory.account(tenant, "auditor")
    assert client.get("/v1/rules/versions", headers=factory.headers(client, officer)).status_code == 403
    assert client.get(f"/v1/rules/versions/{setup.v1_id}", headers=factory.headers(client, auditor)).status_code == 200
    assert client.post("/v1/rules/versions", json={"parent_version_id": str(setup.v1_id)},
                       headers=factory.headers(client, auditor)).status_code == 403  # fmt: skip
    outsider = factory.account(factory.tenant(), "admin")
    assert client.get(f"/v1/rules/versions/{setup.v1_id}", headers=factory.headers(client, outsider)).status_code == 404
    assert client.post("/v1/rules/versions", json={"parent_version_id": str(setup.v1_id)},
                       headers=factory.headers(client, outsider)).status_code == 404  # fmt: skip
    extra = client.post("/v1/rules/versions", json={"parent_version_id": str(setup.v1_id), "status": "published"},
                        headers=factory.headers(client, author))  # fmt: skip
    assert extra.status_code == 422  # unknown fields are refused
