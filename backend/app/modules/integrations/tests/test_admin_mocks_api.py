"""GET and POST /v1/admin/mocks: admins only, audited, and the change reaches the mock service."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import system_session
from app.db import models
from app.mocks.state import STATE
from app.modules.integrations.testing import fresh_mocks


@pytest.fixture()
def mocks() -> Iterator[None]:
    with fresh_mocks():
        yield


def test_admin_controls_the_mocks_and_the_change_is_audited(client: Any, factory: Any, mocks: None) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    officer = factory.headers(client, factory.account(tenant, "officer"))

    assert client.get("/v1/admin/mocks", headers=officer).status_code == 403
    before = client.get("/v1/admin/mocks", headers=admin)
    assert before.status_code == 200 and before.json()["transport"] == "inprocess"
    assert before.json()["services"]["sms"]["down"] is False

    refused = client.post("/v1/admin/mocks", headers=admin, json={"service": "sms", "down": True, "reason": "demo", "extra": 1})
    assert refused.status_code == 422
    changed = client.post("/v1/admin/mocks", headers=admin, json={"service": "sms", "down": True, "reason": "show an SMS outage"})
    assert changed.status_code == 200 and changed.json()["services"]["sms"]["down"] is True
    assert STATE.controls["sms"].down is True

    with system_session() as db:
        row = db.scalar(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "mocks.control_changed"))
        assert row is not None and row.reason == "show an SMS outage" and row.object_id == "sms"

    reset = client.post("/v1/admin/mocks", headers=admin, json={"reset": True, "reason": "back to normal"})
    assert reset.status_code == 200 and reset.json()["services"]["sms"]["down"] is False


def test_a_sign_up_code_reaches_the_admin_simulated_sms_view_only_and_only_while_it_lives(client: Any, factory: Any, mocks: None) -> None:
    """In-process (serverless) the gateway forgets between requests; the admin's view reads the department's copies."""
    import re
    import uuid
    from datetime import timedelta

    from app.core.mockdata import make_mock_phone
    from app.modules.people import registration

    registration._ip_hits.clear()
    registration._phone_starts.clear()
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    officer = factory.headers(client, factory.account(tenant, "officer"))
    phone = make_mock_phone(uuid.uuid4().int % 9_000_000 + 500_000)
    started = client.post("/v1/people/register/start", json={"tenant_slug": tenant.slug, "phone": phone, "lang": "en"})
    assert started.status_code == 202, started.text

    assert client.get("/v1/admin/mocks/sms", headers=officer).status_code == 403
    view = client.get("/v1/admin/mocks/sms", headers=admin)
    assert view.status_code == 200, view.text
    found = [re.search(r"\b(\d{6})\b", m["body"]) for m in view.json() if "sign-up code" in m["body"]]
    assert found and found[0] is not None, view.json()
    code = found[0].group(1)
    assert phone[-7:] not in view.text, "numbers stay masked"
    assert code not in client.get("/v1/outbox", headers=admin, params={"channel": "sms"}).text, "the department outbox hides it"

    body = {"tenant_slug": tenant.slug, "registration_id": started.json()["registration_id"], "code": code, "full_name": "New Citizen",
            "pin": "8352"}  # fmt: skip
    assert client.post("/v1/people/register/complete", json=body).status_code == 201

    with system_session() as db:
        for row in db.scalars(select(models.Notification).where(models.Notification.tenant_id == tenant.id,
                                                                models.Notification.template == "registration_code")):  # fmt: skip
            row.created_at = row.created_at - timedelta(minutes=11)
        db.commit()
    assert code not in client.get("/v1/admin/mocks/sms", headers=admin).text, "after its lifetime the code is hidden here too"
