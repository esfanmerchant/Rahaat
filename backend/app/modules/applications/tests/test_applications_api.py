"""Applications through the API, against Postgres with Row Level Security on."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import system_session
from app.db import models
from app.modules.applications.tests.support import World, build_world, eligible_patch, new_app


def _denied(tenant_id: uuid.UUID, reason: str) -> list[models.AuditLog]:
    with system_session() as db:
        return list(db.scalars(select(models.AuditLog).where(
            models.AuditLog.tenant_id == tenant_id, models.AuditLog.action == "access.denied", models.AuditLog.reason == reason)).all())  # fmt: skip


def test_programs_and_my_person(client: TestClient, world: World) -> None:
    programs = client.get("/v1/programs", headers=world.h("officer")).json()
    assert [p["slug"] for p in programs] == ["rahat"]
    brief = programs[0]["rule_version"]
    assert brief["version_no"] == 1 and brief["required_docs"] == ["rahat_id"] and brief["payment_pkr"] == 12000

    me = client.get("/v1/me/person", headers=world.h("citizen"))
    assert me.status_code == 200 and "x-rahat-stub" not in me.headers
    body = me.json()
    assert body["id"] == str(world.citizen.person_id) and body["full_name"] == "Test Citizen"
    assert body["national_id_masked"].endswith(body["national_id_masked"][-3:]) and "•" in body["national_id_masked"]
    assert "0999" not in (body["phone_masked"] or ""), "identifiers are masked"
    helper_view = client.get("/v1/me/person", headers=world.h("helper", world.citizen.person_id))
    assert helper_view.json()["id"] == str(world.citizen.person_id)
    assert client.get("/v1/me/person", headers=world.h("officer")).status_code == 403


def test_create_is_idempotent_on_client_op_id(client: TestClient, world: World) -> None:
    op = uuid.uuid4().hex
    first = new_app(client, world, client_op_id=op)
    assert first.status_code == 201, first.text
    again = new_app(client, world, client_op_id=op)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    body = first.json()
    assert body["status"] == "draft" and body["version"] == 1 and body["tracking_code"].startswith("R-")
    assert len(body["tracking_symbols"]) == 3
    assert body["missing_fields"] == ["income_band", "receives_other_aid", "is_widow", "has_disability", "household_size"]
    # Another person cannot reuse (or discover) the id.
    taken = new_app(client, world, "other_citizen", client_op_id=op)
    assert taken.status_code == 409 and taken.json()["code"] == "client_op_id_conflict"
    listing = client.get("/v1/applications", headers=world.h("citizen")).json()
    assert [a["id"] for a in listing["items"]] == [body["id"]]


def test_one_citizen_cannot_read_or_change_another_application(client: TestClient, factory: Any, world: World) -> None:
    mine = new_app(client, world).json()
    elsewhere = build_world(factory, client)
    theirs_cross_tenant = new_app(client, elsewhere).json()
    for who, app_id in [("other_citizen", mine["id"]), ("citizen", theirs_cross_tenant["id"])]:
        headers = world.h(who)
        assert client.get(f"/v1/applications/{app_id}", headers=headers).status_code == 404
        patch = client.patch(f"/v1/applications/{app_id}", json={"base_version": 1, "form_patch": eligible_patch()}, headers=headers)
        assert patch.status_code == 404
        assert client.post(f"/v1/applications/{app_id}/submit", headers=headers).status_code == 404
        upload = client.post(f"/v1/applications/{app_id}/documents", headers=headers, files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})
        assert upload.status_code == 404
    assert client.get("/v1/applications", headers=world.h("other_citizen")).json()["items"] == []
    with system_session() as db:
        assert db.get(models.Application, uuid.UUID(mine["id"])).version == 1, "nothing changed"


def test_helper_needs_a_live_delegation_with_the_right_scope(client: TestClient, factory: Any, world: World) -> None:
    tid = world.tenant.id
    no_header = client.get("/v1/applications", headers=world.h("helper"))
    assert no_header.status_code == 403 and no_header.json()["code"] == "acting_for_required"
    stranger = client.get("/v1/applications", headers=world.h("helper", world.other_citizen.person_id))
    assert stranger.status_code == 403 and stranger.json()["code"] == "no_delegation"
    assert _denied(tid, "acting_for_required") and _denied(tid, "no_delegation"), "denied attempts are audited"
    row = _denied(tid, "no_delegation")[0]
    assert row.actor_id == str(world.helper.user_id) and row.acting_for_person_id == world.other_citizen.person_id

    created = new_app(client, world, "helper", acting_for=world.citizen.person_id)
    assert created.status_code == 201 and created.json()["person_id"] == str(world.citizen.person_id)
    with system_session() as db:
        audit_row = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tid,
                                                             models.AuditLog.action == "application.created")).one()  # fmt: skip
        assert audit_row.actor_id == str(world.helper.user_id) and audit_row.acting_for_person_id == world.citizen.person_id
        assert db.get(models.Application, uuid.UUID(created.json()["id"])).submitted_via == "helper"

    # A delegation without the upload scope cannot upload; an expired one cannot do anything.
    limited = build_world(factory, client, helper_scopes=("track",))
    app_id = new_app(client, limited).json()["id"]
    upload = client.post(f"/v1/applications/{app_id}/documents", headers=limited.h("helper", limited.citizen.person_id),
                         files={"file": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})  # fmt: skip
    assert upload.status_code == 403 and upload.json()["code"] == "scope_not_delegated"
    assert client.get(f"/v1/applications/{app_id}", headers=limited.h("helper", limited.citizen.person_id)).status_code == 200
    with system_session() as db:
        for d in db.scalars(select(models.HelperDelegation).where(models.HelperDelegation.tenant_id == limited.tenant.id)).all():
            d.expires_at = d.created_at
    assert client.get(f"/v1/applications/{app_id}", headers=limited.h("helper", limited.citizen.person_id)).status_code == 403

    # A citizen cannot act for someone else by sending the header either.
    spoof = client.get("/v1/applications", headers=world.h("citizen", world.other_citizen.person_id))
    assert spoof.status_code == 403 and spoof.json()["code"] == "acting_for_not_allowed"


def test_client_sent_verified_or_server_provenance_is_rejected(client: TestClient, world: World) -> None:
    forged = {"full_name": {"value": "Zainab Bibi", "confidence": 1.0, "provenance": "qr_signed", "verified": True}}
    created = new_app(client, world, form=forged)
    assert created.status_code == 422 and created.json()["code"] == "invalid_form"
    assert {e["code"] for e in created.json()["errors"]} == {"provenance_not_allowed", "verified_not_allowed"}

    app = new_app(client, world).json()
    for bad in ({"income_band": {"value": "under_15k", "provenance": "registry", "verified": True}},
                {"income_band": {"value": "under_15k", "provenance": "tapped", "verified": True}},
                {"income_band": {"value": "under_15k", "provenance": "ocr"}}):  # fmt: skip
        response = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": bad}, headers=world.h("citizen"))
        assert response.status_code == 422, response.text
        assert "stack" not in response.text.lower() and response.json()["request_id"]
    extra_field = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": {}, "status": "approved"},
                               headers=world.h("citizen"))  # fmt: skip
    assert extra_field.status_code == 422, "input models forbid extra fields"
    with system_session() as db:
        assert db.get(models.Application, uuid.UUID(app["id"])).version == 1


def test_patch_uses_base_version_as_an_optimistic_lock(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    url = f"/v1/applications/{app['id']}"
    first = client.patch(url, json={"base_version": 1, "form_patch": eligible_patch()}, headers=world.h("citizen"))
    assert first.status_code == 200 and first.json()["version"] == 2 and first.json()["missing_fields"] == []
    assert first.json()["form"]["household_size"]["value"] == 5
    stale = client.patch(url, json={"base_version": 1, "form_patch": {"household_size": {"value": 7}}}, headers=world.h("citizen"))
    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "version_conflict" and body["current_version"] == 2 and body["form"]["household_size"]["value"] == 5


def test_consent_is_required_to_create_or_change(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    with system_session() as db:
        for consent in db.scalars(select(models.Consent).where(models.Consent.person_id == world.citizen.person_id)).all():
            consent.field_scopes = ["identity"]
    narrowed = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": eligible_patch()},
                            headers=world.h("citizen"))  # fmt: skip
    assert narrowed.status_code == 409 and narrowed.json()["code"] == "consent_scope_missing"
    assert set(narrowed.json()["missing_scopes"]) == {"household", "income"}
    with system_session() as db:
        for consent in db.scalars(select(models.Consent).where(models.Consent.person_id == world.citizen.person_id)).all():
            consent.status = "expired"
    response = new_app(client, world)
    assert response.status_code == 409 and response.json()["code"] == "consent_required"
    assert client.post(f"/v1/applications/{app['id']}/submit", headers=world.h("citizen")).json()["code"] == "consent_required"
    assert _denied(world.tenant.id, "consent_required")
