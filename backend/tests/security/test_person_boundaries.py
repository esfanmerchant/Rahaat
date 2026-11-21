"""Inside one department: a person reaches only their own records, a helper only the families that delegated to
them, and a withdrawn consent stops officers, helpers and API keys on the very next request."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import apikeys
from app.core.db import system_session
from app.core.security import decode_access_token
from app.db import models
from app.modules.cases import testing as case_data
from tests.security import support
from tests.security.support import PARAM, World

PERSON_ID_ROUTES = [r for r in support.protected_routes() if PARAM.search(r["path"]) and "citizen" in r["roles"]]


@pytest.fixture(scope="module")
def neighbour(world: World) -> dict[str, Any]:
    """A second citizen in department A, with an application, a consent and a session of their own."""
    account = world.factory.account(world.a.tenant, "citizen")
    program_id, _ = case_data.program(world.a.tenant_id)
    application_id = case_data.application(world.a.tenant_id, account.person_id, program_id, status="draft")
    with system_session() as db:
        consent_id = db.scalar(select(models.Consent.id).where(models.Consent.person_id == account.person_id))
    session_id = decode_access_token(world.factory.login(world.client, account)["access_token"]).session_id
    ids = {"application_id": application_id, "consent_id": consent_id, "session_id": session_id}
    return {"account": account, "ids": ids, "markers": {str(v) for v in ids.values()} | {str(account.person_id)}}


@pytest.mark.parametrize("route", PERSON_ID_ROUTES, ids=support.route_id)
def test_a_citizen_cannot_reach_another_persons_records(world: World, neighbour: dict[str, Any], route: dict[str, Any]) -> None:
    params = PARAM.findall(route["path"])
    assert all(p in neighbour["ids"] for p in params), f"add a {params} of a second person to the neighbour fixture"
    world.warm()
    before = support.fingerprint(world.a)
    response = world.call(route["method"], support.fill(route["path"], neighbour["ids"]), side=world.a, who="citizen", template=route["path"])
    assert response.status_code in (403, 404), f"{response.status_code} {response.text[:300]}"
    assert not support.leaked(response.text, neighbour["markers"])
    assert support.fingerprint(world.a) == before


def test_a_helper_reaches_only_the_families_that_delegated_to_them(world: World, neighbour: dict[str, Any]) -> None:
    helper = {**world.headers(world.a, "helper"), "X-Acting-For": str(neighbour["account"].person_id)}
    heads = support.audit_heads(world.a)
    for method, path in (("GET", "/v1/me/person"), ("GET", "/v1/applications"), ("GET", "/v1/consents"),
                         ("GET", f"/v1/applications/{neighbour['ids']['application_id']}"),
                         ("POST", f"/v1/consents/{neighbour['ids']['consent_id']}/withdraw")):  # fmt: skip
        response = world.client.request(method, path, headers=helper)
        assert response.status_code == 403 and response.json()["code"] == "no_delegation", f"{method} {path}: {response.text}"
        assert not support.leaked(response.text, neighbour["markers"] - {str(neighbour["account"].person_id)})
    denied = support.audit_since(heads)
    assert len(denied) == 5 and {row.reason for row in denied} == {"no_delegation"}

    own_family = world.client.get("/v1/me/person", headers=world.headers(world.a, "helper"))
    assert own_family.status_code == 200, "the helper still reaches the family that did delegate"


def test_withdrawal_stops_officers_helpers_and_api_keys_on_the_next_request(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen, officer, helper = factory.account(tenant, "citizen"), factory.account(tenant, "officer"), factory.account(tenant, "helper")
    case = case_data.review_case(tenant.id, citizen.person_id)
    raw, prefix, digest = apikeys.generate()
    with system_session() as db:
        db.add(models.HelperDelegation(tenant_id=tenant.id, helper_user_id=helper.user_id, person_id=citizen.person_id,
                                       scopes=["track", "apply", "upload"], expires_at=datetime.now(UTC) + timedelta(days=1)))  # fmt: skip
        db.add(models.ApiKey(id=uuid.uuid4(), tenant_id=tenant.id, name="NGO sync", prefix=prefix, key_hash=digest, scopes=["cases:read"],
                             rate_limit_per_min=100, expires_at=datetime.now(UTC) + timedelta(days=1)))  # fmt: skip
        consent_id = db.scalar(select(models.Consent.id).where(models.Consent.person_id == citizen.person_id))
    readers = {
        "officer": ("GET", f"/v1/cases/{case['case_id']}", factory.headers(client, officer)),
        "helper": ("GET", "/v1/me/person", {**factory.headers(client, helper), "X-Acting-For": str(citizen.person_id)}),
    }
    for who, (method, path, headers) in readers.items():
        assert client.request(method, path, headers=headers).status_code == 200, f"{who} reads while consent is active"
    queue = client.get("/v1/cases", headers={"X-API-Key": raw})
    assert queue.status_code == 200 and queue.json()["items"][0]["subject_name"] == "Test Citizen", "the key sees the person"

    withdrawn = client.post(f"/v1/consents/{consent_id}/withdraw", headers=factory.headers(client, citizen))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn"

    for who, (method, path, headers) in readers.items():
        blocked = client.request(method, path, headers=headers)
        assert blocked.status_code == 403 and blocked.json()["code"] == "consent_required", f"{who}: {blocked.text}"
    after = client.get("/v1/cases", headers={"X-API-Key": raw}).json()["items"]
    assert after[0]["subject_name"] is None, "the key no longer reads the person: the database hides the row"
    trail = case_data.rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id)
    assert any(r.action == "consent.withdrawn" for r in trail)
    refused = [r for r in trail if r.action == "access.denied" and r.reason == "consent_required"]
    assert len(refused) == 2, "each blocked read is on the record"
