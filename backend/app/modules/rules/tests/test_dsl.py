"""Rule DSL: validation, three-valued evaluation and the trace. DB-free."""

from __future__ import annotations

import copy
import itertools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts.engine import Fact
from app.modules.rules import dsl
from app.modules.rules.dsl import UNKNOWN, evaluate_expr, evaluate_rules, validate
from app.seed import RULES_V1

BOOL_VARS = ("identity_verified", "receives_other_aid", "is_widow", "has_disability")


def fact(value: Any, *, verified: bool = True, confidence: float = 1.0) -> Fact:
    return Fact(value=value, known=True, verified=verified, confidence=confidence, source="registry" if verified else "form")


def codes(errors: list[dsl.DslError]) -> set[str]:
    return {e.code for e in errors}


# --- validation ----------------------------------------------------------------------------------------


def test_seeded_rule_version_is_valid() -> None:
    assert validate(RULES_V1) == []


def test_unknown_operator_is_rejected_with_a_repairable_message() -> None:
    bad = copy.deepcopy(RULES_V1)
    bad["all"][1]["expr"] = {"eval": ["__import__('os')"]}
    errors = validate(bad)
    assert "unknown_operator" in codes(errors)
    assert errors[0].path == "$.all[1].expr" and "Allowed operators" in errors[0].message


def test_unknown_variable_and_parameter_name_the_known_ones() -> None:
    bad = copy.deepcopy(RULES_V1)
    bad["all"][1]["expr"] = {"<=": [{"var": "income"}, {"param": "cap"}]}
    errors = validate(bad)
    assert {"unknown_variable", "unknown_parameter"} <= codes(errors)
    assert any("verified_income_pkr" in e.message for e in errors)


def test_type_errors_are_caught_before_publishing() -> None:
    bad = copy.deepcopy(RULES_V1)
    bad["all"][1]["expr"] = {"<=": [{"var": "is_widow"}, 3]}
    assert "type" in codes(validate(bad))
    bad["all"][1]["expr"] = {"+": [{"var": "household_size"}, 1]}
    assert "not_boolean" in codes(validate(bad))
    bad["all"][1]["expr"] = {"and": [{"var": "household_size"}]}
    assert "type" in codes(validate(bad))


def test_null_literal_is_refused_so_nobody_can_test_for_a_gap() -> None:
    bad = copy.deepcopy(RULES_V1)
    bad["all"][0]["expr"] = {"==": [{"var": "identity_verified"}, None]}
    assert "null_literal" in codes(validate(bad))


def test_depth_and_node_limits() -> None:
    deep: Any = {"var": "is_widow"}
    for _ in range(dsl.MAX_DEPTH):
        deep = {"not": [deep]}
    assert "too_deep" in codes(validate({"all": [{"id": "r", "hard": False, "expr": deep}]}))
    wide = {"or": [{"var": "is_widow"}] * (dsl.MAX_NODES + 1)}
    assert "too_many_nodes" in codes(validate({"all": [{"id": "r", "hard": False, "expr": wide}]}))


def test_structure_errors() -> None:
    assert codes(validate([])) == {"not_an_object"}
    assert "no_rules" in codes(validate({"all": []}))
    dup = {"all": [{"id": "a", "hard": True, "expr": True}, {"id": "a", "hard": True, "expr": True}]}
    assert "duplicate_id" in codes(validate(dup))
    assert "unknown_key" in codes(validate({**RULES_V1, "code": "print(1)"}))
    assert "out_of_range" in codes(validate({**RULES_V1, "params": {"income_cap": -5}}))
    assert "bad_payment" in codes(validate({**RULES_V1, "payment_pkr": True}))


json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=True) | st.text(max_size=5),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=6), children, max_size=3),
    max_leaves=25,
)


@settings(max_examples=300, deadline=None)
@given(json_values)
def test_validator_never_raises_on_arbitrary_json(value: Any) -> None:
    validate(value)
    validate({"all": [{"id": "r", "hard": True, "expr": value}]})


# --- three-valued evaluation ---------------------------------------------------------------------------


def bool_exprs() -> st.SearchStrategy[Any]:
    leaves = st.sampled_from([{"var": v} for v in BOOL_VARS]) | st.booleans()
    return st.recursive(
        leaves,
        lambda kids: (
            st.builds(lambda xs: {"and": xs}, st.lists(kids, min_size=1, max_size=3))
            | st.builds(lambda xs: {"or": xs}, st.lists(kids, min_size=1, max_size=3))
            | st.builds(lambda x: {"not": [x]}, kids)
        ),
        max_leaves=8,
    )


def reference(expr: Any, env: dict[str, bool]) -> bool:
    """Ordinary two-valued semantics, written independently of the interpreter."""
    if isinstance(expr, bool):
        return expr
    ((op, args),) = expr.items()
    if op == "var":
        return env[args]
    if op == "and":
        return all(reference(a, env) for a in args)
    if op == "or":
        return any(reference(a, env) for a in args)
    return not reference(args[0], env)


partial_envs = st.fixed_dictionaries({v: st.sampled_from([True, False, None]) for v in BOOL_VARS})


def facts_from(env: dict[str, bool | None]) -> dict[str, Fact]:
    return {k: fact(v) if v is not None else Fact() for k, v in env.items()}


@settings(max_examples=400, deadline=None)
@given(bool_exprs(), partial_envs)
def test_a_definite_answer_never_depends_on_an_unknown(expr: Any, env: dict[str, bool | None]) -> None:
    """Soundness: if the result is true or false, every way of filling the unknowns gives that same answer."""
    result = evaluate_expr(expr, facts_from(env), {})
    unknowns = [k for k, v in env.items() if v is None]
    completions = [dict(env, **dict(zip(unknowns, values, strict=True))) for values in itertools.product([True, False], repeat=len(unknowns))]
    answers = {reference(expr, completion) for completion in completions}  # type: ignore[arg-type]
    if result is UNKNOWN:
        assert len(answers) == 2 or len(answers) == 1  # unknown is always allowed (Kleene is not complete)
    else:
        assert answers == {result}


@settings(max_examples=300, deadline=None)
@given(bool_exprs(), st.fixed_dictionaries({v: st.booleans() for v in BOOL_VARS}))
def test_with_everything_known_it_is_ordinary_logic(expr: Any, env: dict[str, bool]) -> None:
    assert evaluate_expr(expr, facts_from(env), {}) == reference(expr, env)  # type: ignore[arg-type]


@settings(max_examples=300, deadline=None)
@given(bool_exprs(), partial_envs, st.sampled_from(BOOL_VARS), st.booleans())
def test_learning_a_value_never_flips_a_definite_answer(expr: Any, env: dict[str, bool | None], name: str, value: bool) -> None:
    before = evaluate_expr(expr, facts_from(env), {})
    after = evaluate_expr(expr, facts_from({**env, name: env[name] if env[name] is not None else value}), {})
    if before is not UNKNOWN:
        assert after == before


@settings(max_examples=200, deadline=None)
@given(st.one_of(st.none(), st.integers(-(10**6), 10**6)), st.integers(0, 10**6))
def test_income_rule_is_unknown_exactly_when_income_is_unknown(income: int | None, cap: int) -> None:
    rules = {**RULES_V1, "params": {"income_cap": cap}}
    facts = {"verified_income_pkr": fact(income) if income is not None else Fact()}
    trace = {e.rule_id: e.trace for e in evaluate_rules(rules, facts)}["income_cap"]
    if income is None:
        assert trace.result == "unknown" and not trace.verified_inputs
    else:
        assert trace.result == ("pass" if income <= cap else "fail")
    assert trace.values_used == {"verified_income_pkr": income, "param.income_cap": cap}


def test_trace_marks_declared_inputs_as_unverified() -> None:
    facts = {
        "identity_verified": fact(True), "verified_income_pkr": fact(18000), "receives_other_aid": fact(False, verified=False, confidence=0.9),
        "is_widow": fact(True), "household_size": fact(3),
    }  # fmt: skip
    trace = {e.rule_id: e for e in evaluate_rules(RULES_V1, facts)}
    assert trace["income_cap"].trace.result == "pass" and trace["income_cap"].trace.verified_inputs
    assert trace["not_already_receiving"].trace.result == "pass" and not trace["not_already_receiving"].trace.verified_inputs
    assert trace["priority_group"].trace.result == "pass"  # true OR unknown is true
    assert trace["income_cap"].settled("pass", 0.9) and not trace["not_already_receiving"].settled("pass", 0.9)


def test_wrong_type_at_run_time_is_unknown_not_an_error() -> None:
    facts = {"household_size": Fact(value="five", known=True, verified=False, confidence=0.5, source="form")}
    rule = {"all": [{"id": "big", "hard": False, "expr": {">=": [{"var": "household_size"}, 5]}}]}
    (e,) = evaluate_rules(rule, facts)
    assert e.trace.result == "unknown" and e.error is not None


def test_arithmetic_and_membership() -> None:
    facts = {"household_size": fact(4), "district": fact("Thatta"), "verified_income_pkr": fact(24000)}
    per_head = {"<=": [{"/": [{"var": "verified_income_pkr"}, {"var": "household_size"}]}, 7000]}
    assert evaluate_expr(per_head, facts, {}) is True
    assert evaluate_expr({"in": [{"var": "district"}, ["Thatta", "Badin"]]}, facts, {}) is True
    assert evaluate_expr({"<=": [{"/": [{"var": "verified_income_pkr"}, 0]}, 1]}, facts, {}) is UNKNOWN


def test_diff_reports_param_and_rule_changes() -> None:
    new = copy.deepcopy(RULES_V1)
    new["params"]["income_cap"] = 25000
    new["all"].pop()
    new["all"].append({"id": "adult", "hard": True, "expr": {">=": [{"var": "age_years"}, 18]}})
    changes = {(c["path"], c["kind"]) for c in dsl.diff(RULES_V1, new)}
    assert ("params.income_cap", "changed") in changes
    assert ("rules.priority_group", "removed") in changes and ("rules.adult", "added") in changes
    assert dsl.diff(RULES_V1, copy.deepcopy(RULES_V1)) == []
