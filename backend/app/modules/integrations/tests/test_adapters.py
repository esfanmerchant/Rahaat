"""Adapters, retries and the circuit breaker, against the in-process mock services. No database."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core.mockdata import make_mock_id
from app.demo_accounts import demo_citizens
from app.mocks.state import STATE
from app.modules.integrations import service
from app.modules.integrations.resilience import CircuitBreaker, backoff_delay
from app.modules.integrations.testing import FakeClock, fresh_mocks


@pytest.fixture()
def clock() -> Iterator[FakeClock]:
    with fresh_mocks() as fake:
        yield fake


def _citizen(name: str) -> dict[str, str]:
    return next(c for c in demo_citizens() if c["name"] == name)


def test_breaker_opens_after_the_threshold_and_lets_one_trial_through() -> None:
    clock = FakeClock()
    gate = CircuitBreaker("x", threshold=2, reset_after=10, clock=clock)
    assert gate.allow()
    gate.record_failure()
    assert gate.state == "closed" and gate.allow()
    gate.record_failure()
    assert gate.state == "open" and not gate.allow()
    clock.advance(10)
    assert gate.state == "half_open"
    assert gate.allow() and not gate.allow()  # exactly one trial call
    gate.record_failure()
    assert gate.state == "open"  # the trial failed: open again for another full period
    clock.advance(10)
    assert gate.allow()
    gate.record_success()
    assert gate.state == "closed" and gate.snapshot()["consecutive_failures"] == 0


def test_backoff_doubles_and_is_capped() -> None:
    assert [backoff_delay(n, base=0.1, cap=0.5) for n in (1, 2, 3, 4)] == [0.1, 0.2, 0.4, 0.5]


def test_identity_and_registry_answer_from_the_demo_stories(clock: FakeClock) -> None:
    zainab = _citizen("Zainab Bibi")
    check = service.verify_identity(zainab["national_id"], "Zainab Bibi", zainab["dob"])
    assert check.status == "match" and check.name_score == 1.0
    status, record = service.lookup_registry(zainab["national_id"])
    assert status == "found" and record is not None
    assert record.is_widow and record.household_size == 5 and record.verified_income_pkr is None
    assert service.verify_identity(zainab["national_id"], "Somebody Else", "1990-01-01").status == "mismatch"


def test_invalid_ids_are_not_found_and_never_sent_out(clock: FakeClock) -> None:
    good = make_mock_id(1_234_567)
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    assert service.lookup_registry(bad) == ("not_found", None)
    assert service.verify_identity("12345-1234567-1", "A", None).status == "not_found"  # mock-lint: allow
    assert STATE.controls["registry"].calls == 0 and STATE.controls["identity"].calls == 0


def test_a_down_service_is_unavailable_opens_the_breaker_and_recovers(clock: FakeClock) -> None:
    some_id = make_mock_id(2_000_001)
    STATE.set_control("registry", latency_ms=None, failure_rate=None, down=True)
    assert service.lookup_registry(some_id) == ("unavailable", None)  # first and one retry, both 503
    assert STATE.controls["registry"].calls == 2 and clock.slept == [0.0]
    assert service.lookup_registry(some_id) == ("unavailable", None)
    assert service.breaker("registry").state == "open"
    calls = STATE.controls["registry"].calls
    assert service.lookup_registry(some_id) == ("unavailable", None)
    assert STATE.controls["registry"].calls == calls, "an open breaker must not call the service at all"

    STATE.set_control("registry", latency_ms=None, failure_rate=None, down=False)
    assert service.lookup_registry(some_id) == ("unavailable", None)  # still open: the reset period has not passed
    clock.advance(30)
    status, record = service.lookup_registry(some_id)  # half-open trial succeeds
    assert status == "found" and record is not None
    assert service.breaker("registry").state == "closed"


def test_a_flaky_service_is_retried_and_succeeds(clock: FakeClock) -> None:
    # Fail exactly the first request: a 100% failure rate for one call, then healthy.
    original = STATE.draw_failure
    seen: list[int] = []

    def first_fails(name: str) -> tuple[bool, int]:
        fail, latency = original(name)
        seen.append(1)
        return (len(seen) == 1) or fail, latency

    STATE.draw_failure = first_fails  # type: ignore[method-assign]
    try:
        check = service.verify_identity(_citizen("Aslam Khan")["national_id"], "Aslam Khan", _citizen("Aslam Khan")["dob"])
    finally:
        STATE.draw_failure = original  # type: ignore[method-assign]
    assert check.status == "match" and len(seen) == 2
    assert service.breaker("identity").snapshot()["consecutive_failures"] == 0


def test_a_slow_service_times_out_as_unavailable() -> None:
    with fresh_mocks(timeout_seconds="0.2", retries="0"):
        STATE.set_control("identity", latency_ms=1_500, failure_rate=None, down=False)
        check = service.verify_identity(_citizen("Aslam Khan")["national_id"], "Aslam Khan", None)
        assert check.status == "unavailable"


def test_payment_and_sms_adapters(clock: FakeClock) -> None:
    first = service.submit_payment(idempotency_key="application:test-0001", amount_pkr=12_000, account_ref="wallet-1", reference="p")
    again = service.submit_payment(idempotency_key="application:test-0001", amount_pkr=12_000, account_ref="wallet-1", reference="p")
    assert first.status == "settled" and first.rail_ref == again.rail_ref and first.settled_pkr == 12_000
    assert service.submit_payment(idempotency_key="application:test-0001", amount_pkr=5, account_ref="w").status == "rejected"
    assert service.send_sms("0999-0000201", "Rahat: hello").status == "sent"
    assert service.send_sms("03001234567", "x").status == "rejected"  # mock-lint: allow
    STATE.set_control("payment", latency_ms=None, failure_rate=None, down=True)
    assert service.submit_payment(idempotency_key="application:test-0002", amount_pkr=1, account_ref="w").status == "unavailable"


def test_degradation_messages_exist_in_both_languages() -> None:
    for name, messages in service.DEGRADED_MESSAGES.items():
        assert set(messages) == {"en", "ur"}, name
        for text in messages.values():
            assert text.count(".") + text.count("۔") <= 3
