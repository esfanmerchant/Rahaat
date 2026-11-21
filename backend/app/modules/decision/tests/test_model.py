"""The evidence model and the synthetic world: determinism, family split, calibration on held-out data."""

from __future__ import annotations

import collections

import numpy as np

from app.modules.decision import model as M
from app.modules.decision.engine import decide, silent_guess_violations
from app.modules.decision.model import get_model, split_cases, training_world
from app.modules.evals import metrics
from app.synth.world import build_world, default_world, family_split


def test_world_is_reproducible_and_big_enough() -> None:
    small_a, small_b = build_world(households=80), build_world(households=80)
    assert [c.inp.model_dump() for c in small_a.cases] == [c.inp.model_dump() for c in small_b.cases]
    assert [c.truth for c in small_a.cases] == [c.truth for c in small_b.cases]
    a = default_world()
    assert len(a.persons) >= 1200
    assert len(a.cases) >= 1000
    tags = collections.Counter(t for c in a.cases for t in c.tags)
    for adversarial in ("forged_card", "impersonation", "double_dip", "ring", "income_misreport", "registry_income_stale",
                        "identity_partial", "card_blurry", "registry_down"):  # fmt: skip
        assert tags[adversarial] >= 10, adversarial
    assert build_world(seed=7, households=20).cases[0].inp != small_a.cases[0].inp


def test_mock_identifiers_only() -> None:
    from app.core.mockdata import is_mock_phone, mock_id_valid

    world = default_world()
    assert all(mock_id_valid(p.national_id) and is_mock_phone(p.phone) for p in world.persons)
    assert all(mock_id_valid(c.inp.form.national_id.value or "") for c in world.cases)


def test_split_is_by_family_so_no_identity_leaks_into_test() -> None:
    parts = split_cases(training_world())
    families = {name: {c.family_id for c in cases} for name, cases in parts.items()}
    assert not families["train"] & families["test"]
    assert not families["calibration"] & families["test"]
    assert not families["train"] & families["calibration"]
    assert family_split("P00001") == family_split("P00001")


def test_training_is_deterministic_and_versioned() -> None:
    small = build_world(households=150)
    first, again = M.train(small), M.train(build_world(households=150))
    assert again.version == first.version and again.data_hash == first.data_hash and again.eligible == first.eligible
    assert first.version.startswith("evidence-lr-") and len(first.version) == len("evidence-lr-") + 12
    assert M.train(small, params={**M.TRAIN_PARAMS, "C": 0.1}).version != first.version
    assert M.train(build_world(seed=5, households=150)).version != first.version
    assert get_model().version != first.version


def test_calibration_on_held_out_families() -> None:
    """Reported numbers, measured on the test split. Bounds are loose on purpose; the values are printed."""
    model = get_model()
    test = model.metrics["test"]
    for target in ("p_eligible", "p_genuine", "p_ok"):
        summary = test[target]
        print(f"\n{target}: n={summary['n']} ECE={summary['ece']} Brier={summary['brier']} AUC={summary['auc']}")
        for row in summary["reliability"]:
            print(f"  [{row['low']:.1f}, {row['high']:.1f})  n={row['count']:4d}  predicted={row['mean_predicted']}  observed={row['observed_rate']}")
        assert len(summary["reliability"]) == 10
        assert sum(r["count"] for r in summary["reliability"]) == summary["n"]
        assert summary["ece"] < 0.06, target
        assert summary["auc"] > 0.9, target
    assert model.metrics["sizes"]["test"] >= 300


def test_routing_quality_on_held_out_cases_at_default_costs() -> None:
    """False approvals, false rejections and unnecessary handoffs, with their cost. Printed for the report."""
    from app.contracts.decision import CostMatrix
    from app.contracts.engine import RuleSetSnapshot
    from app.seed import RULES_V1

    model = get_model()
    costs = CostMatrix()
    test = split_cases(training_world())["test"]
    counts: collections.Counter[str] = collections.Counter()
    for case in test:
        dsl = {**RULES_V1, "params": {**RULES_V1["params"], "income_cap": case.income_cap}}
        result = decide(case.inp, RuleSetSnapshot(rule_version_id="v1", version_no=1, dsl=dsl), costs, model)
        counts[result.route] += 1
        counts["silent_guess"] += bool(silent_guess_violations(result))
        if result.outcome == "approved" and not case.truth.ok:
            counts["false_approve"] += 1
        if result.outcome == "rejected" and case.truth.eligible:
            counts["false_reject"] += 1
        if result.route != "auto" and case.truth.ok:
            counts["unnecessary_handoff"] += 1
    n = len(test)
    realised = (counts["false_approve"] * costs.wrong_approve + counts["false_reject"] * costs.wrong_reject
                + counts["human"] * costs.human_cost(1.0) + counts["ask_more"] * (costs.ask_proof + costs.delay_per_day))  # fmt: skip
    print(f"\nheld-out n={n} routes={dict(counts)} auto_rate={counts['auto'] / n:.3f} "
          f"cost_per_case={realised / n:.3f} (all-human baseline {costs.human_cost(1.0):.3f})")  # fmt: skip
    assert counts["silent_guess"] == 0
    assert counts["false_approve"] <= 0.02 * n
    assert counts["false_reject"] <= 0.02 * n
    assert realised / n < costs.human_cost(1.0)  # cheaper than sending everything to a person


def test_logistic_regression_reaches_the_optimum_and_isotonic_is_monotone() -> None:
    """Our IRLS solution has zero gradient of the penalised loss (what scikit-learn's lbfgs also solves);
    the PAV map is non-decreasing and reproduces block means. Checked without importing scikit-learn (slow)."""
    rng = np.random.default_rng(3)
    x = rng.normal(size=(400, 5))
    y = (x @ np.array([1.5, -2.0, 0.5, 0.0, 1.0]) + rng.normal(size=400) > 0).astype(float)
    w = M.fit_logistic(x, y, 2.0)
    xb = np.hstack([np.ones((400, 1)), x])
    p = 1 / (1 + np.exp(-(xb @ w)))
    reg = np.full(6, 2.0)
    reg[0] = 0.0
    assert np.max(np.abs(xb.T @ (p - y) + reg * w)) < 1e-6

    raw = list(rng.uniform(size=300))
    labels = [float(v) for v in (rng.uniform(size=300) < np.asarray(raw))]
    xs, ys = M.fit_isotonic(raw, labels)
    assert xs == sorted(xs) and ys == sorted(ys)
    assert M.fit_isotonic([0.1, 0.2, 0.3, 0.4], [1.0, 0.0, 1.0, 1.0]) == ([0.1, 0.2, 0.3, 0.4], [0.5, 0.5, 1.0, 1.0])
    assert M._interp(0.25, [0.1, 0.2, 0.3], [0.0, 0.5, 1.0]) == 0.75


def test_metrics() -> None:
    assert metrics.ece([0.1, 0.9], [0, 1]) == 0.1
    assert metrics.auc([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == 0.75
    assert metrics.brier([1.0, 0.0], [1, 0]) == 0.0
