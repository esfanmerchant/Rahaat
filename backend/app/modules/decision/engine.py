"""`decide()`: the cost-based decision (PLAN 6.1). A pure function.

    decide(inp, rules, costs, model) -> DecisionResult

It reads no database, clock or random source: the same input, rule version, cost matrix and model always
give the same result, down to `result_hash`. That is what makes replay, the Digital Twin and evals possible.

How a case is routed:
1. Resolve facts from the evidence (facts.py) and evaluate the rule version with three-valued logic.
2. The model gives p_eligible and p_genuine; p_ok = p_eligible * p_genuine (independence is an assumption).
3. Price every action that is allowed:
   - approve, only when every hard rule passes on verified inputs at or above the confidence floor:
     (1 - p_ok) * C_wrong_approve
   - human, always: C_human_review + C_delay_per_day * queue_days
   - ask for proof, only when exactly one document would settle everything that stands in the way:
     C_ask_proof + C_delay_per_day * proof_days + q * min(approve', human) + (1 - q) * human, where approve' is
     priced with p_ok' recomputed on the input with that proof added, and q = p_ok / p_ok' is the chance the
     proof confirms the claim
   - reject, only when a hard rule fails on verified inputs at or above the floor and identity is verified
     (so the record is really this person's): (1 - p_ineligible) * C_wrong_reject
4. Choose the cheapest; on a tie the safer action wins (human, then ask, then approve, then reject).
5. Hard guards override and send the case to a human.
6. The silent-guess invariant is checked on the result; if it would be broken the case goes to a human.

The thresholds that fall out of the cost matrix (approve when p_ok >= 1 - human / C_wrong_approve, and so on)
are reported for the UI; the routing itself compares costs, so a cost edit moves the thresholds with it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.contracts.common import INCOME_BAND_BOUNDS
from app.contracts.decision import CostMatrix, TypedDecision
from app.contracts.documents import Authenticity, DocumentCheck, QrResult
from app.contracts.engine import DecisionInput, DecisionResult, EvidenceModel, Fact, RuleSetSnapshot
from app.core.audit import canonical_json, hash_payload
from app.modules.decision import explain
from app.modules.decision import facts as F
from app.modules.decision.features import DEFAULT_INCOME_CAP, compute_features
from app.modules.rules.dsl import RuleEvaluation, evaluate_rules, validate

ENGINE_VERSION: Final = "decide-1"
PRECISION: Final = 4
DEFAULT_PROOF_DAYS: Final = 1.0
TIE_ORDER: Final = ("human", "ask_proof", "approve", "reject")
ROUTES: Final[dict[str, tuple[str, str]]] = {
    "approve": ("auto", "approved"),
    "reject": ("auto", "rejected"),
    "ask_proof": ("ask_more", "needs_proof"),
    "human": ("human", "needs_human"),
}
GUARDS: Final = (
    "consent_missing", "document_suspect", "card_id_mismatch", "document_needs_review", "identity_mismatch",
    "possible_duplicate", "duplicate_record", "anomaly_flag", "verified_sources_disagree", "registry_unavailable",
)  # fmt: skip
SOURCE_DISAGREEMENT: Final = 0.25  # two verified incomes further apart than this need a person


def _r(value: float) -> float:
    return round(float(value), PRECISION)


def guards_for(inp: DecisionInput) -> list[str]:
    """Hard guards: any one of these sends the case to a human, whatever the costs say."""
    found: set[str] = set()
    if not inp.consent_ok:
        found.add("consent_missing")
    for doc in inp.documents:
        if doc.authenticity.choice == "suspect" or doc.qr.signature_valid is False:
            found.add("document_suspect")
        elif doc.authenticity.route == "human":
            found.add("document_needs_review")
    if F.signed_card_id_mismatch(inp):
        found.add("card_id_mismatch")
    if inp.identity is not None and inp.identity.status == "mismatch":
        found.add("identity_mismatch")
    if inp.duplicate is not None and inp.duplicate.band == "possible":
        found.add("possible_duplicate")
    if inp.duplicate is not None and inp.duplicate.band == "same":
        found.add("duplicate_record")
    if inp.anomaly is not None and inp.anomaly.flagged:
        found.add("anomaly_flag")
    if inp.registry_status == "unavailable":
        found.add("registry_unavailable")
    reg = F.registry_record(inp)
    proofs = F.signed_income_proofs(inp)
    if reg is not None and reg.verified_income_pkr is not None and proofs:
        base = max(reg.verified_income_pkr, max(proofs), 1)
        if abs(reg.verified_income_pkr - max(proofs)) / base > SOURCE_DISAGREEMENT:
            found.add("verified_sources_disagree")
    return [g for g in GUARDS if g in found]


def counterfactual(inp: DecisionInput, proof: str, params: Mapping[str, Any]) -> DecisionInput:
    """The same input with the requested proof supplied and confirming the claim. Used to price asking for it."""
    if proof == "income_proof":
        cap = F.param(params, "income_cap", DEFAULT_INCOME_CAP)
        band = inp.form.income_band.value
        low, high = INCOME_BAND_BOUNDS.get(band, (0, None)) if band else (0, None)
        top = min(cap, high if high is not None else cap)
        income = int((low + top) / 2) if low < top else int(cap * 0.9)
        doc = DocumentCheck(
            document_id="counterfactual-income_proof", kind="income_proof", quality="ok",
            qr=QrResult(found=True, signature_valid=True, issuer_key_id="counterfactual", payload={"monthly_income_pkr": income}),
            authenticity=TypedDecision[Authenticity](choice="genuine", probabilities={"genuine": 0.95, "suspect": 0.05}, confidence=0.95,
                                                     route="auto", model_version="counterfactual"),
            model_version="counterfactual",
        )  # fmt: skip
        return inp.model_copy(update={"documents": [*inp.documents, doc]})
    if proof == "rahat_id":
        form = inp.form
        payload = {"national_id": form.national_id.value, "name": form.full_name.value, "dob": form.dob.value}
        doc = DocumentCheck(
            document_id="counterfactual-rahat_id", kind="rahat_id", quality="ok",
            qr=QrResult(found=True, signature_valid=True, issuer_key_id="counterfactual", payload=payload),
            authenticity=TypedDecision[Authenticity](choice="genuine", probabilities={"genuine": 0.97, "suspect": 0.03}, confidence=0.97,
                                                     route="auto", model_version="counterfactual"),
            model_version="counterfactual",
        )  # fmt: skip
        others = [d for d in inp.documents if d.kind != "rahat_id"]
        return inp.model_copy(update={"documents": [*others, doc]})
    raise ValueError(f"no counterfactual for proof {proof!r}")


@dataclass(frozen=True, slots=True)
class _Scored:
    facts: dict[str, Fact]
    evals: list[RuleEvaluation]
    p_eligible: float
    p_genuine: float

    @property
    def p_ok(self) -> float:
        return _r(self.p_eligible * self.p_genuine)


def _score(inp: DecisionInput, dsl: Mapping[str, Any], model: EvidenceModel) -> _Scored:
    params: Mapping[str, Any] = dsl.get("params", {}) or {}
    facts = F.build_facts(inp, params)
    evals = evaluate_rules(dsl, facts)
    probs = model.predict(compute_features(inp, facts, params))
    return _Scored(facts=facts, evals=evals, p_eligible=_r(probs.p_eligible), p_genuine=_r(probs.p_genuine))


def _settled_fact(fact: Fact, floor: float) -> bool:
    return fact.known and fact.verified and fact.confidence >= floor


def _blocking_proof(inp: DecisionInput, scored: _Scored, floor: float) -> str | None:
    """The single document that would settle every hard rule standing in the way, or None."""
    needed: set[str] = set()
    for e in scored.evals:
        if not e.trace.hard or e.settled("pass", floor):
            continue
        blocking = [v for v in e.variables if not _settled_fact(scored.facts.get(v, F.UNKNOWN_FACT), floor)]
        if not blocking:
            return None  # unsettled for a reason no document can change
        for variable in blocking:
            proof = F.resolvable_by(inp, variable, scored.facts.get(variable, F.UNKNOWN_FACT))
            if proof is None:
                return None
            needed.add(proof)
    return needed.pop() if len(needed) == 1 else None


def silent_guess_violations(result: DecisionResult, floor: float | None = None) -> list[str]:
    """Why an automatic result would be a silent guess. Empty for every result `decide()` returns.

    Checked from the result alone, so evals and audits can recompute the metric over stored decisions.
    """
    if result.route != "auto":
        return []
    floor = result.thresholds.get("confidence_floor", F.DEFAULT_CONFIDENCE_FLOOR) if floor is None else floor
    problems: list[str] = []
    if result.guards:
        problems.append("guard_active")
    hard = [t for t in result.rule_trace if t.hard]

    def below_floor(trace_vars: Sequence[str]) -> bool:
        return any(result.facts.get(v, F.UNKNOWN_FACT).confidence < floor for v in trace_vars)

    if result.outcome == "approved":
        if result.p_ok < result.thresholds.get("approve", 1.0):
            problems.append("below_approve_threshold")
        if any(t.result != "pass" or not t.verified_inputs for t in hard):
            problems.append("hard_rule_not_verified_pass")
        if any(below_floor([v for v in t.values_used if not v.startswith("param.")]) for t in hard):
            problems.append("below_confidence_floor")
    elif result.outcome == "rejected":
        failing = [t for t in hard if t.result == "fail" and t.verified_inputs
                   and not below_floor([v for v in t.values_used if not v.startswith("param.")])]  # fmt: skip
        if not failing:
            problems.append("reject_without_verified_failure")
        identity = result.facts.get("identity_verified", F.UNKNOWN_FACT)
        if not (identity.known and identity.value is True and identity.verified):
            problems.append("reject_identity_not_verified")
        if round(1 - result.p_eligible, PRECISION) < result.thresholds.get("reject", 1.0):
            problems.append("below_reject_threshold")
    else:
        problems.append("auto_without_outcome")
    return problems


def _reasons(action: str, guards: Sequence[str], evals: Sequence[RuleEvaluation], floor: float, approve_allowed: bool,
             reject_allowed: bool, proof: str | None, p_ok: float, thresholds: Mapping[str, float]) -> list[str]:  # fmt: skip
    rules: list[str] = []
    for e in evals:
        if not e.trace.hard or e.settled("pass", floor):
            continue
        result = e.trace.result
        if result == "unknown":
            rules.append(f"rule_unknown.{e.rule_id}")
        elif not e.trace.verified_inputs:
            rules.append(f"rule_{result}_unverified.{e.rule_id}")
        elif e.min_confidence < floor:
            rules.append(f"rule_{result}_below_floor.{e.rule_id}")
        else:
            rules.append(f"rule_failed.{e.rule_id}")
    out = [f"guard.{g}" for g in guards]
    if action == "approve":
        out += ["rules.all_hard_verified_pass", "cost.approve_cheapest"]
    elif action == "reject":
        out += [*rules, "cost.reject_cheapest"]
    elif action == "ask_proof":
        out += [f"ask_proof.{proof}", *rules, "cost.ask_proof_cheapest"]
    else:
        out += rules
        if approve_allowed and p_ok < thresholds["approve"]:
            out.append("cost.approve_below_threshold")
        if reject_allowed:
            out.append("cost.reject_not_cheapest")
        if not guards:
            out.append("cost.human_cheapest")
    return list(dict.fromkeys(out))


def _finish(result: DecisionResult, costs: CostMatrix) -> DecisionResult:
    material = result.model_dump(mode="json", exclude={"result_hash"})
    material["cost_matrix"] = costs.model_dump(mode="json")
    return result.model_copy(update={"result_hash": hash_payload(material)})


def _invalid_rules(inp: DecisionInput, rules: RuleSetSnapshot, costs: CostMatrix, model: EvidenceModel, input_hash: str) -> DecisionResult:
    """A rule version that does not validate never decides anything: a person does."""
    human = _r(costs.human_cost(inp.queue_days))
    explanation = explain.explanation_for("human_check", inp.lang)
    result = DecisionResult(
        route="human", outcome="needs_human", p_eligible=0.0, p_genuine=0.0, p_ok=0.0, probabilities={},
        expected_costs={"human": human}, thresholds={}, facts={}, rule_trace=[], reasons=["guard.rules_invalid"],
        guards=["rules_invalid"], explanation=explanation, model_version=model.version, engine_version=ENGINE_VERSION,
        rule_version_id=rules.rule_version_id, rule_version_no=rules.version_no, input_hash=input_hash, result_hash="",
    )  # fmt: skip
    return _finish(result, costs)


def decide(inp: DecisionInput, rules: RuleSetSnapshot, costs: CostMatrix, model: EvidenceModel) -> DecisionResult:
    """Route one application: approve, reject, ask for one proof, or hand to a person. Pure and replayable."""
    input_hash = hash_payload(inp.model_dump(mode="json"))
    dsl = rules.dsl
    if validate(dsl):
        return _invalid_rules(inp, rules, costs, model, input_hash)
    params: Mapping[str, Any] = dsl.get("params", {}) or {}
    floor = _r(F.param(params, "confidence_floor", F.DEFAULT_CONFIDENCE_FLOOR))
    proof_days = F.param(params, "proof_days", DEFAULT_PROOF_DAYS)

    scored = _score(inp, dsl, model)
    p_e, p_g, p_ok = scored.p_eligible, scored.p_genuine, scored.p_ok
    p_inel = _r(1 - p_e)
    human = _r(costs.human_cost(inp.queue_days))
    thresholds = {
        "approve": _r(costs.approve_threshold(inp.queue_days)),
        "reject": _r(costs.reject_threshold(inp.queue_days)),
        "confidence_floor": floor,
    }

    hard = [e for e in scored.evals if e.trace.hard]
    approve_allowed = all(e.settled("pass", floor) for e in hard)
    failing = [e for e in hard if e.settled("fail", floor)]
    identity = scored.facts["identity_verified"]
    reject_allowed = bool(failing) and identity.known and identity.value is True and identity.verified

    expected: dict[str, float] = {"human": human}
    if approve_allowed:
        expected["approve"] = _r((1 - p_ok) * costs.wrong_approve)
    if reject_allowed:
        expected["reject"] = _r((1 - p_inel) * costs.wrong_reject)
    proof = None if failing or approve_allowed else _blocking_proof(inp, scored, floor)
    ask_detail: dict[str, float] = {}
    if proof is not None:
        cf = _score(counterfactual(inp, proof, params), dsl, model)
        cf_approve = all(e.settled("pass", floor) for e in cf.evals if e.trace.hard)
        after = min(_r((1 - cf.p_ok) * costs.wrong_approve), human) if cf_approve else human
        q = _r(min(1.0, p_ok / cf.p_ok)) if cf.p_ok > 0 else 0.0
        expected["ask_proof"] = _r(costs.ask_proof + costs.delay_per_day * proof_days + q * after + (1 - q) * human)
        ask_detail = {"p_ok_if_confirmed": cf.p_ok, "q_confirms": q}

    action = min(expected, key=lambda a: (expected[a], TIE_ORDER.index(a)))
    guards = guards_for(inp)
    if guards:
        action = "human"
    route, outcome = ROUTES[action]
    ask_proof = proof if action == "ask_proof" else None
    reasons = _reasons(action, guards, scored.evals, floor, approve_allowed, reject_allowed, proof, p_ok, thresholds)
    blockers = [e for e in hard if not e.settled("pass", floor)]

    def build(route_: str, outcome_: str, reasons_: list[str], ask_: str | None) -> DecisionResult:
        code = explain.citizen_code(route=route_, outcome=outcome_, guards=guards, ask_proof=ask_, inp=inp, failing=failing, blockers=blockers)
        handoff = None
        if route_ != "auto":
            handoff = explain.build_handoff(inp=inp, facts=scored.facts, evals=scored.evals, floor=floor, p_eligible=p_e, p_genuine=p_g,
                                            proof=ask_ or proof, guards=guards, expected_costs=expected)  # fmt: skip
        return DecisionResult(
            route=route_, outcome=outcome_, p_eligible=p_e, p_genuine=p_g, p_ok=p_ok,  # type: ignore[arg-type]
            probabilities={"p_eligible": p_e, "p_genuine": p_g, "p_ok": p_ok, "p_ineligible": p_inel, **ask_detail},
            expected_costs=expected, thresholds=thresholds, facts=scored.facts, rule_trace=[e.trace for e in scored.evals],
            reasons=reasons_, guards=guards, ask_proof=ask_, handoff=handoff, explanation=explain.explanation_for(code, inp.lang),
            payment_pkr=dsl.get("payment_pkr") if outcome_ == "approved" else None, model_version=model.version,
            engine_version=ENGINE_VERSION, rule_version_id=rules.rule_version_id, rule_version_no=rules.version_no,
            input_hash=input_hash, result_hash="",
        )  # fmt: skip

    result = build(route, outcome, reasons, ask_proof)
    violations = silent_guess_violations(result, floor)
    if violations:  # the invariant would be broken: never guess, hand it to a person
        result = build("human", "needs_human", ["invariant_fallback", *[f"invariant.{v}" for v in violations], *reasons], None)
    return _finish(result, costs)


def stable_json(result: DecisionResult) -> str:
    return canonical_json(result.model_dump(mode="json"))
