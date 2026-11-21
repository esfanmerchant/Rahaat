"""POST /v1/sync: queued offline changes are applied once, re-authorised now, and merged field by field."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.db import system_session
from app.core.security import hash_secret
from app.db import models
from app.modules.applications.tests.support import FAMILY_PIN, Fakes, World, eligible_patch, new_app


def _op(kind: str, *, entity_id: uuid.UUID | str | None = None, base_version: int | None = None, patch: dict[str, Any] | None = None,
        op_id: str | None = None) -> dict[str, Any]:  # fmt: skip
    body: dict[str, Any] = {"op_id": op_id or uuid.uuid4().hex, "kind": kind, "patch": patch or {},
                            "created_at": datetime.now(UTC).isoformat()}  # fmt: skip
    if entity_id is not None:
        body["entity_id"] = str(entity_id)
    if base_version is not None:
        body["base_version"] = base_version
    return body


def _create(world: World, entity_id: uuid.UUID, **kw: Any) -> dict[str, Any]:
    return _op("create_application", entity_id=entity_id, patch={"program_id": str(world.program_id)}, **kw)


def _sync(client: TestClient, headers: dict[str, str], device_id: str, ops: list[dict[str, Any]]) -> Any:
    return client.post("/v1/sync", json={"device_id": device_id, "ops": ops}, headers=headers)


def _count(model: Any, *where: Any) -> int:
    with system_session() as db:
        return int(db.scalar(select(func.count()).select_from(model).where(*where)) or 0)


def test_five_applications_made_offline_and_sent_twice_end_up_as_five(client: TestClient, factory: Any, world: World) -> None:
    """The brief's case: a helper with five families, no signal, then a flaky connection that makes the phone send twice."""
    families = [world.citizen]
    for _ in range(4):
        account = factory.account(world.tenant, "citizen")
        with system_session() as db:
            db.add(models.HelperDelegation(tenant_id=world.tenant.id, helper_user_id=world.helper.user_id, person_id=account.person_id,
                                           scopes=["track", "apply", "upload"], pin_hash=hash_secret(FAMILY_PIN),
                                           expires_at=datetime.now(UTC) + timedelta(days=30)))  # fmt: skip
        world.delegated.add(account.person_id)
        families.append(account)
    device = "shared-phone-" + uuid.uuid4().hex[:8]
    queued = {f.person_id: [_create(world, uuid.uuid4())] for f in families}
    for family in families:
        app_id = queued[family.person_id][0]["entity_id"]
        queued[family.person_id].append(_op("patch_application", entity_id=app_id, base_version=1, patch=eligible_patch()))

    first = {}
    for family in families:  # each family's queue goes up after switching to that family with its PIN
        response = _sync(client, world.h("helper", family.person_id), device, queued[family.person_id])
        assert response.status_code == 200, response.text
        first[family.person_id] = response.json()["results"]
        assert [r["status"] for r in first[family.person_id]] == ["applied", "applied"]
    for family in families:  # the connection dropped before the answers arrived, so the phone sends everything again
        again = _sync(client, world.h("helper", family.person_id), device, queued[family.person_id]).json()["results"]
        assert [r["status"] for r in again] == ["duplicate", "duplicate"]
        assert [r["original_status"] for r in again] == ["applied", "applied"]
        assert again[0]["entity_id"] == first[family.person_id][0]["entity_id"] and again[1]["version"] == 2

    person_ids = [f.person_id for f in families]
    assert _count(models.Application, models.Application.person_id.in_(person_ids)) == 5, "five, not ten"
    assert _count(models.SyncOp, models.SyncOp.device_id == device) == 10
    with system_session() as db:
        created = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == world.tenant.id,
                                                           models.AuditLog.action == "application.created")).all()  # fmt: skip
        assert len(created) == 5 and all(r.actor_id == str(world.helper.user_id) for r in created)
        assert {r.acting_for_person_id for r in created} == set(person_ids), "each one names the helper and the family"
        forms = db.scalars(select(models.Application.form).where(models.Application.person_id.in_(person_ids))).all()
        assert all(f["household_size"]["value"] == 5 for f in forms)


def test_a_citizen_batch_creates_edits_and_submits_once(client: TestClient, world: World, fakes: Fakes) -> None:
    app_id = uuid.uuid4()
    device = "phone-" + uuid.uuid4().hex[:10]
    ops = [_create(world, app_id), _op("patch_application", entity_id=app_id, base_version=1, patch=eligible_patch()),
           _op("submit_application", entity_id=app_id)]  # fmt: skip
    fakes.outcome = "needs_human"
    response = _sync(client, world.h("citizen"), device, ops)
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["applied", "applied", "applied"]
    assert results[0]["entity_id"] == str(app_id) and results[0]["tracking_code"].startswith("R-")
    assert results[2]["application_status"] == "in_review" and fakes.n("decide_and_record") == 1
    repeat = _sync(client, world.h("citizen"), device, ops).json()["results"]
    assert [r["status"] for r in repeat] == ["duplicate"] * 3
    assert fakes.n("decide_and_record") == 1, "the submit was not run again"
    assert _count(models.Application, models.Application.person_id == world.citizen.person_id) == 1
    assert client.get(f"/v1/applications/{app_id}", headers=world.h("citizen")).json()["status"] == "in_review"


def test_a_withdrawn_consent_rejects_a_queued_op(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    device = "phone-" + uuid.uuid4().hex[:10]
    queued = _op("patch_application", entity_id=app["id"], base_version=1, patch=eligible_patch())
    consent_id = next(c["id"] for c in client.get("/v1/consents", headers=world.h("citizen")).json() if c["status"] == "active")
    assert client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("citizen")).status_code == 200

    result = _sync(client, world.h("citizen"), device, [queued]).json()["results"][0]
    assert result["status"] == "rejected" and result["reason"] == "consent_required" and result["retryable"] is False
    repeat = _sync(client, world.h("citizen"), device, [queued]).json()["results"][0]
    assert repeat["status"] == "duplicate" and repeat["original_status"] == "rejected" and repeat["reason"] == "consent_required"
    with system_session() as db:
        stored = db.get(models.Application, uuid.UUID(app["id"]))
        assert stored.form["household_size"]["value"] is None and stored.status == "on_hold_consent", "nothing was applied"
        denied = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == world.tenant.id, models.AuditLog.action == "access.denied",
                                                          models.AuditLog.reason == "consent_required")).all()  # fmt: skip
        assert denied, "the refused op is on record"


def test_edits_against_an_old_version_merge_field_by_field(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    url = f"/v1/applications/{app['id']}"
    online = client.patch(url, json={"base_version": 1, "form_patch": {"household_size": {"value": 6, "provenance": "typed"}}},
                          headers=world.h("citizen"))  # fmt: skip
    assert online.json()["version"] == 2
    device = "phone-" + uuid.uuid4().hex[:10]
    untouched = _op("patch_application", entity_id=app["id"], base_version=1,
                    patch={"income_band": {"value": "under_15k", "provenance": "tapped"}, "household_size": {"value": 6}})  # fmt: skip
    clash = _op("patch_application", entity_id=app["id"], base_version=1,
                patch={"household_size": {"value": 4, "provenance": "tapped"}, "is_widow": {"value": True, "provenance": "tapped"}})  # fmt: skip
    results = _sync(client, world.h("citizen"), device, [untouched, clash]).json()["results"]
    assert results[0]["status"] == "applied" and results[0]["applied_fields"] == ["income_band"]
    assert results[0]["unchanged_fields"] == ["household_size"] and results[0]["version"] == 3
    assert results[1]["status"] == "conflict" and results[1]["applied_fields"] == ["is_widow"]
    conflict = results[1]["conflicts"][0]
    assert conflict["field"] == "household_size" and conflict["your_value"] == 4 and conflict["reason"] == "changed_since_your_version"
    assert conflict["server_value"]["value"] == 6
    form = client.get(url, headers=world.h("citizen")).json()["form"]
    assert form["household_size"]["value"] == 6 and form["income_band"]["value"] == "under_15k" and form["is_widow"]["value"] is True
    # The device resolves the conflict with a new op against the current version.
    resolved = _op("patch_application", entity_id=app["id"], base_version=4, patch={"household_size": {"value": 4, "provenance": "tapped"}})
    assert _sync(client, world.h("citizen"), device, [resolved]).json()["results"][0]["status"] == "applied"
    bad = _op("patch_application", entity_id=app["id"], base_version=1, patch={"household_size": {"value": 9, "provenance": "registry"}})
    rejected = _sync(client, world.h("citizen"), device, [bad]).json()["results"][0]
    assert rejected["status"] == "rejected" and rejected["reason"] == "invalid_form"


def test_a_signed_card_field_is_a_conflict_not_an_overwrite(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    with system_session() as db:
        row = db.get(models.Application, uuid.UUID(app["id"]))
        form = dict(row.form)
        form["full_name"] = {"value": "Test Citizen", "confidence": 1.0, "provenance": "qr_signed", "verified": True}
        row.form = form
    op = _op("patch_application", entity_id=app["id"], base_version=1, patch={"full_name": {"value": "Someone Else", "provenance": "typed"}})
    result = _sync(client, world.h("citizen"), "phone-" + uuid.uuid4().hex[:10], [op]).json()["results"][0]
    assert result["status"] == "conflict" and result["conflicts"][0]["reason"] == "field_locked"
    assert client.get(f"/v1/applications/{app['id']}", headers=world.h("citizen")).json()["form"]["full_name"]["value"] == "Test Citizen"


def test_helper_sync_needs_a_ticket_and_stays_with_that_family(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    device = "shared-" + uuid.uuid4().hex[:10]
    op = _create(world, uuid.uuid4())
    no_ticket = _sync(client, world.h("helper", pid, ticket=False), device, [op])
    assert no_ticket.status_code == 403 and no_ticket.json()["code"] == "ticket_required"
    elsewhere = {**_create(world, uuid.uuid4()), "person_id": str(world.other_citizen.person_id)}
    results = _sync(client, world.h("helper", pid), device, [elsewhere, op]).json()["results"]
    assert results[0]["status"] == "rejected" and results[0]["reason"] == "wrong_person" and results[0]["retryable"] is True
    assert results[1]["status"] == "applied"
    assert _count(models.SyncOp, models.SyncOp.op_id == elsewhere["op_id"]) == 0, "a retryable refusal is not recorded"


def test_op_ids_are_not_shared_between_people_and_bad_ops_are_refused(client: TestClient, world: World) -> None:
    device = "phone-" + uuid.uuid4().hex[:10]
    op = _create(world, uuid.uuid4())
    assert _sync(client, world.h("citizen"), device, [op]).json()["results"][0]["status"] == "applied"
    stolen = _sync(client, world.h("other_citizen"), device, [op]).json()["results"][0]
    assert stolen["status"] == "rejected" and stolen["reason"] == "op_id_taken" and stolen["entity_id"] is None
    missing = _sync(client, world.h("citizen"), device, [_op("create_application", patch={"form": {}})]).json()["results"][0]
    assert missing["status"] == "rejected" and missing["reason"] == "invalid_op"
    nowhere = _sync(client, world.h("citizen"), device, [_op("submit_application", entity_id=uuid.uuid4())]).json()["results"][0]
    assert nowhere["status"] == "rejected" and nowhere["reason"] == "not_found"
    taken = _sync(client, world.h("other_citizen"), device, [_create(world, uuid.UUID(op["entity_id"]))]).json()["results"][0]
    assert taken["status"] == "rejected" and taken["reason"] == "entity_id_taken", "another person's application id is never reused"
    assert _sync(client, world.h("citizen"), device, [{**op, "surprise": 1}]).status_code == 422
    assert client.post("/v1/sync", json={"device_id": device, "ops": [op] * 51}, headers=world.h("citizen")).status_code == 422
    assert _sync(client, world.h("officer"), device, [op]).status_code == 403


def test_the_same_batch_arriving_four_times_at_once_applies_once(client: TestClient, world: World) -> None:
    from concurrent.futures import ThreadPoolExecutor

    app_id = uuid.uuid4()
    device = "phone-" + uuid.uuid4().hex[:10]
    ops = [_create(world, app_id), _op("patch_application", entity_id=app_id, base_version=1, patch=eligible_patch())]
    headers = world.h("citizen")
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: _sync(client, headers, device, ops), range(4)))
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    statuses = [[res["status"] for res in r.json()["results"]] for r in responses]
    assert sum(s.count("applied") for s in statuses) == 2 and sum(s.count("duplicate") for s in statuses) == 6, statuses
    assert _count(models.Application, models.Application.person_id == world.citizen.person_id) == 1
    with system_session() as db:
        assert db.get(models.Application, app_id).version == 2, "the edit was applied exactly once"


def test_a_helper_resending_one_familys_ops_from_another_family_is_told_to_switch(client: TestClient, factory: Any, world: World) -> None:
    second = factory.account(world.tenant, "citizen")
    with system_session() as db:
        db.add(models.HelperDelegation(tenant_id=world.tenant.id, helper_user_id=world.helper.user_id, person_id=second.person_id,
                                       scopes=["track", "apply", "upload"], pin_hash=hash_secret(FAMILY_PIN),
                                       expires_at=datetime.now(UTC) + timedelta(days=30)))  # fmt: skip
    world.delegated.add(second.person_id)
    device = "shared-" + uuid.uuid4().hex[:10]
    op = _create(world, uuid.uuid4())
    assert _sync(client, world.h("helper", world.citizen.person_id), device, [op]).json()["results"][0]["status"] == "applied"
    elsewhere = _sync(client, world.h("helper", second.person_id), device, [op]).json()["results"][0]
    assert elsewhere["status"] == "rejected" and elsewhere["reason"] == "wrong_person" and elsewhere["retryable"] is True
    back = _sync(client, world.h("helper", world.citizen.person_id), device, [op]).json()["results"][0]
    assert back["status"] == "duplicate" and back["original_status"] == "applied"
    # A citizen naming someone else in an op is refused for good.
    other = {**_create(world, uuid.uuid4()), "person_id": str(world.other_citizen.person_id)}
    refused = _sync(client, world.h("citizen"), device, [other]).json()["results"][0]
    assert refused["reason"] == "wrong_person" and refused["retryable"] is False
