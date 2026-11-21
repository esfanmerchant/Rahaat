"""Plan limits and usage maths. Pure functions with DB-free tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

METRICS: Final[tuple[str, ...]] = ("api_calls", "ocr", "sms", "ai_calls", "applications")
METRIC_LABELS: Final[dict[str, str]] = {
    "api_calls": "API calls", "ocr": "Document checks", "sms": "Text messages", "ai_calls": "AI calls (speech and assistant)",
    "applications": "Applications started",
}  # fmt: skip

# Limits per month. A metric missing from a plan is not limited; a tenant without a plan is not limited either.
PLAN_CATALOGUE: Final[tuple[tuple[str, str, int, dict[str, int]], ...]] = (
    ("free", "Free", 0, {"api_calls": 1_000, "ocr": 100, "sms": 200, "ai_calls": 500, "applications": 50}),
    ("standard", "Standard", 25_000, {"api_calls": 50_000, "ocr": 5_000, "sms": 10_000, "ai_calls": 25_000, "applications": 2_000}),
    ("government", "Government", 150_000,
     {"api_calls": 5_000_000, "ocr": 500_000, "sms": 1_000_000, "ai_calls": 2_500_000, "applications": 500_000}),
)  # fmt: skip
PUBLIC_PLAN_CODES: Final[tuple[str, ...]] = tuple(code for code, *_ in PLAN_CATALOGUE)
DEMO_PLAN: Final = "government"  # the demo departments: high limits, so the demo never meets one by accident


def period_of(now: datetime) -> str:
    """The metering period: the calendar month in UTC (the same rule as API key metering)."""
    return now.astimezone(UTC).strftime("%Y-%m")


def resets_at(now: datetime) -> datetime:
    """The first moment of next month, UTC: when this month's counters start again."""
    now = now.astimezone(UTC)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return datetime(year, month, 1, tzinfo=UTC)


def previous_periods(now: datetime, count: int) -> list[str]:
    """The `count` months ending with the current one, oldest first."""
    now = now.astimezone(UTC)
    index = now.year * 12 + (now.month - 1)
    return [f"{(i // 12):04d}-{(i % 12) + 1:02d}" for i in range(index - count + 1, index + 1)]


def limit_for(limits: dict[str, Any] | None, metric: str) -> int | None:
    """The monthly limit of a metric, or None when it is not limited."""
    if not limits or metric not in limits:
        return None
    value = limits[metric]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def would_exceed(used: int, amount: int, limit: int | None) -> bool:
    return limit is not None and used + amount > limit


def percent_used(used: int, limit: int | None) -> float | None:
    """None when there is no limit; 0 for a limit of 0 with nothing used; capped at 100 for display."""
    if limit is None:
        return None
    if limit == 0:
        return 100.0 if used > 0 else 0.0
    return round(min(100.0, used * 100.0 / limit), 1)
