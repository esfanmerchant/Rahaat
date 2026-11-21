"""From a message to a `TypedDecision[ScamLabel]`: verify codes, abstain rules, cost-based routing. Pure.

Order of evidence:
1. A verify code that we really issued, on text that reads exactly like the message we sent: confirmed real.
   A real code on changed text, or a code shaped like ours that we never issued, is strong scam evidence.
2. The calibrated model (text model stacked with the link, sender and money signals).
3. Abstain rules: too short to judge, or the text model and the signals pull hard in opposite directions.
4. Routing from costs (PLAN 6.1): answer alone only when that is cheaper in expectation than a person looking.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from app.contracts.common import Route, ScamLabel
from app.contracts.decision import TypedDecision
from app.modules.scam.explain import SIGNAL_REASON
from app.modules.scam.model import CLASSES, LEGIT_CLASSES, SCAM_CLASSES, ScamModel
from app.modules.scam.signals import SCAM_SIDE_SIGNALS, SIGNAL_NAMES, Signals, looks_like_our_code, match_template


@dataclass(frozen=True)
class ScamCosts:
    """Costs in the same units as the tenant cost matrix (1 unit is about Rs 120)."""

    missed_scam: float = 100.0  # a person pays a scammer or gives away a PIN: about one relief payment
    false_alarm: float = 30.0  # a real message is called a scam and real help is ignored (as a wrong rejection)
    human_review: float = 3.0  # an officer looks at it
    wrong_kind: float = 1.0  # the right side (scam or not), the wrong kind of scam

    def thresholds(self) -> dict[str, float]:
        return {
            "auto_scam_min_p_scam": round(1 - self.human_review / self.false_alarm, 4),
            "auto_real_min_p_real": round(1 - self.human_review / self.missed_scam, 4),
        }


DEFAULT_COSTS = ScamCosts()


@dataclass(frozen=True)
class DecisionRules:
    """When to abstain. Chosen by cross-validation over training families only (see `tune.py`), never on the test set."""

    min_words: int = 4  # fewer words than this is too little to judge
    choice_floor: float = 0.35  # never name a kind of scam below this probability, even for a person to review
    mixed_logit: float = 2.0  # text model and signals each this sure, in opposite directions: ask a person
    code_logit: float = 3.0  # a code shaped like ours that we never issued multiplies the odds of a scam by about 20
    real_text_max: float = 1.0  # "looks real" also needs the text model alone below this (1.0: off; tuning found no gain)


DEFAULT_RULES = DecisionRules()


@dataclass(frozen=True)
class CodeCheck:
    genuine: bool
    template: str | None = None
    channel: str | None = None
    department: str | None = None
    sent_at: str | None = None


Verifier = Callable[[str], CodeCheck]


@dataclass
class ScamResult:
    decision: TypedDecision[ScamLabel]
    certainty: str  # likely_scam | might_be_scam | not_sure | looks_real | confirmed_real
    reasons: list[str]  # citizen reason codes, most important first
    signals: Signals
    p_scam: float
    p_scam_text: float | None = None
    text_probabilities: dict[str, float] = field(default_factory=dict)
    contributions: list[dict[str, Any]] = field(default_factory=list)
    text_weight: float | None = None
    compared_with: str | None = None
    abstain_reason: str | None = None
    verify: dict[str, Any] | None = None
    costs: dict[str, float] = field(default_factory=dict)
    thresholds: dict[str, float] = field(default_factory=dict)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _shift(probs: dict[str, float], logit: float) -> dict[str, float]:
    """Move the scam side's total by `logit` in log-odds, keeping the split inside each side."""
    p_scam = sum(probs[c] for c in SCAM_CLASSES)
    target = 1 / (1 + math.exp(-(_logit(p_scam) + logit)))
    scam_scale = target / p_scam if p_scam > 0 else 0.0
    legit_scale = (1 - target) / (1 - p_scam) if p_scam < 1 else 0.0
    out = {c: probs[c] * (scam_scale if c in SCAM_CLASSES else legit_scale) for c in CLASSES}
    if p_scam <= 0:  # nothing to scale: spread the new scam mass evenly
        out.update({c: target / len(SCAM_CLASSES) for c in SCAM_CLASSES})
    return out


def _decision(choice: str | None, probs: dict[str, float], route: str, reasons: list[str], version: str) -> TypedDecision[ScamLabel]:
    confidence = probs.get(choice, 0.0) if choice else max(probs.values(), default=0.0)
    return TypedDecision[ScamLabel](
        choice=cast(ScamLabel, choice) if choice else None, probabilities={k: round(v, 4) for k, v in probs.items()},
        confidence=round(min(max(confidence, 0.0), 1.0), 4), route=cast(Route, route),
        reasons=reasons, model_version=version, abstained=choice is None,
    )  # fmt: skip


def _check_codes(signals: Signals, verify: Verifier | None) -> tuple[tuple[str, CodeCheck] | None, bool, bool]:
    """(the genuine code and its check, a code shaped like ours was not issued, a code could not be checked)."""
    fake = unchecked = False
    for code in signals.codes:
        if not looks_like_our_code(code):
            continue
        if verify is None:
            unchecked = True
            continue
        try:
            check = verify(code)
        except Exception:  # noqa: BLE001  (a lookup failure must never turn into a verdict)
            unchecked = True
            continue
        if check.genuine:
            return (code, check), False, False
        fake = True
    return None, fake, unchecked


def _verify_info(code: str, check: CodeCheck | None) -> dict[str, Any]:
    return {"code": code, "genuine": bool(check and check.genuine), "template": check.template if check else None,
            "department": check.department if check else None, "sent_at": check.sent_at if check else None}  # fmt: skip


def _scam_reasons(signals: Signals, parts: dict[str, float], forced: list[str]) -> list[str]:
    ordered = sorted((name for name, weight in parts.items() if weight > 0 and name in SIGNAL_REASON), key=lambda n: -parts[n])
    reasons = list(forced)
    for name in ordered:
        code = SIGNAL_REASON[name]
        if code == "has_link" and any(r.startswith("link_") for r in reasons):
            continue
        if code not in reasons:
            reasons.append(code)
    if not any(r in SIGNAL_REASON.values() for r in reasons) and not forced:
        reasons.append("reads_like_scam")
    if not signals.codes and "rahat" in signals.text.lower() and "rahat_without_code" not in reasons:
        reasons.append("rahat_without_code")
    return reasons


def decide(signals: Signals, model: ScamModel, *, verify: Verifier | None = None, costs: ScamCosts = DEFAULT_COSTS,
           rules: DecisionRules = DEFAULT_RULES) -> ScamResult:  # fmt: skip
    thresholds = costs.thresholds() | {k: float(v) for k, v in asdict(rules).items()}
    genuine, fake_code, _unchecked = _check_codes(signals, verify)

    if signals.bare_code:  # only a code was pasted: we can say whether we issued it, nothing more
        code = signals.codes[0] if signals.codes else ""
        if genuine:
            probs = {c: 1.0 if c == "legit_program_message" else 0.0 for c in CLASSES}
            reasons = ["verify_code_confirmed", "compare_with_app"]
            return ScamResult(_decision("legit_program_message", probs, "auto", reasons, model.version), "confirmed_real", reasons,
                              signals, 0.0, verify=_verify_info(*genuine), thresholds=thresholds)  # fmt: skip
        if fake_code:
            probs = {c: 0.0 for c in CLASSES} | {"impersonation": 0.8, "unknown": 0.2}  # rule: a typo is the other explanation
            reasons = ["verify_code_not_found", "code_typo_possible"]
            return ScamResult(_decision("impersonation", probs, "human", reasons, model.version), "might_be_scam", reasons, signals, 0.8,
                              verify=_verify_info(code, None), thresholds=thresholds)  # fmt: skip
        probs = {c: 1 / len(CLASSES) for c in CLASSES}
        return ScamResult(_decision(None, probs, "human", ["too_short"], model.version), "not_sure", ["too_short"], signals, 0.5,
                          abstain_reason="too_short", thresholds=thresholds)  # fmt: skip

    text_probs, final = model.predict([signals.text], [signals.vector()])
    probs = {c: float(final[0][i]) for i, c in enumerate(CLASSES)}
    text_row = text_probs[0]
    p_scam_text = float(sum(text_row[: len(SCAM_CLASSES)]))
    forced: list[str] = []
    abstain: str | None = None
    verify_info: dict[str, Any] | None = None
    scam_side = any(signals.values.get(name) for name in SCAM_SIDE_SIGNALS) or bool(signals.urls)

    if genuine:
        code, check = genuine
        verify_info = _verify_info(code, check)
        exact = match_template(signals.text, only=check.template)
        if exact is not None and exact.code == code:
            confirmed = {c: 1.0 if c == "legit_program_message" else 0.0 for c in CLASSES}
            reasons = ["verify_code_confirmed"]
            return ScamResult(_decision("legit_program_message", confirmed, "auto", reasons, model.version), "confirmed_real", reasons,
                              signals, 0.0, p_scam_text, {c: round(float(text_row[i]), 4) for i, c in enumerate(CLASSES)},
                              verify=verify_info, thresholds=thresholds)  # fmt: skip
        if scam_side:
            probs = _shift(probs, rules.code_logit)
            forced.append("code_real_text_changed")
        else:
            abstain = "code_real_text_differs"
    elif fake_code:
        verify_info = _verify_info(signals.codes[0], None)
        if signals.template is not None and not scam_side:
            abstain = "code_typo_possible"
            forced.append("verify_code_not_found")
        else:
            probs = _shift(probs, rules.code_logit)
            forced.append("verify_code_not_found")

    p_scam = sum(probs[c] for c in SCAM_CLASSES)
    high_risk_link = any(u.risk == "high" for u in signals.urls)
    if abstain is None and not forced and signals.word_count < rules.min_words and not high_risk_link:
        abstain = "too_short"
    if abstain is None and not forced:
        no_signals = model.stacker.predict_proba(model.stack_input(text_probs, [[0.0] * len(SIGNAL_NAMES)]))
        index = {label: i for i, label in enumerate(model.stacker.classes_)}
        p_plain = float(sum(no_signals[0][index[c]] for c in SCAM_CLASSES if c in index))
        text_lean, signal_lean = _logit(p_scam_text), _logit(p_scam) - _logit(p_plain)
        limit = rules.mixed_logit
        if (text_lean >= limit and signal_lean <= -limit) or (text_lean <= -limit and signal_lean >= limit):
            abstain = "mixed_signals"

    best_scam = max(SCAM_CLASSES, key=lambda c: probs[c])
    best_legit = max(LEGIT_CLASSES, key=lambda c: probs[c])
    p_real = 1 - p_scam
    route_costs = {
        "auto_scam": (1 - p_scam) * costs.false_alarm + (p_scam - probs[best_scam]) * costs.wrong_kind,
        "auto_real": (1 - p_real) * costs.missed_scam + (p_real - probs[best_legit]) * costs.wrong_kind,
        "human": costs.human_review,
    }
    choice: str | None
    if abstain is not None:
        certainty, choice, route = "not_sure", None, "human"
    elif route_costs["auto_scam"] <= costs.human_review:
        certainty, choice, route = "likely_scam", best_scam, "auto"
    elif route_costs["auto_real"] <= costs.human_review and not scam_side and not forced and p_scam_text <= rules.real_text_max:
        certainty, choice, route = "looks_real", best_legit, "auto"
    elif p_scam >= 0.5 and probs[best_scam] >= rules.choice_floor:
        certainty, choice, route = "might_be_scam", best_scam, "human"
    else:
        certainty, choice, route, abstain = "not_sure", None, "human", "model_unsure"

    top = choice or max(CLASSES, key=lambda c: probs[c])
    other = best_legit if top in SCAM_CLASSES else best_scam
    text_part, parts = model.pairwise(text_row, signals.vector(), CLASSES.index(top), CLASSES.index(other))
    if certainty in ("likely_scam", "might_be_scam"):
        reasons = _scam_reasons(signals, parts, forced)
    elif certainty == "looks_real":
        reasons = ["no_scam_signs"]
        if signals.template is not None:
            reasons.append("matches_template")
        if signals.sender.kind == "official":
            reasons.append("official_sender")
        if best_legit == "legit_program_message" and genuine is None:
            reasons.append("no_code_to_check")
    else:
        reasons = [abstain or "model_unsure", *forced]
        toward_scam = model.pairwise(text_row, signals.vector(), CLASSES.index(best_scam), CLASSES.index(best_legit))[1]
        reasons += [r for r in _scam_reasons(signals, toward_scam, []) if r not in ("reads_like_scam",) and r not in reasons][:2]
    reasons = list(dict.fromkeys(reasons))
    codes = reasons + [f"signal:{name}" for name in signals.fired()]
    contributions = [{"signal": name, "weight": round(weight, 3)} for name, weight in sorted(parts.items(), key=lambda kv: -abs(kv[1]))]
    return ScamResult(
        decision=_decision(choice, probs, route, codes, model.version), certainty=certainty, reasons=reasons, signals=signals,
        p_scam=round(p_scam, 4), p_scam_text=round(p_scam_text, 4),
        text_probabilities={c: round(float(text_row[i]), 4) for i, c in enumerate(CLASSES)}, contributions=contributions,
        text_weight=round(text_part, 3), compared_with=other, abstain_reason=abstain, verify=verify_info,
        costs={k: round(v, 3) for k, v in route_costs.items()}, thresholds=thresholds,
    )  # fmt: skip
