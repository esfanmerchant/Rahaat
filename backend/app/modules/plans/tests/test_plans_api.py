"""Metering and enforcement against Postgres: the 429 problem, atomic counting, graceful degradation, API keys, the usage report."""

from __future__ import annotations

import io
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image
from sqlalchemy import select

from app.core import apikeys
from app.core.db import RlsContext, session_scope, system_session
from app.db import models
from app.modules.cases import testing as t
from app.modules.notifications.service import notify
from app.modules.plans import rules, seed_step, service


def _plan(limits: dict[str, int]) -> uuid.UUID:
    with system_session() as db:
        plan = models.Plan(code=f"test-{uuid.uuid4().hex[:10]}", name="Test plan", price_pkr=0, limits=limits)
        db.add(plan)
        db.flush()
        return plan.id


def _on_plan(tenant: Any, limits: dict[str, int]) -> None:
    plan_id = _plan(limits)
    with system_session() as db:
        row = db.get(models.Tenant, tenant.id)
        assert row is not None
        row.plan_id = plan_id


def _used(tenant_id: uuid.UUID, metric: str) -> int:
    with system_session() as db:
        return service.used_this_month(db, tenant_id, metric)


def _apply(client: Any, headers: dict[str, str], program_id: uuid.UUID, op: str = "op-0000001") -> Any:
    return client.post("/v1/applications", headers=headers, json={"program_id": str(program_id), "client_op_id": op})


def test_the_application_limit_refuses_at_creation_with_a_clear_problem_and_counts_each_application_once(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen)
    admin = factory.headers(client, factory.account(tenant, "admin"))
    first, second = t.program(tenant.id)[0], t.program(tenant.id)[0]
    _on_plan(tenant, {"applications": 1})

    created = _apply(client, headers, first)
    assert created.status_code == 201
    replay = _apply(client, headers, first)  # the same client_op_id: the same application, not a second unit
    assert replay.status_code == 200 and replay.json()["id"] == created.json()["id"]
    assert _used(tenant.id, "applications") == 1

    refused = _apply(client, headers, second, op="op-0000002")
    body = refused.json()
    assert refused.status_code == 429 and body["code"] == "plan_limit_reached" and refused.headers["content-type"].startswith("application/problem+json")
    assert (body["metric"], body["limit"], body["used"]) == ("applications", 1, 1)
    next_month = datetime.fromisoformat(body["resets_at"])
    assert next_month.day == 1 and next_month > datetime.now(UTC) and int(refused.headers["retry-after"]) > 0
    assert "request_id" in body and _used(tenant.id, "applications") == 1, "a refusal uses no unit"

    # The work already started is untouched: the citizen can still read and save the application they have.
    assert client.get(f"/v1/applications/{created.json()['id']}", headers=headers).status_code == 200
    saved = client.patch(f"/v1/applications/{created.json()['id']}", headers=headers,
                         json={"base_version": 1, "form_patch": {"household_size": {"value": 4, "confidence": 0.8, "provenance": "typed"}}})
    assert saved.status_code == 200

    usage = client.get("/v1/admin/usage", headers=admin).json()
    row = next(m for m in usage["metrics"] if m["metric"] == "applications")
    assert row == {"metric": "applications", "label": "Applications started", "used": 1, "limit": 1, "percent_used": 100.0, "reached": True}
    assert usage["plan"]["name"] == "Test plan" and usage["period"] == rules.period_of(datetime.now(UTC)) and usage["resets_at"] == body["resets_at"]
    assert len(usage["history"]) == 5 and all(set(h["counts"]) == set(rules.METRICS) for h in usage["history"])
    assert next(m for m in usage["metrics"] if m["metric"] == "sms")["limit"] is None, "a metric the plan does not list is not limited"
    for who in (factory.headers(client, factory.account(tenant, "officer")), headers):
        assert client.get("/v1/admin/usage", headers=who).status_code == 403

    other = factory.tenant()  # another department is neither limited nor counted
    other_citizen = factory.headers(client, factory.account(other, "citizen"))
    assert _apply(client, other_citizen, t.program(other.id)[0]).status_code == 201
    assert client.get("/v1/admin/usage", headers=factory.headers(client, factory.account(other, "admin"))).json()["plan"] is None


def test_the_last_unit_goes_to_exactly_one_of_many_racing_callers(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    _on_plan(tenant, {"ai_calls": 5})
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        with session_scope(RlsContext(role="worker", tenant_id=tenant.id)) as db:
            got = service.try_consume(db, tenant.id, "ai_calls")
        with lock:
            results.append(got)

    threads = [threading.Thread(target=worker) for _ in range(14)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 5 and results.count(False) == 9 and _used(tenant.id, "ai_calls") == 5


def test_a_limit_is_exact_unlimited_is_metered_and_a_rolled_back_request_uses_nothing(factory: Any) -> None:
    tenant = factory.tenant()
    with session_scope(RlsContext(role="worker", tenant_id=tenant.id)) as db:
        for _ in range(3):
            service.consume(db, tenant.id, "ocr")  # no plan: counted, never refused
    assert _used(tenant.id, "ocr") == 3

    _on_plan(tenant, {"sms": 0, "ocr": 3})
    with session_scope(RlsContext(role="worker", tenant_id=tenant.id)) as db:
        assert service.try_consume(db, tenant.id, "sms") is False  # a limit of zero never lets the first row in
        assert service.try_consume(db, tenant.id, "ocr") is False
    try:
        with session_scope(RlsContext(role="worker", tenant_id=tenant.id)) as db:
            service.try_consume(db, tenant.id, "api_calls")
            raise RuntimeError("the request failed after metering")
    except RuntimeError:
        pass
    assert _used(tenant.id, "api_calls") == 0 and _used(tenant.id, "sms") == 0


def test_text_messages_degrade_to_in_app_over_the_limit(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _on_plan(tenant, {"sms": 1})

    def send() -> list[str]:
        with session_scope(RlsContext(role="worker", tenant_id=tenant.id)) as db:
            return [n.channel for n in notify(db, tenant_id=tenant.id, person_id=citizen.person_id, template="person_will_check",
                                              payload={"tracking_code": "R-12345"})]  # fmt: skip

    assert send() == ["in_app", "sms"]
    assert send() == ["in_app"], "over the limit the person still gets the message in the app"
    assert _used(tenant.id, "sms") == 1


def test_api_key_calls_are_refused_once_the_months_limit_is_used(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    _on_plan(tenant, {"api_calls": 2})
    raw, prefix, digest = apikeys.generate()
    with system_session() as db:
        db.add(models.ApiKey(id=uuid.uuid4(), tenant_id=tenant.id, name="plan test", prefix=prefix, key_hash=digest, scopes=["payments:read"],
                             rate_limit_per_min=1000, expires_at=datetime.now(UTC) + timedelta(days=1)))  # fmt: skip
    statuses = [client.get("/v1/payments", headers={"X-API-Key": raw}) for _ in range(3)]
    assert [r.status_code for r in statuses] == [200, 200, 429]
    body = statuses[2].json()
    assert body["code"] == "plan_limit_reached" and (body["metric"], body["limit"], body["used"]) == ("api_calls", 2, 2)
    assert _used(tenant.id, "api_calls") == 2, "the refused call is not counted"


def test_over_the_ocr_limit_a_photo_is_kept_for_a_person_instead_of_losing_the_upload(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    headers = factory.headers(client, citizen)
    application = _apply(client, headers, t.program(tenant.id)[0]).json()
    _on_plan(tenant, {"ocr": 0})
    buffer = io.BytesIO()
    Image.new("RGB", (80, 50), (190, 170, 150)).save(buffer, format="PNG")
    response = client.post(f"/v1/applications/{application['id']}/documents", headers=headers, data={"kind": "rahat_id"},
                           files={"file": ("card.png", buffer.getvalue(), "image/png")})  # fmt: skip
    assert response.status_code == 201, response.text
    with system_session() as db:
        document = db.scalar(select(models.Document).where(models.Document.application_id == uuid.UUID(application["id"])))
        assert document is not None
        assert db.scalar(select(models.DocumentCheck).where(models.DocumentCheck.document_id == document.id)) is None, "no automatic check was run"
    assert _used(tenant.id, "ocr") == 0


def test_speech_is_refused_over_the_ai_limit_but_typing_is_not_blocked(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    headers = factory.headers(client, factory.account(tenant, "citizen"))
    _on_plan(tenant, {"ai_calls": 0})
    refused = client.post("/v1/voice/stt", headers=headers, content=b"RIFF....", params={"lang": "ur"})
    assert refused.status_code == 429 and refused.json()["code"] == "plan_limit_reached" and refused.json()["metric"] == "ai_calls"
    assert _apply(client, headers, t.program(tenant.id)[0]).status_code == 201


def test_the_plan_catalogue_is_public_and_the_seed_puts_demo_departments_on_government(client: Any) -> None:
    with system_session() as db:
        seed_step.seed(db)
        seed_step.seed(db)  # safe to run twice
    response = client.get("/v1/plans")
    assert response.status_code == 200
    plans = response.json()
    assert [p["code"] for p in plans] == ["free", "standard", "government"]
    assert all(set(p["limits"]) == set(rules.METRICS) for p in plans) and plans[2]["limits"]["applications"] > plans[1]["limits"]["applications"]
