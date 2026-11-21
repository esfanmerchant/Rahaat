"""The arithmetic of the impact report. Pure: plain numbers in, plain numbers out, no database and no clock.

Everything here is either counted from rows or computed from measured durations. The only numbers that are
not measured are the explicit assumptions the caller passes in (`ASSUMED_*`), and they are echoed back
with their names so a reader can see exactly what they are.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Any, Final

ASSUMED_MINUTES_PER_MANUAL_REVIEW: Final = 10.0  # used only when no officer review time has been measured yet
ASSUMED_PKR_PER_COST_UNIT: Final = 120.0  # the cost matrix is in units; the contract documents 1 unit as about Rs 120
OUTCOME_ACTION: Final = {"approved": "approve", "rejected": "reject", "needs_proof": "ask_proof", "needs_human": "human"}
ROUTES: Final = ("auto", "ask_more", "human")
FRAUD_GUARDS: Final = {
    "forged_cards_flagged": ("document_suspect",),
    "identity_mismatches": ("identity_mismatch", "card_id_mismatch"),
    "duplicates_caught": ("possible_duplicate", "duplicate_record"),
    "anomaly_guard": ("anomaly_flag",),
}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile, q in 0..100."""
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1])


def durations(seconds: Iterable[float | None]) -> dict[str, Any]:
    """Count, median and 90th percentile of measured durations (negative values are clock noise and dropped)."""
    clean = [float(s) for s in seconds if s is not None and s >= 0]
    median = percentile(clean, 50)
    p90 = percentile(clean, 90)
    return {"n": len(clean), "median_seconds": None if median is None else round(median, 1), "p90_seconds": None if p90 is None else round(p90, 1)}


def route_mix(routes: Iterable[str]) -> dict[str, Any]:
    counts = Counter(routes)
    n = sum(counts[r] for r in ROUTES)
    rate = {r: (round(counts[r] / n, 4) if n else None) for r in ROUTES}
    return {
        "decisions": n,
        "by_route": {r: counts[r] for r in ROUTES},
        "rate": rate,
        "handoff_rate": rate["human"],
        "not_automatic_rate": None if not n else round((n - counts["auto"]) / n, 4),
    }


def guard_counts(guard_lists: Iterable[Sequence[str]]) -> dict[str, int]:
    """Decisions that raised each kind of fraud-related guard (a decision counts once per kind)."""
    out = {name: 0 for name in FRAUD_GUARDS}
    held = 0
    for guards in guard_lists:
        present = set(guards)
        for name, members in FRAUD_GUARDS.items():
            if present & set(members):
                out[name] += 1
        held += bool(present)
    out["held_for_a_person_by_a_guard"] = held
    return out


def expected_cost(decisions: Iterable[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    """Expected cost per decision from the stored traces, against the same claims all sent to a person.

    Each item is (outcome, expected_costs, cost_matrix). The chosen action's expected cost is what the engine
    itself computed; the baseline is `human_review + delay_per_day` for that decision's own cost matrix.
    These are expectations under the cost matrix, not money that was spent.
    """
    chosen: list[float] = []
    baseline: list[float] = []
    for outcome, costs, matrix in decisions:
        action = OUTCOME_ACTION.get(outcome)
        value = (costs or {}).get(action) if action else None
        if isinstance(value, int | float) and not math.isnan(value):
            chosen.append(float(value))
            baseline.append(float(matrix.get("human_review", 3.0)) + float(matrix.get("delay_per_day", 0.2)))
    n = len(chosen)
    per = round(sum(chosen) / n, 4) if n else None
    base = round(sum(baseline) / n, 4) if n else None
    return {
        "decisions": n,
        "per_claim_units": per,
        "all_to_a_person_per_claim_units": base,
        "per_claim_pkr_assumed": None if per is None else round(per * ASSUMED_PKR_PER_COST_UNIT, 1),
        "units_saved_per_claim": None if per is None or base is None else round(base - per, 4),
    }


def time_saved(
    *,
    automatic_decisions: int,
    median_review_seconds: float | None,
    median_case_seconds: float | None,
    median_automatic_seconds: float | None,
    assumed_minutes_per_manual_review: float,
) -> dict[str, Any]:
    """What the automatic decisions spared, in two parts, both a counterfactual ("had a person handled each one the way persons handle cases now").

    * hands_on: measured median officer review time (first look to action) x automatic decisions. Falls back to
      the named assumption when no review has been timed yet, and says so.
    * waiting: measured median case open-to-resolve time minus measured median automatic time, x automatic decisions.
    """
    if median_review_seconds is not None:
        minutes, source = median_review_seconds / 60, "measured_median_review_seconds"
    else:
        minutes, source = assumed_minutes_per_manual_review, "assumed_minutes_per_manual_review"
    hands_on = round(automatic_decisions * minutes / 60, 2)
    waiting = None
    if median_case_seconds is not None and median_automatic_seconds is not None and automatic_decisions:
        waiting = round(automatic_decisions * max(0.0, median_case_seconds - median_automatic_seconds) / 3600, 2)
    return {
        "automatic_decisions": automatic_decisions,
        "minutes_per_manual_review_used": round(minutes, 2),
        "hands_on_source": source,
        "hands_on_hours_saved": hands_on,
        "waiting_hours_avoided": waiting,
        "label": "Counterfactual estimate: automatic decisions multiplied by measured per-case human times. Not a measured saving.",
    }
