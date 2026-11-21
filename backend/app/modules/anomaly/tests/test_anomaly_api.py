"""The anomaly API: policies, a ring becomes one case, a second run opens nothing, RLS and consent, resolved cases do not return. Uses Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.contracts.application import ApplicationFormV1, FieldValue
from app.core.db import system_session
from app.db import models
from app.modules.anomaly import service
from app.modules.cases import testing as t
from app.modules.jobs.service import run_pending


def _form(payout: str, national_id: str, district: str = "Dadu") -> dict[str, Any]:
    form = ApplicationFormV1(
        payout_account=FieldValue[str](value=payout, confidence=1.0, provenance="typed"),
        national_id=FieldValue[str](value=national_id, confidence=1.0, provenance="typed"),
        district=FieldValue[str](value=district, confidence=1.0, provenance="typed"),
    )
    return form.model_dump(mode="json")


def _apply(tenant_id: uuid.UUID, person_id: uuid.UUID, program_id: uuid.UUID, form: dict[str, Any], *, via: str = "web", by: uuid.UUID | None = None,
          at: datetime | None = None) -> uuid.UUID:  # fmt: skip
    at = at or datetime.now(UTC)
    with system_session() as db:
        row = models.Application(id=uuid.uuid4(), tenant_id=tenant_id, program_id=program_id, person_id=person_id, status="submitted", form=form,
                                 tracking_code=f"R-{uuid.uuid4().int % 100000:05d}", submitted_at=at, created_at=at, submitted_via=via, created_by=by)  # fmt: skip
        db.add(row)
        db.flush()
        return row.id


def _run(client: Any, headers: dict[str, str], tenant_id: uuid.UUID) -> Any:
    queued = client.post("/v1/anomalies/run", headers=headers)
    assert queued.status_code == 202, queued.text
    run_pending(tenant_id=tenant_id, kinds=[service.JOB_KIND])
    return queued


def _ring(factory: Any, tenant: Any, size: int = 3) -> tuple[list[uuid.UUID], uuid.UUID]:
    program_id, _ = t.program(tenant.id)
    ids = []
    for _ in range(size):
        citizen = factory.account(tenant, "citizen")
        ids.append(_apply(tenant.id, citizen.person_id, program_id, _form("mock-wallet-7777", f"00000-{uuid.uuid4().int % 9999999:07d}-1")))
    return ids, program_id


def test_a_shared_wallet_becomes_one_anomaly_case_and_a_second_run_opens_nothing(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    officer = factory.headers(client, factory.account(tenant, "officer"))
    ids, _ = _ring(factory, tenant)

    _run(client, admin, tenant.id)
    body = client.get("/v1/anomalies", headers=admin).json()
    ring = [f for f in body["flags"] if f["detector"] == "shared_payout"]
    assert len(ring) == 1 and ring[0]["evidence_count"] == 3 and set(ring[0]["evidence_ids"]) == {str(i) for i in ids}
    assert ring[0]["evidence"]["people"] == 3 and ring[0]["cheapest_check"] and body["counts"]["shared_payout"] == 1
    assert "mock-wallet-7777" not in str(body), "no raw account in any staff chip"
    scan = body["last_scan"]
    assert scan["applications_scanned"] == 3 and scan["cases_opened"] == 1 and scan["trigger"] == "manual"
    by_name = {d["detector"]: d for d in scan["detectors"]}
    assert by_name["shared_payout"]["status"] == "flagged" and by_name["application_spike"]["status"] == "abstained"
    assert by_name["application_spike"]["abstained_reason"] == "thin_baseline"

    # The case is in the officer queue, carries the handoff package, and an officer can resolve it with a reason.
    queue = client.get("/v1/cases", headers=officer, params={"kind": "anomaly_review"}).json()["items"]
    assert [c["id"] for c in queue] == [ring[0]["case_id"]] and queue[0]["opened_reason"] == "anomaly_shared_payout"
    detail = client.get(f"/v1/cases/{ring[0]['case_id']}", headers=officer).json()
    assert detail["handoff"]["guards"] == ["anomaly_flag"] and detail["handoff"]["suggested_question"]
    assert detail["handoff"]["evidence"]["detector"] == "shared_payout" and len(detail["handoff"]["evidence"]["application_ids"]) == 3

    _run(client, admin, tenant.id)  # the same data again: no second case
    again = client.get("/v1/anomalies", headers=admin).json()
    assert len(again["flags"]) == 1 and again["last_scan"]["cases_opened"] == 0
    with system_session() as db:
        kinds = db.scalars(select(models.Case.kind).where(models.Case.tenant_id == tenant.id)).all()
        assert kinds.count("anomaly_review") == 1
        actions = set(db.scalars(select(models.AuditLog.action).where(models.AuditLog.tenant_id == tenant.id)).all())
        assert {"anomaly.run_requested", "anomaly.scan", "case.opened"} <= actions

    # Resolved as reviewed: the same three applications never come back, a fourth reopens the question as a new case.
    case_id = ring[0]["case_id"]
    done = client.post(f"/v1/cases/{case_id}/actions", headers=officer, json={"action": "approve", "reason": "All four are one family; checked"})
    assert done.status_code == 200, done.text
    _run(client, admin, tenant.id)
    assert client.get("/v1/anomalies", headers=admin).json()["last_scan"]["suppressed"] == 1
    program_id, _ = t.program(tenant.id)
    _apply(tenant.id, factory.account(tenant, "citizen").person_id, program_id, _form("mock-wallet-7777", "00000-1234567-1"))
    _run(client, admin, tenant.id)
    latest = client.get("/v1/anomalies", headers=admin).json()
    assert latest["last_scan"]["cases_opened"] == 1 and latest["counts"]["shared_payout"] == 1 and len(latest["flags"]) == 2


def test_a_growing_pattern_refreshes_its_open_case_instead_of_opening_another(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    _ring(factory, tenant)
    _run(client, admin, tenant.id)
    program_id, _ = t.program(tenant.id)
    _apply(tenant.id, factory.account(tenant, "citizen").person_id, program_id, _form("mock-wallet-7777", "00000-7654321-1"))
    _run(client, admin, tenant.id)
    body = client.get("/v1/anomalies", headers=admin).json()
    assert len(body["flags"]) == 1 and body["flags"][0]["evidence_count"] == 4
    assert body["last_scan"]["cases_opened"] == 0 and body["last_scan"]["cases_refreshed"] == 1


def test_repeated_id_and_helper_burst_open_their_own_cases(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    program_id, _ = t.program(tenant.id)
    helper = factory.account(tenant, "officer").user_id  # any user id will do as the submitting helper
    now = datetime.now(UTC)
    for k in range(3):  # one ID number on three different people
        _apply(tenant.id, factory.account(tenant, "citizen").person_id, program_id, _form(f"wallet-{k}", "00000-5550000-5"))
    for k in range(10):  # ten families in ten minutes through one helper
        _apply(tenant.id, factory.account(tenant, "citizen").person_id, program_id, _form(f"wallet-h{k}", f"00000-66600{k:02d}-6"), via="helper", by=helper,
               at=now - timedelta(minutes=k))  # fmt: skip
    _run(client, admin, tenant.id)
    flags = client.get("/v1/anomalies", headers=admin).json()["flags"]
    assert sorted(f["detector"] for f in flags) == ["helper_burst", "repeated_identity"]
    burst = next(f for f in flags if f["detector"] == "helper_burst")
    assert burst["evidence"]["families"] == 10 and burst["priority"] == 25


def test_who_may_read_and_run_and_other_departments_see_nothing(client: Any, factory: Any) -> None:
    tenant, other = factory.tenant(), factory.tenant()
    _ring(factory, tenant)
    admin = factory.headers(client, factory.account(tenant, "admin"))
    _run(client, admin, tenant.id)
    for role, may_read, may_run in (("officer", True, True), ("auditor", True, False), ("citizen", False, False), ("helper", False, False)):
        headers = factory.headers(client, factory.account(tenant, role))
        assert (client.get("/v1/anomalies", headers=headers).status_code == 200) is may_read, role
        assert (client.post("/v1/anomalies/run", headers=headers).status_code == 202) is may_run, role
    assert client.get("/v1/anomalies").status_code == 401 and client.post("/v1/anomalies/run").status_code == 401
    outsider = client.get("/v1/anomalies", headers=factory.headers(client, factory.account(other, "admin"))).json()
    assert outsider["flags"] == [] and outsider["last_scan"] is None


def test_a_person_who_withdrew_consent_is_left_out_of_every_pattern(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    ids, _ = _ring(factory, tenant)
    with system_session() as db:
        person_id = db.scalar(select(models.Application.person_id).where(models.Application.id == ids[0]))
        consent = db.scalar(select(models.Consent).where(models.Consent.person_id == person_id))
        assert consent is not None
        consent.status = "withdrawn"
        consent.withdrawn_at = datetime.now(UTC)
    _run(client, admin, tenant.id)
    body = client.get("/v1/anomalies", headers=admin).json()
    assert body["last_scan"]["applications_scanned"] == 2 and body["flags"] == []


def test_anomaly_evidence_feeds_the_engine_guard_only_for_flagged_applications(client: Any, factory: Any) -> None:
    tenant = factory.tenant()
    admin = factory.headers(client, factory.account(tenant, "admin"))
    ids, program_id = _ring(factory, tenant)
    clean = _apply(tenant.id, factory.account(tenant, "citizen").person_id, program_id, _form("mock-wallet-clean", "00000-2223334-4"))
    _run(client, admin, tenant.id)
    with system_session() as db:
        flagged = service.anomaly_evidence_for(db, tenant.id, ids[0])
        assert flagged is not None and flagged.flagged and flagged.reasons == ["anomaly_shared_payout"] and flagged.score > 0.5
        assert service.anomaly_evidence_for(db, tenant.id, clean) is None
