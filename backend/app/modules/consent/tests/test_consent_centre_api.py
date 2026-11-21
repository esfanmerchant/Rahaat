"""The consent centre: who looked at my data, corrections, export and erasure, through the HTTP API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import system_session
from app.db import models
from app.modules.applications.tests.support import World, eligible_patch, jpeg_bytes, new_app
from app.modules.cases import testing as case_testing


def _log(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/v1/me/access-log", headers=headers)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def _withdraw(client: TestClient, world: World) -> None:
    consent_id = next(c["id"] for c in client.get("/v1/consents", headers=world.h("citizen")).json() if c["status"] == "active")
    assert client.post(f"/v1/consents/{consent_id}/withdraw", headers=world.h("citizen")).status_code == 200


def _case_of(request_id: str) -> models.Case:
    with system_session() as db:
        request = db.get(models.CorrectionRequest, uuid.UUID(request_id))
        assert request is not None and request.case_id is not None
        case = db.get(models.Case, request.case_id)
        db.expunge(case)
        return case


def _decide(client: TestClient, world: World, case_id: uuid.UUID, action: str, reason: str = "Checked against the card") -> Any:
    return client.post(f"/v1/cases/{case_id}/actions", json={"action": action, "reason": reason}, headers=world.h("officer"))


def test_an_officer_read_appears_in_the_citizen_access_log(client: TestClient, world: World, uploads: Any) -> None:
    pid = world.citizen.person_id
    review = case_testing.review_case(world.tenant.id, pid)
    assert client.get(f"/v1/cases/{review['case_id']}", headers=world.h("officer")).status_code == 200
    draft = new_app(client, world)  # review_case used its own program, so this one is free
    doc = client.post(f"/v1/applications/{draft.json()['id']}/documents", headers=world.h("citizen"),
                      files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})  # fmt: skip
    document_id = doc.json()["document"]["document_id"]
    assert client.get(f"/v1/documents/{document_id}/content", headers=world.h("officer")).status_code == 200

    entries = _log(client, world.h("citizen"))
    viewed = {e["what"]: e for e in entries if e["event"] == "viewed"}
    assert set(viewed) >= {"case_detail", "document_content"}
    case_view = viewed["case_detail"]
    assert case_view["actor_kind"] == "staff" and case_view["actor_role"] == "officer" and case_view["department"] == "Test Department"
    assert case_view["reason"] == "case_review" and case_view["allowed"] is True and case_view["actor_name"] is None
    body = client.get("/v1/me/access-log", headers=world.h("citizen")).text
    assert "@test.rahat.example" not in body and str(world.officer.user_id) not in body, "never a staff email or id"
    assert all(e["action"] != "application.created" for e in entries), "my own actions are not 'someone looked'"

    # After withdrawal the officer is refused, and the refused attempt is in the log too.
    _withdraw(client, world)
    assert client.get(f"/v1/cases/{review['case_id']}", headers=world.h("officer")).status_code == 403
    assert client.get(f"/v1/documents/{document_id}/content", headers=world.h("officer")).status_code == 403
    denied = [e for e in _log(client, world.h("citizen")) if e["event"] == "denied"]
    assert len(denied) >= 2 and all(e["actor_role"] == "officer" and e["allowed"] is False for e in denied)
    assert {e["reason"] for e in denied} == {"consent_required"}
    # Another citizen's log stays empty.
    assert _log(client, world.h("other_citizen")) == []


def test_helper_switches_and_reads_are_in_the_log_by_name(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    client.post("/v1/helper/switch", json={"person_id": str(pid), "pin": "0000"}, headers=world.h("helper"))  # a wrong PIN
    assert client.get("/v1/me/person", headers=world.h("helper", pid)).status_code == 200
    assert client.get("/v1/applications", headers=world.h("helper", pid)).status_code == 200
    events = {(e["event"], e["what"]) for e in _log(client, world.h("citizen")) if e["actor_kind"] == "helper"}
    assert ("denied", None) in events, "the wrong PIN is in the log"
    assert {("helper_opened", "helper.switched"), ("viewed", "person_record"), ("viewed", "applications_list")} <= events
    names = {e["actor_name"] for e in _log(client, world.h("citizen")) if e["actor_kind"] == "helper"}
    assert names == {"Test Helper"}
    # The helper may read the family's log too, and that read is recorded.
    assert client.get("/v1/me/access-log", headers=world.h("helper", pid)).status_code == 200
    assert any(e["what"] == "access_log" for e in _log(client, world.h("citizen")))


def test_a_correction_is_reviewed_by_an_officer_and_applied_as_typed(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    misheard = {**eligible_patch(), "full_name": {"value": "Test Citizan", "provenance": "spoken", "confidence": 0.6}}
    client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": misheard}, headers=world.h("citizen"))
    asked = client.post("/v1/me/corrections", headers=world.h("citizen"),
                        json={"field": "full_name", "new_value": "Test Citizen", "reason": "The name was heard wrong"})  # fmt: skip
    assert asked.status_code == 201, asked.text
    request = asked.json()
    assert request["kind"] == "correction" and request["status"] == "open" and request["new_value"] == "Test Citizen"
    again = client.post("/v1/me/corrections", headers=world.h("citizen"),
                        json={"field": "full_name", "new_value": "Test Citizen", "reason": "Asking twice"})  # fmt: skip
    assert again.status_code == 409 and again.json()["code"] == "correction_open"
    same = client.post("/v1/me/corrections", headers=world.h("citizen"), json={"field": "household_size", "new_value": 5, "reason": "No change"})
    assert same.status_code == 422 and same.json()["code"] == "no_change"
    bad = client.post("/v1/me/corrections", headers=world.h("citizen"), json={"field": "national_id", "new_value": "12345", "reason": "Wrong id"})
    assert bad.status_code == 422
    unknown = client.post("/v1/me/corrections", headers=world.h("citizen"), json={"field": "status", "new_value": "approved", "reason": "Please"})
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_field"

    case = _case_of(request["id"])
    assert case.kind == "correction" and case.subject_person_id == world.citizen.person_id and case.application_id == uuid.UUID(app["id"])
    detail = client.get(f"/v1/cases/{case.id}", headers=world.h("officer")).json()
    assert detail["handoff"]["evidence"]["current_value"] == "Test Citizan" and detail["handoff"]["evidence"]["requested_value"] == "Test Citizen"
    assert _decide(client, world, case.id, "approve").status_code == 200

    stored = client.get(f"/v1/applications/{app['id']}", headers=world.h("citizen")).json()
    assert stored["form"]["full_name"] == {"value": "Test Citizen", "confidence": 1.0, "provenance": "typed", "verified": False}
    assert stored["version"] == 3
    assert client.get("/v1/me/data-requests", headers=world.h("citizen")).json()[0]["status"] == "accepted"
    with system_session() as db:
        row = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == world.tenant.id,
                                                       models.AuditLog.action == "application.corrected")).one()  # fmt: skip
        assert row.actor_id == str(world.officer.user_id) and row.actor_role == "officer", "the audit names who changed it"
        assert db.get(models.Person, world.citizen.person_id).full_name == "Test Citizen"
    assert _decide(client, world, case.id, "approve").status_code == 409, "a decided case cannot be decided again"


def test_a_rejected_correction_changes_nothing_and_a_verified_value_can_be_corrected(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    with system_session() as db:
        row = db.get(models.Application, uuid.UUID(app["id"]))
        form = dict(row.form)
        form["dob"] = {"value": "1980-01-01", "confidence": 1.0, "provenance": "qr_signed", "verified": True}
        row.form = form
    locked = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": {"dob": {"value": "1981-01-01"}}},
                          headers=world.h("citizen"))  # fmt: skip
    assert locked.status_code == 422, "a verified value cannot be typed over"
    asked = client.post("/v1/me/corrections", headers=world.h("helper", world.citizen.person_id),
                        json={"field": "dob", "new_value": "1981-01-01", "reason": "The card was printed wrong"})  # fmt: skip
    assert asked.status_code == 201, "a helper can ask for the family"
    case = _case_of(asked.json()["id"])
    assert _decide(client, world, case.id, "reject", "The card is signed and matches the registry").status_code == 200
    assert client.get(f"/v1/applications/{app['id']}", headers=world.h("citizen")).json()["form"]["dob"]["value"] == "1980-01-01"
    assert client.get("/v1/me/data-requests", headers=world.h("citizen")).json()[0]["status"] == "rejected"
    retry = client.post("/v1/me/corrections", headers=world.h("citizen"),
                        json={"field": "dob", "new_value": "1981-01-01", "reason": "Here is my birth certificate"})  # fmt: skip
    assert _decide(client, world, _case_of(retry.json()["id"]).id, "approve").status_code == 200
    assert client.get(f"/v1/applications/{app['id']}", headers=world.h("citizen")).json()["form"]["dob"] == {
        "value": "1981-01-01", "confidence": 1.0, "provenance": "typed", "verified": False}  # fmt: skip


def test_export_has_everything_with_my_identifiers_and_masks_them_for_a_helper(client: TestClient, world: World) -> None:
    app = new_app(client, world).json()
    client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": {
        "phone": {"value": world.citizen.identifier, "provenance": "typed"}}}, headers=world.h("citizen"))  # fmt: skip
    mine = client.get("/v1/me/export", headers=world.h("citizen"))
    assert mine.status_code == 200 and mine.headers["content-disposition"].startswith("attachment")
    data = mine.json()
    assert data["notice"].startswith("PROTOTYPE") and data["requested_by"] == "you"
    assert data["person"]["phone"] == world.citizen.identifier and data["person"]["national_id"].startswith("00000-")
    assert [a["id"] for a in data["applications"]] == [app["id"]]
    assert data["applications"][0]["answers"]["phone"]["value"] == world.citizen.identifier
    assert data["consents"][0]["status"] == "active" and data["helpers"][0]["name"] == "Test Helper"
    assert world.helper.identifier not in mine.text, "the helper's number is masked even in my own export"
    assert "signals" not in mine.text, "no detection details"

    theirs = client.get("/v1/me/export", headers=world.h("helper", world.citizen.person_id)).json()
    assert theirs["requested_by"] == "your helper"
    assert theirs["person"]["phone"].endswith(world.citizen.identifier[-3:]) and theirs["person"]["phone"] != world.citizen.identifier
    assert world.citizen.identifier not in str(theirs) and "00000-" not in str(theirs["person"])
    exported = [e for e in _log(client, world.h("citizen")) if e["event"] == "exported"]
    assert len(exported) == 1 and exported[0]["actor_kind"] == "helper", "the helper's export is in my log; mine is not"


def test_erasure_waits_for_an_officer_then_erases_and_keeps_payments(client: TestClient, world: World, uploads: Any) -> None:
    pid = world.citizen.person_id
    app = new_app(client, world).json()
    doc = client.post(f"/v1/applications/{app['id']}/documents", headers=world.h("citizen"), files={"file": ("a.jpg", jpeg_bytes(), "image/jpeg")})
    assert doc.status_code == 201
    stored_files = list(uploads.rglob("*.*"))
    assert stored_files
    paid = case_testing.review_case(world.tenant.id, pid)  # a second, already decided program with a payment
    with system_session() as db:
        db.add(models.Payment(tenant_id=world.tenant.id, application_id=paid["application_id"], person_id=pid, amount_pkr=12_000,
                              status="settled", idempotency_key=f"t:{uuid.uuid4().hex}"))  # fmt: skip
        db.get(models.Application, paid["application_id"]).status = "paid"

    assert client.post("/v1/me/erasure-request", json={"reason": "I moved away"}, headers=world.h("helper", pid)).status_code == 403
    asked = client.post("/v1/me/erasure-request", json={"reason": "I moved away"}, headers=world.h("citizen"))
    assert asked.status_code == 201 and asked.json()["kind"] == "erasure" and asked.json()["status"] == "open"
    assert client.post("/v1/me/erasure-request", json={}, headers=world.h("citizen")).json()["code"] == "erasure_request_open"
    assert client.get("/v1/me/person", headers=world.h("citizen")).status_code == 200, "nothing is deleted on request"
    _withdraw(client, world)  # erasure still works after the person took their consent back

    case = _case_of(asked.json()["id"])
    assert case.subject_person_id is None and case.opened_reason == "erasure_request"
    decided = _decide(client, world, case.id, "approve", "No open payment or investigation")
    assert decided.status_code == 200, decided.text
    with system_session() as db:
        person = db.get(models.Person, pid)
        assert person.status == "deleted" and person.full_name == "" and person.national_id_enc is None and person.phone_hash is None
        assert db.scalars(select(models.Document).where(models.Document.person_id == pid)).all() == []
        draft = db.get(models.Application, uuid.UUID(app["id"]))
        assert draft.status == "withdrawn" and draft.form["full_name"]["value"] is None
        assert db.get(models.Application, paid["application_id"]).status == "paid", "the paid application is kept"
        assert db.scalars(select(models.Payment).where(models.Payment.person_id == pid)).all(), "payments are kept"
        assert all(d.revoked_at is not None for d in db.scalars(select(models.HelperDelegation).where(models.HelperDelegation.person_id == pid)))
        assert all(c.status == "withdrawn" for c in db.scalars(select(models.Consent).where(models.Consent.person_id == pid)))
        actions = db.scalars(select(models.AuditLog.action).where(models.AuditLog.tenant_id == world.tenant.id)).all()
        assert "person.erased" in actions and "person.erasure.accepted" in actions
    assert not any(f.exists() for f in stored_files), "the stored photos are gone"
    assert client.get("/v1/me/person", headers=world.h("citizen")).status_code == 404


def test_a_rejected_erasure_keeps_the_data(client: TestClient, world: World) -> None:
    asked = client.post("/v1/me/erasure-request", json={}, headers=world.h("citizen")).json()
    assert _decide(client, world, _case_of(asked["id"]).id, "reject", "An investigation into this payment is open").status_code == 200
    assert client.get("/v1/me/person", headers=world.h("citizen")).status_code == 200
    assert client.get("/v1/me/data-requests", headers=world.h("citizen")).json()[0]["status"] == "rejected"


def test_identity_and_payout_corrections_are_the_persons_own_and_never_on_a_decided_application(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    app = new_app(client, world).json()
    body = {"field": "payout_account", "new_value": "0999-7654321", "reason": "Send it to this wallet", "application_id": app["id"]}
    by_helper = client.post("/v1/me/corrections", json=body, headers=world.h("helper", pid))
    assert by_helper.status_code == 403 and by_helper.json()["code"] == "citizen_only_field", "a helper cannot redirect a payout"
    with system_session() as db:
        db.get(models.Application, uuid.UUID(app["id"])).status = "approved"  # approved; the payment may still be waiting
    decided = client.post("/v1/me/corrections", json=body, headers=world.h("citizen"))
    assert decided.status_code == 409 and decided.json()["code"] == "application_decided"
    # A name on a decided application is corrected on the person record only; the decided answers stay.
    name = client.post("/v1/me/corrections", json={"field": "full_name", "new_value": "Test Citizen Bibi", "reason": "My full name"},
                       headers=world.h("helper", pid))  # fmt: skip
    assert name.status_code == 201, name.text
    case = _case_of(name.json()["id"])
    assert case.application_id is None
    detail = client.get(f"/v1/cases/{case.id}", headers=world.h("officer")).json()
    assert "helper" in detail["handoff"]["understanding"] and detail["handoff"]["evidence"]["requested_by_role"] == "helper"
    assert _decide(client, world, case.id, "approve").status_code == 200
    with system_session() as db:
        assert db.get(models.Person, pid).full_name == "Test Citizen Bibi"
        assert db.get(models.Application, uuid.UUID(app["id"])).form["full_name"]["value"] is None


def test_after_withdrawal_a_helper_sees_no_requests_and_identifiers_are_masked(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    new_app(client, world)
    asked = client.post("/v1/me/corrections", json={"field": "phone", "new_value": "0999-7654321", "reason": "New number"},
                        headers=world.h("citizen"))  # fmt: skip
    assert asked.status_code == 201, asked.text
    case = _case_of(asked.json()["id"])
    assert "0999-7654321" not in str(case.handoff), "identifiers stay out of case packages"
    masked = client.get("/v1/me/data-requests", headers=world.h("helper", pid)).json()[0]["new_value"]
    assert masked != "0999-7654321" and masked.endswith("321")
    assert client.get("/v1/me/data-requests", headers=world.h("citizen")).json()[0]["new_value"] == "0999-7654321"
    _withdraw(client, world)
    after = client.get("/v1/me/data-requests", headers=world.h("helper", pid))
    assert after.status_code == 403 and after.json()["code"] == "consent_required"
    assert client.get("/v1/me/export", headers=world.h("helper", pid)).status_code == 403


def test_erasure_also_clears_copies_in_sync_records_and_case_packages(client: TestClient, world: World) -> None:
    pid = world.citizen.person_id
    app = new_app(client, world).json()
    op = {"op_id": uuid.uuid4().hex, "kind": "patch_application", "entity_id": app["id"], "base_version": 1,
          "patch": {"phone": {"value": "0999-1112223", "provenance": "typed"}}}  # fmt: skip
    synced = client.post("/v1/sync", json={"device_id": "phone-" + uuid.uuid4().hex[:8], "ops": [op]}, headers=world.h("citizen"))
    assert synced.status_code == 200
    correction = client.post("/v1/me/corrections", json={"field": "household_size", "new_value": 7, "reason": "Two more children"},
                             headers=world.h("citizen")).json()  # fmt: skip
    erase = client.post("/v1/me/erasure-request", json={}, headers=world.h("citizen")).json()
    assert _decide(client, world, _case_of(erase["id"]).id, "approve", "No open payment or investigation").status_code == 200
    with system_session() as db:
        ops = db.scalars(select(models.SyncOp).where(models.SyncOp.person_id == pid)).all()
        assert ops and all(o.payload == {} and "0999" not in str(o.result) for o in ops)
        cases = db.scalars(select(models.Case).where(models.Case.subject_person_id == pid)).all()
        assert cases and all(c.handoff == {} and c.status in ("resolved", "closed") for c in cases)
        assert db.get(models.CorrectionRequest, uuid.UUID(correction["id"])).status == "rejected"
        requests = db.scalars(select(models.CorrectionRequest).where(models.CorrectionRequest.person_id == pid)).all()
        assert all(r.new_value_enc == "" for r in requests)
        erased = db.scalars(select(models.AuditLog).where(models.AuditLog.tenant_id == world.tenant.id,
                                                          models.AuditLog.action == "person.erased")).one()  # fmt: skip
        assert erased.actor_id == str(world.officer.user_id), "the erasure row names the officer who approved it"


def test_an_erasure_never_hangs_behind_a_writer_waiting_for_the_audit_lock(client: TestClient, world: World) -> None:
    """Regression: the erasure used to run while the officer's transaction held the tenant's audit lock, so a citizen's
    edit holding the application row and waiting for that lock blocked everyone, with no deadlock Postgres could see."""
    import threading
    import time

    from sqlalchemy import text

    from app.core import audit
    from app.core.db import RlsContext, open_session

    app_id = uuid.UUID(new_app(client, world).json()["id"])
    case_id = _case_of(client.post("/v1/me/erasure-request", json={}, headers=world.h("citizen")).json()["id"]).id
    officer_headers = world.h("officer")
    locked, go, outcome = threading.Event(), threading.Event(), {}

    def writer() -> None:  # what PATCH /v1/applications/{id} does: lock the row, then write its audit row
        session = open_session(RlsContext(role="system"))
        try:
            session.scalars(select(models.Application).where(models.Application.id == app_id).with_for_update()).first()
            locked.set()
            go.wait(15)
            session.execute(text("SET LOCAL lock_timeout = 8000"))
            audit.write(session, tenant_id=world.tenant.id, action="test.writer")
            outcome["writer"] = "got the audit lock"
            session.rollback()
        except Exception as exc:  # noqa: BLE001
            outcome["writer"] = type(exc).__name__
        finally:
            session.close()

    def officer() -> None:
        started = time.monotonic()
        response = client.post(f"/v1/cases/{case_id}/actions", json={"action": "approve", "reason": "Erasure checked"},
                               headers=officer_headers)  # fmt: skip
        outcome["officer"] = (response.status_code, round(time.monotonic() - started, 1))

    w = threading.Thread(target=writer, daemon=True)
    w.start()
    assert locked.wait(10)
    o = threading.Thread(target=officer, daemon=True)
    o.start()
    time.sleep(1.5)  # the erasure is now waiting for the application row the writer holds
    go.set()
    w.join(20)
    o.join(30)
    assert outcome.get("writer") == "got the audit lock", outcome
    assert outcome.get("officer", (None,))[0] == 200 and not o.is_alive(), outcome
