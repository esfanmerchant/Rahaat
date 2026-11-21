"""The submit pipeline with the other tracks replaced by fakes at their real import paths."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.contracts.engine import RegistryRecord
from app.core.db import system_session
from app.core.mockdata import make_mock_id
from app.db import models
from app.modules.applications.tests.support import Fakes, World, eligible_patch, jpeg_bytes, new_app


def _ready(client: TestClient, world: World) -> dict[str, str]:
    app = new_app(client, world).json()
    patched = client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": eligible_patch()},
                           headers=world.h("citizen"))  # fmt: skip
    assert patched.status_code == 200, patched.text
    return patched.json()


def _submit(client: TestClient, world: World, app_id: str) -> dict:
    response = client.post(f"/v1/applications/{app_id}/submit", headers=world.h("citizen"))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("outcome", "status", "case", "payment"),
    [("approved", "approved", 0, 1), ("rejected", "rejected", 0, 0), ("needs_proof", "needs_proof", 0, 0), ("needs_human", "in_review", 1, 0)],
)
def test_each_outcome_is_applied(client: TestClient, world: World, fakes: Fakes, outcome: str, status: str, case: int, payment: int) -> None:
    fakes.outcome = outcome
    app = _ready(client, world)
    out = _submit(client, world, app["id"])
    assert out["application"]["status"] == status and out["decision"]["outcome"] == outcome
    assert fakes.n("open_case") == case and fakes.n("request_payment") == payment
    if payment:
        assert fakes.calls["request_payment"][0]["amount_pkr"] == 12000, "the amount comes from the rule version"
    assert [c["template"] for c in fakes.calls["notify"]] == [f"application_{status}"]
    assert out["application"]["timeline"][-1]["status"] == status
    inp = fakes.calls["decide_and_record"][0]["inp"]
    assert inp.registry_status == "unavailable" and inp.consent_ok and inp.form.household_size.value == 5
    assert inp.identity is None, "no identity check without a name and date of birth on the form"


def test_submitting_twice_returns_the_first_result(client: TestClient, world: World, fakes: Fakes) -> None:
    fakes.outcome = "approved"
    app = _ready(client, world)
    first = _submit(client, world, app["id"])
    second = _submit(client, world, app["id"])
    assert second["decision"]["decision_id"] == first["decision"]["decision_id"]
    assert second["application"]["version"] == first["application"]["version"]
    assert fakes.n("decide_and_record") == 1 and fakes.n("request_payment") == 1 and fakes.n("notify") == 1
    with system_session() as db:
        assert db.scalar(select(func.count()).select_from(models.Decision).where(models.Decision.application_id == uuid.UUID(app["id"]))) == 1


def test_needs_proof_then_resubmit_decides_again(client: TestClient, world: World, fakes: Fakes, uploads: object) -> None:
    fakes.outcome = "needs_proof"
    app = _ready(client, world)
    assert _submit(client, world, app["id"])["application"]["status"] == "needs_proof"
    up = client.post(f"/v1/applications/{app['id']}/documents", headers=world.h("citizen"),
                     files={"file": ("x.jpg", jpeg_bytes(), "image/jpeg")}, data={"kind": "income_proof"})  # fmt: skip
    assert up.status_code == 201, up.text
    fakes.outcome = "approved"
    again = _submit(client, world, app["id"])
    assert again["application"]["status"] == "approved" and fakes.n("decide_and_record") == 2
    assert len(fakes.calls["decide_and_record"][1]["inp"].documents) == 1


def test_without_any_other_track_a_person_reviews(client: TestClient, world: World, no_hooks: Fakes) -> None:
    app = _ready(client, world)
    out = _submit(client, world, app["id"])
    assert out["decision"] is None and out["application"]["status"] == "in_review"
    assert out["application"]["timeline"][-1]["label_key"] == "timeline.person_checking"
    with system_session() as db:
        assert db.scalar(select(func.count()).select_from(models.Decision).where(models.Decision.application_id == uuid.UUID(app["id"]))) == 0
        reasons = db.scalars(select(models.AuditLog.reason).where(models.AuditLog.object_id == app["id"],
                                                                  models.AuditLog.action == "application.status_changed")).all()  # fmt: skip
        assert reasons == ["engine_unavailable"]


def test_engine_missing_opens_a_case_and_engine_failure_rolls_back_its_writes(client: TestClient, world: World, fakes: Fakes,
                                                                                monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    fakes.engine_raises = True
    app = _ready(client, world)
    out = _submit(client, world, app["id"])
    assert out["application"]["status"] == "in_review" and out["decision"] is None
    case = fakes.calls["open_case"][0]
    assert case["opened_reason"] == "engine_failed" and case["handoff"].question
    with system_session() as db:
        # The fake engine added a case before failing; the savepoint removed it. Only open_case's own case remains.
        assert db.scalar(select(func.count()).select_from(models.Case).where(models.Case.tenant_id == world.tenant.id)) == 1


def test_registry_and_identity_are_passed_on(client: TestClient, world: World, fakes: Fakes) -> None:
    national_id = make_mock_id(9_100_001)
    fakes.registry = ("found", RegistryRecord(national_id=national_id, verified_income_pkr=12000, income_as_of="2026-10-01"))
    app = new_app(client, world).json()
    patch = {**eligible_patch(), "full_name": {"value": "Test Citizen"}, "dob": {"value": "1980-01-01"}}
    client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": patch}, headers=world.h("citizen"))
    _submit(client, world, app["id"])
    inp = fakes.calls["decide_and_record"][0]["inp"]
    assert inp.registry_status == "found" and inp.registry.verified_income_pkr == 12000
    assert inp.identity.status == "match"
    registered = fakes.calls["lookup_registry"][0]["national_id"]
    assert registered.startswith("00000-"), "the person's registered ID is used when the form has none"


def test_a_typed_id_that_is_not_the_persons_own_is_an_identity_mismatch(client: TestClient, world: World, fakes: Fakes) -> None:
    app = new_app(client, world).json()
    patch = {**eligible_patch(), "national_id": {"value": make_mock_id(9_200_002), "provenance": "typed"}}
    assert client.patch(f"/v1/applications/{app['id']}", json={"base_version": 1, "form_patch": patch}, headers=world.h("citizen")).status_code == 200
    _submit(client, world, app["id"])
    inp = fakes.calls["decide_and_record"][0]["inp"]
    assert inp.identity.status == "mismatch"
    assert fakes.n("verify_identity") == 0, "a known mismatch is not sent for matching"


def test_unchecked_upload_goes_to_a_person_without_calling_the_engine(client: TestClient, world: World, fakes: Fakes,
                                                                       monkeypatch: pytest.MonkeyPatch, uploads: object) -> None:  # fmt: skip
    import sys

    monkeypatch.setitem(sys.modules, "app.modules.docs_ai.service", None)
    app = _ready(client, world)
    up = client.post(f"/v1/applications/{app['id']}/documents", headers=world.h("citizen"), files={"file": ("x.jpg", jpeg_bytes(), "image/jpeg")})
    assert up.status_code == 201 and up.json()["document"]["message_key"] == "doc_person_will_check"
    out = _submit(client, world, app["id"])
    assert out["application"]["status"] == "in_review" and fakes.n("decide_and_record") == 0
    assert fakes.calls["open_case"][0]["opened_reason"] == "document_unchecked"
