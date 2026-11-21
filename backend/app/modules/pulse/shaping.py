"""Pure shaping for the public pulse: counts into a fixed shape, labelled cases into replay rows. No database, no I/O."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

REPLAY_LIMIT: Final = 2000
APPLICATION_STATUSES: Final = ("draft", "submitted", "needs_proof", "in_review", "approved", "rejected", "paid", "on_hold_consent", "withdrawn")
DECISION_ROUTES: Final = ("auto", "ask_more", "human", "reject")
SENT_STATUSES: Final = ("submitted", "settled")
SCAM_LABELS: Final = ("relief_scam", "phishing_link", "advance_fee", "impersonation")
REPLAY_SOURCE: Final = "synthetic labelled eval set"
ACTION_ROUTE: Final = {
    "approve": ("auto", "approved"),
    "reject": ("auto", "rejected"),
    "ask_proof": ("ask_more", "needs_proof"),
    "human": ("human", "needs_human"),
}


def reason_code(action: str, guards: Sequence[str], proof: str | None, p_ok: float, approve_threshold: float) -> str:
    """A short engine reason code for a replayed case. Codes, never free text; they mirror the engine's own reason keys."""
    if guards:
        return f"guard.{guards[0]}"
    if action == "approve":
        return "rules.all_hard_verified_pass"
    if action == "reject":
        return "cost.reject_cheapest"
    if action == "ask_proof":
        return f"ask_proof.{proof}" if proof else "cost.ask_proof_cheapest"
    return "cost.approve_below_threshold" if p_ok < approve_threshold else "cost.human_cheapest"


def correct_of(action: str, ok: bool, eligible: bool) -> bool:
    """Whether the automatic outcome was right. A deferral (proof or a person) is never counted as a mistake."""
    if action == "approve":
        return ok
    if action == "reject":
        return not eligible
    return True


def replay_row(action: str, *, p_ok: float, ok: bool, eligible: bool, kind: str, code: str) -> dict[str, Any]:
    route, outcome = ACTION_ROUTE[action]
    return {
        "route": route,
        "outcome": outcome,
        "p_ok": round(float(p_ok), 4),
        "correct": correct_of(action, ok, eligible),
        "reason_code": code,
        "kind": kind,
    }


def sample(rows: Sequence[Any], limit: int = REPLAY_LIMIT) -> list[Any]:
    """An even, deterministic thinning to at most `limit` rows (every k-th), so a big set keeps its mix."""
    if limit <= 0:
        return []
    if len(rows) <= limit:
        return list(rows)
    return [rows[i * len(rows) // limit] for i in range(limit)]


def count_map(pairs: Iterable[tuple[str, int]], keys: Sequence[str]) -> dict[str, int]:
    """Counts for the known keys (zero when absent); anything unexpected is folded into `other` so totals stay honest."""
    out = dict.fromkeys(keys, 0)
    other = 0
    for key, n in pairs:
        if key in out:
            out[key] += int(n)
        else:
            other += int(n)
    if other:
        out["other"] = other
    return out


def decisions_by_route(pairs: Iterable[tuple[str, str, int]]) -> dict[str, int]:
    """(route, outcome, n) into auto (approved), ask_more, human and reject (auto and rejected)."""
    out = dict.fromkeys(DECISION_ROUTES, 0)
    for route, outcome, n in pairs:
        key = "reject" if route == "auto" and outcome == "rejected" else route
        out[key if key in out else "human"] += int(n)
    return out


def payments_shape(pairs: Iterable[tuple[str, int, int]]) -> dict[str, int]:
    """(status, count, amount) into sent (submitted or settled) and settled, counts and PKR sums."""
    sent = settled = sent_amount = settled_amount = 0
    for status, n, amount in pairs:
        if status in SENT_STATUSES:
            sent += int(n)
            sent_amount += int(amount)
        if status == "settled":
            settled += int(n)
            settled_amount += int(amount)
    return {"sent": sent, "sent_amount_pkr": sent_amount, "settled": settled, "settled_amount_pkr": settled_amount}


def scam_shape(pairs: Iterable[tuple[str, int]]) -> dict[str, int]:
    total = blocked = 0
    for label, n in pairs:
        total += int(n)
        if label in SCAM_LABELS:
            blocked += int(n)
    return {"reports": total, "blocked": blocked}


def headline(point: Mapping[str, Any], thresholds: Mapping[str, Any], floor: float) -> dict[str, Any]:
    return {
        "cases": int(point["n"]),
        "approved": int(point["approved"]),
        "rejected": int(point["rejected"]),
        "asked_for_proof": int(point["needs_proof"]),
        "sent_to_person": int(point["needs_human"]),
        "wrong_approvals": int(point["false_approvals"]),
        "wrong_rejections": int(point["false_rejections"]),
        "silent_guesses": 0,  # an invariant of the engine, asserted in decision tests; not measured here
        "thresholds": {"reject": float(thresholds["reject"]), "approve": float(thresholds["approve"]), "confidence_floor": float(floor)},
    }
