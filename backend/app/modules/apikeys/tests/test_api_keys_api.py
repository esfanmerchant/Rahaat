"""API keys through the HTTP API: issued once, scoped, metered, stopped at once by revocation and expiry."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core import apikeys
from app.core.db import system_session
from app.db import models
from app.modules.cases import testing as case_data

KEYS = "/v1/admin/api-keys"


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def _create(client: TestClient, headers: dict[str, str], **body: Any) -> dict[str, Any]:
    response = client.post(KEYS, headers=headers, json={"name": "Partner sync", "scopes": ["payments:read"], **body})
    assert response.status_code == 201, response.text
    return response.json()


def _calls_this_month(tenant_id: Any) -> int:
    with system_session() as db:
        count = db.scalar(select(models.UsageCounter.count).where(
            models.UsageCounter.tenant_id == tenant_id, models.UsageCounter.metric == "api_calls",
            models.UsageCounter.period == apikeys.period(datetime.now(UTC))))  # fmt: skip
    return int(count or 0)


def _audit(tenant_id: Any) -> list[models.AuditLog]:
    return case_data.rows(models.AuditLog, models.AuditLog.tenant_id == tenant_id)


def test_a_key_is_shown_once_works_for_its_scope_and_is_metered(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    created = client.post(KEYS, headers=admin, json={"name": "Reconciliation", "scopes": ["payments:read"], "rate_limit_per_minute": 30})
    assert created.status_code == 201 and created.headers["cache-control"] == "no-store"
    body = created.json()
    raw = body["key"]
    assert raw.startswith(f"rk_{body['prefix']}_") and body["status"] == "active" and body["scopes"] == ["payments:read"]
    assert body["rate_limit_per_minute"] == 30 and body["expires_at"], "every key expires"

    listed = client.get(KEYS, headers=admin)
    assert listed.status_code == 200 and [k["id"] for k in listed.json()] == [body["id"]]
    assert raw not in listed.text and "key" not in listed.json()[0], "the secret is shown once, at creation"
    assert raw not in client.get(f"{KEYS}/{body['id']}", headers=admin).text

    for headers in (_bearer(raw), {"X-API-Key": raw}):
        response = client.get("/v1/payments", headers=headers)
        assert response.status_code == 200 and response.json()["items"] == []
    assert _calls_this_month(tenant.id) == 2, "each admitted call is metered for the department"
    key = case_data.get(models.ApiKey, body["id"])
    assert key.last_used_at is not None
    created_rows = [r for r in _audit(tenant.id) if r.action == "apikey.created"]
    assert len(created_rows) == 1 and created_rows[0].object_id == body["id"]


def test_a_key_cannot_reach_a_route_outside_its_scopes(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    raw = _create(client, factory.headers(client, factory.account(tenant, "admin")))["key"]
    for path in ("/v1/cases", "/v1/auth/me", "/v1/programs", KEYS, "/v1/audit"):
        refused = client.get(path, headers=_bearer(raw))
        assert refused.status_code == 403 and refused.json()["code"] == "api_scope_missing", path
    assert _calls_this_month(tenant.id) == 0, "refused calls are not metered"
    denied = [r for r in _audit(tenant.id) if r.action == "access.denied"]
    assert len(denied) == 5 and {r.actor_type for r in denied} == {"api_key"} and {r.actor_role for r in denied} == {"api_client"}
    assert {r.reason for r in denied} == {"api_scope_missing"}


def test_revoking_a_key_stops_it_on_the_very_next_request(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    created = _create(client, admin)
    assert client.get("/v1/payments", headers=_bearer(created["key"])).status_code == 200

    revoked = client.post(f"{KEYS}/{created['id']}/revoke", headers=admin, json={"reason": "partner contract ended"})
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    after = client.get("/v1/payments", headers=_bearer(created["key"]))
    assert after.status_code == 401 and after.json()["code"] == "api_key_revoked"
    assert client.post(f"{KEYS}/{created['id']}/revoke", headers=admin).json()["status"] == "revoked", "revoking twice is harmless"

    actions = [(r.action, r.reason) for r in _audit(tenant.id)]
    assert ("apikey.revoked", "partner contract ended") in actions
    assert ("access.denied", "api_key_revoked") in actions, "the refused use is recorded even though the request failed"
    assert client.get(KEYS, headers=admin).json() == [], "revoked keys are hidden unless asked for"
    assert client.get(KEYS, headers=admin, params={"include_inactive": True}).json()[0]["status"] == "revoked"


def test_an_expired_key_stops_at_once(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    created = _create(client, factory.headers(client, factory.account(tenant, "admin")), expires_in_days=1)
    assert client.get("/v1/payments", headers=_bearer(created["key"])).status_code == 200
    with system_session() as db:
        db.execute(update(models.ApiKey).where(models.ApiKey.id == created["id"]).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    refused = client.get("/v1/payments", headers=_bearer(created["key"]))
    assert refused.status_code == 401 and refused.json()["code"] == "api_key_expired"


def test_a_key_of_a_suspended_department_stops(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    created = _create(client, factory.headers(client, factory.account(tenant, "admin")))
    with system_session() as db:
        db.execute(update(models.Tenant).where(models.Tenant.id == tenant.id).values(status="suspended"))
    refused = client.get("/v1/payments", headers=_bearer(created["key"]))
    assert refused.status_code == 401 and refused.json()["code"] == "api_key_tenant_inactive"


def test_rotation_replaces_the_secret_and_the_old_key_stops(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    old = _create(client, admin, rate_limit_per_minute=25, expires_in_days=30)
    rotated = client.post(f"{KEYS}/{old['id']}/rotate", headers=admin, json={"reason": "yearly rotation"})
    assert rotated.status_code == 201
    new = rotated.json()
    assert new["key"] != old["key"] and new["prefix"] != old["prefix"]
    assert (new["name"], new["scopes"], new["rate_limit_per_minute"]) == (old["name"], old["scopes"], 25)
    assert client.get("/v1/payments", headers=_bearer(new["key"])).status_code == 200
    assert client.get("/v1/payments", headers=_bearer(old["key"])).json()["code"] == "api_key_revoked"
    again = client.post(f"{KEYS}/{old['id']}/rotate", headers=admin)
    assert again.status_code == 409 and again.json()["code"] == "api_key_revoked", "a revoked key cannot be brought back by rotating it"

    graced = _create(client, admin)
    replacement = client.post(f"{KEYS}/{graced['id']}/rotate", headers=admin, json={"grace_minutes": 30}).json()
    assert client.get("/v1/payments", headers=_bearer(graced["key"])).status_code == 200, "the old key works during the grace period"
    assert client.get("/v1/payments", headers=_bearer(replacement["key"])).status_code == 200
    ending = case_data.get(models.ApiKey, graced["id"])
    assert ending.revoked_at is None and ending.expires_at <= datetime.now(UTC) + timedelta(minutes=31)
    rotations = [r for r in _audit(tenant.id) if r.action == "apikey.rotated"]
    assert {r.object_id for r in rotations} == {old["id"], graced["id"]}


def test_a_key_that_reads_personal_data_needs_a_second_admin(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    first, second = factory.account(tenant, "admin"), factory.account(tenant, "admin")
    first_headers, second_headers = factory.headers(client, first), factory.headers(client, second)
    citizen = factory.account(tenant, "citizen")
    case = case_data.review_case(tenant.id, citizen.person_id)

    pending = _create(client, first_headers, name="NGO case sync", scopes=["cases:read"])
    assert pending["status"] == "pending_approval" and pending["scopes"] == [] and pending["requested_scopes"] == ["cases:read"]
    waiting = client.get("/v1/cases", headers=_bearer(pending["key"]))
    assert waiting.status_code == 403 and waiting.json()["code"] == "api_key_pending_approval"

    self_approval = client.post(f"{KEYS}/{pending['id']}/decide", headers=first_headers, json={"approve": True, "reason": "please"})
    assert self_approval.status_code == 403 and self_approval.json()["code"] == "second_admin_required"
    approved = client.post(f"{KEYS}/{pending['id']}/decide", headers=second_headers, json={"approve": True, "reason": "agreement signed"})
    assert approved.status_code == 200 and approved.json()["status"] == "active" and approved.json()["scopes"] == ["cases:read"]

    queue = client.get("/v1/cases", headers=_bearer(pending["key"]))
    assert queue.status_code == 200 and [c["id"] for c in queue.json()["items"]] == [str(case["case_id"])]
    assert client.get(f"/v1/cases/{case['case_id']}", headers=_bearer(pending["key"])).status_code == 200
    assert client.get("/v1/payments", headers=_bearer(pending["key"])).status_code == 403, "cases:read does not open payments"

    case_data.set_consent(citizen.person_id, "withdrawn")
    blocked = client.get(f"/v1/cases/{case['case_id']}", headers=_bearer(pending["key"]))
    assert blocked.status_code == 403 and blocked.json()["code"] == "consent_required", "a key loses access with the consent"
    assert client.get("/v1/cases", headers=_bearer(pending["key"])).json()["items"][0]["subject_name"] is None

    viewed = [r for r in _audit(tenant.id) if r.action == "case.viewed"]
    assert viewed and viewed[0].actor_type == "api_key" and viewed[0].actor_id == pending["id"], "a key is never recorded as a person"


def test_a_refused_approval_revokes_the_key(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    first, second = factory.account(tenant, "admin"), factory.account(tenant, "admin")
    pending = _create(client, factory.headers(client, first), scopes=["cases:read"])
    refused = client.post(f"{KEYS}/{pending['id']}/decide", headers=factory.headers(client, second),
                          json={"approve": False, "reason": "no agreement"})  # fmt: skip
    assert refused.status_code == 200 and refused.json()["status"] == "revoked"
    assert client.get("/v1/cases", headers=_bearer(pending["key"])).json()["code"] == "api_key_revoked"


def test_wrong_secrets_and_malformed_keys_are_refused_and_misuse_is_recorded(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    created = _create(client, factory.headers(client, factory.account(tenant, "admin")))
    forged = f"rk_{created['prefix']}_{'A' * 43}"
    for raw in (forged, "rk_0123456789_" + "B" * 43, "rk_not-a-key", "rk_" + "x" * 300):
        refused = client.get("/v1/payments", headers=_bearer(raw))
        assert refused.status_code == 401 and refused.json()["code"] == "invalid_api_key", raw
        assert refused.json()["detail"] == "This API key is not valid.", "the same answer whether or not the prefix exists"
    both = client.get("/v1/payments", headers={**_bearer(created["key"]), "X-API-Key": created["key"]})
    assert both.status_code == 401 and both.json()["code"] == "ambiguous_credentials"

    misuse = case_data.rows(models.SecurityEvent, models.SecurityEvent.tenant_id == tenant.id)
    assert [e.kind for e in misuse] == ["api_key_misuse"], "only the attempt on a real prefix is a security event"
    assert [r.reason for r in _audit(tenant.id) if r.action == "access.denied"] == ["api_key_invalid"]


def test_key_management_is_validated_and_tenant_scoped(client: TestClient, factory: Any) -> None:
    mine, theirs = factory.tenant(), factory.tenant()
    admin = factory.headers(client, factory.account(mine, "admin"))
    their_key = _create(client, factory.headers(client, factory.account(theirs, "admin")))
    for verb, suffix in (("get", ""), ("post", "/rotate"), ("post", "/revoke"), ("post", "/decide")):
        kwargs = {"json": {"approve": True, "reason": "looks fine"}} if suffix == "/decide" else {}
        response = getattr(client, verb)(f"{KEYS}/{their_key['id']}{suffix}", headers=admin, **kwargs)
        assert response.status_code == 404, f"{verb} {suffix}: another department's key is not found"
    assert client.get("/v1/payments", headers=_bearer(their_key["key"])).status_code == 200, "and it still works"

    bad_bodies = [
        ({"name": "x", "scopes": ["payments:read"]}, "invalid_input"),
        ({"name": "Partner", "scopes": []}, "invalid_input"),
        ({"name": "Partner", "scopes": ["cases:write"]}, "unknown_scope"),
        ({"name": "Partner", "scopes": ["scam:check"]}, "scope_not_available"),
        ({"name": "Partner", "scopes": ["payments:read"], "rate_limit_per_minute": 100_000}, "invalid_input"),
        ({"name": "Partner", "scopes": ["payments:read"], "expires_in_days": 0}, "invalid_input"),
        ({"name": "Partner", "scopes": ["payments:read"], "never_expires": True}, "invalid_input"),
    ]
    for body, code in bad_bodies:
        response = client.post(KEYS, headers=admin, json=body)
        assert response.status_code == 422 and response.json()["code"] == code, body
    scopes = {s["name"]: s for s in client.get(f"{KEYS}/scopes", headers=admin).json()}
    assert scopes["cases:read"]["needs_second_admin"] and "GET /v1/cases/{case_id}" in scopes["cases:read"]["endpoints"]
    assert scopes["payments:read"]["endpoints"] == ["GET /v1/payments"]


def test_keys_are_never_stored_or_logged_in_clear(client: TestClient, factory: Any, caplog: pytest.LogCaptureFixture) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    caplog.set_level(logging.DEBUG)
    created = _create(client, admin)
    raw, secret = created["key"], created["key"].split("_", 2)[2]
    client.get("/v1/payments", headers=_bearer(raw))
    client.get("/v1/cases", headers={"X-API-Key": raw})
    client.post(f"{KEYS}/{created['id']}/rotate", headers=admin)

    with system_session() as db:
        stored = db.execute(select(models.ApiKey).where(models.ApiKey.tenant_id == tenant.id)).scalars().all()
        dumped = " ".join(str({c.name: getattr(k, c.key) for c in models.ApiKey.__table__.columns}) for k in stored)
        audit_rows = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id))
        trail = " ".join(f"{r.details} {r.reason} {r.object_id}" for r in audit_rows)
    assert secret not in dumped and raw not in dumped and created["prefix"] in dumped, "only the prefix and a hash are kept"
    assert secret not in trail
    logged = " ".join(f"{r.getMessage()} {r.args}" for r in caplog.records)
    assert secret not in logged, "the key is never written to a log"
