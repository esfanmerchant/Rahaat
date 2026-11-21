"""The impact arithmetic, DB-free."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.modules.analytics import impact as imp


def test_route_mix_counts_each_route_and_the_handoff_rate() -> None:
    mix = imp.route_mix(["auto", "auto", "human", "ask_more"])
    assert mix["decisions"] == 4 and mix["by_route"] == {"auto": 2, "ask_more": 1, "human": 1}
    assert mix["handoff_rate"] == 0.25 and mix["not_automatic_rate"] == 0.5
    empty = imp.route_mix([])
    assert empty["decisions"] == 0 and empty["handoff_rate"] is None and empty["not_automatic_rate"] is None


def test_durations_use_nearest_rank_and_drop_negative_noise() -> None:
    d = imp.durations([10, 20, 30, 40, 100, -5, None])
    assert d == {"n": 5, "median_seconds": 30.0, "p90_seconds": 100.0}
    assert imp.durations([]) == {"n": 0, "median_seconds": None, "p90_seconds": None}


def test_guard_counts_count_a_decision_once_per_kind() -> None:
    g = imp.guard_counts([["document_suspect", "identity_mismatch"], ["possible_duplicate", "duplicate_record"], [], ["anomaly_flag"]])
    assert g == {"forged_cards_flagged": 1, "identity_mismatches": 1, "duplicates_caught": 1, "anomaly_guard": 1, "held_for_a_person_by_a_guard": 3}


def test_expected_cost_uses_the_chosen_action_and_a_baseline_of_everything_to_a_person() -> None:
    matrix = {"human_review": 3.0, "delay_per_day": 0.2}
    out = imp.expected_cost(
        [("approved", {"approve": 1.0, "human": 3.2}, matrix), ("needs_human", {"approve": 20.0, "human": 3.2}, matrix), ("approved", {}, matrix)]
    )
    assert out["decisions"] == 2 and out["per_claim_units"] == 2.1 and out["all_to_a_person_per_claim_units"] == 3.2
    assert out["units_saved_per_claim"] == 1.1 and out["per_claim_pkr_assumed"] == 252.0
    assert imp.expected_cost([])["per_claim_units"] is None


def test_time_saved_prefers_the_measured_review_time_and_names_the_assumption_otherwise() -> None:
    measured = imp.time_saved(
        automatic_decisions=120, median_review_seconds=300, median_case_seconds=7200, median_automatic_seconds=2, assumed_minutes_per_manual_review=10
    )
    assert measured["hands_on_source"] == "measured_median_review_seconds" and measured["hands_on_hours_saved"] == 10.0
    assert measured["waiting_hours_avoided"] == round(120 * 7198 / 3600, 2) and "counterfactual" in measured["label"].lower()
    fallback = imp.time_saved(
        automatic_decisions=60,
        median_review_seconds=None,
        median_case_seconds=None,
        median_automatic_seconds=None,
        assumed_minutes_per_manual_review=12,
    )
    assert fallback["hands_on_source"] == "assumed_minutes_per_manual_review" and fallback["hands_on_hours_saved"] == 12.0
    assert fallback["waiting_hours_avoided"] is None


@given(st.lists(st.floats(0, 1e6, allow_nan=False), min_size=1, max_size=200))
def test_median_never_exceeds_p90(values: list[float]) -> None:
    d = imp.durations(values)
    assert d["median_seconds"] is not None and d["p90_seconds"] is not None and d["median_seconds"] <= d["p90_seconds"] + 0.05


@given(st.lists(st.sampled_from(["auto", "ask_more", "human"]), max_size=100))
def test_route_rates_sum_to_one(routes: list[str]) -> None:
    mix = imp.route_mix(routes)
    if routes:
        assert abs(sum(mix["rate"].values()) - 1.0) < 1e-3 and mix["decisions"] == len(routes)


@given(st.integers(0, 5000), st.floats(1, 240), st.floats(1, 240))
def test_more_assumed_minutes_never_save_fewer_hours(n: int, low: float, extra: float) -> None:
    def hours(minutes: float) -> float:
        return float(
            imp.time_saved(
                automatic_decisions=n,
                median_review_seconds=None,
                median_case_seconds=None,
                median_automatic_seconds=None,
                assumed_minutes_per_manual_review=minutes,
            )["hands_on_hours_saved"]
        )

    assert hours(low + extra) >= hours(low) - 0.01
