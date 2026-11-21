"""API keys across the whole surface: scope is the only way in, revocation and expiry stop a key at once,
and the secret is never stored or logged in clear (checked across every table and every log record)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text, update

from app.core import apikeys
from app.core.db import system_session
from app.db import models
from app.db.base import Base
from tests.security import support
from tests.security.support import World

KEYED = [r for r in support.registry() if r["api_scopes"]]


def _fresh_key(side: support.Side, scopes: list[str]) -> tuple[str, uuid.UUID]:
    raw, prefix, digest = apikeys.generate()
    with system_session() as db:
        key = models.ApiKey(id=uuid.uuid4(), tenant_id=side.tenant_id, name="security probe", prefix=prefix, key_hash=digest, scopes=scopes,
                            rate_limit_per_min=1000, expires_at=datetime.now(UTC) + timedelta(days=1))  # fmt: skip
        db.add(key)
        db.flush()
        return raw, key.id


def test_keys_are_admitted_on_reads_with_a_scope(world: World) -> None:
    assert {support.route_id(r) for r in KEYED} >= {"GET /v1/cases", "GET /v1/cases/{case_id}", "GET /v1/payments"}


@pytest.mark.parametrize("route", KEYED, ids=support.route_id)
def test_the_right_scope_opens_a_route_and_revocation_or_expiry_close_it_at_once(world: World, route: dict[str, Any]) -> None:
    path = support.fill(route["path"], world.a.ids)
    for ending in ("revoke", "expire"):
        raw, key_id = _fresh_key(world.a, list(route["api_scopes"]))
        headers = {"Authorization": f"Bearer {raw}"}
        assert world.client.request(route["method"], path, headers=headers).status_code == 200
        with system_session() as db:
            values = {"revoked_at": datetime.now(UTC)} if ending == "revoke" else {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
            db.execute(update(models.ApiKey).where(models.ApiKey.id == key_id).values(**values))
        stopped = world.client.request(route["method"], path, headers=headers)
        expected = "api_key_revoked" if ending == "revoke" else "api_key_expired"
        assert stopped.status_code == 401 and stopped.json()["code"] == expected, f"{ending}: {stopped.text}"


def test_a_key_is_never_stored_or_logged_in_clear(world: World, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    admin = world.headers(world.a, "admin")
    created = world.client.post("/v1/admin/api-keys", headers=admin, json={"name": "Clear-text probe", "scopes": ["payments:read"]}).json()
    rotated = world.client.post(f"/v1/admin/api-keys/{created['id']}/rotate", headers=admin).json()
    secrets_seen = [created["key"].split("_", 2)[2], rotated["key"].split("_", 2)[2]]
    for raw in (created["key"], rotated["key"]):
        world.client.get("/v1/payments", headers={"X-API-Key": raw})
        world.client.get("/v1/cases", headers={"Authorization": f"Bearer {raw}"})

    tables = [t.name for t in Base.metadata.sorted_tables]
    with system_session() as db:
        for secret in secrets_seen:
            holding = [name for name in tables
                       if db.execute(text(f"SELECT count(*) FROM {name} x WHERE strpos(x::text, :s) > 0"), {"s": secret}).scalar_one()]  # noqa: S608  # fmt: skip
            assert holding == [], f"the secret is stored in {holding}"
    logged = "\n".join(f"{record.getMessage()} {record.args} {getattr(record, 'fields', '')}" for record in caplog.records)
    assert caplog.records, "requests were logged"
    for secret in secrets_seen:
        assert secret not in logged
