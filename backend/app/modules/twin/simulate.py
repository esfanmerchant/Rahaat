"""What a draft rule version would change, case by case. Pure: no database, no clock, no side effects.

Every case is assessed twice with the pure engine (`assess`), once under the base version and once under
the draft, and routed with the department's costs (`route_for`, the function `decide()` uses). Then:

- how many approvals, rejections, proof requests and hand-offs change, and in which direction;
- the expected cost of the chosen actions before and after (and, on labelled cases, the realised cost
  against the truth under each version's own rules);
- fairness slices (district, gender, age band, language): a slice is flagged when its approval or hand-off
  rate moves at least FLAG_GAP more than the whole set does, and by more than chance would explain (two
  standard errors of a slice that size changing at the overall rate), among slices of at least MIN_SLICE;
- a sample of changed cases with before and after.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.contracts.decision import CostMatrix
from app.contracts.engine import DecisionInput, EvidenceModel
from app.modules.decision import facts as F
from app.modules.decision.engine import ROUTES, Pricing, assess, route_for
from app.modules.evals.decision_eval import LabelledScore, age_band, realised_cost

OUTCOMES: Final = ("approved", "rejected", "needs_proof", "needs_human")
SLICE_KEYS: Final = ("district", "gender", "age_band", "language")
MIN_SLICE: Final = 10
FLAG_GAP: Final = 0.05
SAMPLE: Final = 20


@dataclass(frozen=True, slots=True)
class TwinCase:
    ref: str
    dataset: str  # live | synthetic
    slices: dict[str, str | None]
    before: Pricing
    after: Pricing
    labelled_before: LabelledScore | None = None
    labelled_after: LabelledScore | None = None


def live_slices(inp: DecisionInput) -> dict[str, str | None]:
    reg = F.registry_record(inp)
    district = (reg.district if reg and reg.district else None) or inp.form.district.value
    gender = (reg.gender if reg and reg.gender else None) or inp.form.gender.value
    dob = (reg.dob if reg and reg.dob else None) or inp.form.dob.value
    return {"district": district, "gender": gender, "age_band": age_band(dob, inp.decided_at), "language": inp.lang}


def live_case(ref: str, inp: DecisionInput, base: Mapping[str, Any], draft: Mapping[str, Any], model: EvidenceModel) -> TwinCase:
    return TwinCase(ref=ref, dataset="live", slices=live_slices(inp), before=assess(inp, base, model).pricing,
                    after=assess(inp, draft, model).pricing)  # fmt: skip


def synthetic_cases(base: Sequence[LabelledScore], draft: Sequence[LabelledScore]) -> list[TwinCase]:
    out = []
    for b, d in zip(base, draft, strict=True):
        slices: dict[str, str | None] = {"district": b.district, "gender": b.gender, "age_band": b.age_band, "language": b.lang}
        out.append(TwinCase(ref=b.case_id, dataset="synthetic", slices=slices, before=b.pricing, after=d.pricing, labelled_before=b,
                            labelled_after=d))  # fmt: skip
    return out


def _rates(outcomes: Sequence[str]) -> dict[str, float]:
    n = len(outcomes) or 1
    counts = Counter(outcomes)
    return {"approve": round(counts["approved"] / n, 4), "human": round(counts["needs_human"] / n, 4),
            "auto": round((counts["approved"] + counts["rejected"]) / n, 4)}  # fmt: skip


def _slices(cases: Sequence[TwinCase], before: Sequence[str], after: Sequence[str]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    overall_before, overall_after = _rates(before), _rates(after)
    approve_shift = overall_after["approve"] - overall_before["approve"]
    human_shift = overall_after["human"] - overall_before["human"]
    n_all = len(cases) or 1
    q_approve = sum(1 for x, y in zip(before, after, strict=True) if (x == "approved") != (y == "approved")) / n_all
    q_human = sum(1 for x, y in zip(before, after, strict=True) if (x == "needs_human") != (y == "needs_human")) / n_all
    out: dict[str, list[dict[str, Any]]] = {}
    flagged: list[str] = []
    for key in SLICE_KEYS:
        groups: dict[str, list[int]] = {}
        for i, case in enumerate(cases):
            groups.setdefault(str(case.slices.get(key) or "unknown"), []).append(i)
        rows = []
        for value, members in sorted(groups.items()):
            rb, ra = _rates([before[i] for i in members]), _rates([after[i] for i in members])
            d_approve, d_human = round(ra["approve"] - rb["approve"], 4), round(ra["human"] - rb["human"], 4)
            size = len(members)
            noise_approve = 2 * math.sqrt(q_approve * (1 - q_approve) / size)
            noise_human = 2 * math.sqrt(q_human * (1 - q_human) / size)
            moved = size >= MIN_SLICE and (abs(d_approve - approve_shift) >= max(FLAG_GAP, noise_approve)
                                           or abs(d_human - human_shift) >= max(FLAG_GAP, noise_human))  # fmt: skip
            rows.append({"value": value, "n": size, "approve_rate_before": rb["approve"], "approve_rate_after": ra["approve"],
                         "approve_change": d_approve, "human_rate_before": rb["human"], "human_rate_after": ra["human"],
                         "human_change": d_human, "noise": round(max(noise_approve, noise_human), 4), "flagged": moved})  # fmt: skip
            if moved:
                flagged.append(f"{key}={value}")
        out[key] = rows
    return out, flagged


def summarise(cases: Sequence[TwinCase], costs: CostMatrix, *, payment_before: int | None, payment_after: int | None) -> dict[str, Any]:
    """Counts, directions, costs and fairness slices for one set of cases (all live, or all synthetic)."""
    before_actions: list[str] = []
    after_actions: list[str] = []
    cost_before = cost_after = 0.0
    for case in cases:
        a, ea = route_for(case.before, costs)
        b, eb = route_for(case.after, costs)
        before_actions.append(a)
        after_actions.append(b)
        cost_before += ea[a]
        cost_after += eb[b]
    before = [ROUTES[a][1] for a in before_actions]
    after = [ROUTES[a][1] for a in after_actions]
    transitions: dict[str, dict[str, int]] = {o: dict.fromkeys(OUTCOMES, 0) for o in OUTCOMES}
    for x, y in zip(before, after, strict=True):
        transitions[x][y] += 1
    n = len(cases)
    counts_before, counts_after = Counter(before), Counter(after)
    slices, flagged = _slices(cases, before, after)
    summary: dict[str, Any] = {
        "n": n, "changed": sum(1 for x, y in zip(before, after, strict=True) if x != y),
        "outcomes_before": {o: counts_before[o] for o in OUTCOMES}, "outcomes_after": {o: counts_after[o] for o in OUTCOMES},
        "change": {o: counts_after[o] - counts_before[o] for o in OUTCOMES}, "transitions": transitions,
        "expected_cost_before": round(cost_before, 2), "expected_cost_after": round(cost_after, 2),
        "expected_cost_change": round(cost_after - cost_before, 2),
        "expected_cost_change_per_case": round((cost_after - cost_before) / n, 4) if n else 0.0,
        "payout_before_pkr": counts_before["approved"] * (payment_before or 0), "payout_after_pkr": counts_after["approved"] * (payment_after or 0),
        "slices": slices, "flagged_slices": flagged,
    }  # fmt: skip
    labelled = [c for c in cases if c.labelled_before is not None and c.labelled_after is not None]
    if labelled and len(labelled) == n:
        real_before = sum(realised_cost(c.labelled_before, a, costs) for c, a in zip(cases, before_actions, strict=True) if c.labelled_before)
        real_after = sum(realised_cost(c.labelled_after, a, costs) for c, a in zip(cases, after_actions, strict=True) if c.labelled_after)

        def mistakes(which: str, actions: Sequence[str]) -> dict[str, int]:
            fa = fr = needless = 0
            for case, action in zip(cases, actions, strict=True):
                score = case.labelled_before if which == "before" else case.labelled_after
                assert score is not None
                fa += action == "approve" and not score.ok
                fr += action == "reject" and score.eligible
                needless += action in ("human", "ask_proof") and score.ok
            return {"false_approvals": fa, "false_rejections": fr, "not_automatic_although_ok": needless}

        summary["labelled"] = {
            "realised_cost_before": round(real_before, 2), "realised_cost_after": round(real_after, 2),
            "realised_cost_change": round(real_after - real_before, 2), "before": mistakes("before", before_actions),
            "after": mistakes("after", after_actions),
            "eligible_before": sum(1 for c in labelled if c.labelled_before and c.labelled_before.eligible),
            "eligible_after": sum(1 for c in labelled if c.labelled_after and c.labelled_after.eligible),
        }  # fmt: skip
    return summary


def changed_sample(cases: Sequence[TwinCase], costs: CostMatrix, limit: int = SAMPLE) -> list[tuple[TwinCase, str, str]]:
    """Up to `limit` changed cases, the most consequential first (a new approval or rejection before a new hand-off)."""
    weight = {"approved": 0, "rejected": 1, "needs_human": 2, "needs_proof": 3}
    changed = []
    for case in cases:
        before = ROUTES[route_for(case.before, costs)[0]][1]
        after = ROUTES[route_for(case.after, costs)[0]][1]
        if before != after:
            changed.append((case, before, after))
    changed.sort(key=lambda item: (min(weight[item[1]], weight[item[2]]), item[0].dataset, item[0].ref))
    return changed[:limit]
