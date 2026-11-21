"""The feature-phone channel against the real app and database: key auth, status, message check, consent, callback, SMS."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core import apikeys
from app.core.crypto import blind_index
from app.core.db import get_engine, system_session
from app.db import models
from app.mocks.state import STATE
from app.modules.applications.tests.support import World
from app.modules.ussd import router as ussd_router
from app.modules.ussd import service
from app.modules.ussd.service import Channel

PIN = "4826"


def _key(tenant_id: uuid.UUID, scopes: list[str]) -> dict[str, str]:
    raw, prefix, digest = apikeys.generate()
    with system_session() as db:
        db.add(models.ApiKey(id=uuid.uuid4(), tenant_id=tenant_id, name="aggregator", prefix=prefix, key_hash=digest, scopes=scopes,
                             rate_limit_per_min=10_000, expires_at=datetime.now(UTC) + timedelta(days=1)))  # fmt: skip
    return {"Authorization": f"Bearer {raw}"}


class Phone:
    """One handset: a session id, the number, the `*` history."""

    def __init__(self, client: TestClient, headers: dict[str, str], msisdn: str) -> None:
        self.client, self.headers, self.msisdn = client, headers, msisdn
        self.session = f"s-{uuid.uuid4().hex[:12]}"
        self.history: list[str] = []

    def press(self, key: str | None = None) -> str:
        if key is not None:
            self.history.append(key)
        response = self.client.post("/v1/channels/ussd", headers=self.headers,
                                    json={"session_id": self.session, "msisdn": self.msisdn, "text": "*".join(self.history)})  # fmt: skip
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text.startswith(("CON ", "END ")), response.text
        assert len(response.text) - 4 <= 182
        return response.text

    def run(self, *keys: str) -> str:
        out = self.press()
        for key in keys:
            out = self.press(key)
        return out


@pytest.fixture()
def lines(world: World) -> dict[str, Any]:
    """A department with a citizen who has one application, plus a channel key and the keypad of each phone."""
    tid, pid = world.tenant.id, world.citizen.person_id
    with system_session() as db:
        code = f"R-{uuid.uuid4().int % 90_000 + 10_000}"
        db.add(models.Application(tenant_id=tid, program_id=world.program_id, person_id=pid, status="in_review", tracking_code=code,
                                  submitted_via="web", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)))  # fmt: skip
    return {"code": code, "digits": code[2:], "key": _key(tid, ["channels:ussd", "channels:sms"]), "world": world}


def _audit_details(tenant_id: uuid.UUID, action: str) -> list[dict[str, Any]]:
    import json

    with system_session() as db:
        rows = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == tenant_id, models.AuditLog.action == action)
                          .order_by(models.AuditLog.seq)).all()  # fmt: skip
        return [{"result": r.result, "reason": r.reason, "actor_type": r.actor_type, **json.loads(r.details)} for r in rows]


def test_channel_routes_need_a_key_with_the_channel_scope(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    body = {"session_id": "s-1", "msisdn": world.citizen.identifier, "text": ""}
    assert client.post("/v1/channels/ussd", json=body).status_code == 401
    wrong = _key(world.tenant.id, ["scam:check", "channels:sms"])
    refused = client.post("/v1/channels/ussd", json=body, headers=wrong)
    assert refused.status_code == 403 and refused.json()["code"] == "api_scope_missing"
    only_ussd = _key(world.tenant.id, ["channels:ussd"])
    sms = client.post("/v1/channels/sms/inbound", json={"msisdn": world.citizen.identifier, "text": "HELP"}, headers=only_ussd)
    assert sms.status_code == 403 and sms.json()["code"] == "api_scope_missing"
    for who in ("citizen", "officer", "helper"):  # a signed-in person is not a channel
        assert client.post("/v1/channels/ussd", json=body, headers=world.h(who)).status_code == 403
    assert client.post("/v1/channels/ussd", json={**body, "extra": 1}, headers=lines["key"]).status_code == 422
    assert client.post("/v1/channels/ussd", json={**body, "session_id": "has space"}, headers=lines["key"]).status_code == 422


def test_a_new_key_with_a_channel_scope_waits_for_a_second_admin(client: TestClient, factory: Any, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    admin = factory.account(world.tenant, "admin")
    headers = factory.headers(client, admin)
    made = client.post("/v1/admin/api-keys", json={"name": "aggregator", "scopes": ["channels:ussd"], "expires_in_days": 30}, headers=headers)
    assert made.status_code == 201, made.text
    assert made.json()["scopes"] == [] and made.json()["requested_scopes"] == ["channels:ussd"], "a key that acts for citizens needs approval"
    body = {"session_id": "s-1", "msisdn": world.citizen.identifier, "text": ""}
    waiting = client.post("/v1/channels/ussd", json=body, headers={"Authorization": f"Bearer {made.json()['key']}"})
    assert waiting.status_code == 403 and waiting.json()["code"] == "api_key_pending_approval"


def test_the_menu_over_http_status_needs_the_right_phone_and_code(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    mine = Phone(client, lines["key"], world.citizen.identifier)
    assert mine.run().startswith("CON Rahat (prototype)\n1 English")
    assert "Check my application" in mine.press("1")
    assert "Type the 5 digits" in mine.press("1")
    answer = mine.press(lines["digits"])
    assert answer.startswith(f"CON {lines['code']} (") and "A person is checking it" in answer
    assert "Zainab" not in answer and "Test Citizen" not in answer, "only the status is shown"

    for who, msisdn in (("another citizen", world.other_citizen.identifier), ("a phone nobody registered", "0999-9999999")):
        other = Phone(client, lines["key"], msisdn)
        assert other.run("1", "1").startswith("CON")
        not_found = other.press(lines["digits"])
        assert "Not found" in not_found, who
    # The answer for a wrong code on my own phone is identical to the answer for someone else's code.
    wrong = Phone(client, lines["key"], world.citizen.identifier)
    assert wrong.run("1", "1", "00001").replace("00001", "X") == Phone(client, lines["key"], "0999-9999999").run("1", "1", "00001").replace(
        "00001", "X"
    )

    # Roman Urdu, and the same status in the person's own words.
    ru = Phone(client, lines["key"], world.citizen.identifier)
    answer = ru.run("2", "1", lines["digits"])
    assert "afsar" in answer and "Wapas" in answer


def test_a_real_looking_number_is_refused_and_nothing_is_stored(client: TestClient, lines: dict[str, Any]) -> None:
    real = "+923001234567"  # mock-lint: allow
    response = client.post("/v1/channels/ussd", headers=lines["key"], json={"session_id": "s-real", "msisdn": real, "text": ""})
    assert response.text == "END This prototype accepts only mock numbers."
    sms = client.post("/v1/channels/sms/inbound", headers=lines["key"], json={"msisdn": real, "text": "STATUS 12345"})
    assert sms.status_code == 200 and sms.json() == {"accepted": False, "command": "rejected", "reply_sent": False}
    denied = _audit_details(lines["world"].tenant.id, "channel.refused")
    assert len(denied) == 2 and all(d["result"] == "denied" and "3001234567" not in str(d) for d in denied)
    with system_session() as db:
        assert db.scalar(select(models.UssdSession.id).where(models.UssdSession.session_key == service._session_key("s-real"))) is None


def test_sessions_resume_repeat_safely_and_time_out_after_three_minutes(lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    channel = Channel(tenant_id=world.tenant.id, kind="ussd", actor_id=uuid.uuid4())
    call = {"session_id": "s-time-1", "msisdn": world.citizen.identifier}
    first = service.handle_ussd(channel, text="", now=1000.0, **call)
    assert first.kind == "CON" and "English" in first.text
    assert service.handle_ussd(channel, text="", now=1001.0, **call) == first, "a repeated request gets the same answer"
    menu_screen = service.handle_ussd(channel, text="1", now=1010.0, **call)
    assert "Check my application" in menu_screen.text
    assert service.handle_ussd(channel, text="1", now=1011.0, **call) == menu_screen, "the aggregator retried: no second step"
    late = service.handle_ussd(channel, text="1*1", now=1010.0 + 181, **call)
    assert late.kind == "END" and "*786#" in late.text
    again = service.handle_ussd(channel, text="", now=1010.0 + 200, **call)
    assert again.kind == "CON" and "English" in again.text, "dialling again after the end starts over"
    # A session id is bound to the phone that opened it.
    stolen = service.handle_ussd(channel, text="1", now=1300.0, session_id="s-time-1", msisdn=world.other_citizen.identifier)
    assert stolen.kind == "END" and "busy" in stolen.text


def test_check_a_message_confirms_our_own_sms_and_not_a_forgery(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    sms = client.post("/v1/channels/sms/inbound", headers=lines["key"], json={"msisdn": world.citizen.identifier, "text": "HELP"})
    assert sms.status_code == 200 and sms.json()["reply_sent"] is True
    with system_session() as db:
        body = db.scalar(select(models.Notification.body).where(models.Notification.tenant_id == world.tenant.id,
                                                                models.Notification.template == "channel_help"))  # fmt: skip
    assert body and body.startswith("Rahat: send STATUS") and body.endswith(tuple("23456789ABCDEFGHJKMNPQRSTUVWXYZ"))
    code = body.rsplit(" ", 1)[1]
    phone = Phone(client, lines["key"], world.citizen.identifier)
    assert "genuine Rahat message" in phone.run("1", "2", code.lower())
    forged = Phone(client, lines["key"], world.citizen.identifier)
    answer = forged.run("1", "2", "ZZZZZZ")
    assert "cannot confirm" in answer and "Do not pay" in answer


def test_stop_sharing_needs_the_pin_and_blocks_the_officer_on_the_very_next_read(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    tid, pid = world.tenant.id, world.citizen.person_id

    def officer_sees_person() -> int:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT set_config('app.role', 'officer', true), set_config('app.tenant_id', :t, true), "
                              "set_config('app.user_id', :u, true)"), {"t": str(tid), "u": str(world.officer.user_id)})  # fmt: skip
            return int(conn.execute(text("SELECT count(*) FROM persons WHERE id = :p"), {"p": str(pid)}).scalar_one())

    assert officer_sees_person() == 1
    other = Phone(client, lines["key"], world.other_citizen.identifier)
    assert "not right" in other.run("1", "3", "1111")  # a wrong PIN changes nothing
    assert officer_sees_person() == 1
    thief = Phone(client, lines["key"], "0999-9999999")
    assert "not right" in thief.run("1", "3", PIN), "an unregistered number gets the same answer as a wrong PIN"

    mine = Phone(client, lines["key"], world.citizen.identifier)
    assert "type your pin" in mine.run("1", "3").lower()
    done = mine.press(PIN)
    assert done.startswith("END Done. Rahat stopped using your data")
    assert officer_sees_person() == 0, "the database stops the officer on the next query"
    with system_session() as db:
        consents = db.scalars(select(models.Consent).where(models.Consent.person_id == pid)).all()
        assert consents and all(c.status == "withdrawn" for c in consents)
        held = db.scalars(select(models.Application.status).where(models.Application.person_id == pid)).all()
        assert held == ["on_hold_consent"]
    assert _audit_details(tid, "consent.withdrawn"), "the real consent service wrote its own audit row"
    assert _audit_details(tid, "channel.consent_withdrawn")[0]["channel"] == "ussd"
    refused = _audit_details(tid, "channel.consent_stop_refused")
    assert len(refused) == 2 and all(r["result"] == "denied" and r["channel"] == "ussd" for r in refused)
    assert PIN not in str(refused) and "1111" not in str(refused), "a PIN is never written down"
    # The person can still see their own application, now on hold.
    status = Phone(client, lines["key"], world.citizen.identifier)
    assert "On hold" in status.run("1", "1", lines["digits"])


def test_five_wrong_pins_lock_the_account_like_a_failed_sign_in(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    phone = Phone(client, lines["key"], world.citizen.identifier)
    phone.run("1", "3")
    answers = [phone.press(f"{n}{n}{n}{n}") for n in (1, 2, 3)]
    assert answers[-1].startswith("END")  # three wrong tries end the session
    for _ in range(2):
        again = Phone(client, lines["key"], world.citizen.identifier)
        again.run("1", "3")
        again.press("7777")
    locked = Phone(client, lines["key"], world.citizen.identifier)
    locked.run("1", "3")
    assert locked.press(PIN).startswith("END Too many tries"), "even the right PIN is refused while the account is locked"
    login = client.post("/v1/auth/login", json={"identifier": world.citizen.identifier, "secret": PIN})
    assert login.status_code == 429, "the same lock holds for sign-in"


def test_talk_to_a_person_opens_one_callback_case_with_a_handoff_note(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    phone = Phone(client, lines["key"], world.citizen.identifier)
    assert "1 Yes, call me" in phone.run("1", "4")
    assert phone.press("1").startswith("END Thank you")
    again = Phone(client, lines["key"], world.citizen.identifier)
    assert again.run("1", "4", "1").startswith("END Thank you")
    unknown = Phone(client, lines["key"], "0999-9999999")
    assert unknown.run("1", "4", "1").startswith("END Thank you"), "the same words for a number nobody registered"
    cases = client.get("/v1/cases", headers=world.h("officer")).json()["items"]
    callbacks = [c for c in cases if c["opened_reason"] == "callback_requested"]
    assert len(callbacks) == 1, "asking twice does not queue twice, and an unknown number queues nothing"
    assert callbacks[0]["kind"] == "complaint" and callbacks[0]["status"] == "open"
    detail = client.get(f"/v1/cases/{callbacks[0]['id']}", headers=world.h("officer")).json()
    assert "call back" in detail["handoff"]["question"] and "USSD" in detail["handoff"]["understanding"]
    rows = _audit_details(world.tenant.id, "channel.callback_requested")
    assert [r["registered"] for r in rows] == [True, True, False] and rows[0]["new_case"] and not rows[1]["new_case"]


def test_sms_commands_reply_through_the_mock_gateway_in_both_languages(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    phone = world.citizen.identifier
    STATE.sms_outbox.clear()

    def send(body: str, message_id: str | None = None) -> dict[str, Any]:
        payload = {"msisdn": phone, "text": body, **({"message_id": message_id} if message_id else {})}
        response = client.post("/v1/channels/sms/inbound", headers=lines["key"], json=payload)
        assert response.status_code == 200, response.text
        return response.json()

    assert send(f"STATUS R-{lines['digits']}") == {"accepted": True, "command": "status", "reply_sent": True}
    assert send(f"halat {lines['digits']}")["reply_sent"] is True
    assert send("STATUS 00001")["command"] == "status"
    assert send("VERIFY ZZZZZZ")["command"] == "verify"
    assert send("madad")["command"] == "help"
    sent = [m for m in STATE.sms_outbox if m["to"] == phone]
    bodies = {m["body"].split(" Code ")[0] for m in sent}
    assert any(b.startswith(f"Rahat: {lines['code']} (") and "A person is checking it" in b for b in bodies), bodies
    assert any("Aik afsar dekh raha hai" in b for b in bodies), "a Roman Urdu keyword gets a Roman Urdu reply"
    assert any("could not find that code" in b for b in bodies) and any("cannot confirm that message" in b for b in bodies)
    assert any("Afsar ke liye *786# dial karein" in b for b in bodies)
    assert all(len(m["body"]) <= 160 and m["body"].rsplit(" ", 1)[1].isalnum() for m in sent), "one SMS each, ending with a verify code"
    assert all(m["sender"] == "RAHAT" for m in sent)
    with system_session() as db:
        rows = db.scalars(
            select(models.Notification).where(models.Notification.tenant_id == world.tenant.id, models.Notification.template.like("channel_%"))
        ).all()
        assert len(rows) == 5 and all(r.status == "sent" and r.verify_code and r.person_id == world.citizen.person_id for r in rows)
        assert {r.lang for r in rows} == {"en", "ru"}
    sms_audit = _audit_details(world.tenant.id, "channel.status_checked")
    assert len(sms_audit) == 3 and all(a["channel"] == "sms" for a in sms_audit)

    # The same message id is answered once.
    before = len([m for m in STATE.sms_outbox if m["to"] == phone])
    assert send("HELP", "msg-1")["command"] == "help"
    assert send("HELP", "msg-1") == {"accepted": True, "command": "duplicate", "reply_sent": False}
    assert len([m for m in STATE.sms_outbox if m["to"] == phone]) == before + 1


def test_sms_stop_needs_the_pin_and_the_reply_still_arrives_after_consent_is_gone(client: TestClient, lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    phone = world.citizen.identifier
    STATE.sms_outbox.clear()
    post = lambda body: client.post("/v1/channels/sms/inbound", headers=lines["key"], json={"msisdn": phone, "text": body}).json()  # noqa: E731
    assert post("STOP 1111")["command"] == "stop"
    assert post("STOP 12")["command"] == "bad_argument"
    with system_session() as db:
        assert db.scalar(select(models.Consent.status).where(models.Consent.person_id == world.citizen.person_id)) == "active"
    assert post(f"ROKEIN {PIN}")["reply_sent"] is True
    with system_session() as db:
        assert db.scalar(select(models.Consent.status).where(models.Consent.person_id == world.citizen.person_id)) == "withdrawn"
    texts = [m["body"] for m in STATE.sms_outbox if m["to"] == phone]
    assert any("PIN is not right" in t for t in texts) and any("band kar diya" in t for t in texts)
    assert not any(PIN in t or "1111" in t for t in texts)
    assert [r["channel"] for r in _audit_details(world.tenant.id, "channel.consent_withdrawn")] == ["sms"]


def test_free_text_is_checked_for_scams_with_the_same_classifier(client: TestClient, lines: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from app.contracts.common import ScamLabel
    from app.contracts.decision import TypedDecision

    world: World = lines["world"]
    calls: list[str] = []

    def fake(message: str, sender: str | None = None, **_: Any) -> TypedDecision[ScamLabel]:
        calls.append(message)
        return TypedDecision[ScamLabel](choice="advance_fee", probabilities={"advance_fee": 0.9}, confidence=0.9, route="auto",
                                        reasons=["fee"], model_version="test", abstained=False)  # fmt: skip

    monkeypatch.setattr("app.modules.scam.service.classify_message", fake)
    STATE.sms_outbox.clear()
    response = client.post(
        "/v1/channels/sms/inbound", headers=lines["key"], json={"msisdn": world.citizen.identifier, "text": "pay a fee to get relief"}
    )
    assert response.json()["command"] == "unknown" and calls == ["pay a fee to get relief"]
    assert any("looks like a scam" in m["body"] for m in STATE.sms_outbox)
    rows = _audit_details(world.tenant.id, "channel.message_unrecognised")
    assert rows[0]["scam_label"] == "advance_fee" and "pay a fee" not in str(rows), "the text itself is not stored"


def test_one_phone_cannot_flood_the_line(client: TestClient, lines: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    world: World = lines["world"]
    monkeypatch.setattr(service, "REQUESTS_PER_MINUTE", 4)
    phone = Phone(client, lines["key"], world.citizen.identifier)
    answers = [phone.press("1" if i else None) for i in range(4)]
    assert all(a.startswith("CON") for a in answers)
    assert phone.press("1") == "END Too many requests. Please wait a minute."
    flooded = client.post("/v1/channels/sms/inbound", headers=lines["key"], json={"msisdn": world.citizen.identifier, "text": "HELP"})
    assert flooded.json() == {"accepted": False, "command": "throttled", "reply_sent": False}
    elsewhere = Phone(client, lines["key"], world.other_citizen.identifier)
    assert elsewhere.press().startswith("CON"), "another phone has its own bucket"


def test_lookups_are_limited_per_phone(client: TestClient, lines: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    world: World = lines["world"]
    monkeypatch.setattr(service, "LOOKUP_PER_MINUTE", 2)
    phone = Phone(client, lines["key"], world.citizen.identifier)
    phone.run("1", "1")
    assert "A person is checking" in phone.press(lines["digits"])
    assert "A person is checking" in phone.press(lines["digits"])
    assert "Not found" in phone.press(lines["digits"]), "past the limit the answer is the plain 'not found'"


def test_the_demo_relay_runs_the_same_menu_without_a_key_and_only_in_demo_mode(client: TestClient, lines: dict[str, Any],
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    world: World = lines["world"]
    monkeypatch.setattr(ussd_router, "DEMO_TENANTS", [{"slug": world.tenant.slug, "name": "t", "name_ur": "t", "region": "PK-SD"}])
    body = {"session_id": "demo-1", "msisdn": world.citizen.identifier, "text": ""}
    first = client.post("/v1/demo/ussd", json=body)
    assert first.status_code == 200 and first.json()["kind"] == "CON" and "English" in first.json()["text"]
    shown = client.post("/v1/demo/ussd", json={**body, "text": "1"}).json()
    assert "Check my application" in shown["text"]
    sms = client.post("/v1/demo/sms", json={"msisdn": world.citizen.identifier, "text": f"STATUS {lines['digits']}"}).json()
    assert sms["accepted"] and sms["reply_sent"] and len(sms["messages"]) == 1 and "A person is checking it" in sms["messages"][0]["body"]
    thread = client.get("/v1/demo/sms", params={"msisdn": world.citizen.identifier}).json()
    assert [m["id"] for m in thread] == [m["id"] for m in sms["messages"]]
    personas = client.get("/v1/demo/ussd/personas").json()
    assert personas["service_code"] == "*786#" and isinstance(personas["personas"], list)

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "prod")
    assert client.post("/v1/demo/ussd", json=body).status_code == 404
    assert client.post("/v1/demo/sms", json={"msisdn": world.citizen.identifier, "text": "HELP"}).status_code == 404
    assert client.get("/v1/demo/sms", params={"msisdn": world.citizen.identifier}).status_code == 404
    assert client.get("/v1/demo/ussd/personas").status_code == 404


def test_session_rows_hold_a_blind_index_never_the_number(lines: dict[str, Any]) -> None:
    world: World = lines["world"]
    channel = Channel(tenant_id=world.tenant.id, kind="ussd", actor_id=uuid.uuid4())
    service.handle_ussd(channel, session_id="s-blind-1", msisdn=world.citizen.identifier, text="", now=5.0)
    with system_session() as db:
        row = db.scalar(select(models.UssdSession).where(models.UssdSession.tenant_id == world.tenant.id))
        assert row is not None and row.msisdn_hash == blind_index(world.citizen.identifier, scope=str(world.tenant.id))
        assert world.citizen.identifier[-7:] not in str(row.data) and row.session_key != "s-blind-1"
