"""The live security probes and the department's security events, through the HTTP API."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.db import models
from app.modules.cases import testing as case_data

PROBES = "/v1/admin/security/probes"


def _run(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(PROBES, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_database_refuses_every_bypass_and_the_run_is_audited(client: TestClient, factory: Any) -> None:
    mine, theirs = factory.tenant(), factory.tenant()
    case_data.review_case(theirs.id, factory.account(theirs, "citizen").person_id)  # another department has data to hide
    for role in ("admin", "auditor"):
        body = _run(client, factory.headers(client, factory.account(mine, role)))
        results = {p["name"]: p for p in body["probes"]}
        enforced = {name: p for name, p in results.items() if name != "consent_function_is_safe"}
        assert all(p["passed"] for p in enforced.values()), {n: p["evidence"] for n, p in enforced.items() if not p["passed"]}
        assert results["runtime_role"]["evidence"]["role"] == "rahat_app"
        assert set(results["no_context_sees_nothing"]["evidence"]["rows_visible"].values()) == {0}
        assert "must be owner" in results["rls_cannot_be_disabled"]["evidence"]["database_said"]
        assert "permission denied" in results["audit_is_append_only"]["evidence"]["database_said"]
        assert "row-level security" in results["row_security_off_is_refused"]["evidence"]["database_said"]
        assert results["other_departments_invisible"]["evidence"]["other_departments_cases"] == 0
    runs = sorted(case_data.rows(models.AuditLog, models.AuditLog.tenant_id == mine.id, models.AuditLog.action == "security.probes_run"),
                  key=lambda r: r.seq)  # fmt: skip
    assert len(runs) == 2 and runs[-1].seq == body["audit_seq"]


def test_the_consent_function_cannot_be_hijacked_by_a_temporary_table(client: TestClient, factory: Any) -> None:
    body = _run(client, factory.headers(client, factory.account(factory.tenant(), "admin")))
    assert {p["name"]: p["passed"] for p in body["probes"]}["consent_function_is_safe"]


def test_security_events_show_refused_key_use_in_this_department_only(client: TestClient, factory: Any) -> None:
    mine, theirs = factory.tenant(), factory.tenant()
    admin = factory.headers(client, factory.account(mine, "admin"))
    for tenant in (mine, theirs):
        owner = admin if tenant is mine else factory.headers(client, factory.account(tenant, "admin"))
        created = client.post("/v1/admin/api-keys", headers=owner, json={"name": "Probe", "scopes": ["payments:read"]}).json()
        forged = f"rk_{created['prefix']}_{'Z' * 43}"
        assert client.get("/v1/payments", headers={"X-API-Key": forged}).status_code == 401
    events = client.get("/v1/admin/security/events", headers=admin)
    assert events.status_code == 200
    assert [e["kind"] for e in events.json()] == ["api_key_misuse"], "only this department's event"
    assert "Z" * 43 not in events.text, "the attempted secret is not stored"
