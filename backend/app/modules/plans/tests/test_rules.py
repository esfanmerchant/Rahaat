"""Limit maths, periods and reset dates. No database."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.plans import rules


def test_period_and_reset_roll_over_the_year() -> None:
    assert rules.period_of(datetime(2026, 11, 21, 23, 59, tzinfo=UTC)) == "2026-11"
    assert rules.resets_at(datetime(2026, 11, 21, tzinfo=UTC)) == datetime(2026, 12, 1, tzinfo=UTC)
    assert rules.resets_at(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


def test_previous_periods_end_with_the_current_month_and_cross_years() -> None:
    assert rules.previous_periods(datetime(2027, 2, 10, tzinfo=UTC), 6) == ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]


@pytest.mark.parametrize(
    ("limits", "metric", "expected"),
    [({"sms": 5}, "sms", 5), ({"sms": 5}, "ocr", None), (None, "sms", None), ({"sms": -1}, "sms", None), ({"sms": True}, "sms", None),
     ({"sms": 0}, "sms", 0)],
)  # fmt: skip
def test_limit_lookup_treats_missing_or_odd_values_as_unlimited(limits: dict[str, object] | None, metric: str, expected: int | None) -> None:
    assert rules.limit_for(limits, metric) == expected


def test_would_exceed_is_exact_at_the_boundary() -> None:
    assert not rules.would_exceed(4, 1, 5) and rules.would_exceed(5, 1, 5) and rules.would_exceed(3, 3, 5)
    assert not rules.would_exceed(10**9, 1, None)
    assert rules.would_exceed(0, 1, 0)


def test_percent_used_is_capped_and_none_without_a_limit() -> None:
    assert rules.percent_used(50, 200) == 25.0 and rules.percent_used(300, 200) == 100.0 and rules.percent_used(7, None) is None
    assert rules.percent_used(0, 0) == 0.0 and rules.percent_used(1, 0) == 100.0


def test_the_catalogue_is_the_three_public_plans_and_the_demo_plan_is_the_largest() -> None:
    assert rules.PUBLIC_PLAN_CODES == ("free", "standard", "government")
    by_code = {code: limits for code, _, _, limits in rules.PLAN_CATALOGUE}
    assert all(set(limits) == set(rules.METRICS) for limits in by_code.values())
    assert all(by_code["government"][m] > by_code["standard"][m] > by_code["free"][m] for m in rules.METRICS)
    assert rules.DEMO_PLAN == "government"
