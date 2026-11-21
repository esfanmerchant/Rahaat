"""Consent grant, narrow and withdraw, and what withdrawal does on the very next request."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.db import get_engine, system_session
from app.db import models
from app.modules.applications.tests.support import Fakes, World, eligible_patch, jpeg_bytes, new_app


def _consent_id(client: TestClient, world: World) -> str:
    consents = client.get("/v1/consents", headers=world.h("citizen")).json()
    active = [c for c in consents if c["status"] == "active"]
    assert len(active) == 1
    return str(active[0]["id"])


def test_list_shows_only_my_consents_with_the_department_name(client: TestClient, world: World) -> None:
    mine = client.get("/v1/consents", headers=world.h("citizen")).json()
    assert len(mine) == 1 and mine[0]["person_id"] == str(world.citizen.person_id)
    assert mine[0]["grantee_type"] == "tenant" and mine[0]["grantee_name"] == "Test Department"
    theirs = client.get("/v1/consents", headers=world.h("other_citizen")).json()
    assert [c["person_id"] for c in theirs] == [str(world.other_citizen.person_id)]
    via_helper = client.get("/v1/consents", headers=world.h("helper", world.citizen.person_id)).json()
    assert [c["id"] for c in via_helper] == [c["id"] for c in mine]


def test_narrow_only_and_every_change_is_recorded(client: TestClient, world: World) -> None:
    consent_id = _consent_id(client, world)
    url = f"/v1/consents/{consent_id}"
    narrowed = client.patch(url, json={"field_scopes": ["identity", "household", "documents"]}, headers=world.h("citizen"))
    assert narrowed.status_code == 200 and narrowed.json()["version"] == 2
    assert narrowed.json()["field_scopes"] == ["identity", "household", "documents"]
    widen = client.patch(url, json={"field_scopes": ["identity", "income"]}, headers=world.h("citizen"))
    assert widen.status_code == 422 and widen.json()["code"] == "consent_widen_not_allowed"
    assert client.patch(url, json={"field_scopes": []}, headers=world.h("citizen")).status_code == 422
    assert client.patch(url, json={"field_scopes": ["identity"]}, headers=world.h("other_citizen")).status_code == 404

    # A field outside the narrowed scopes can no longer be written.
    app = new_app(client, world).json()
    blocked = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": {"income_band": {"value": "under_15k"}}},
                           headers=world.h("citizen"))  # fmt: skip
    assert blocked.status_code == 409 and blocked.json()["missing_scopes"] == ["income"]
    with system_session() as db:
        events = db.scalars(select(models.ConsentEvent.event).where(models.ConsentEvent.consent_id == uuid.UUID(consent_id))).all()
        assert "narrowed" in events
        assert db.scalar(select(func.count()).select_from(models.AuditLog).where(models.AuditLog.action == "consent.narrowed",
                                                                               models.AuditLog.object_id == consent_id)) == 1  # fmt: skip


def test_grant_is_idempotent_and_takes_the_person_from_the_request_not_the_body(client: TestClient, world: World) -> None:
    same = client.post("/v1/consents", json={"field_scopes": ["identity", "contact", "household", "income", "documents"]},
                       headers=world.h("citizen"))  # fmt: skip
    assert same.status_code == 200 and same.json()["id"] == _consent_id(client, world)
    different = client.post("/v1/consents", json={"field_scopes": ["identity"]}, headers=world.h("citizen"))
    assert different.status_code == 409 and different.json()["code"] == "consent_exists"
    other = client.post("/v1/consents", json={"person_id": str(world.other_citizen.person_id), "field_scopes": ["identity"]},
                        headers=world.h("citizen"))  # fmt: skip
    assert other.status_code == 403 and other.json()["code"] == "person_mismatch"
    extra = client.post("/v1/consents", json={"field_scopes": ["identity"], "grantee_id": str(uuid.uuid4())}, headers=world.h("citizen"))
    assert extra.status_code == 422


def test_withdrawal_holds_applications_and_blocks_access_on_the_next_request(client: TestClient, world: World, fakes: Fakes,
                                                                               uploads: Any) -> None:  # fmt: skip
    tid, pid = world.tenant.id, world.citizen.person_id
    draft = new_app(client, world).json()
    submitted = new_app(client, world).json()
    client.patch(f"/v1/applications/{submitted['id']}", json={"base_version": 1, "form_patch": eligible_patch()}, headers=world.h("citizen"))
    fakes.outcome = "needs_human"
    assert client.post(f"/v1/applications/{submitted['id']}/submit", headers=world.h("citizen")).json()["application"]["status"] == "in_review"
    doc = client.post(f"/v1/applications/{draft['id']}/documents", headers=world.h("citizen"), files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    document_id = doc.json()["document"]["document_id"]
    assert client.get(f"/v1/documents/{document_id}/content", headers=world.h("officer")).status_code == 200
    with system_session() as db:
        db.add(models.Job(tenant_id=tid, kind="notify", person_id=pid, status="queued"))
        db.add(models.Job(tenant_id=tid, kind="notify", person_id=world.other_citizen.person_id, status="queued"))
        db.add(models.MemoryItem(tenant_id=tid, person_id=pid, kind="preference", key="lang", value={"v": "ur"}))

    consent_id = _consent_id(client, world)
    withdrawn = client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("citizen"))
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "withdrawn" and withdrawn.json()["withdrawn_at"]

    # The citizen still sees their own applications, now on hold.
    statuses = {a["id"]: a["status"] for a in client.get("/v1/applications", headers=world.h("citizen")).json()["items"]}
    assert statuses == {draft["id"]: "on_hold_consent", submitted["id"]: "on_hold_consent"}
    # Nothing can be changed, uploaded or submitted.
    patch = client.patch(f"/v1/applications/{draft['id']}", json={"base_version": 2, "form_patch": {}}, headers=world.h("citizen"))
    assert patch.status_code == 409 and patch.json()["code"] == "consent_required"
    upload = client.post(f"/v1/applications/{draft['id']}/documents", headers=world.h("citizen"),
                         files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})  # fmt: skip
    assert upload.status_code == 409 and upload.json()["code"] == "consent_required"
    assert new_app(client, world).json()["code"] == "consent_required"
    # Officer and helper reads stop at once; the database refuses the officer.
    officer_view = client.get(f"/v1/documents/{document_id}/content", headers=world.h("officer"))
    assert officer_view.status_code == 403 and officer_view.json()["code"] == "consent_required"
    helper_view = client.get(f"/v1/applications/{draft['id']}", headers=world.h("helper", pid))
    assert helper_view.status_code == 403 and helper_view.json()["code"] == "consent_required"
    with get_engine().connect() as conn:
        conn.execute(text("SELECT set_config('app.role', 'officer', true), set_config('app.tenant_id', :t, true), "
                          "set_config('app.user_id', :u, true)"), {"t": str(tid), "u": str(world.officer.user_id)})  # fmt: skip
        assert conn.execute(text("SELECT count(*) FROM applications WHERE person_id = :p"), {"p": str(pid)}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM persons WHERE id = :p"), {"p": str(pid)}).scalar_one() == 0

    with system_session() as db:
        jobs = dict(db.execute(select(models.Job.person_id, models.Job.status).where(models.Job.tenant_id == tid)).all())  # type: ignore[arg-type]
        assert jobs == {pid: "cancelled", world.other_citizen.person_id: "queued"}
        assert db.scalar(select(func.count()).select_from(models.MemoryItem).where(models.MemoryItem.person_id == pid)) == 0
        events = db.scalars(select(models.ConsentEvent).where(models.ConsentEvent.consent_id == uuid.UUID(consent_id),
                                                               models.ConsentEvent.event == "withdrawn")).all()  # fmt: skip
        assert len(events) == 1 and set(events[0].details["held"]) == {draft["id"], submitted["id"]}
        actions = db.scalars(select(models.AuditLog.action).where(models.AuditLog.tenant_id == tid)).all()
        assert "consent.withdrawn" in actions and actions.count("application.on_hold_consent") == 2
        denied = db.scalars(select(models.AuditLog.reason).where(models.AuditLog.tenant_id == tid, models.AuditLog.result == "denied")).all()
        assert denied.count("consent_required") >= 4, "every refused attempt left an audit row"

    # Withdrawing again changes nothing; granting again resumes where each application was.
    assert client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("citizen")).json()["version"] == withdrawn.json()["version"]
    regrant = client.post("/v1/consents", json={"field_scopes": ["identity", "contact", "household", "income", "documents"]},
                          headers=world.h("citizen"))  # fmt: skip
    assert regrant.status_code == 201
    statuses = {a["id"]: a["status"] for a in client.get("/v1/applications", headers=world.h("citizen")).json()["items"]}
    assert statuses == {draft["id"]: "draft", submitted["id"]: "in_review"}
    assert client.get(f"/v1/documents/{document_id}/content", headers=world.h("officer")).status_code == 200


def test_helper_can_withdraw_for_the_person(client: TestClient, world: World) -> None:
    consent_id = _consent_id(client, world)
    response = client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("helper", world.citizen.person_id))
    assert response.status_code == 200 and response.json()["status"] == "withdrawn"
    with system_session() as db:
        row = db.scalars(select(models.AuditLog).where(models.AuditLog.action == "consent.withdrawn",
                                                       models.AuditLog.object_id == consent_id)).one()  # fmt: skip
        assert row.actor_id == str(world.helper.user_id) and row.acting_for_person_id == world.citizen.person_id
    # Another person's consent is not found, whoever asks.
    other = client.get("/v1/consents", headers=world.h("other_citizen")).json()[0]["id"]
    assert client.post(f"/v1/consents/{other}/withdraw", headers=world.h("citizen")).status_code == 404


def test_only_known_purposes_and_only_the_application_consent_resumes(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    unknown = client.post("/v1/consents", json={"purpose": "anything_else", "field_scopes": ["identity"]}, headers=world.h("citizen"))
    assert unknown.status_code == 422 and unknown.json()["code"] == "invalid_purpose"
    client.post(f"/v1/consents/{_consent_id(client, world)}/withdraw", headers=world.h("citizen"))
    other = client.post("/v1/consents", json={"purpose": "scam_report", "field_scopes": ["contact"]}, headers=world.h("citizen"))
    assert other.status_code == 201
    assert client.get(f"/v1/applications/{app['id']}", headers=world.h("citizen")).json()["status"] == "on_hold_consent"


def test_helper_cannot_read_the_person_after_withdrawal(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    assert client.get("/v1/me/person", headers=world.h("helper", pid)).status_code == 200
    client.post(f"/v1/consents/{_consent_id(client, world)}/withdraw", headers=world.h("citizen"))
    after = client.get("/v1/me/person", headers=world.h("helper", pid))
    assert after.status_code == 403 and after.json()["code"] == "consent_required"
    assert client.get("/v1/me/person", headers=world.h("citizen")).status_code == 200, "the person still sees themself"
    # The helper can still see and restore the consent for the person.
    assert client.get("/v1/consents", headers=world.h("helper", pid)).status_code == 200
