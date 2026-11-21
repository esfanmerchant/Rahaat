"""Threshold analysis (B7): the slider's numbers are the engine's numbers. DB-free."""

from __future__ import annotations

import time

from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts.decision import CostMatrix
from app.contracts.engine import RuleSetSnapshot
from app.modules.decision.engine import ROUTES, assess, decide, route_for, silent_guess_violations
from app.modules.decision.model import get_model, training_world
from app.modules.evals import decision_eval as E
from app.seed import RULES_V1

SNAPSHOT = RuleSetSnapshot(rule_version_id="v1", version_no=1, dsl=RULES_V1)
costs_strategy = st.builds(
    CostMatrix,
    wrong_approve=st.floats(5, 500), wrong_reject=st.floats(2, 200), human_review=st.floats(0.5, 40),
    ask_proof=st.floats(0, 10), delay_per_day=st.floats(0, 3),
)  # fmt: skip


def _scores() -> list[E.LabelledScore]:
    return E.cached_scores(RULES_V1, get_model())


def test_heldout_world_is_big_labelled_and_not_the_training_people() -> None:
    world = E.heldout_world()
    scores = _scores()
    assert len(scores) >= 1000 and len(world.cases) == len(scores)
    training_people = {(p.full_name, p.dob) for p in training_world().persons}
    shared = sum(1 for p in world.persons if (p.full_name, p.dob) in training_people)
    assert shared / len(world.persons) < 0.02, "the held-out world must be other people"
    assert {s.truth_class for s in scores} == set(E.TRUTH_CLASSES)
    info = E.dataset_info(world, scores)
    assert info["cases"] == len(scores) and info["held_out"] is True


@settings(max_examples=25, deadline=None)
@given(costs_strategy)
def test_slider_routing_is_exactly_what_decide_does(costs: CostMatrix) -> None:
    """route_for() on cached assessments equals a full decide() for any cost matrix, on a slice of cases."""
    model = get_model()
    for case in E.heldout_world().cases[::37]:
        pricing = assess(case.inp, RULES_V1, model).pricing
        action, expected = route_for(pricing, costs)
        result = decide(case.inp, SNAPSHOT, costs, model)
        assert ROUTES[action] == (result.route, result.outcome), case.case_id
        assert expected == result.expected_costs
        assert not silent_guess_violations(result)


@settings(max_examples=40, deadline=None)
@given(costs_strategy)
def test_slider_thresholds_follow_the_cost_matrix(costs: CostMatrix) -> None:
    report = E.analyse(_scores(), costs)
    human = costs.human_review + costs.delay_per_day * 1.0
    assert report["thresholds"]["approve"] == round(max(0.0, 1 - human / costs.wrong_approve), 4)
    assert report["thresholds"]["reject"] == round(max(0.0, 1 - human / costs.wrong_reject), 4)
    point = report["operating_point"]
    assert point["approved"] + point["rejected"] + point["needs_proof"] + point["needs_human"] == point["n"]
    assert sum(sum(row.values()) for row in report["confusion"]["counts"].values()) == point["n"]
    assert point["false_approvals"] <= point["approved"] and point["false_rejections"] <= point["rejected"]
    assert point["silent_guesses"] == 0


def test_a_dearer_wrong_approval_never_approves_more() -> None:
    scores = _scores()
    approvals = [E.analyse(scores, CostMatrix(wrong_approve=c))["operating_point"]["approved"] for c in (20, 50, 100, 300, 1000)]
    assert approvals == sorted(approvals, reverse=True)


def test_curves_and_calibration_are_reported() -> None:
    report = E.analyse(_scores(), CostMatrix())
    print(f"\nB7 held-out: {report['operating_point']}\n best={report['best_threshold']} roc_auc={report['roc_auc']} "
          f"ap={report['average_precision']} ece={report['reliability']['ece']}\n{report['explanation']}")  # fmt: skip
    curve = report["cost_curve"]
    assert [row["threshold"] for row in curve] == sorted(row["threshold"] for row in curve)
    approvals = [row["approvals"] for row in curve]
    assert approvals == sorted(approvals, reverse=True), "a higher threshold never approves more"
    assert any(abs(row["threshold"] - 0.968) < 1e-9 for row in curve)
    roc = report["roc"]
    assert roc and all(0 <= p["tpr"] <= 1 and 0 <= p["fpr"] <= 1 for p in roc)
    assert [p["tpr"] for p in roc] == sorted(p["tpr"] for p in roc), "ROC points go from strict to lenient"
    assert report["pr"] and report["roc_auc"] is not None and report["average_precision"] is not None
    assert len(report["reliability"]["bins"]) == 10 and report["reliability"]["ece"] < 0.08
    assert "0.968" in report["explanation"] and str(report["operating_point"]["n"]) in report["explanation"]


def test_analysis_is_fast_enough_for_a_slider() -> None:
    scores = _scores()
    E.analyse(scores, CostMatrix())  # warm the cost-independent parts
    timings = []
    for c in (40, 100, 250):
        started = time.perf_counter()
        E.analyse(scores, CostMatrix(wrong_approve=c))
        timings.append(time.perf_counter() - started)
    print(f"\nanalyse timings ms: {[round(t * 1000, 1) for t in timings]}")
    assert min(timings) < 0.3


def test_realised_costs() -> None:
    costs = CostMatrix()
    good = next(s for s in _scores() if s.ok)
    bad = next(s for s in _scores() if not s.eligible and s.genuine)
    assert E.realised_cost(good, "approve", costs) == 0.0 and E.realised_cost(bad, "approve", costs) == 100.0
    assert E.realised_cost(good, "reject", costs) == 30.0 and E.realised_cost(bad, "reject", costs) == 0.0
    assert E.realised_cost(good, "human", costs) == costs.human_cost(1.0)
    assert E.realised_cost(bad, "ask_proof", costs) == costs.ask_proof + costs.delay_per_day + costs.human_cost(1.0)
