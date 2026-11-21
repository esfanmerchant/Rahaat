"""The anomaly detectors, DB-free: rings, spikes against a baseline, helper bursts, repeated IDs, abstention, determinism, dedupe."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.anomaly import detectors as D
from app.modules.anomaly.dedupe import ExistingCase, plan_cases
from app.modules.anomaly.evaluate import run_world, summarise
from app.synth.anomaly_world import build_anomaly_world

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


def rec(n: int, *, at: datetime = T0, **kw: object) -> D.AppRecord:
    base: dict[str, object] = {"app_id": f"a{n}", "person_id": f"p{n}", "at": at, "district": "Dadu", "payout": f"acct{n}", "national_id": f"id{n}",
                               "household": f"h{n}"}  # fmt: skip
    base.update(kw)
    return D.AppRecord(**base)  # type: ignore[arg-type]


# --- shared payout ----------------------------------------------------------------------------------------


def test_one_wallet_behind_three_households_is_flagged_with_evidence_and_a_human_route() -> None:
    rows = [rec(i, payout="9f8e7d6c5b4a39281706") for i in range(3)] + [rec(10 + i) for i in range(5)]
    result = D.detect_shared_payout(rows)
    assert result.status == "flagged" and len(result.findings) == 1
    f = result.findings[0]
    assert f.evidence_ids == ["a0", "a1", "a2"] and f.evidence["people"] == 3 and f.evidence["households"] == 3
    assert f.decision.route == "human" and f.decision.choice == "anomaly" and not f.decision.abstained
    assert "9f8e7d6c5b4a39281706" not in str(f.evidence) and f.evidence["account"] == "fp-9f8e7d6c", "chips show a short label only"
    assert f.cheapest_check and f.pattern_key == "shared_payout:9f8e7d6c5b4a39281706"


def test_relatives_sharing_a_wallet_and_two_people_are_not_flagged() -> None:
    family = [rec(i, payout="w", household="hh") for i in range(4)]
    pair = [rec(10 + i, payout="p") for i in range(2)]
    assert D.detect_shared_payout(family + pair).status == "clear"


def test_shared_payout_abstains_without_payout_data() -> None:
    result = D.detect_shared_payout([rec(1, payout=None), rec(2, payout=None)])
    assert result.status == "abstained" and result.abstention is not None and result.abstention.abstained
    assert result.abstention.route != "auto" and result.abstention.reasons == ["no_payout_data"] and not result.findings


# --- application spike ------------------------------------------------------------------------------------


def quiet_month(per_day: int = 3, days: int = 14, district: str = "Dadu") -> list[D.AppRecord]:
    return [rec(d * 100 + k, at=T0 + timedelta(days=d, minutes=k), district=district) for d in range(days) for k in range(per_day)]


def test_a_district_spike_against_its_baseline_is_flagged() -> None:
    rows = quiet_month() + [rec(5000 + k, at=T0 + timedelta(days=14, minutes=k)) for k in range(20)]
    result = D.detect_application_spike(rows, today=date(2026, 11, 15))
    assert result.status == "flagged"
    f = result.findings[0]
    assert f.evidence["applications"] == 20 and f.evidence["usual_per_day"] == 3.0 and f.evidence["robust_z"] >= 3.5
    assert f.pattern_key == "application_spike:Dadu:2026-11-15" and len(f.evidence_ids) == 20


def test_a_normal_busy_day_is_not_a_spike() -> None:
    rows = quiet_month() + [rec(5000 + k, at=T0 + timedelta(days=14, minutes=k)) for k in range(5)]
    assert D.detect_application_spike(rows, today=date(2026, 11, 15)).status == "clear"


def test_spike_abstains_on_thin_baseline_instead_of_guessing() -> None:
    rows = [rec(k, at=T0 + timedelta(days=2, minutes=k)) for k in range(30)]  # 30 in one day, but only 2 days of history
    result = D.detect_application_spike(rows, today=date(2026, 11, 3))
    assert result.status == "abstained" and result.abstention is not None and result.abstention.reasons == ["thin_baseline"]
    assert result.data_points["needed_days"] == 7 and not result.findings
    assert D.detect_application_spike([], today=date(2026, 11, 3)).status == "abstained"


def test_a_quiet_district_does_not_flag_on_a_small_jump() -> None:
    rows = [rec(i, at=T0 + timedelta(days=i * 2)) for i in range(7)]
    rows += [rec(900 + k, at=T0 + timedelta(days=15)) for k in range(3)]  # 3 applications against a baseline of about 0: below min_count
    assert D.detect_application_spike(rows, today=date(2026, 11, 16)).status == "clear"


def test_eval_days_looks_back_over_earlier_days() -> None:
    rows = quiet_month(days=20) + [rec(7000 + k, at=T0 + timedelta(days=12, hours=1, minutes=k)) for k in range(25)]
    now_only = D.detect_application_spike(rows, today=date(2026, 11, 20))
    assert now_only.status == "clear"
    back = D.detect_application_spike(rows, today=date(2026, 11, 20), eval_days=10)
    assert [f.evidence["day"] for f in back.findings] == ["2026-11-13"]


# --- helper burst -----------------------------------------------------------------------------------------


def helper_rows(helper: str, count: int, *, start: int, gap_minutes: int, offset: int = 0) -> list[D.AppRecord]:
    return [rec(offset + i, at=T0 + timedelta(minutes=start + i * gap_minutes), helper_id=helper) for i in range(count)]


def test_a_helper_submitting_for_twelve_families_in_forty_minutes_is_flagged_once() -> None:
    rows = helper_rows("h1", 12, start=0, gap_minutes=3) + helper_rows("h2", 12, start=0, gap_minutes=300, offset=100)
    result = D.detect_helper_burst(rows)
    assert result.status == "flagged" and len(result.findings) == 1
    f = result.findings[0]
    assert f.evidence["families"] == 12 and f.evidence["minutes"] == 33 and len(f.evidence_ids) == 12


def test_a_long_burst_is_one_flag_not_one_per_window() -> None:
    rows = helper_rows("h1", 40, start=0, gap_minutes=2)  # 80 minutes of steady work: two windows, one day, one key
    result = D.detect_helper_burst(rows)
    assert len(result.findings) == 1 and result.findings[0].evidence["families"] == 40


def test_helper_burst_abstains_when_there_is_no_helper_data() -> None:
    result = D.detect_helper_burst([rec(i) for i in range(30)])
    assert result.status == "abstained" and result.abstention is not None and result.abstention.reasons == ["thin_helper_data"]


# --- repeated identity ------------------------------------------------------------------------------------


def test_one_id_on_two_people_and_one_id_tried_many_times_are_flagged_but_one_retry_is_not() -> None:
    rows = [rec(1, national_id="x"), rec(2, national_id="x"),
            rec(3, national_id="y", person_id="same", status="rejected"), rec(4, national_id="y", person_id="same", status="rejected"),
            rec(5, national_id="y", person_id="same"),
            rec(6, national_id="z", person_id="again", status="withdrawn"), rec(7, national_id="z", person_id="again")]  # fmt: skip
    result = D.detect_repeated_identity(rows)
    by_code = {f.summary_code: f for f in result.findings}
    assert set(by_code) == {"identity_on_several_people", "identity_many_attempts"}
    assert by_code["identity_on_several_people"].priority < by_code["identity_many_attempts"].priority
    assert by_code["identity_many_attempts"].evidence["refused"] == 2 and not any("z" == f.evidence["id"] for f in result.findings)


def test_repeated_identity_abstains_without_ids() -> None:
    assert D.detect_repeated_identity([rec(1, national_id=None)]).status == "abstained"


# --- determinism, properties and the evaluation -----------------------------------------------------------


def test_detectors_are_deterministic_and_order_independent() -> None:
    world = build_anomaly_world()
    today = world.today.date()
    a = [r.model_dump(mode="json") for r in D.run_all(world.records, today=today)]
    b = [r.model_dump(mode="json") for r in D.run_all(list(reversed(world.records)), today=today)]
    assert a == b


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.integers(0, 6), st.integers(0, 4), st.integers(0, 6)), max_size=60))
def test_findings_are_always_human_routed_and_ids_point_at_real_records(items: list[tuple[int, int, int]]) -> None:
    rows = [rec(i, person_id=f"p{p}", payout=f"w{w}", national_id=f"n{n}", household=f"h{p % 3}") for i, (p, w, n) in enumerate(items)]
    known = {r.app_id for r in rows}
    for result in D.run_all(rows, today=date(2026, 11, 2)):
        assert (result.status == "abstained") == (result.abstention is not None)
        for f in result.findings:
            assert f.decision.route == "human" and 0.0 <= f.confidence <= 1.0 and set(f.evidence_ids) <= known and f.evidence_ids


@settings(max_examples=40, deadline=None)
@given(st.integers(3, 12), st.integers(3, 12))
def test_a_bigger_ring_is_never_less_confident(small: int, extra: int) -> None:
    def confidence(n: int) -> float:
        return D.detect_shared_payout([rec(i, payout="w") for i in range(n)]).findings[0].confidence

    assert confidence(small + extra) >= confidence(small)


def test_evaluation_is_reproducible_and_meets_the_stated_floor() -> None:
    first, again = run_world(20261201), run_world(20261201)
    assert first == again
    rows = {r["detector"]: r for r in first["detectors"]}
    assert all(r["recall"] >= 0.8 for r in rows.values()) and rows["helper_burst"]["precision"] == 1.0
    assert first["thin_data_check"] == {"status": "abstained", "reason": "thin_baseline"}
    pooled = summarise([first])
    assert set(pooled) == set(D.DETECTORS)


# --- dedupe -----------------------------------------------------------------------------------------------


def finding(key: str = "shared_payout:k", ids: tuple[str, ...] = ("a1", "a2", "a3")) -> D.Finding:
    return D._flag("shared_payout", key, 0.7, ["payout_account_shared"], evidence={}, ids=ids, priority=30)


def test_one_pattern_opens_one_case_and_the_same_run_twice_changes_nothing() -> None:
    f = finding()
    assert [a.kind for a in plan_cases([f, f], [])] == ["open"]
    held = ExistingCase("c1", f.pattern_key, True, frozenset(f.evidence_ids))
    assert [a.kind for a in plan_cases([f], [held])] == ["unchanged"]


def test_a_pattern_that_grew_refreshes_its_active_case_and_a_reviewed_one_is_not_reopened() -> None:
    grown = finding(ids=("a1", "a2", "a3", "a4"))
    active = ExistingCase("c1", grown.pattern_key, True, frozenset({"a1", "a2", "a3"}))
    (action,) = plan_cases([grown], [active])
    assert action.kind == "refresh" and action.case_id == "c1" and action.new_ids == ("a4",)
    resolved = ExistingCase("c2", grown.pattern_key, False, frozenset({"a1", "a2", "a3"}))
    assert plan_cases([finding()], [resolved])[0].kind == "suppress"
    again = plan_cases([grown], [resolved])[0]
    assert again.kind == "open" and again.new_ids == ("a4",)
