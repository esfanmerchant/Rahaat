"""Calibration and classification metrics. Pure Python over lists, so results are exact and reproducible."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def reliability(probs: Sequence[float], labels: Sequence[bool | int], bins: int = 10) -> list[dict[str, Any]]:
    """Equal-width bins: how often the event happened among cases given about this probability."""
    rows: list[dict[str, Any]] = []
    for b in range(bins):
        low, high = b / bins, (b + 1) / bins
        members = [(p, int(y)) for p, y in zip(probs, labels, strict=True) if (low <= p < high) or (b == bins - 1 and p == 1.0)]
        count = len(members)
        rows.append({
            "bin": b, "low": round(low, 2), "high": round(high, 2), "count": count,
            "mean_predicted": round(sum(p for p, _ in members) / count, 4) if count else None,
            "observed_rate": round(sum(y for _, y in members) / count, 4) if count else None,
        })  # fmt: skip
    return rows


def ece(probs: Sequence[float], labels: Sequence[bool | int], bins: int = 10) -> float:
    """Expected calibration error: the count-weighted gap between predicted and observed rates."""
    total = len(probs)
    if total == 0:
        return 0.0
    gap = 0.0
    for row in reliability(probs, labels, bins):
        if row["count"]:
            gap += row["count"] / total * abs(row["mean_predicted"] - row["observed_rate"])
    return round(gap, 4)


def brier(probs: Sequence[float], labels: Sequence[bool | int]) -> float:
    if not probs:
        return 0.0
    return round(sum((p - int(y)) ** 2 for p, y in zip(probs, labels, strict=True)) / len(probs), 4)


def auc(probs: Sequence[float], labels: Sequence[bool | int]) -> float | None:
    """Area under the ROC curve by rank statistic (ties count half). None when only one class is present."""
    pos = [p for p, y in zip(probs, labels, strict=True) if y]
    neg = [p for p, y in zip(probs, labels, strict=True) if not y]
    if not pos or not neg:
        return None
    ordered = sorted([(p, 1) for p in pos] + [(p, 0) for p in neg])
    rank_sum = 0.0
    i = 0
    while i < len(ordered):
        j = i
        while j < len(ordered) and ordered[j][0] == ordered[i][0]:
            j += 1
        mid_rank = (i + 1 + j) / 2.0
        rank_sum += mid_rank * sum(1 for k in range(i, j) if ordered[k][1] == 1)
        i = j
    return round((rank_sum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)), 4)


def summary(probs: Sequence[float], labels: Sequence[bool | int], bins: int = 10) -> dict[str, Any]:
    return {
        "n": len(probs), "positive_rate": round(sum(int(y) for y in labels) / len(labels), 4) if labels else None,
        "ece": ece(probs, labels, bins), "brier": brier(probs, labels), "auc": auc(probs, labels),
        "reliability": reliability(probs, labels, bins),
    }  # fmt: skip
