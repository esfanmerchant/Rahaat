"""Self-registration with a one-time code: works end to end and gives nothing away about who exists."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import system_session
from app.core.mockdata import make_mock_phone
from app.db import models
from app.modules.applications.tests.support import Fakes
from app.modules.people import registration


@pytest.fixture(autouse=True)
def _fresh_throttles() -> None:
    registration._ip_hits.clear()
    registration._phone_starts.clear()


def _phone() -> str:
    import uuid

    return make_mock_phone(uuid.uuid4().int % 9_000_000 + 500_000)


def _start(client: TestClient, slug: str, phone: str) -> Any:
    return client.post("/v1/people/register/start", json={"tenant_slug": slug, "phone": phone, "lang": "ur"})


def test_register_then_sign_in_and_use_the_app(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    phone = _phone()
    started = _start(client, tenant.slug, phone)
    assert started.status_code == 202, started.text
    sms = fakes.calls["notify"][-1]
    assert sms["template"] == "registration_code" and len(sms["payload"]["code"]) == 6
    assert sms["payload"]["code"] not in started.text, "the code is never in the response"

    body = {"tenant_slug": tenant.slug, "registration_id": started.json()["registration_id"], "full_name": "New Citizen", "pin": "8352"}
    wrong = client.post("/v1/people/register/complete", json={**body, "code": "000000" if sms["payload"]["code"] != "000000" else "111111"})
    assert wrong.status_code == 401 and wrong.json()["code"] == "invalid_code"
    weak = client.post("/v1/people/register/complete", json={**body, "code": sms["payload"]["code"], "pin": "1234"})
    assert weak.status_code == 422 and weak.json()["code"] == "weak_pin"
    done = client.post("/v1/people/register/complete", json={**body, "code": sms["payload"]["code"]})
    assert done.status_code == 201, done.text
    replay = client.post("/v1/people/register/complete", json={**body, "code": sms["payload"]["code"]})
    assert replay.status_code == 401, "a code works once"

    login = client.post("/v1/auth/login", json={"identifier": phone, "secret": "8352"})
    assert login.status_code == 200 and login.json()["active"]["person_id"] == done.json()["person_id"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/v1/me/person", headers=headers).json()["full_name"] == "New Citizen"
    consent = client.post("/v1/consents", json={"field_scopes": ["identity", "household"]}, headers=headers)
    assert consent.status_code == 201


def test_start_gives_the_same_answer_for_registered_and_new_numbers(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    existing = factory.account(tenant, "citizen")
    new = _start(client, tenant.slug, _phone())
    known = _start(client, tenant.slug, existing.identifier)
    assert new.status_code == known.status_code == 202
    assert set(new.json()) == set(known.json()) and new.json()["message_key"] == known.json()["message_key"]
    assert new.json()["expires_in"] == known.json()["expires_in"]
    assert [c["template"] for c in fakes.calls["notify"]] == ["registration_code", "registration_exists"]
    assert "code" not in fakes.calls["notify"][1]["payload"]
    # The decoy id fails exactly like a wrong code.
    decoy = client.post("/v1/people/register/complete", json={"tenant_slug": tenant.slug, "registration_id": known.json()["registration_id"],
                                                              "code": "123456", "full_name": "Someone", "pin": "8352"})  # fmt: skip
    assert decoy.status_code == 401 and decoy.json()["code"] == "invalid_code"
    with system_session() as db:
        audit_rows = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id,
                                                              models.AuditLog.action == "person.registration_started")).all()  # fmt: skip
        assert len(audit_rows) == 2 and {r.actor_type for r in audit_rows} == {"system"}


def test_codes_lock_after_five_wrong_tries(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    started = _start(client, tenant.slug, _phone()).json()
    code = fakes.calls["notify"][-1]["payload"]["code"]
    wrong = "000000" if code != "000000" else "111111"
    body = {"tenant_slug": tenant.slug, "registration_id": started["registration_id"], "full_name": "New Citizen", "pin": "8352"}
    for _ in range(registration.MAX_ATTEMPTS):
        assert client.post("/v1/people/register/complete", json={**body, "code": wrong}).status_code == 401
    assert client.post("/v1/people/register/complete", json={**body, "code": code}).status_code == 401, "locked even with the right code"


def test_only_mock_phones_and_bounded_requests(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    real_looking = _start(client, tenant.slug, "0300-1234567")  # mock-lint: allow
    assert real_looking.status_code == 422 and real_looking.json()["code"] == "mock_phone_format"
    extra = client.post("/v1/people/register/start", json={"tenant_slug": tenant.slug, "phone": _phone(), "role": "admin"})
    assert extra.status_code == 422
    phone = _phone()
    for _ in range(registration.MAX_STARTS_PER_PHONE + 2):
        assert _start(client, tenant.slug, phone).status_code == 202
    assert fakes.n("notify") == registration.MAX_STARTS_PER_PHONE, "repeat requests for one number stop sending, silently"


def test_every_start_gets_a_fresh_id_and_only_the_latest_one_works(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    existing = factory.account(tenant, "citizen")
    phone = _phone()
    new_ids = {_start(client, tenant.slug, phone).json()["registration_id"] for _ in range(2)}
    known_ids = {_start(client, tenant.slug, existing.identifier).json()["registration_id"] for _ in range(2)}
    assert len(new_ids) == 2 and len(known_ids) == 2, "ids never reveal whether a number is registered"
    latest = fakes.calls["notify"][1]  # the code sent with the second start
    body = {"tenant_slug": tenant.slug, "full_name": "New Citizen", "pin": "8352", "code": latest["payload"]["code"]}
    results = sorted(client.post("/v1/people/register/complete", json={**body, "registration_id": i}).status_code for i in new_ids)
    assert results == [201, 401], "a new start replaces the earlier id"


def test_over_the_limit_the_code_already_sent_keeps_working(client: TestClient, factory: Any, fakes: Fakes) -> None:
    tenant = factory.tenant()
    phone = _phone()
    ids = [_start(client, tenant.slug, phone).json()["registration_id"] for _ in range(registration.MAX_STARTS_PER_PHONE + 1)]
    last_sent = fakes.calls["notify"][-1]["payload"]["code"]
    body = {"tenant_slug": tenant.slug, "full_name": "New Citizen", "pin": "8352", "code": last_sent,
            "registration_id": ids[registration.MAX_STARTS_PER_PHONE - 1]}  # fmt: skip
    assert client.post("/v1/people/register/complete", json=body).status_code == 201
