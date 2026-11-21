"""Rate limits answer 429 with Retry-After and a plain message: per network, per user, per department, per API key."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.policy import describe_routes
from tests.security.support import png_bytes


def _assert_limited(response: Any, scope: str) -> dict[str, Any]:
    assert response.status_code == 429, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    retry = int(response.headers["retry-after"])
    body = response.json()
    assert retry >= 1 and body["retry_after_seconds"] == retry
    assert body["code"] == "rate_limited" and body["limit_scope"] == scope, body
    assert body["detail"].startswith(("Too many", "You are", "This API key", "Your department")) and "Wait" in body["detail"]
    assert "Traceback" not in response.text
    return body


def test_anonymous_calls_are_limited_per_network_and_health_is_exempt(app: Any, client: TestClient, strict_limits: Callable[..., None]) -> None:
    strict_limits(anonymous=3)
    for _ in range(3):
        assert client.get("/v1/system/info").status_code == 200
    _assert_limited(client.get("/v1/system/info"), "ip")
    _assert_limited(client.post("/v1/notifications/verify", json={"code": "ABCD1234"}), "ip")
    for path in ("/healthz", "/readyz", "/metrics", "/openapi.json", "/docs"):
        assert client.get(path).status_code == 200, f"{path} must never be rate limited"

    with TestClient(app, client=("203.0.113.9", 40000)) as elsewhere:
        assert elsewhere.get("/v1/system/info").status_code == 200, "another network has its own bucket"


def test_probing_for_endpoints_counts_against_the_network(client: TestClient, strict_limits: Callable[..., None]) -> None:
    strict_limits(anonymous=3)
    assert client.get("/v1/no-such-endpoint").status_code == 404
    assert client.get("/v1/another-guess").status_code == 404
    assert client.delete("/v1/system/info").status_code == 405
    _assert_limited(client.get("/v1/third-guess"), "ip")
    assert client.get("/healthz").status_code == 200


def test_failed_credentials_count_against_the_network(client: TestClient, strict_limits: Callable[..., None]) -> None:
    strict_limits(anonymous=3)
    for token in ("not-a-token", "rk_0123456789_" + "A" * 43, "eyJhbGciOiJub25lIn0.e30."):
        assert client.get("/v1/cases", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    _assert_limited(client.get("/v1/cases", headers={"Authorization": "Bearer guess-number-four"}), "ip")


def test_each_user_has_a_bucket(client: TestClient, factory: Any, strict_limits: Callable[..., None]) -> None:
    tenant = factory.tenant()
    first, second = factory.headers(client, factory.account(tenant, "officer")), factory.headers(client, factory.account(tenant, "officer"))
    strict_limits(user=3)
    for _ in range(3):
        assert client.get("/v1/cases", headers=first).status_code == 200
    body = _assert_limited(client.get("/v1/cases", headers=first), "user")
    assert body["limit_per_minute"] == 3
    assert client.get("/v1/cases", headers=second).status_code == 200, "a colleague is not slowed down"


def test_a_departments_staff_share_one_lane(client: TestClient, factory: Any, strict_limits: Callable[..., None]) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    first, second = factory.headers(client, factory.account(tenant, "officer")), factory.headers(client, factory.account(tenant, "officer"))
    outsider = factory.headers(client, factory.account(other, "officer"))
    citizen = factory.headers(client, factory.account(tenant, "citizen"))
    strict_limits(user=100, tenant=4)
    for headers in (first, first, second, second):
        assert client.get("/v1/cases", headers=headers).status_code == 200
    _assert_limited(client.get("/v1/cases", headers=second), "tenant")
    assert client.get("/v1/cases", headers=outsider).status_code == 200, "another department is not affected"
    assert client.get("/v1/applications", headers=citizen).status_code == 200, "citizens have their own lane"


def test_a_crowd_of_citizen_accounts_cannot_lock_officers_out(client: TestClient, factory: Any, strict_limits: Callable[..., None]) -> None:
    """Regression: citizens and staff shared one department lane, and anyone can register a citizen account."""
    tenant = factory.tenant()
    crowd = [factory.headers(client, factory.account(tenant, "citizen")) for _ in range(3)]
    officer = factory.headers(client, factory.account(tenant, "officer"))
    strict_limits(user=100, tenant=6)
    for headers in crowd * 2:
        assert client.get("/v1/applications", headers=headers).status_code == 200
    _assert_limited(client.get("/v1/applications", headers=crowd[0]), "tenant")
    assert client.get("/v1/cases", headers=officer).status_code == 200, "the staff lane is untouched"


def test_replaying_a_refused_key_cannot_flood_the_audit_log(client: TestClient, factory: Any, strict_limits: Callable[..., None]) -> None:
    """Regression: a refused key was recorded before the rate limit was charged, so 429s still wrote audit rows."""
    from app.db import models
    from app.modules.cases import testing as case_data

    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    created = client.post("/v1/admin/api-keys", headers=admin, json={"name": "Old partner", "scopes": ["payments:read"]}).json()
    client.post(f"/v1/admin/api-keys/{created['id']}/revoke", headers=admin)
    strict_limits(anonymous=2)
    forged = f"rk_{created['prefix']}_{'Q' * 43}"
    statuses = [client.get("/v1/payments", headers={"X-API-Key": raw}).status_code for raw in [forged] * 6 + [created["key"]] * 6]
    assert statuses.count(401) == 2 and statuses.count(429) == 10
    denied = case_data.rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "access.denied")
    events = case_data.rows(models.SecurityEvent, models.SecurityEvent.tenant_id == tenant.id)
    assert len(denied) == 2 and len(events) == 2, "only the attempts that were answered are recorded"


def test_an_api_key_has_its_own_limit_and_cannot_starve_the_officers(client: TestClient, factory: Any,
                                                                     strict_limits: Callable[..., None]) -> None:  # fmt: skip
    tenant = factory.tenant()
    admin, officer = factory.headers(client, factory.account(tenant, "admin")), factory.headers(client, factory.account(tenant, "officer"))
    strict_limits(tenant=5)
    key = client.post("/v1/admin/api-keys", headers=admin, json={"name": "Busy partner", "scopes": ["payments:read"],
                                                                 "rate_limit_per_minute": 2}).json()["key"]  # fmt: skip
    for _ in range(2):
        assert client.get("/v1/payments", headers={"X-API-Key": key}).status_code == 200
    body = _assert_limited(client.get("/v1/payments", headers={"X-API-Key": key}), "api_key")
    assert body["limit_per_minute"] == 2 and "2 requests a minute" in body["detail"]
    assert client.get("/v1/payments", headers=officer).status_code == 200, "people and keys use separate department lanes"


def test_costly_routes_count_as_several_requests(client: TestClient, factory: Any, strict_limits: Callable[..., None], app: Any) -> None:
    costs = {(r["method"], r["path"]): r["cost"] for r in describe_routes(app)}
    assert costs[("POST", "/v1/applications/{application_id}/documents")] == 10
    citizen = factory.headers(client, factory.account(factory.tenant(), "citizen"))
    strict_limits(user=12)
    upload = {"files": {"file": ("card.png", png_bytes(), "image/png")}, "data": {"kind": "rahat_id"}}
    first = client.post("/v1/applications/00000000-0000-4000-8000-000000000001/documents", headers=citizen, **upload)
    assert first.status_code == 404, "the first upload is admitted (ten of twelve) and then finds no application"
    _assert_limited(client.post("/v1/applications/00000000-0000-4000-8000-000000000001/documents", headers=citizen, **upload), "user")
    assert client.get("/v1/applications", headers=citizen).status_code == 200, "two single requests are still left"


def test_sign_in_keeps_its_own_stricter_throttle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.modules.auth import service as auth_service

    monkeypatch.setattr(get_settings(), "login_ip_attempts_per_minute", 2)
    auth_service._ip_hits.clear()
    try:
        attempt = {"identifier": "nobody-throttle@test.rahat.example", "secret": "wrong"}
        assert [client.post("/v1/auth/login", json=attempt).status_code for _ in range(2)] == [401, 401]
        throttled = client.post("/v1/auth/login", json=attempt)
        assert throttled.status_code == 429 and throttled.headers["retry-after"] == "60"
        assert throttled.json()["detail"].startswith("Too many sign-in attempts")
    finally:
        auth_service._ip_hits.clear()


def test_admins_see_their_departments_current_use(client: TestClient, factory: Any, strict_limits: Callable[..., None]) -> None:
    tenant = factory.tenant()
    admin_account, officer_account = factory.account(tenant, "admin"), factory.account(tenant, "officer")
    admin, officer = factory.headers(client, admin_account), factory.headers(client, officer_account)
    strict_limits(user=50, tenant=500)
    created = client.post("/v1/admin/api-keys", headers=admin, json={"name": "Usage probe", "scopes": ["payments:read"],
                                                                     "rate_limit_per_minute": 10}).json()  # fmt: skip
    for _ in range(3):
        client.get("/v1/cases", headers=officer)
        client.get("/v1/payments", headers={"X-API-Key": created["key"]})

    usage = client.get("/v1/admin/rate-limits", headers=admin)
    assert usage.status_code == 200
    body = usage.json()
    people = {p["user_id"]: p for p in body["people"]}
    officer_bucket = people[str(officer_account.user_id)]
    assert 47 <= officer_bucket["remaining"] < 50 and officer_bucket["per_minute"] == 50 and officer_bucket["display_name"]
    assert [(k["name"], k["per_minute"]) for k in body["api_keys"]] == [("Usage probe", 10)]
    assert 7 <= body["api_keys"][0]["remaining"] < 10, "three calls taken, refilling slowly"
    assert {lane["label"] for lane in body["department"]} == {"staff", "api_keys"}, "lanes appear once used"
    assert body["api_calls_this_month"] == 3 and body["limits"]["user_per_minute"] == 50
    assert {"method": "POST", "path": "/v1/applications/{application_id}/documents", "cost": 10} in body["costly_routes"]
    assert created["key"] not in usage.text
