"""Admins set the four-eyes limit; officers and auditors can read it; nobody else can change it."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def test_an_admin_lowers_the_limit_and_it_is_audited(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    admin, officer, citizen = factory.account(tenant, "admin"), factory.account(tenant, "officer"), factory.account(tenant, "citizen")
    admin_h, officer_h = factory.headers(client, admin), factory.headers(client, officer)

    assert client.get("/v1/admin/payment-settings", headers=officer_h).json() == {"four_eyes_limit_pkr": 15000}
    body = {"four_eyes_limit_pkr": 10000, "reason": "Demo: every payment needs two officers"}
    changed = client.put("/v1/admin/payment-settings", headers=admin_h, json=body)
    assert changed.status_code == 200 and changed.json() == {"four_eyes_limit_pkr": 10000}
    assert client.get("/v1/admin/payment-settings", headers=officer_h).json()["four_eyes_limit_pkr"] == 10000

    refused = client.put("/v1/admin/payment-settings", headers=officer_h, json={"four_eyes_limit_pkr": 1, "reason": "trying it"})
    assert refused.status_code == 403
    assert client.get("/v1/admin/payment-settings", headers=factory.headers(client, citizen)).status_code == 403
    assert client.put("/v1/admin/payment-settings", headers=admin_h, json={"four_eyes_limit_pkr": 5000}).status_code == 422, "a reason is required"

    auditor = factory.account(tenant, "auditor")
    trail = client.get("/v1/audit", headers=factory.headers(client, auditor), params={"action": "payments.four_eyes_limit_changed"}).json()["items"]
    assert trail and trail[0]["details"] == {"from_pkr": 15000, "to_pkr": 10000} and trail[0]["reason"].startswith("Demo")
