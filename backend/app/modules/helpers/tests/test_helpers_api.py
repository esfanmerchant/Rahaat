"""Helper delegations and switching on a shared phone, through the HTTP API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import system_session
from app.core.security import hash_secret
from app.db import models
from app.modules.applications.tests.support import FAMILY_PIN, World, new_app
from app.modules.helpers import tickets


def _family(factory: Any, world: World, *, pin: str = FAMILY_PIN, scopes: tuple[str, ...] = ("track", "apply", "upload")) -> Any:
    """Another citizen of the same department who chose the world's helper."""
    account = factory.account(world.tenant, "citizen")
    with system_session() as db:
        db.add(models.HelperDelegation(tenant_id=world.tenant.id, helper_user_id=world.helper.user_id, person_id=account.person_id,
                                       scopes=list(scopes), pin_hash=hash_secret(pin),
                                       expires_at=datetime.now(UTC) + timedelta(days=30)))  # fmt: skip
    world.delegated.add(account.person_id)
    return account


def _switch(client: TestClient, world: World, person_id: uuid.UUID, pin: str = FAMILY_PIN, headers: dict[str, str] | None = None) -> Any:
    return client.post("/v1/helper/switch", json={"person_id": str(person_id), "pin": pin}, headers=headers or world.h("helper"))


def _as_helper(world: World, person_id: uuid.UUID, ticket: str | None) -> dict[str, str]:
    headers = world.h("helper", person_id, ticket=False)
    if ticket:
        headers["X-Helper-Ticket"] = ticket
    return headers


def _audit(tenant_id: uuid.UUID, action: str) -> list[models.AuditLog]:
    with system_session() as db:
        return list(db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant_id, models.AuditLog.action == action)
                               .order_by(models.AuditLog.seq)).all())  # fmt: skip


def test_a_helper_without_a_ticket_is_refused_and_it_is_audited(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    bare = client.get("/v1/applications", headers=_as_helper(world, pid, None))
    assert bare.status_code == 403 and bare.json()["code"] == "ticket_required"
    forged = client.get("/v1/applications", headers=_as_helper(world, pid, "not-a-real-ticket"))
    assert forged.status_code == 403 and forged.json()["code"] == "ticket_invalid"
    denied = [r for r in _audit(world.tenant.id, "access.denied") if r.reason in ("ticket_required", "ticket_invalid")]
    assert {r.reason for r in denied} == {"ticket_required", "ticket_invalid"}
    assert all(r.actor_id == str(world.helper.user_id) and r.object_id == str(pid) for r in denied)

    switched = _switch(client, world, pid)
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["person_id"] == str(pid) and body["display_name"] == "Test Citizen" and body["expires_in"] == 900
    ok = client.get("/v1/applications", headers=_as_helper(world, pid, body["ticket"]))
    assert ok.status_code == 200
    row = _audit(world.tenant.id, tickets.SWITCHED)[-1]
    assert row.actor_id == str(world.helper.user_id) and row.acting_for_person_id == pid
    assert body["ticket"] not in row.details and tickets.ticket_hash(body["ticket"]) in row.details, "only the hash is stored"


def test_a_ticket_belongs_to_one_session_and_one_family(client: TestClient, factory: Any, world: World) -> None:
    family_a, family_b = world.citizen, _family(factory, world)
    ticket_a = _switch(client, world, family_a.person_id).json()["ticket"]
    # The same ticket does not open another family, even one the helper may help.
    other = client.get("/v1/me/person", headers=_as_helper(world, family_b.person_id, ticket_a))
    assert other.status_code == 403 and other.json()["code"] == "ticket_invalid"
    # Another sign-in of the same helper (another phone) cannot use it.
    second_phone = factory.headers(client, world.helper)
    stolen = client.get("/v1/me/person", headers={**second_phone, "X-Acting-For": str(family_a.person_id), "X-Helper-Ticket": ticket_a})
    assert stolen.status_code == 403 and stolen.json()["code"] == "ticket_invalid"

    # Switching to family B ends the ticket for family A at once.
    ticket_b = _switch(client, world, family_b.person_id).json()["ticket"]
    assert client.get("/v1/me/person", headers=_as_helper(world, family_b.person_id, ticket_b)).json()["id"] == str(family_b.person_id)
    old = client.get("/v1/me/person", headers=_as_helper(world, family_a.person_id, ticket_a))
    assert old.status_code == 403 and old.json()["code"] == "ticket_invalid"

    # Handing the phone back ends the current ticket too.
    assert client.post("/v1/helper/switch/end", headers=world.h("helper")).status_code == 204
    ended = client.get("/v1/me/person", headers=_as_helper(world, family_b.person_id, ticket_b))
    assert ended.status_code == 403 and ended.json()["code"] == "ticket_invalid"


def test_a_wrong_family_pin_is_limited(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    lefts = []
    for _ in range(tickets.PIN_MAX_PER_FAMILY):
        wrong = _switch(client, world, pid, pin="1357")
        assert wrong.status_code == 403 and wrong.json()["code"] == "pin_incorrect"
        lefts.append(wrong.json()["attempts_left"])
    assert lefts == [4, 3, 2, 1, 0]
    locked = _switch(client, world, pid)  # even the right PIN waits now
    assert locked.status_code == 429 and locked.json()["code"] == "pin_locked"
    assert int(locked.headers["Retry-After"]) > 0
    reasons = [r.reason for r in _audit(world.tenant.id, tickets.SWITCH_DENIED)]
    assert reasons == ["wrong_pin"] * 5 + ["pin_locked"], "every refused switch is on record, in its own transaction"
    assert all(r.object_id == str(pid) and r.result == "denied" for r in _audit(world.tenant.id, tickets.SWITCH_DENIED))


def test_a_wrong_pin_count_resets_after_a_good_switch_and_strangers_are_refused(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    for _ in range(3):
        assert _switch(client, world, pid, pin="1357").status_code == 403
    assert _switch(client, world, pid).status_code == 200
    assert _switch(client, world, pid, pin="1357").json()["attempts_left"] == 4
    stranger = _switch(client, world, world.other_citizen.person_id)
    assert stranger.status_code == 403 and stranger.json()["code"] == "no_delegation"
    bad_body = client.post("/v1/helper/switch", json={"person_id": str(pid), "pin": "12ab"}, headers=world.h("helper"))
    assert bad_body.status_code == 422
    citizen = client.post("/v1/helper/switch", json={"person_id": str(pid), "pin": FAMILY_PIN}, headers=world.h("citizen"))
    assert citizen.status_code == 403 and citizen.json()["code"] == "role_not_allowed"


def test_revocation_kills_a_live_ticket_and_a_new_delegation_does_not_revive_it(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    ticket = _switch(client, world, pid).json()["ticket"]
    assert client.get("/v1/applications", headers=_as_helper(world, pid, ticket)).status_code == 200
    mine = client.get("/v1/me/helpers", headers=world.h("citizen")).json()
    assert len(mine) == 1 and mine[0]["status"] == "live" and mine[0]["pin_set"] is True
    revoked = client.post(f"/v1/me/helpers/{mine[0]['id']}/revoke", headers=world.h("citizen"))
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"

    after = client.get("/v1/applications", headers=_as_helper(world, pid, ticket))
    assert after.status_code == 403 and after.json()["code"] == "no_delegation"
    assert _switch(client, world, pid).json()["code"] == "no_delegation"

    granted = client.post("/v1/me/helpers", headers=world.h("citizen"),
                          json={"helper_phone": world.helper.identifier, "scopes": ["track"], "pin": "6181", "expires_in_days": 7})  # fmt: skip
    assert granted.status_code == 201, granted.text
    revived = client.get("/v1/applications", headers=_as_helper(world, pid, ticket))
    assert revived.status_code == 403 and revived.json()["code"] == "ticket_invalid", "an old ticket never comes back"
    assert _switch(client, world, pid, pin=FAMILY_PIN).json()["code"] == "pin_incorrect", "the new delegation has the new PIN"
    fresh = _switch(client, world, pid, pin="6181").json()
    assert fresh["scopes"] == ["track"]
    assert client.get("/v1/applications", headers=_as_helper(world, pid, fresh["ticket"])).status_code == 200
    write = client.post("/v1/applications", json={"program_id": str(world.program_id), "client_op_id": uuid.uuid4().hex},
                        headers=_as_helper(world, pid, fresh["ticket"]))  # fmt: skip
    assert write.status_code == 403 and write.json()["code"] == "scope_not_delegated"


def test_withdrawn_consent_stops_a_helper_with_a_live_ticket(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    ticket = _switch(client, world, pid).json()["ticket"]
    app_id = new_app(client, world).json()["id"]
    assert client.get(f"/v1/applications/{app_id}", headers=_as_helper(world, pid, ticket)).status_code == 200
    consent_id = next(c["id"] for c in client.get("/v1/consents", headers=world.h("citizen")).json() if c["status"] == "active")
    assert client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("citizen")).status_code == 200
    read = client.get(f"/v1/applications/{app_id}", headers=_as_helper(world, pid, ticket))
    assert read.status_code == 403 and read.json()["code"] == "consent_required"
    families = client.get("/v1/helper/families", headers=world.h("helper")).json()["items"]
    assert families[0]["consent_active"] is False and families[0]["application"] is None


def test_citizen_grants_a_helper_by_phone(client: TestClient, factory: Any, world: World) -> None:
    other_helper = factory.account(world.tenant, "helper")
    body = {"helper_phone": other_helper.identifier, "scopes": ["apply", "track"], "pin": "6181", "expires_in_days": 30}
    granted = client.post("/v1/me/helpers", json=body, headers=world.h("citizen"))
    assert granted.status_code == 201, granted.text
    out = granted.json()
    assert out["scopes"] == ["track", "apply"] and out["helper_name"] == "Test Helper"
    assert out["helper_phone_masked"].endswith(other_helper.identifier[-3:])
    assert other_helper.identifier not in granted.text, "the helper's number is shown masked"
    again = client.post("/v1/me/helpers", json=body, headers=world.h("citizen"))
    assert again.status_code == 409 and again.json()["code"] == "delegation_exists"

    citizen_number = client.post("/v1/me/helpers", json={**body, "helper_phone": world.other_citizen.identifier}, headers=world.h("citizen"))
    unknown = client.post("/v1/me/helpers", json={**body, "helper_phone": "0999-7777777"}, headers=world.h("citizen"))
    assert citizen_number.status_code == unknown.status_code == 404
    assert citizen_number.json()["detail"] == unknown.json()["detail"], "a citizen's number and an unknown number look the same"
    assert client.post("/v1/me/helpers", json={**body, "pin": "1234"}, headers=world.h("citizen")).json()["code"] == "weak_pin"
    real_looking = "03001234567"  # mock-lint: allow
    assert client.post("/v1/me/helpers", json={**body, "helper_phone": real_looking}, headers=world.h("citizen")).status_code == 422
    assert client.post("/v1/me/helpers", json={**body, "extra": 1}, headers=world.h("citizen")).status_code == 422
    # Only the person decides: the helper cannot grant or list on the family's behalf.
    assert client.get("/v1/me/helpers", headers=world.h("helper", world.citizen.person_id)).status_code == 403
    assert client.post("/v1/me/helpers", json=body, headers=world.h("other_citizen")).status_code == 201
    other_id = client.get("/v1/me/helpers", headers=world.h("other_citizen")).json()[0]["id"]
    assert client.post(f"/v1/me/helpers/{other_id}/revoke", headers=world.h("citizen")).status_code == 404

    # The new helper can now switch to the citizen with the citizen's PIN.
    helper_headers = factory.headers(client, other_helper)
    switched = client.post("/v1/helper/switch", json={"person_id": str(world.citizen.person_id), "pin": "6181"}, headers=helper_headers)
    assert switched.status_code == 200 and switched.json()["scopes"] == ["track", "apply"]
    actions = [r.action for r in _audit(world.tenant.id, "helper.delegation_granted")]
    assert len(actions) == 2


def test_my_families_shows_status_and_who_is_current(client: TestClient, factory: Any, world: World) -> None:
    pid = world.citizen.person_id
    second = _family(factory, world)
    third = _family(factory, world)
    app = new_app(client, world).json()
    _switch(client, world, pid)
    with system_session() as db:
        delegation = db.scalars(select(models.HelperDelegation).where(models.HelperDelegation.person_id == third.person_id)).one()
        delegation.revoked_at = datetime.now(UTC)
    listing = client.get("/v1/helper/families", headers=world.h("helper"))
    assert listing.status_code == 200, listing.text
    body = listing.json()
    by_person = {item["person_id"]: item for item in body["items"]}
    assert set(by_person) == {str(pid), str(second.person_id), str(third.person_id)} and body["live_count"] == 2
    mine = by_person[str(pid)]
    assert mine["current"] is True and mine["display_name"] == "Test Citizen" and mine["consent_active"] is True
    assert mine["application"]["id"] == app["id"] and mine["application"]["status"] == "draft"
    assert len(mine["application"]["tracking_symbols"]) == 3
    assert body["current_person_id"] == str(pid)
    gone = by_person[str(third.person_id)]
    assert gone["delegation_status"] == "revoked" and gone["display_name"] is None and gone["application"] is None
    # Seeing a family in the list is a read of their data: one row per family per hour, not one per refresh.
    client.get("/v1/helper/families", headers=world.h("helper"))
    views = [r for r in _audit(world.tenant.id, "person.data_viewed") if '"family_list"' in r.details]
    assert sorted(r.object_id for r in views) == sorted([str(pid), str(second.person_id)])
    assert client.get("/v1/helper/families", headers=world.h("citizen")).status_code == 403


def test_an_expired_ticket_is_refused(client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = world.citizen.person_id
    monkeypatch.setattr(tickets, "TICKET_TTL", timedelta(seconds=-1))
    ticket = _switch(client, world, pid).json()["ticket"]
    expired = client.get("/v1/me/person", headers=_as_helper(world, pid, ticket))
    assert expired.status_code == 403 and expired.json()["code"] == "ticket_expired"


def test_wrong_pins_sent_in_parallel_are_all_counted(client: TestClient, world: World) -> None:
    from concurrent.futures import ThreadPoolExecutor

    pid = world.citizen.person_id
    headers = world.h("helper")
    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(lambda _: _switch(client, world, pid, pin="1357", headers=headers).json()["code"], range(8)))
    assert codes.count("pin_incorrect") == tickets.PIN_MAX_PER_FAMILY and codes.count("pin_locked") == 3, codes
