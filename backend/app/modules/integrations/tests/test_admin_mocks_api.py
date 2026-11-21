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
