"""The mock services: demo stories, deterministic records, identity matching, keys, idempotency, failure controls."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.mockdata import make_mock_id
from app.demo_accounts import demo_citizens
from app.mocks import identity, registry
from app.mocks.config import DEV_KEYS, KEY_HEADER
from app.mocks.main import app
from app.mocks.state import STATE

TODAY = date(2026, 11, 21)


def _by_name(name: str) -> dict[str, str]:
    return next(c for c in demo_citizens() if c["name"] == name)


def _key(service: str) -> dict[str, str]:
    return {KEY_HEADER: DEV_KEYS[service]}


@pytest.fixture()
def mock() -> Iterator[TestClient]:
    STATE.reset_all()
    with TestClient(app) as client:
        yield client
    STATE.reset_all()


def test_demo_stories_the_demo_depends_on() -> None:
    zainab = registry.find(_by_name("Zainab Bibi")["national_id"], today=TODAY)
    aslam = registry.find(_by_name("Aslam Khan")["national_id"], today=TODAY)
    rukhsana = registry.find(_by_name("Rukhsana Parveen")["national_id"], today=TODAY)
    assert zainab and aslam and rukhsana
    assert zainab.is_widow and zainab.household_size == 5 and zainab.verified_income_pkr is None and zainab.income_as_of is None
    assert aslam.verified_income_pkr == 24_000 and aslam.household_size == 6 and aslam.receives_other_aid is False
    assert aslam.income_as_of == "2026-11-01"
    assert rukhsana.verified_income_pkr == 41_000
    # The registry agrees with the seed: same name, ID and date of birth.
    assert zainab.dob == _by_name("Zainab Bibi")["dob"] and zainab.full_name == "Zainab Bibi"


def test_other_valid_ids_get_a_stable_derived_record_and_bad_check_digits_are_not_found() -> None:
    some_id = make_mock_id(4_242_424)
    first, second = registry.find(some_id, today=TODAY), registry.find(some_id, today=TODAY)
    assert first is not None and first == second
    assert 1 <= first.household_size <= 9
    body, check = some_id[:-1], int(some_id[-1])
    wrong = f"{body}{(check + 1) % 10}"
    assert registry.find(wrong, today=TODAY) is None
    assert registry.find("not-an-id", today=TODAY) is None


def test_identity_match_partial_and_mismatch() -> None:
    zainab = registry.find(_by_name("Zainab Bibi")["national_id"], today=TODAY)
    assert zainab is not None
    assert identity.match(zainab, "Zainab Bibi", "1978-03-14")[0] == "match"
    assert identity.match(zainab, "BIBI, Zainab", "1978-03-14")[0] == "match"  # order and case do not matter
    assert identity.match(zainab, "زینب بی بی", "1978-03-14")[0] == "match"  # the Urdu spelling on file
    assert identity.match(zainab, "Zainab Bibi", "1979-03-14")[0] == "partial"  # date of birth disagrees
    assert identity.match(zainab, "Zaynab Bibi", "1978-03-14")[0] == "match"  # one letter apart
    assert identity.match(zainab, "Zainab", "1978-03-14")[0] == "partial"  # given name only
    assert identity.match(zainab, "Zainab Bibi", None)[0] == "partial"  # unknown stays unknown
    assert identity.match(zainab, "Kamran Memon", "1978-03-14")[0] == "mismatch"


def test_each_service_needs_its_own_key(mock: TestClient) -> None:
    some_id = make_mock_id(1_000_202)
    assert mock.get(f"/registry/persons/{some_id}").status_code == 401
    assert mock.get(f"/registry/persons/{some_id}", headers=_key("sms")).status_code == 401
    ok = mock.get(f"/registry/persons/{some_id}", headers=_key("registry"))
    assert ok.status_code == 200 and ok.json()["household_size"] == 6
    assert "full_name_ur" not in ok.json()


def test_identity_endpoint_and_not_found(mock: TestClient) -> None:
    citizen = _by_name("Aslam Khan")
    answer = mock.post("/identity/verify", headers=_key("identity"),
                       json={"national_id": citizen["national_id"], "full_name": "Aslam Khan", "dob": citizen["dob"]})
    assert answer.status_code == 200 and answer.json()["status"] == "match"
    wrong = citizen["national_id"][:-1] + str((int(citizen["national_id"][-1]) + 1) % 10)
    assert mock.post("/identity/verify", headers=_key("identity"), json={"national_id": wrong}).status_code == 404
    assert mock.post("/identity/verify", headers=_key("identity"), json={"national_id": wrong, "extra": 1}).status_code == 422


def test_payment_rail_is_idempotent_on_the_key(mock: TestClient) -> None:
    body = {"idempotency_key": "application:abc-123", "amount_pkr": 12_000, "account_ref": "wallet-0001", "reference": "p1"}
    first = mock.post("/payments", headers=_key("payment"), json=body).json()
    again = mock.post("/payments", headers=_key("payment"), json=body).json()
    assert first["rail_ref"] == again["rail_ref"] and again["replayed"] is True and first["status"] == "settled"
    conflict = mock.post("/payments", headers=_key("payment"), json={**body, "amount_pkr": 99_000})
    assert conflict.status_code == 409 and conflict.json()["code"] == "idempotency_conflict"
    assert len(STATE.payments) == 1


def test_sms_gateway_has_a_readable_outbox_and_refuses_real_numbers(mock: TestClient) -> None:
    sent = mock.post("/sms/messages", headers=_key("sms"), json={"to": "09990000201", "body": "Rahat: test. Code: ABC234"})
    assert sent.status_code == 200 and sent.json()["to"] == "0999-0000201"
    assert mock.post("/sms/messages", headers=_key("sms"), json={"to": "03001234567", "body": "x"}).status_code == 422  # mock-lint: allow
    outbox = mock.get("/sms/outbox", headers=_key("sms"), params={"to": "0999-0000201"}).json()["items"]
    assert [m["body"] for m in outbox] == ["Rahat: test. Code: ABC234"]


def test_controls_make_a_service_down_slow_or_flaky(mock: TestClient) -> None:
    assert mock.post("/control/sms", json={"down": True}).status_code == 401  # control has its own key
    assert mock.post("/control/sms", headers=_key("control"), json={"down": True}).status_code == 200
    down = mock.post("/sms/messages", headers=_key("sms"), json={"to": "0999-0000201", "body": "x"})
    assert down.status_code == 503 and down.json()["code"] == "service_unavailable"
    mock.post("/control/sms", headers=_key("control"), json={"down": False, "failure_rate": 1.0})
    assert mock.post("/sms/messages", headers=_key("sms"), json={"to": "0999-0000201", "body": "x"}).status_code == 503
    controls = mock.post("/control/reset", headers=_key("control")).json()["services"]
    assert controls["sms"] == {"latency_ms": 0, "failure_rate": 0.0, "down": False, "calls": 0, "failures_injected": 0}
    assert mock.post("/sms/messages", headers=_key("sms"), json={"to": "0999-0000201", "body": "x"}).status_code == 200


def test_registry_override_for_a_scenario(mock: TestClient) -> None:
    aslam_id = _by_name("Aslam Khan")["national_id"]
    changed = mock.put(f"/control/registry/{aslam_id}", headers=_key("control"), json={"clear_income": True})
    assert changed.status_code == 200 and changed.json()["verified_income_pkr"] is None
    assert mock.get(f"/registry/persons/{aslam_id}", headers=_key("registry")).json()["verified_income_pkr"] is None
    mock.delete(f"/control/registry/{aslam_id}", headers=_key("control"))
    assert mock.get(f"/registry/persons/{aslam_id}", headers=_key("registry")).json()["verified_income_pkr"] == 24_000
