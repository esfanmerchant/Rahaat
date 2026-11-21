"""Payment rules. No database."""

from __future__ import annotations

import uuid

import pytest

from app.modules.payments import rules


def test_state_machine_allows_only_the_listed_moves() -> None:
    assert rules.can_move("pending_approval", "approved") and rules.can_move("approved", "settled")
    assert rules.can_move("failed", "settled") and rules.can_move("settled", "reversed")
    for current, wanted in [("pending_approval", "settled"), ("settled", "failed"), ("cancelled", "approved"), ("reversed", "settled")]:
        assert not rules.can_move(current, wanted)
        with pytest.raises(rules.IllegalPaymentTransition):
            rules.check_move(current, wanted)


def test_four_eyes_limit_from_tenant_config() -> None:
    assert rules.four_eyes_limit({}) == 15_000
    assert rules.four_eyes_limit({"payment_four_eyes_limit_pkr": 10_000}) == 10_000
    assert rules.four_eyes_limit({"payment_four_eyes_limit_pkr": "junk"}) == 15_000
    assert not rules.needs_second_approver(12_000, 15_000)
    assert not rules.needs_second_approver(15_000, 15_000)  # at the limit: released at once
    assert rules.needs_second_approver(15_001, 15_000)


def test_the_second_approver_must_be_someone_else() -> None:
    maker, checker = uuid.uuid4(), uuid.uuid4()
    assert not rules.may_release(maker, [maker])
    assert not rules.may_release(maker, [None, str(maker)])
    assert rules.may_release(checker, [maker, None])


def test_one_key_per_application_and_reconciliation() -> None:
    app_id = uuid.uuid4()
    assert rules.idempotency_key(app_id) == rules.idempotency_key(app_id) == f"application:{app_id}"
    assert rules.reconciliation_status(12_000, 12_000) == "matched"
    assert rules.reconciliation_status(12_000, 11_000) == "amount_mismatch"
    assert rules.reconciliation_status(12_000, None) == "missing_on_rail"
