"""Regression: one person could open two applications for one program and be paid twice (found on the live site)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.db import system_session
from app.db import models


def _program(tenant_id: uuid.UUID) -> uuid.UUID:
    with system_session() as db:
        program = models.Program(tenant_id=tenant_id, slug=f"p-{uuid.uuid4().hex[:8]}", name="Test program")
        db.add(program)
        db.flush()
        return program.id


def test_a_second_open_application_for_the_same_program_is_refused(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    program_id = _program(tenant.id)
    headers = factory.headers(client, citizen)

    first = client.post("/v1/applications", headers=headers, json={"program_id": str(program_id), "client_op_id": f"op-{uuid.uuid4().hex}"})
    assert first.status_code == 201, first.text
    again = client.post("/v1/applications", headers=headers, json={"program_id": str(program_id), "client_op_id": f"op-{uuid.uuid4().hex}"})
    assert again.status_code == 409 and again.json()["code"] == "application_exists"
    assert again.json()["application_id"] == first.json()["id"]

    with system_session() as db:  # a rejected application no longer blocks a new one
        db.get(models.Application, uuid.UUID(first.json()["id"])).status = "rejected"
    later = client.post("/v1/applications", headers=headers, json={"program_id": str(program_id), "client_op_id": f"op-{uuid.uuid4().hex}"})
    assert later.status_code == 201, later.text


def test_the_database_refuses_two_open_applications_even_if_the_service_is_bypassed(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    program_id = _program(tenant.id)
    with system_session() as db:
        db.add(models.Application(tenant_id=tenant.id, program_id=program_id, person_id=citizen.person_id, status="paid"))
    with pytest.raises(IntegrityError, match="uq_applications_one_open"):
        with system_session() as db:
            db.add(models.Application(tenant_id=tenant.id, program_id=program_id, person_id=citizen.person_id, status="draft"))
