"""Counts for the Scam Map with k-anonymity: every number shown is a count of at least K reports. Pure.

Each published grouping (district x kind x day, district x kind, district, kind x day, day) is suppressed on
its own: a group of 1 to K-1 reports is hidden, a group of 0 shows as 0. Differencing two groupings can
reveal the total of hidden groups in an unnamed set (for example "2 reports in this district on days not
shown"), never the count of a named small group. That limit is stated in the response.
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from datetime import UTC, date, datetime, timedelta, timezone

K = 5
PKT = timezone(timedelta(hours=5), "PKT")  # Pakistan has no daylight saving
NOTE = "Groups with fewer than 5 reports are hidden, so totals are a lower bound."


def suppress[Key: Hashable](counts: Iterable[tuple[Key, int]], k: int = K) -> tuple[list[tuple[Key, int]], int]:
    """(groups with at least k reports, number of groups hidden). Groups of zero are neither shown nor hidden."""
    shown: list[tuple[Key, int]] = []
    hidden = 0
    for key, count in counts:
        if count >= k:
            shown.append((key, count))
        elif count > 0:
            hidden += 1
    return shown, hidden


def rollup[Key: Hashable](rows: Iterable[tuple[tuple[str | None, ...], int]], keep: tuple[int, ...]) -> dict[tuple[str | None, ...], int]:
    """Sum fine-grained counts up to the positions in `keep`."""
    out: dict[tuple[str | None, ...], int] = {}
    for key, count in rows:
        coarse = tuple(key[i] for i in keep)
        out[coarse] = out.get(coarse, 0) + count
    return out


def window(days: int, now: datetime | None = None) -> tuple[date, date, datetime]:
    """(first day, last day, first instant in UTC) of the last `days` calendar days in Pakistan time."""
    now = (now or datetime.now(UTC)).astimezone(PKT)
    last = now.date()
    first = last - timedelta(days=days - 1)
    return first, last, datetime.combine(first, datetime.min.time(), tzinfo=PKT).astimezone(UTC)


def day_series(counts: dict[str, int], first: date, last: date, k: int = K) -> list[tuple[str, int | None]]:
    """Every day in the window: its count, 0, or None when 1 to k-1 reports are hidden."""
    out: list[tuple[str, int | None]] = []
    day = first
    while day <= last:
        value = counts.get(day.isoformat(), 0)
        out.append((day.isoformat(), value if value == 0 or value >= k else None))
        day += timedelta(days=1)
    return out
