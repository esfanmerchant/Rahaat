"""Case state machine, SLA and override rules. No database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.cases import rules

NOW = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("current", "event"),
    [
        ("resolved", "approve"), ("resolved", "reject"), ("closed", "reopen"), ("closed", "approve"),
        ("waiting_proof", "request_proof"), ("escalated", "escalate"), ("open", "reopen"), ("open", "proof_received"),
        ("resolved", "assign"), ("in_review", "fly"),
    ],
)  # fmt: skip
def test_illegal_transitions_are_refused(current: str, event: str) -> None:
    with pytest.raises(rules.IllegalCaseTransition):
        rules.next_status(current, event)


def test_the_normal_paths() -> None:
    assert rules.next_status("open", "assign") == "assigned"
    assert rules.next_status("in_review", "assign") == "in_review"  # handing over keeps the work state
    assert rules.next_status("assigned", "request_proof") == "waiting_proof"
    assert rules.next_status("waiting_proof", "proof_received") == "in_review"
    assert rules.next_status("waiting_proof", "approve") == "resolved"
    assert rules.next_status("in_review", "escalate") == "escalated"
    assert rules.next_status("escalated", "assign") == "assigned"
    assert rules.next_status("resolved", "reopen") == "open"
    assert rules.next_status("resolved", "close") == "closed"


def test_allowed_actions_follow_the_state() -> None:
    assert rules.allowed_actions("open") == ["approve", "reject", "request_proof", "escalate"]
    assert rules.allowed_actions("waiting_proof") == ["approve", "reject", "escalate"]
    assert rules.allowed_actions("escalated") == ["approve", "reject", "request_proof"]
    assert rules.allowed_actions("resolved") == [] and rules.allowed_actions("closed") == []


def test_sla_and_escalation() -> None:
    assert rules.sla_due("application_review", 50, NOW) == NOW + timedelta(hours=48)
    assert rules.sla_due("application_review", 10, NOW) == NOW + timedelta(hours=24)  # urgent: half the time
    assert rules.sla_due("scam_review", 50, NOW) == NOW + timedelta(hours=12)
    assert rules.escalated_priority(50) == 30 and rules.escalated_priority(10) == 0
    assert rules.escalated_sla(NOW + timedelta(hours=48), NOW) == NOW + timedelta(hours=24)
    assert rules.escalated_sla(NOW + timedelta(hours=2), NOW) == NOW + timedelta(hours=2)  # never later than before


def test_engine_lean_and_override() -> None:
    assert rules.engine_lean("approved", 0.99) == "approve"
    assert rules.engine_lean("rejected", 0.02) == "reject"
    eligible_first = [{"label": "income_above_cap", "probability": 0.19}, {"label": "eligible", "probability": 0.81}]
    assert rules.engine_lean("needs_human", 0.3, eligible_first) == "approve"  # the hypotheses win over p_ok
    assert rules.engine_lean("needs_human", 0.3) == "reject"
    assert rules.engine_lean("needs_human", None) is None
    assert rules.overrode_engine("reject", "approve") and rules.overrode_engine("approve", "reject")
    assert not rules.overrode_engine("approve", "approve")
    assert not rules.overrode_engine("request_proof", "approve") and not rules.overrode_engine("approve", None)
    assert rules.review_seconds(NOW - timedelta(seconds=95), NOW) == 95 and rules.review_seconds(None, NOW) is None
