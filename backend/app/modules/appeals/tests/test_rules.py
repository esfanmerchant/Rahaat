"""Appeal eligibility, the different-officer rule and complaint routing. No database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.appeals import rules

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
DECISION = uuid.uuid4()


def _reason(**overrides: object) -> str | None:
    args: dict[str, object] = {"application_status": "rejected", "decided_at": NOW - timedelta(days=3), "now": NOW, "decision_id": DECISION, "earlier": []}
    args.update(overrides)
    return rules.ineligible_reason(**args)  # type: ignore[arg-type]


def test_a_rejected_application_inside_the_window_may_appeal() -> None:
    assert _reason() is None
    assert _reason(decided_at=NOW - timedelta(days=30)) is None  # the last day still counts


@pytest.mark.parametrize("status", ["draft", "submitted", "needs_proof", "in_review", "approved", "paid", "withdrawn"])
def test_only_a_rejection_can_be_appealed(status: str) -> None:
    assert _reason(application_status=status) == "appeal_not_applicable"


def test_the_window_closes_after_thirty_days_and_an_unknown_decision_time_is_refused() -> None:
    assert _reason(decided_at=NOW - timedelta(days=30, minutes=1)) == "appeal_window_closed"
    assert _reason(decided_at=None) == "appeal_window_closed"
    assert rules.days_left(NOW - timedelta(days=10), NOW) == 20 and rules.days_left(NOW - timedelta(days=40), NOW) == 0


def test_one_open_appeal_at_a_time_and_one_decided_appeal_per_decision() -> None:
    assert _reason(earlier=[("open", DECISION)]) == "appeal_already_open"
    assert _reason(earlier=[("upheld", DECISION)]) == "appeal_already_decided"
    assert _reason(earlier=[("overturned", DECISION)]) == "appeal_already_decided"
    assert _reason(earlier=[("withdrawn", DECISION)]) is None  # a withdrawn appeal does not use up the right
    assert _reason(earlier=[("upheld", uuid.uuid4())]) is None  # a newer decision can be appealed again


def test_nobody_who_took_part_in_the_first_decision_decides_the_appeal() -> None:
    first, second, approver, other = (uuid.uuid4() for _ in range(4))
    deciders = rules.collect_deciders([(first, None), (second, approver), (None, None)])
    assert deciders == {first, second, approver}
    assert not rules.may_decide(first, deciders) and not rules.may_decide(approver, deciders)
    assert rules.may_decide(other, deciders) and rules.may_decide(other, [])  # an engine-only decision has no officer to exclude


def test_what_the_citizen_is_told_never_depends_on_staff_notes() -> None:
    assert [rules.appeal_citizen_status(s) for s in ("open", "upheld", "overturned", "withdrawn")] == [
        "being_checked", "first_answer_stays", "approved_after_appeal", "withdrawn"]  # fmt: skip


def test_complaints_are_routed_by_category() -> None:
    assert rules.complaint_route("scam_attempt") == ("scam_review", 20)
    assert rules.complaint_route("staff") == ("complaint", 30)
    assert rules.complaint_route("service") == ("complaint", 50)
    assert rules.category_of(rules.complaint_reason("payment")) == "payment" and rules.category_of("income_unverified") == "other"
    assert [rules.complaint_citizen_status(s) for s in ("open", "assigned", "in_review", "escalated", "resolved", "closed")] == [
        "received", "received", "being_checked", "being_checked", "resolved", "resolved"]  # fmt: skip
