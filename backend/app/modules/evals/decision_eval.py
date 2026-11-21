"""The cost of being wrong, measured (B7): what a cost matrix makes the engine do on labelled cases it never saw.

    scores = score_world(heldout_world(), dsl, model)       # slow part, once per rule version and model
    report = analyse(scores, costs)                          # fast part, for every slider move

The labelled set is a synthetic world built from its own seed, so none of its people or families were in
the model's training, calibration or test data. Each case is scored once with `engine.assess()` (facts,
rules, probabilities, allowed actions, what a proof would bring). Pricing it under a cost matrix then uses
`engine.route_for()`, the same function `decide()` uses, so the operating point reported here is exactly
what the engine does with those costs.

Truth follows the rule version: a case is eligible when the version's hard rules pass on the claimed
person's *true* attributes (true income, true other aid, ...). So the same synthetic people can be scored
against any draft, which is what the Digital Twin needs.

Realised cost with the labels: a right approval or rejection costs 0, a wrong approval `C_wrong_approve`,
a wrong rejection `C_wrong_reject`, a person `C_human_review + C_delay_per_day * queue_days` (a person is
assumed to get it right), asking for proof `C_ask_proof + C_delay_per_day * proof_days` plus what follows:
for an eligible and genuine case the proof confirms it and the engine approves when it may and that is
cheaper, otherwise a person decides.
"""

from __future__ import annotations

import threading
from bisect import bisect_left
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from functools import lru_cache
from typing import Any, Final

import numpy as np

from app.contracts.decision import CostMatrix
from app.contracts.engine import EvidenceModel, Fact
from app.core.audit import hash_payload
from app.modules.decision import facts as F
from app.modules.decision.engine import PRECISION, Pricing, assess, route_for
from app.modules.evals import metrics
from app.modules.rules.dsl import evaluate_rules, validate
from app.synth.world import SEED, SynthCase, SynthPerson, World, build_world

HELDOUT_SEED: Final = SEED + 101
HELDOUT_HOUSEHOLDS: Final = 450
OUTCOMES: Final = ("approved", "rejected", "needs_proof", "needs_human")
TRUTH_CLASSES: Final = ("eligible_and_genuine", "not_eligible", "not_genuine")
ACTION_OUTCOME: Final = {"approve": "approved", "reject": "rejected", "ask_proof": "needs_proof", "human": "needs_human"}
CURVE_THRESHOLDS: Final[tuple[float, ...]] = tuple(
    sorted({round(0.5 + i * 0.01, 3) for i in range(50)} | {round(0.95 + i * 0.002, 3) for i in range(25)} | {0.999, 1.0})
)
AGE_BANDS: Final = ((0, 30, "18-29"), (30, 45, "30-44"), (45, 60, "45-59"), (60, 200, "60+"))


@lru_cache(maxsize=1)
def heldout_world() -> World:
    """1,000+ labelled cases from people the evidence model never saw (its own seed)."""
    return build_world(HELDOUT_SEED, households=HELDOUT_HOUSEHOLDS)


def age_band(dob: str | None, on: str | None) -> str | None:
    born, day = F.parse_date(dob), F.parse_date(on)
    if born is None or day is None:
        return None
    years = day.year - born.year - ((day.month, day.day) < (born.month, born.day))
    return next((label for low, high, label in AGE_BANDS if low <= years < high), None)


def _true_facts(person: SynthPerson, decided_at: str) -> dict[str, Fact]:
    def fact(value: Any) -> Fact:
        return Fact(value=value, known=True, verified=True, confidence=1.0, source="derived")

    born, day = date.fromisoformat(person.dob), F.parse_date(decided_at) or date(2026, 11, 15)
    years = day.year - born.year - ((day.month, day.day) < (born.month, born.day))
    return {
        "identity_verified": fact(True), "verified_income_pkr": fact(person.true_income_pkr),
        "receives_other_aid": fact(person.receives_other_aid), "is_widow": fact(person.is_widow),
        "has_disability": fact(person.has_disability), "household_size": fact(person.household_size),
        "district": fact(person.district), "gender": fact(person.gender), "age_years": fact(years),
    }  # fmt: skip


def eligible_under(dsl: Mapping[str, Any], person: SynthPerson, decided_at: str) -> bool:
    """The rule version's own answer for the claimed person's household, from the truth instead of evidence."""
    return all(e.trace.result == "pass" for e in evaluate_rules(dsl, _true_facts(person, decided_at)) if e.trace.hard)


@dataclass(frozen=True, slots=True)
class LabelledScore:
    """One labelled case: its cost-independent engine assessment and the truth under the rule version."""

    case_id: str
    family_id: str
    pricing: Pricing
    eligible: bool
    genuine: bool
    fraud: str | None
    district: str | None
    gender: str | None
    age_band: str | None
    lang: str
    tags: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.eligible and self.genuine

    @property
    def truth_class(self) -> str:
        return "not_genuine" if not self.genuine else ("eligible_and_genuine" if self.eligible else "not_eligible")


def score_case(case: SynthCase, person: SynthPerson, dsl: Mapping[str, Any], model: EvidenceModel) -> LabelledScore:
    assessed = assess(case.inp, dsl, model)
    return LabelledScore(
        case_id=case.case_id, family_id=case.family_id, pricing=assessed.pricing,
        eligible=eligible_under(dsl, person, case.inp.decided_at), genuine=case.truth.genuine, fraud=case.truth.fraud,
        district=person.district, gender=person.gender, age_band=age_band(person.dob, case.inp.decided_at),
        lang=case.inp.lang, tags=case.tags,
    )  # fmt: skip


def score_world(world: World, dsl: Mapping[str, Any], model: EvidenceModel) -> list[LabelledScore]:
    """Assess every case of a world under one validated rule version. The slow step (a few seconds)."""
    if validate(dsl):
        raise ValueError("the rule version does not validate")
    persons = {p.ref: p for p in world.persons}
    return [score_case(case, persons[case.family_id], dsl, model) for case in world.cases]


_cache: dict[tuple[str, str, int], list[LabelledScore]] = {}
_cache_lock = threading.Lock()


def cached_scores(dsl: Mapping[str, Any], model: EvidenceModel) -> list[LabelledScore]:
    """Scores of the held-out world for this rule content and model, computed once per process."""
    key = (hash_payload(dict(dsl)), model.version, HELDOUT_SEED)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    scores = score_world(heldout_world(), dsl, model)
    with _cache_lock:
        if len(_cache) >= 6:
            _cache.pop(next(iter(_cache)))
        _cache[key] = scores
    return scores


# --- realised cost with the labels ---------------------------------------------------------------------


def realised_cost(score: LabelledScore, action: str, costs: CostMatrix, approve_at: float | None = None) -> float:
    """What the action really cost, given the truth. `approve_at` replaces the cost rule after a proof (curve)."""
    pricing = score.pricing
    human = costs.human_cost(pricing.queue_days)
    if action == "approve":
        return 0.0 if score.ok else costs.wrong_approve
    if action == "reject":
        return costs.wrong_reject if score.eligible else 0.0
    if action == "human":
        return human
    asked = costs.ask_proof + costs.delay_per_day * pricing.proof_days
    if score.ok and pricing.cf_approvable and pricing.cf_p_ok is not None:
        if approve_at is None:
            approves = round((1 - pricing.cf_p_ok) * costs.wrong_approve, PRECISION) < round(human, PRECISION)
        else:
            approves = pricing.cf_p_ok >= approve_at
        return asked + (0.0 if approves else human)
    return asked + human


def _fallback(pricing: Pricing, costs: CostMatrix) -> str:
    """What the engine does with a case when approving alone is not on the table (below the approve threshold)."""
    action, _ = route_for(replace(pricing, approve_allowed=False), costs)
    return action


@dataclass
class _Arrays:
    """The labelled set as arrays, for fast sweeps over the approve threshold."""

    p_ok: Any
    ok: Any
    approvable: Any
    cost_approved: Any
    fallback_cost: Any  # realised cost of the fallback action when its follow-up does not approve
    ask_can_approve: Any  # fallback is ask_proof and an approval may follow a confirmed proof
    cf_p_ok: Any
    human: Any


def _arrays(scores: Sequence[LabelledScore], costs: CostMatrix) -> _Arrays:
    n = len(scores)
    p_ok = np.zeros(n)
    ok = np.zeros(n, dtype=bool)
    approvable = np.zeros(n, dtype=bool)
    cost_approved = np.zeros(n)
    fallback_cost = np.zeros(n)
    ask_can_approve = np.zeros(n, dtype=bool)
    cf = np.zeros(n)
    human = np.zeros(n)
    for i, s in enumerate(scores):
        pr = s.pricing
        p_ok[i] = pr.p_ok
        ok[i] = s.ok
        approvable[i] = pr.approve_allowed and not pr.guards
        cost_approved[i] = 0.0 if s.ok else costs.wrong_approve
        human[i] = costs.human_cost(pr.queue_days)
        action = _fallback(pr, costs)
        if action == "ask_proof":
            fallback_cost[i] = costs.ask_proof + costs.delay_per_day * pr.proof_days + human[i]
            if s.ok and pr.cf_approvable and pr.cf_p_ok is not None:
                ask_can_approve[i] = True
                cf[i] = pr.cf_p_ok
        else:
            fallback_cost[i] = realised_cost(s, action, costs)
    return _Arrays(p_ok, ok, approvable, cost_approved, fallback_cost, ask_can_approve, cf, human)


def cost_curve(scores: Sequence[LabelledScore], costs: CostMatrix, thresholds: Sequence[float] = CURVE_THRESHOLDS) -> list[dict[str, Any]]:
    """Realised cost per case if the engine approved alone exactly when p_ok >= t (everything else unchanged)."""
    a = _arrays(scores, costs)
    n = max(1, len(scores))
    rows = []
    for t in thresholds:
        approve = a.approvable & (a.p_ok >= t)
        follow = a.ask_can_approve & (a.cf_p_ok >= t)
        fallback = np.where(follow, a.fallback_cost - a.human, a.fallback_cost)
        total = float(np.where(approve, a.cost_approved, fallback).sum())
        rows.append({
            "threshold": round(float(t), 4), "cost_per_case": round(total / n, 4), "approvals": int(approve.sum()),
            "false_approvals": int((approve & ~a.ok).sum()),
        })  # fmt: skip
    return rows


def _rank_curve(scores: Sequence[LabelledScore]) -> tuple[list[dict[str, float]], list[dict[str, float]], float | None, float | None]:
    """ROC and precision-recall of p_ok as the approve signal, over cases where the rules let it act."""
    pool = [(s.pricing.p_ok, s.ok) for s in scores if s.pricing.approve_allowed and not s.pricing.guards]
    positives = sum(1 for _, y in pool if y)
    negatives = len(pool) - positives
    if not pool or not positives or not negatives:
        return [], [], None, None
    ordered = sorted(pool, key=lambda item: -item[0])
    probs = [p for p, _ in ordered]
    labels = [y for _, y in ordered]
    cum_tp: list[int] = []
    tp = 0
    for y in labels:
        tp += int(y)
        cum_tp.append(tp)
    ascending = sorted(probs)
    roc: list[dict[str, float]] = []
    pr: list[dict[str, float]] = []
    for t in sorted({round(i / 100, 2) for i in range(101)} | {0.968, 0.99, 0.995}, reverse=True):
        k = len(ascending) - bisect_left(ascending, t)  # cases with p_ok >= t: the first k of the descending order
        true_pos = cum_tp[k - 1] if k else 0
        false_pos = k - true_pos
        roc.append({"threshold": t, "tpr": round(true_pos / positives, 4), "fpr": round(false_pos / negatives, 4)})
        if k:
            pr.append({"threshold": t, "precision": round(true_pos / k, 4), "recall": round(true_pos / positives, 4)})
    ap = 0.0
    seen = 0
    for i, y in enumerate(labels):
        if y:
            seen += 1
            ap += seen / (i + 1)
    return roc, pr, metrics.auc(probs, [int(y) for y in labels]), round(ap / positives, 4)


@dataclass(frozen=True, slots=True)
class CostIndependent:
    roc: list[dict[str, float]]
    pr: list[dict[str, float]]
    roc_auc: float | None
    average_precision: float | None
    reliability: dict[str, Any]
    pool: int


_independent_cache: dict[int, CostIndependent] = {}


def cost_independent(scores: Sequence[LabelledScore]) -> CostIndependent:
    """ROC, PR and calibration do not depend on the costs; computed once per scored set."""
    key = id(scores)
    hit = _independent_cache.get(key)
    if hit is not None:
        return hit
    roc, pr, roc_auc, ap = _rank_curve(scores)
    probs = [s.pricing.p_ok for s in scores]
    labels = [int(s.ok) for s in scores]
    summary = metrics.summary(probs, labels)
    pool = sum(1 for s in scores if s.pricing.approve_allowed and not s.pricing.guards)
    result = CostIndependent(roc=roc, pr=pr, roc_auc=roc_auc, average_precision=ap, reliability=summary, pool=pool)
    if len(_independent_cache) > 8:
        _independent_cache.clear()
    _independent_cache[key] = result
    return result


def operating_point(scores: Sequence[LabelledScore], costs: CostMatrix) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Route every case exactly as the engine would under these costs and count what went right and wrong."""
    n = len(scores)
    actions = [route_for(s.pricing, costs)[0] for s in scores]
    confusion = {truth: dict.fromkeys(OUTCOMES, 0) for truth in TRUTH_CLASSES}
    counts = dict.fromkeys(("approve", "reject", "ask_proof", "human"), 0)
    false_approvals = false_rejections = unnecessary_handoffs = unnecessary_asks = 0
    total = 0.0
    for score, action in zip(scores, actions, strict=True):
        counts[action] += 1
        confusion[score.truth_class][ACTION_OUTCOME[action]] += 1
        total += realised_cost(score, action, costs)
        if action == "approve" and not score.ok:
            false_approvals += 1
        if action == "reject" and score.eligible:
            false_rejections += 1
        if action == "human" and score.ok:
            unnecessary_handoffs += 1
        if action == "ask_proof" and score.ok:
            unnecessary_asks += 1
    human = costs.human_cost(1.0)

    def rate(value: int) -> float:
        return round(value / n, 4) if n else 0.0

    point = {
        "n": n, "approved": counts["approve"], "rejected": counts["reject"], "needs_proof": counts["ask_proof"],
        "needs_human": counts["human"], "auto_rate": rate(counts["approve"] + counts["reject"]),
        "false_approvals": false_approvals, "false_approve_rate": rate(false_approvals),
        "false_approve_share_of_approvals": round(false_approvals / counts["approve"], 4) if counts["approve"] else 0.0,
        "false_rejections": false_rejections, "false_reject_rate": rate(false_rejections),
        "unnecessary_handoffs": unnecessary_handoffs, "unnecessary_handoff_rate": rate(unnecessary_handoffs),
        "unnecessary_proof_requests": unnecessary_asks, "unnecessary_proof_request_rate": rate(unnecessary_asks),
        "not_automatic_although_ok": unnecessary_handoffs + unnecessary_asks,
        "not_automatic_although_ok_rate": rate(unnecessary_handoffs + unnecessary_asks),
        "cost_per_case": round(total / n, 4) if n else 0.0, "all_human_cost_per_case": round(human, 4),
        "saving_per_case": round(human - total / n, 4) if n else 0.0, "silent_guesses": 0,
        "cost_of_false_approvals": round(false_approvals * costs.wrong_approve, 2),
        "cost_of_false_rejections": round(false_rejections * costs.wrong_reject, 2),
        "cost_of_unnecessary_handoffs": round(unnecessary_handoffs * human, 2),
    }  # fmt: skip
    return point, {"rows": list(TRUTH_CLASSES), "columns": list(OUTCOMES), "counts": confusion}, actions


def _nearest(curve: Sequence[Mapping[str, Any]], threshold: float) -> Mapping[str, Any]:
    return min(curve, key=lambda row: (abs(row["threshold"] - threshold), row["threshold"]))


def explain_choice(costs: CostMatrix, point: Mapping[str, Any], curve: Sequence[Mapping[str, Any]], ece: float) -> str:
    """One paragraph, from the numbers, on why the derived approve threshold is the point to use."""
    human = costs.human_cost(1.0)
    derived = round(costs.approve_threshold(1.0), 4)
    best = min(curve, key=lambda row: (row["cost_per_case"], -row["threshold"]))
    lower = _nearest(curve, max(0.5, derived - 0.07))
    higher = _nearest(curve, min(0.995, derived + (1 - derived) / 2))
    at = _nearest(curve, derived)
    n = max(1, int(point["n"]))
    ratio = costs.wrong_approve / human if human else float("inf")
    gap_units = (at["cost_per_case"] - best["cost_per_case"]) * n
    if gap_units <= 1e-9:
        verdict = f"It is also the cheapest point measured on these cases ({at['cost_per_case']:.2f} per case)."
    elif gap_units < costs.wrong_approve:
        verdict = (
            f"The cheapest point measured is {best['threshold']:.3f} at {best['cost_per_case']:.2f} per case, {gap_units:.0f} units "
            f"less in total over {n} cases: less than the cost of one wrong approval ({costs.wrong_approve:g}), so these cases "
            f"cannot tell the two points apart and the derived one is kept."
        )
    else:
        verdict = (
            f"The cheapest point measured is {best['threshold']:.3f} at {best['cost_per_case']:.2f} per case, {gap_units:.0f} units "
            f"less in total over {n} cases. That is more than one wrong approval, which says the probabilities in that range are "
            f"off (ECE {ece:.3f}); the fix is to recalibrate the model, not to move the threshold by hand."
        )
    return (
        f"A wrong approval costs {costs.wrong_approve:g} units and a person's review {human:g} (review plus one day of waiting), "
        f"so a wrong approval is {ratio:.0f} times worse and the engine approves alone only when p_ok >= 1 - {human:g}/"
        f"{costs.wrong_approve:g} = {derived:.3f}: below that, a person is the cheaper risk. On {point['n']} labelled cases from "
        f"people the model never saw, that point approves {point['approved']} alone with {point['false_approvals']} wrong, "
        f"rejects {point['rejected']} with {point['false_rejections']} wrong, asks {point['needs_proof']} for one proof and sends "
        f"{point['needs_human']} to a person, at {point['cost_per_case']:.2f} units per case against {human:.2f} for sending "
        f"everyone to a person. Approving from {lower['threshold']:.3f} would cost {lower['cost_per_case']:.2f} per case with "
        f"{lower['false_approvals']} wrong approvals; waiting for {higher['threshold']:.3f} would cost "
        f"{higher['cost_per_case']:.2f} and approve only {higher['approvals']} alone. {verdict} The threshold follows from the "
        f"department's costs, so it moves with them, instead of being tuned to one test set; calibration error on these cases "
        f"is {ece:.3f}."
    )


def analyse(scores: Sequence[LabelledScore], costs: CostMatrix) -> dict[str, Any]:
    """Everything the cost page shows for one cost matrix. Fast (no engine calls): safe for a slider."""
    point, confusion, _ = operating_point(scores, costs)
    curve = cost_curve(scores, costs)
    fixed = cost_independent(scores)
    derived = round(costs.approve_threshold(1.0), 4)
    best = min(curve, key=lambda row: (row["cost_per_case"], -row["threshold"]))
    return {
        "costs": costs.model_dump(mode="json"),
        "thresholds": {
            "approve": derived, "reject": round(costs.reject_threshold(1.0), 4), "queue_days": 1.0,
            "approve_formula": f"1 - ({costs.human_review:g} + {costs.delay_per_day:g} x 1 day) / {costs.wrong_approve:g}",
            "reject_formula": f"1 - ({costs.human_review:g} + {costs.delay_per_day:g} x 1 day) / {costs.wrong_reject:g}",
        },  # fmt: skip
        "operating_point": point,
        "confusion": confusion,
        "cost_curve": curve,
        "best_threshold": {"threshold": best["threshold"], "cost_per_case": best["cost_per_case"]},
        "roc": fixed.roc,
        "roc_auc": fixed.roc_auc,
        "pr": fixed.pr,
        "average_precision": fixed.average_precision,
        "approvable_cases": fixed.pool,
        "reliability": {"bins": fixed.reliability["reliability"], "ece": fixed.reliability["ece"], "brier": fixed.reliability["brier"],
                        "auc": fixed.reliability["auc"], "n": fixed.reliability["n"]},  # fmt: skip
        "explanation": explain_choice(costs, point, curve, float(fixed.reliability["ece"])),
    }


def dataset_info(world: World, scores: Sequence[LabelledScore]) -> dict[str, Any]:
    return {
        "name": "synthetic held-out world", "seed": world.seed, "persons": len(world.persons), "cases": len(scores),
        "families": len({s.family_id for s in scores}), "eligible_and_genuine": sum(1 for s in scores if s.ok),
        "not_genuine": sum(1 for s in scores if not s.genuine), "held_out": True,
        "note": "Built from its own seed: no person or family in it was used to train, calibrate or test the evidence model.",
    }  # fmt: skip
