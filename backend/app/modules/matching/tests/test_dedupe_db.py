"""Dedupe against the register: bands, review cases, links, officers, consent, pending sign-ups. Uses Postgres."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.contracts.decision import CostMatrix
from app.core.crypto import blind_index, encrypt_field
from app.core.db import SYSTEM, open_session, system_session
from app.core.mockdata import make_mock_id, make_mock_phone
from app.db import models
from app.modules.decision import service as decision_service
from app.modules.decision.tests.dbsetup import citizen_session, make_application, make_program, withdraw_consent
from app.modules.matching.service import backfill_name_keys, check_duplicates
from app.synth.golden import base_input


def _set_person(person_id: uuid.UUID, tenant: Any, *, name: str, dob: date | None, phone: str | None, national_id: str | None,
                gender: str | None = "male", district: str | None = "Hyderabad", name_ur: str | None = None) -> None:  # fmt: skip
    scope = str(tenant.id)
    with system_session() as db:
        person = db.get(models.Person, person_id)
        assert person is not None
        person.full_name, person.full_name_ur, person.dob, person.gender, person.district = name, name_ur, dob, gender, district
        person.phone_enc = encrypt_field(tenant.wrapped_dek, phone) if phone else None
        person.phone_hash = blind_index(phone, scope=scope) if phone else None
        person.national_id_enc = encrypt_field(tenant.wrapped_dek, national_id) if national_id else None
        person.national_id_hash = blind_index(national_id, scope=scope) if national_id else None
        person.name_key = None


def _register_person(tenant: Any, *, name: str, dob: date | None, phone: str | None, national_id: str | None, status: str = "active",
                     consent: bool = True, **kw: Any) -> uuid.UUID:  # fmt: skip
    """An existing record in the register (as a helper or the seed would have created it)."""
    from datetime import UTC, datetime, timedelta

    with system_session() as db:
        person = models.Person(tenant_id=tenant.id, full_name=name, status=status)
        db.add(person)
        db.flush()
        if consent:
            db.add(models.Consent(tenant_id=tenant.id, person_id=person.id, grantee_type="tenant", grantee_id=tenant.id,
                                  purpose="relief_application", field_scopes=["identity", "contact", "household", "income", "documents"],
                                  granted_at=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(days=30)))  # fmt: skip
        person_id = person.id
    _set_person(person_id, tenant, name=name, dob=dob, phone=phone, national_id=national_id, **kw)
    return person_id


def _check(citizen: Any) -> Any:
    with citizen_session(citizen) as db:
        return check_duplicates(db, tenant_id=citizen.tenant_id, person_id=citizen.person_id)


def _rows(model: Any, *where: Any) -> list[Any]:
    with open_session(SYSTEM) as db:
        return list(db.scalars(select(model).where(*where)).all())


DOB = date(1985, 4, 2)


def test_mohammad_against_an_existing_muhammed_with_another_phone_is_possible_and_goes_to_a_person(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _set_person(citizen.person_id, tenant, name="Mohammad Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_100_001),
                national_id=make_mock_id(5_100_001))  # fmt: skip
    existing = _register_person(tenant, name="Muhammed Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_100_999), national_id=None)

    evidence = _check(citizen)
    assert evidence is not None and evidence.band == "possible" and evidence.other_person_ref == str(existing)
    (pair,) = _rows(models.DuplicateCandidate, models.DuplicateCandidate.tenant_id == tenant.id)
    assert pair.status == "open" and pair.band == "possible" and "phone" in pair.evidence["conflicts"], "never merged"
    (case,) = _rows(models.Case, models.Case.tenant_id == tenant.id)
    assert case.kind == "duplicate_review" and case.subject_person_id == citizen.person_id and pair.case_id == case.id
    assert case.handoff["question"] == "Are these two records the same person?"
    assert "Mohammad" not in json.dumps(pair.evidence) and "Muhammed" not in json.dumps(pair.evidence), "no names in stored evidence"
    persons = _rows(models.Person, models.Person.tenant_id == tenant.id)
    assert all(p.status == "active" and p.merged_into_id is None for p in persons), "two person rows stay two rows"

    # The engine treats it as a guard: a clean, verified application still goes to a person.
    setup = make_program(tenant.id)
    application_id = make_application(tenant.id, citizen.person_id, setup.program_id)
    inp = base_input(application_id=str(application_id), duplicate=evidence)
    with citizen_session(citizen) as db:
        decision = decision_service.decide_and_record(db, tenant_id=tenant.id, application_id=application_id, person_id=citizen.person_id, inp=inp)
        assert (decision.route, decision.outcome) == ("human", "needs_human") and "possible_duplicate" in decision.guards

    again = _check(citizen)  # a second submission refreshes the pair; it does not open a second case
    assert again is not None and again.band == "possible"
    assert len(_rows(models.Case, models.Case.tenant_id == tenant.id)) == 1
    assert len(_rows(models.DuplicateCandidate, models.DuplicateCandidate.tenant_id == tenant.id)) == 1


def test_the_same_spelling_change_with_the_same_national_id_is_still_only_possible_when_the_phone_differs(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    shared_id = make_mock_id(5_200_001)
    _set_person(citizen.person_id, tenant, name="Mohammad Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_200_001), national_id=shared_id)
    _register_person(tenant, name="Muhammed Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_200_777), national_id=shared_id)
    evidence = _check(citizen)
    assert evidence is not None and evidence.band == "possible"


def test_high_score_with_an_agreeing_identifier_links_logs_and_an_officer_can_unlink(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.account(tenant, "officer")
    shared_id, phone = make_mock_id(5_300_001), make_mock_phone(5_300_001)
    _set_person(citizen.person_id, tenant, name="Zenab Bibi", dob=DOB, phone=phone, national_id=shared_id, gender="female")
    other = _register_person(tenant, name="Zainab", dob=DOB, phone=phone, national_id=shared_id, gender="female", name_ur="زینب")

    evidence = _check(citizen)
    assert evidence is not None and evidence.band == "same" and evidence.other_person_ref == str(other)
    (pair,) = _rows(models.DuplicateCandidate, models.DuplicateCandidate.tenant_id == tenant.id)
    assert pair.status == "linked" and not _rows(models.Case, models.Case.tenant_id == tenant.id), "a link needs no review case"
    linked = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "person.linked")
    assert len(linked) == 1 and linked[0].actor_type == "system"

    headers = factory.headers(client, officer)
    listed = client.get("/v1/duplicates?status=linked", headers=headers)
    assert listed.status_code == 200 and [i["id"] for i in listed.json()["items"]] == [str(pair.id)]
    detail = client.get(f"/v1/duplicates/{pair.id}", headers=headers).json()
    assert detail["comparison_now"]["band"] == "same" and detail["person_a"]["readable"] and detail["person_b"]["readable"]
    assert client.post(f"/v1/duplicates/{pair.id}/unlink", json={"reason": "x"}, headers=headers).status_code == 422, "a reason is required"
    undone = client.post(f"/v1/duplicates/{pair.id}/unlink", json={"reason": "Two sisters with the same card number typed"}, headers=headers)
    assert undone.status_code == 200 and undone.json()["status"] == "reversed"
    unlinked = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "person.unlinked")
    assert len(unlinked) == 1 and unlinked[0].reason.startswith("Two sisters")
    after = _check(citizen)
    assert after is not None and after.band == "distinct", "the officer's answer is respected next time"
    relink = client.post(f"/v1/duplicates/{pair.id}/link", json={"reason": "Checked the card in person"}, headers=headers)
    assert relink.status_code == 200 and relink.json()["status"] == "linked", "links are reversible both ways"


def test_a_name_alone_never_links_and_different_national_ids_mean_two_people(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _set_person(citizen.person_id, tenant, name="Muhammad Ali Khan", dob=DOB, phone=make_mock_phone(5_400_001), national_id=make_mock_id(5_400_001))
    _register_person(tenant, name="Muhammad Ali Khan", dob=date(1990, 7, 7), phone=None, national_id=None)  # namesake, other date of birth
    _register_person(tenant, name="Mohd Ali Khan", dob=DOB, phone=make_mock_phone(5_400_555), national_id=make_mock_id(5_400_555))
    evidence = _check(citizen)
    assert evidence is not None and evidence.band == "distinct"
    assert not _rows(models.DuplicateCandidate, models.DuplicateCandidate.tenant_id == tenant.id)
    assert not _rows(models.Case, models.Case.tenant_id == tenant.id)
    (checked,) = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "person.dedupe_checked")
    assert json.loads(checked.details)["candidates"] == 2


def test_blocking_pending_sign_ups_and_withdrawn_consent_are_not_compared(factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    _set_person(citizen.person_id, tenant, name="Rashid Soomro", dob=DOB, phone=make_mock_phone(5_500_001), national_id=None)
    _register_person(tenant, name="Rasheed Sumro", dob=DOB, phone=None, national_id=None, status="pending")
    withdrawn = _register_person(tenant, name="Rasheed Soomro", dob=DOB, phone=None, national_id=None)
    withdraw_consent(tenant.id, withdrawn)
    _register_person(tenant, name="Kulsoom Begum", dob=date(1950, 1, 1), phone=None, national_id=None, gender="female")  # shares no key
    evidence = _check(citizen)
    assert evidence is not None and evidence.band == "distinct"
    (checked,) = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "person.dedupe_checked")
    assert json.loads(checked.details)["candidates"] == 0, "pending, withdrawn and unrelated people are never compared"


def test_officers_decide_possible_pairs_with_a_reason_and_need_both_consents(client: TestClient, factory: Any) -> None:
    tenant = factory.tenant()
    citizen = factory.account(tenant, "citizen")
    officer = factory.account(tenant, "officer")
    _set_person(citizen.person_id, tenant, name="Mohammad Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_600_001), national_id=None)
    other = _register_person(tenant, name="Muhammed Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_600_777), national_id=None)
    _check(citizen)
    (pair,) = _rows(models.DuplicateCandidate, models.DuplicateCandidate.tenant_id == tenant.id)
    headers = factory.headers(client, officer)
    assert client.get("/v1/duplicates", headers=factory.headers(client, factory.account(tenant, "auditor"))).status_code == 403
    decided = client.post(f"/v1/duplicates/{pair.id}/distinct", json={"reason": "Brothers: different fathers' names"}, headers=headers)
    assert decided.status_code == 200 and decided.json()["status"] == "rejected"
    (case,) = _rows(models.Case, models.Case.tenant_id == tenant.id)
    assert case.status == "resolved" and case.resolution == "rejected", "the review case is closed with the officer's answer"
    assert client.post(f"/v1/duplicates/{pair.id}/distinct", json={"reason": "again please"}, headers=headers).status_code == 409

    withdraw_consent(tenant.id, other)
    assert client.get(f"/v1/duplicates/{pair.id}", headers=headers).status_code == 403
    denied = _rows(models.AuditLog, models.AuditLog.tenant_id == tenant.id, models.AuditLog.action == "access.denied")
    assert any(row.object_type == "duplicate_candidate" for row in denied)


def test_the_submit_pipeline_passes_dedupe_evidence_to_the_engine(client: TestClient, factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.applications.tests.support import Fakes, build_world, eligible_patch, install, new_app

    fakes = Fakes()
    install(monkeypatch, fakes)
    world = build_world(factory, client)
    _set_person(world.citizen.person_id, world.tenant, name="Mohammad Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_700_001),
                national_id=make_mock_id(5_700_001))  # fmt: skip
    _register_person(world.tenant, name="Muhammed Aslam Qureshi", dob=DOB, phone=make_mock_phone(5_700_777), national_id=None)
    app = new_app(client, world).json()
    patched = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": eligible_patch()}, headers=world.h("citizen"))
    assert patched.status_code == 200, patched.text
    assert client.post(f"/v1/applications/{app['id']}/submit", headers=world.h("citizen")).status_code == 200
    inp = fakes.calls["decide_and_record"][0]["inp"]
    assert inp.duplicate is not None and inp.duplicate.band == "possible"
    assert [c["kind"] for c in fakes.calls["open_case"]][:1] == ["duplicate_review"]


def test_backfill_gives_every_active_person_a_blocking_key(factory: Any) -> None:
    tenant = factory.tenant()
    pid = _register_person(tenant, name="Haji Rasheed Sumro", dob=DOB, phone=None, national_id=None)
    with system_session() as db:
        assert backfill_name_keys(db, [tenant.id]) >= 1
        person = db.get(models.Person, pid)
        assert person is not None and person.name_key == "rsd+smr"
        assert backfill_name_keys(db, [tenant.id]) == 0, "idempotent"
    assert CostMatrix().approve_threshold() > 0.9
