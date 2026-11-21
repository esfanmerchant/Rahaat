"""decide(): golden cases, cost math, the silent-guess invariant, reject safety and replay. DB-free."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.contracts.application import FieldValue
from app.contracts.decision import CostMatrix
from app.contracts.engine import (
    AnomalyEvidence,
    DecisionInput,
    DuplicateEvidence,
    EvidenceProbabilities,
    IdentityCheck,
    RuleSetSnapshot,
)
from app.modules.decision import engine
from app.modules.decision.engine import decide, silent_guess_violations
from app.modules.decision.model import get_model
from app.seed import RULES_V1
from app.synth import golden
from app.synth.golden import GOLDEN, base_input, card, form, income_proof, registry

RULES = RuleSetSnapshot(rule_version_id="00000000-0000-4000-8000-0000000000v1".replace("v1", "01"), version_no=1, dsl=RULES_V1)


class FixedModel:
    """A stand-in model that says whatever the test wants. The engine must stay safe whatever it says."""

    def __init__(self, p_eligible: float, p_genuine: float, version: str = "fixed-test") -> None:
        self.p = EvidenceProbabilities(p_eligible=p_eligible, p_genuine=p_genuine)
        self.version = version

    def predict(self, features: dict[str, float]) -> EvidenceProbabilities:
        return self.p


def rules_with(**params: Any) -> RuleSetSnapshot:
    dsl = copy.deepcopy(RULES_V1)
    dsl["params"].update(params)
    return RuleSetSnapshot(rule_version_id="rules-test", version_no=9, dsl=dsl)


# --- golden cases with the real model -------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_case_routes_as_expected(name: str) -> None:
    build, routes, outcomes = GOLDEN[name]
    result = decide(build(), RULES, CostMatrix(), get_model())
    assert result.route in routes, (name, result.route, result.reasons)
    if outcomes is not None:
        assert result.outcome in outcomes, (name, result.outcome, result.reasons)
    assert silent_guess_violations(result) == []
    assert "invariant_fallback" not in result.reasons
    if result.route != "auto":
        assert result.handoff is not None and result.handoff.hypotheses and len(result.handoff.hypotheses) == 2
    if result.route == "ask_more":
        assert result.ask_proof in ("income_proof", "rahat_id") and result.handoff and result.handoff.resolving_proof == result.ask_proof


def test_silent_guess_count_is_zero_over_the_golden_set() -> None:
    model = get_model()
    results = [decide(build(), RULES, CostMatrix(), model) for build, _, _ in GOLDEN.values()]
    assert sum(1 for r in results if silent_guess_violations(r)) == 0
    assert sum(1 for r in results if "invariant_fallback" in r.reasons) == 0


def test_demo_personas() -> None:
    model = get_model()
    approved = decide(base_input(), RULES, CostMatrix(), model)
    assert (approved.route, approved.outcome, approved.payment_pkr) == ("auto", "approved", 12000)
    missing_income = decide(base_input(registry=registry(verified_income_pkr=None, income_as_of=None)), RULES, CostMatrix(), model)
    assert missing_income.route == "ask_more" and missing_income.ask_proof == "income_proof"
    assert missing_income.explanation.reason_codes == ["ask_income_proof"]
    forged = decide(base_input(documents=[card(signed=False)]), RULES, CostMatrix(), model)
    assert forged.route == "human" and "document_suspect" in forged.guards
    assert forged.explanation.reason_codes == ["human_check"]  # the citizen is never told why


def test_each_guard_alone_forces_a_human_even_with_a_perfect_score() -> None:
    model = FixedModel(0.999, 0.999)
    cases = {
        "consent_missing": base_input(consent_ok=False),
        "document_suspect": base_input(documents=[card(signed=False)]),
        "card_id_mismatch": base_input(documents=[card(national_id=golden.OTHER_ID)]),
        "identity_mismatch": base_input(identity=IdentityCheck(status="mismatch", name_score=0.2)),
        "possible_duplicate": base_input(duplicate=DuplicateEvidence(band="possible", score=0.7)),
        "duplicate_record": base_input(duplicate=DuplicateEvidence(band="same", score=0.98)),
        "anomaly_flag": base_input(anomaly=AnomalyEvidence(score=0.95, flagged=True)),
        "registry_unavailable": base_input(registry_status="unavailable", registry=None),
        "verified_sources_disagree": base_input(documents=[card(), income_proof(45_000)]),
    }
    for guard, inp in cases.items():
        result = decide(inp, RULES, CostMatrix(), model)
        assert result.route == "human" and guard in result.guards, guard
        assert result.reasons[0].startswith("guard."), guard


def test_invalid_rule_version_never_decides() -> None:
    broken = RuleSetSnapshot(rule_version_id="bad", version_no=2, dsl={"all": [{"id": "x", "hard": True, "expr": {"eval": ["1"]}}]})
    result = decide(base_input(), broken, CostMatrix(), FixedModel(0.999, 0.999))
    assert result.route == "human" and result.guards == ["rules_invalid"]


# --- cost math --------------------------------------------------------------------------------------------

probability = st.floats(min_value=0.0, max_value=1.0, allow_nan=False).map(lambda p: round(p, 4))
cost_matrices = st.builds(
    CostMatrix,
    wrong_approve=st.floats(10, 500),
    wrong_reject=st.floats(5, 200),
    human_review=st.floats(0.5, 20),
    ask_proof=st.floats(0, 5),
    delay_per_day=st.floats(0, 2),
)


@settings(max_examples=200, deadline=None)
@given(cost_matrices, st.floats(0, 10))
def test_reported_thresholds_come_from_the_cost_matrix(costs: CostMatrix, queue_days: float) -> None:
    result = decide(base_input(queue_days=round(queue_days, 2)), RULES, costs, FixedModel(0.5, 0.5))
    qd = round(queue_days, 2)
    assert result.thresholds["approve"] == round(costs.approve_threshold(qd), 4)
    assert result.thresholds["reject"] == round(costs.reject_threshold(qd), 4)
    assert result.expected_costs["human"] == round(costs.human_cost(qd), 4)


@settings(max_examples=300, deadline=None)
@given(probability, cost_matrices)
def test_approve_exactly_when_p_ok_clears_the_derived_threshold(p_ok: float, costs: CostMatrix) -> None:
    """On a fully verified case, approve iff (1 - p_ok) * C_wrong_approve < human cost. Ties go to the human."""
    result = decide(base_input(), RULES, costs, FixedModel(p_ok, 1.0))
    approve_cost = round((1 - result.p_ok) * costs.wrong_approve, 4)
    human_cost = round(costs.human_cost(1.0), 4)
    assert result.expected_costs["approve"] == approve_cost
    if approve_cost < human_cost:
        assert (result.route, result.outcome) == ("auto", "approved")
        assert result.p_ok >= result.thresholds["approve"] - 1e-4
    else:
        assert result.route == "human"
        assert result.p_ok <= result.thresholds["approve"] + 1e-4


@settings(max_examples=150, deadline=None)
@given(probability, probability, cost_matrices)
def test_more_confidence_never_makes_approval_less_likely(p1: float, p2: float, costs: CostMatrix) -> None:
    low, high = sorted((p1, p2))
    first = decide(base_input(), RULES, costs, FixedModel(low, 1.0))
    second = decide(base_input(), RULES, costs, FixedModel(high, 1.0))
    assert first.expected_costs["approve"] >= second.expected_costs["approve"]
    if first.outcome == "approved":
        assert second.outcome == "approved"


@settings(max_examples=150, deadline=None)
@given(probability, cost_matrices)
def test_reject_cost_uses_p_ineligible(p_eligible: float, costs: CostMatrix) -> None:
    result = decide(base_input(registry=registry(verified_income_pkr=60_000)), RULES, costs, FixedModel(p_eligible, 1.0))
    assert result.expected_costs["reject"] == round(result.p_eligible * costs.wrong_reject, 4)
    if result.outcome == "rejected":
        assert round(1 - result.p_eligible, 4) >= result.thresholds["reject"] - 1e-4


def test_ask_cost_formula() -> None:
    costs = CostMatrix()
    inp = base_input(registry=registry(verified_income_pkr=None, income_as_of=None))
    result = decide(inp, RULES, costs, FixedModel(0.95, 1.0))
    # p_ok = 0.95; with the proof the fixed model still says 0.95, so q = 1 and the proof only adds cost.
    after = min(round((1 - 0.95) * costs.wrong_approve, 4), costs.human_cost(1.0))
    expected = round(costs.ask_proof + costs.delay_per_day * 1.0 + after, 4)
    assert result.expected_costs["ask_proof"] == expected
    assert result.route == "human"  # 1.2 + 3.2 > 3.2


# --- reject safety ----------------------------------------------------------------------------------------

identity_states = st.sampled_from(["match", "partial", "mismatch", "not_found", "unavailable", None])
card_states = st.sampled_from(["signed", "tampered", "none", "blurry", "other_id", "missing"])
registry_states = st.sampled_from(["found", "not_found", "unavailable"])
income_states = st.sampled_from(["fresh_low", "fresh_high", "stale_low", "stale_high", "missing"])
aid_states = st.sampled_from(["reg_true", "reg_false", "decl_true", "decl_false", "unknown"])
bands = st.sampled_from([None, "under_15k", "15k_30k", "30k_50k", "over_50k"])


def build_case(identity: str | None, card_state: str, reg_state: str, income: str, aid: str, band: str | None, proof: int | None,
               dup: str | None, anomaly: bool, consent: bool) -> DecisionInput:  # fmt: skip
    docs = {
        "signed": [card()], "tampered": [card(signed=False)], "none": [card(signed=None)], "blurry": [card(signed=None, quality="blurry")],
        "other_id": [card(national_id=golden.OTHER_ID)], "missing": [],
    }[card_state]  # fmt: skip
    if proof is not None:
        docs = [*docs, income_proof(proof)]
    income_value, as_of = {
        "fresh_low": (18_000, "2026-06-01"), "fresh_high": (55_000, "2026-06-01"), "stale_low": (18_000, "2023-01-01"),
        "stale_high": (55_000, "2023-01-01"), "missing": (None, None),
    }[income]  # fmt: skip
    reg_aid = {"reg_true": True, "reg_false": False}.get(aid)
    declared_aid = {"decl_true": True, "decl_false": False}.get(aid)
    record = registry(verified_income_pkr=income_value, income_as_of=as_of, receives_other_aid=reg_aid)
    return base_input(
        identity=IdentityCheck(status=identity, name_score=0.9) if identity else None, documents=docs, registry_status=reg_state,
        registry=record if reg_state == "found" else None,
        form=form(receives_other_aid=FieldValue[bool](value=declared_aid, confidence=1.0),
                  income_band=FieldValue(value=band, confidence=1.0)),
        duplicate=DuplicateEvidence(band=dup, score=0.5) if dup else None, anomaly=AnomalyEvidence(score=0.9 if anomaly else 0.1, flagged=anomaly),
        consent_ok=consent,
    )  # fmt: skip


evidence = st.builds(
    build_case, identity_states, card_states, registry_states, income_states, aid_states, bands,
    st.one_of(st.none(), st.sampled_from([12_000, 29_000, 31_000, 70_000])), st.sampled_from([None, "distinct", "possible", "same"]),
    st.booleans(), st.booleans(),
)  # fmt: skip


@settings(max_examples=400, deadline=None)
@given(evidence, probability, probability, cost_matrices)
def test_invariants_hold_for_any_evidence_and_any_model(inp: DecisionInput, p_e: float, p_g: float, costs: CostMatrix) -> None:
    result = decide(inp, RULES, costs, FixedModel(p_e, p_g))
    assert silent_guess_violations(result) == []
    assert "invariant_fallback" not in result.reasons, result.reasons
    if result.guards:
        assert result.route == "human"
    if result.route == "auto":
        hard = [t for t in result.rule_trace if t.hard]
        if result.outcome == "approved":
            assert all(t.result == "pass" and t.verified_inputs for t in hard)
        else:
            assert any(t.result == "fail" and t.verified_inputs for t in hard)
            assert result.facts["identity_verified"].value is True and result.facts["identity_verified"].verified
    else:
        assert result.handoff is not None
    assert (result.route == "ask_more") == (result.ask_proof is not None)


@settings(max_examples=300, deadline=None)
@given(identity_states, card_states, bands, aid_states.filter(lambda a: a.startswith("decl") or a == "unknown"), probability, probability)
def test_reject_is_impossible_on_unverified_facts(identity: str | None, card_state: str, band: str | None, aid: str, p_e: float,
                                                  p_g: float) -> None:  # fmt: skip
    """No registry income, no signed proof, aid only declared: nothing verified can fail, so nothing is rejected."""
    inp = build_case(identity, card_state, "found", "missing", aid, band, None, None, False, True)
    result = decide(inp, RULES, CostMatrix(), FixedModel(p_e, p_g))
    assert result.outcome != "rejected"
    assert "reject" not in result.expected_costs


def test_stale_registry_income_over_cap_is_not_a_rejection() -> None:
    inp = base_input(registry=registry(verified_income_pkr=90_000, income_as_of="2022-01-01"))
    assert decide(inp, RULES, CostMatrix(), FixedModel(0.0, 1.0)).outcome != "rejected"


# --- determinism and replay -----------------------------------------------------------------------------


def test_identical_input_replays_to_identical_result_hash() -> None:
    model = get_model()
    for build, _, _ in GOLDEN.values():
        inp = build()
        first = decide(inp, RULES, CostMatrix(), model)
        snapshot = inp.model_dump(mode="json")  # what the decisions row stores
        second = decide(DecisionInput.model_validate(snapshot), RULES, CostMatrix(), model)
        assert first.result_hash == second.result_hash and first.input_hash == second.input_hash
        assert engine.stable_json(first) == engine.stable_json(second)


def test_hash_changes_when_anything_that_matters_changes() -> None:
    model = get_model()
    base = decide(base_input(), RULES, CostMatrix(), model)
    assert decide(base_input(queue_days=2.0), RULES, CostMatrix(), model).result_hash != base.result_hash
    assert decide(base_input(), RULES, CostMatrix(wrong_approve=150), model).result_hash != base.result_hash
    assert decide(base_input(), rules_with(income_cap=25_000), CostMatrix(), model).result_hash != base.result_hash
    assert decide(base_input(), RULES, CostMatrix(), FixedModel(0.999, 0.999, "other")).result_hash != base.result_hash


def test_engine_reads_no_clock_or_random_source() -> None:
    import ast
    import inspect

    from app.modules.decision import explain, facts, features

    for module in (engine, facts, features, explain):
        tree = ast.parse(inspect.getsource(module))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom) for a in n.names}
        modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not ({"random", "uuid4", "now", "utcnow", "time", "perf_counter", "today"} & (names | imported)), module.__name__
        assert not ({"random", "time", "app.core.db", "sqlalchemy"} & modules), module.__name__


def test_rule_change_changes_the_outcome_of_the_same_input() -> None:
    model = get_model()
    inp = base_input(registry=registry(verified_income_pkr=25_000))
    v1 = decide(inp, RULES, CostMatrix(), model)
    v2 = decide(inp, rules_with(income_cap=20_000), CostMatrix(), model)
    assert v1.outcome == "approved" and v2.outcome != "approved"
    assert {t.rule_id: t.result for t in v2.rule_trace}["income_cap"] == "fail"
