"""Audit hash chain (including tampering by a database administrator) and the basics of the HTTP surface."""

from __future__ import annotations

import threading
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import audit
from app.core.db import SYSTEM, get_owner_engine, open_session, system_session


def _write(tenant_id: Any, count: int, prefix: str = "test.event") -> None:
    for index in range(count):
        with system_session() as db:
            audit.write(db, tenant_id=tenant_id, action=f"{prefix}.{index}", actor_type="system", details={"n": index})


def _verify(tenant_id: Any) -> audit.ChainReport:
    with open_session(SYSTEM) as db:
        return audit.verify_chain(db, tenant_id)


def test_chain_verifies_and_reports_its_head(factory: Any) -> None:
    tenant = factory.tenant()
    _write(tenant.id, 6)
    report = _verify(tenant.id)
    assert report.ok and report.checked == 6 and report.head_seq == 6 and len(report.head_hash) == 64


def test_editing_a_row_as_database_owner_is_detected(factory: Any) -> None:
    tenant = factory.tenant()
    _write(tenant.id, 6)
    with get_owner_engine().begin() as conn:  # what a rogue administrator could do
        conn.execute(text("UPDATE audit_log SET reason = 'covered up' WHERE tenant_id = :t AND seq = 3"), {"t": tenant.id})
    report = _verify(tenant.id)
    assert not report.ok and report.first_broken_seq == 3 and report.problem == "row content was changed"


def test_editing_the_details_is_detected(factory: Any) -> None:
    tenant = factory.tenant()
    _write(tenant.id, 4)
    with get_owner_engine().begin() as conn:
        conn.execute(text("UPDATE audit_log SET details = :forged WHERE tenant_id = :t AND seq = 2"),
                     {"t": tenant.id, "forged": '{"n":99}'})
    assert _verify(tenant.id).first_broken_seq == 2


def test_deleting_a_row_is_detected(factory: Any) -> None:
    tenant = factory.tenant()
    _write(tenant.id, 5)
    with get_owner_engine().begin() as conn:
        conn.execute(text("DELETE FROM audit_log WHERE tenant_id = :t AND seq = 4"), {"t": tenant.id})
    report = _verify(tenant.id)
    assert not report.ok and report.first_broken_seq == 4 and report.problem == "a row is missing"


def test_replacing_a_row_with_a_self_consistent_forgery_breaks_the_next_link(factory: Any) -> None:
    tenant = factory.tenant()
    _write(tenant.id, 4)
    with get_owner_engine().begin() as conn:  # the forger recomputes nothing after it, so the chain still breaks
        conn.execute(text("UPDATE audit_log SET hash = repeat('a', 64) WHERE tenant_id = :t AND seq = 2"), {"t": tenant.id})
    assert _verify(tenant.id).first_broken_seq == 2


def test_concurrent_writers_keep_one_unbroken_chain(factory: Any) -> None:
    tenant = factory.tenant()
    threads = [threading.Thread(target=_write, args=(tenant.id, 10, f"worker{n}")) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    report = _verify(tenant.id)
    assert report.ok and report.checked == 40, "appends are serialised per tenant"


def test_auditor_can_verify_and_browse_but_officer_cannot(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    auditor, officer = factory.account(tenant, "auditor"), factory.account(tenant, "officer")
    auditor_headers, officer_headers = factory.headers(client, auditor), factory.headers(client, officer)

    verified = client.get("/v1/audit/verify", headers=auditor_headers)
    assert verified.status_code == 200 and verified.json()["ok"] is True

    denied = client.get("/v1/audit", headers=officer_headers)
    assert denied.status_code == 403 and denied.json()["code"] == "role_not_allowed"

    page = client.get("/v1/audit", headers=auditor_headers, params={"result": "denied"}).json()
    blocked = [e for e in page["items"] if e["action"] == "access.denied"]
    assert blocked and blocked[0]["actor_id"] == str(officer.user_id), "the blocked attempt is itself on the record"
    assert blocked[0]["object_id"] == "audit:read"

    first_page = client.get("/v1/audit", headers=auditor_headers, params={"limit": 2}).json()
    assert len(first_page["items"]) == 2 and first_page["next_cursor"]
    second_page = client.get("/v1/audit", headers=auditor_headers, params={"limit": 2, "cursor": first_page["next_cursor"]}).json()
    assert second_page["items"][0]["seq"] < first_page["items"][-1]["seq"]
    assert client.get("/v1/audit", headers=auditor_headers, params={"limit": 5000}).status_code == 422, "page size is capped"


def test_audit_is_tenant_scoped_through_the_api(client: TestClient, factory: Any) -> None:
    mine, theirs = factory.tenant(), factory.tenant()
    _write(theirs.id, 3, "their.secret")
    auditor = factory.account(mine, "auditor")
    actions = [e["action"] for e in client.get("/v1/audit", headers=factory.headers(client, auditor)).json()["items"]]
    assert not any(a.startswith("their.secret") for a in actions)


def test_health_info_and_demo_accounts(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}
    info = client.get("/v1/system/info").json()
    assert info["prototype_label"].startswith("Prototype. Not an official service.") and info["demo_mode"] is True
    accounts = client.get("/v1/demo/accounts").json()["accounts"]
    assert {a["role"] for a in accounts} == {"admin", "officer", "auditor", "helper", "citizen"}
    assert all(a["identifier"].startswith("0999-") for a in accounts if a["kind"] == "citizen")
    assert "rahat_http_requests_total" in client.get("/metrics").text


def test_errors_are_problem_documents_and_never_leak_internals(client: TestClient) -> None:
    missing = client.get("/v1/does-not-exist")
    assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "not_found" and missing.json()["request_id"] == missing.headers["x-request-id"]

    invalid = client.post("/v1/auth/login", json={"identifier": "a@b.example", "secret": "x", "is_admin": True})
    assert invalid.status_code == 422, "unknown fields are rejected, so nothing can be mass-assigned"
    body = invalid.json()
    assert body["code"] == "invalid_input" and body["errors"][0]["field"] == "body.is_admin"
    assert "Traceback" not in invalid.text

    assert client.post("/v1/auth/login", content=b"{not json", headers={"content-type": "application/json"}).status_code == 422


def test_security_headers_and_request_ids(client: TestClient) -> None:
    response = client.get("/v1/system/info", headers={"X-Request-ID": "judge-run-0001"})
    assert response.headers["x-request-id"] == "judge-run-0001"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp

    injected = client.get("/healthz", headers={"X-Request-ID": "bad id\twith spaces"})
    assert injected.headers["x-request-id"] != "bad id\twith spaces", "unsafe request ids are replaced"

    docs = client.get("/docs")
    assert docs.status_code == 200 and "cdn.jsdelivr.net" in docs.headers["content-security-policy"]


def test_oversized_bodies_are_refused(client: TestClient) -> None:
    response = client.post("/v1/auth/login", content=b"x" * 7_000_000, headers={"content-type": "application/json"})
    assert response.status_code == 413 and response.json()["code"] == "payload_too_large"


def test_policy_registry_is_visible_to_admin_and_auditor_only(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    admin, citizen = factory.account(tenant, "admin"), factory.account(tenant, "citizen")
    registry = client.get("/v1/system/policies", headers=factory.headers(client, admin)).json()
    assert all(entry["policy"] for entry in registry) and len(registry) >= 15
    assert client.get("/v1/system/policies", headers=factory.headers(client, citizen)).status_code == 403
    assert client.get("/v1/system/health", headers=factory.headers(client, admin)).json()["database"] == "ok"


def test_contract_stubs_are_marked_and_enforce_roles(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen, officer = factory.account(tenant, "citizen"), factory.account(tenant, "officer")
    # Any path that is still a stub in this build. /v1/applications became real with Track A's applications module.
    mine = client.get("/v1/notifications", headers=factory.headers(client, citizen))
    assert mine.status_code == 200 and mine.headers["x-rahat-stub"] == "1"
    assert "x-rahat-stub" not in client.get("/v1/applications", headers=factory.headers(client, citizen)).headers
    assert client.get("/v1/cases", headers=factory.headers(client, citizen)).status_code == 403
    assert client.get("/v1/cases", headers=factory.headers(client, officer)).json()["items"][0]["kind"] == "application_review"


def test_seed_creates_working_demo_accounts_and_is_repeatable(client: TestClient, database: None) -> None:
    from app import seed
    from app.db import models

    def run() -> int:
        with system_session() as db:
            seed.seed(db)
            return int(db.execute(text("SELECT count(*) FROM memberships")).scalar_one()) + db.query(models.Person).count()

    first, second = run(), run()
    assert first == second, "running the seed twice must not duplicate anything"

    accounts = client.get("/v1/demo/accounts").json()["accounts"]
    for account in accounts:
        response = client.post("/v1/auth/login", json={"identifier": account["identifier"], "secret": account["secret"]})
        assert response.status_code == 200, f"{account['label']} could not sign in: {response.text}"
        assert response.json()["active"]["role"] == account["role"]
    auditor = next(a for a in accounts if a["role"] == "auditor")
    session = client.post("/v1/auth/login", json={"identifier": auditor["identifier"], "secret": auditor["secret"]}).json()
    assert len(session["memberships"]) == 2, "the auditor belongs to both departments"
    assert client.get("/v1/audit/verify", headers={"Authorization": f"Bearer {session['access_token']}"}).json()["ok"] is True
