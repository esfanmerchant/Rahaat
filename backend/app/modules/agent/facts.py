"""CaseFacts: everything a planner may look at, and the pure functions that say what the facts support.

`untrusted` holds the free text of the case (OCR text, officer notes, transcripts, message text). It is carried
so a hosted planner can be shown it inside clearly delimited data fields, and so the input guard can scan it. The
local planner never reads it, and neither do `approval_blockers` or `reject_blockers`: free text cannot change what
the facts support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal

from app.contracts.api import CaseDetail

ACTIVE_CASE: Final = frozenset({"open", "assigned", "in_review", "escalated", "waiting_proof"})
REVIEWABLE_APPLICATION: Final = frozenset({"submitted", "in_review", "needs_proof"})
INTEGRITY_GUARDS: Final = frozenset({"document_suspect", "card_id_mismatch", "identity_mismatch", "duplicate_record", "possible_duplicate",
                                     "anomaly_flag"})  # fmt: skip
CONFLICT_GUARDS: Final = frozenset({"verified_sources_disagree"})
WAIT_GUARDS: Final = frozenset({"registry_unavailable", "consent_missing"})
DUPLICATE_BANDS: Final = frozenset({"same", "possible"})
# Engine reason codes that mean "the rule result is not settled yet": the engine itself would not approve on them.
UNSETTLED_REASONS: Final = ("rule_pass_below_floor", "rule_fail_below_floor", "rule_unknown", "rule_pass_unverified", "ask_proof")
TIE_MARGIN: Final = 0.10
REJECT_P_OK_MAX: Final = 0.5
UntrustedSource = Literal["ocr", "note", "transcript", "message", "evidence"]


@dataclass(frozen=True, slots=True)
class RuleFact:
    rule_id: str
    hard: bool
    result: str  # pass | fail | unknown
    verified: bool


@dataclass(frozen=True, slots=True)
class UntrustedText:
    source: UntrustedSource
    text: str


@dataclass(frozen=True, slots=True)
class CaseFacts:
    case_id: str
    case_kind: str
    case_status: str
    opened_reason: str
    application_status: str | None
    allowed_actions: tuple[str, ...]
    decision_id: str | None = None
    decision_application_id: str | None = None
    application_id: str | None = None
    decision_outcome: str | None = None
    decision_route: str | None = None
    p_ok: float | None = None
    approve_threshold: float | None = None
    reject_threshold: float | None = None
    rule_version_no: int | None = None
    rules: tuple[RuleFact, ...] = ()
    guards: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    resolving_proof: str | None = None
    suggested_question: str | None = None
    understanding: str = ""
    hypotheses: tuple[tuple[str, float], ...] = ()
    uncertain_fields: tuple[tuple[str, str], ...] = ()  # (field, reason code)
    expected_costs: tuple[tuple[str, float], ...] = ()
    duplicate_band: str | None = None  # same | possible | distinct | None (not compared)
    document_suspect: bool = False
    payment_pkr: int | None = None  # from the rule version, never from a model
    payment_exists: bool = False
    note_count: int = 0
    untrusted: tuple[UntrustedText, ...] = field(default=(), compare=False)

    @property
    def hard_failed(self) -> tuple[RuleFact, ...]:
        return tuple(r for r in self.rules if r.hard and r.result == "fail")


def from_detail(detail: CaseDetail, *, application_status: str | None, application_id: str | None, duplicate_band: str | None,
                payment_pkr: int | None, payment_exists: bool) -> CaseFacts:  # fmt: skip
    """Build the facts from the officer's case view. Pure: the caller reads the database."""
    trace = detail.decision
    handoff = detail.handoff
    untrusted: list[UntrustedText] = []
    for check in detail.document_checks:
        if check.ocr.raw_text:
            untrusted.append(UntrustedText("ocr", check.ocr.raw_text))
    for note in detail.notes:
        untrusted.append(UntrustedText("note", note.body))
    if handoff is not None:
        for key, value in handoff.evidence.items():
            source: UntrustedSource = "transcript" if "transcript" in key else "ocr" if "ocr" in key else "evidence"
            for text in [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else []:
                if text.strip():
                    untrusted.append(UntrustedText(source, text))
    thresholds = trace.thresholds if trace else {}
    return CaseFacts(
        case_id=str(detail.id), case_kind=detail.kind, case_status=detail.status, opened_reason=detail.opened_reason,
        application_status=application_status, allowed_actions=tuple(detail.allowed_actions),
        decision_id=trace.decision_id if trace else None, decision_application_id=trace.application_id if trace else None,
        application_id=application_id, decision_outcome=trace.outcome if trace else None, decision_route=trace.route if trace else None,
        p_ok=trace.p_ok if trace else None, approve_threshold=thresholds.get("approve"), reject_threshold=thresholds.get("reject"),
        rule_version_no=trace.rule_version_no if trace else None,
        rules=tuple(RuleFact(t.rule_id, t.hard, t.result, t.verified_inputs) for t in (trace.rule_trace if trace else [])),
        guards=tuple(trace.guards) if trace else (), reasons=tuple(trace.reasons) if trace else (),
        resolving_proof=handoff.resolving_proof if handoff else None, suggested_question=handoff.suggested_question if handoff else None,
        understanding=handoff.understanding if handoff else "",
        hypotheses=tuple((h.label, h.probability) for h in (handoff.hypotheses if handoff else [])),
        uncertain_fields=tuple((u.field, u.why) for u in (handoff.uncertain_fields if handoff else [])),
        expected_costs=tuple(sorted((handoff.expected_costs if handoff else {}).items())),
        duplicate_band=duplicate_band,
        document_suspect=any(c.authenticity.choice == "suspect" for c in detail.document_checks),
        payment_pkr=payment_pkr, payment_exists=payment_exists, note_count=len(detail.notes), untrusted=tuple(untrusted),
    )  # fmt: skip


# --- what the facts support ------------------------------------------------------------------------------


def risk_flags(facts: CaseFacts) -> list[str]:
    """Signals that a person must look at the integrity of the case before any money moves."""
    flags = [f"guard:{g}" for g in facts.guards if g in INTEGRITY_GUARDS]
    if facts.document_suspect:
        flags.append("document_suspect")
    if facts.duplicate_band in DUPLICATE_BANDS:
        flags.append(f"duplicate:{facts.duplicate_band}")
    return list(dict.fromkeys(flags))


def approval_blockers(facts: CaseFacts) -> list[str]:
    """Why approve_and_pay is not supported. Empty means the trace and the rules support it."""
    blockers: list[str] = []
    if facts.decision_id is None or facts.decision_outcome is None:
        return ["no_decision"]
    if facts.decision_application_id != facts.application_id:
        blockers.append("decision_for_other_application")
    if facts.decision_outcome in ("rejected", "needs_proof"):
        blockers.append("decision_is_reject" if facts.decision_outcome == "rejected" else "engine_asked_for_proof")
    blockers += [f"engine_not_settled:{r.split('.')[0]}" for r in facts.reasons if r.startswith(UNSETTLED_REASONS)]
    blockers += [f"guard:{g}" for g in facts.guards]
    blockers += risk_flags(facts)
    if not facts.rules:
        blockers.append("no_rule_trace")
    for rule in facts.rules:
        if not rule.hard:
            continue
        if rule.result != "pass":
            blockers.append(f"hard_rule_{rule.result}:{rule.rule_id}")
        elif not rule.verified:
            blockers.append(f"hard_rule_unverified:{rule.rule_id}")
    if facts.p_ok is None or facts.approve_threshold is None or facts.p_ok < facts.approve_threshold:
        blockers.append("p_ok_below_threshold")
    if not facts.payment_pkr or facts.payment_pkr <= 0:
        blockers.append("no_payment_amount")
    if facts.application_status not in REVIEWABLE_APPLICATION:
        blockers.append("application_not_reviewable")
    if facts.payment_exists:
        blockers.append("already_paid")
    return list(dict.fromkeys(blockers))


def reject_blockers(facts: CaseFacts) -> list[str]:
    """Why reject_with_reason is not supported: it needs a verified failed hard rule that the engine stands behind."""
    if facts.decision_id is None:
        return ["no_decision"]
    blockers: list[str] = []
    failed = facts.hard_failed
    if not failed:
        blockers.append("no_failed_hard_rule")
    if any(not r.verified for r in failed):
        blockers.append("failure_not_verified")
    if not any(reason.startswith("rule_failed.") for reason in facts.reasons):
        blockers.append("engine_does_not_stand_behind_failure")
    if any(r.rule_id == "identity_verified" and r.result != "pass" for r in facts.rules):
        blockers.append("identity_not_confirmed")
    if facts.p_ok is None or facts.p_ok > REJECT_P_OK_MAX:
        blockers.append("model_disagrees")
    blockers += [f"guard:{g}" for g in facts.guards] + risk_flags(facts)
    if facts.application_status not in REVIEWABLE_APPLICATION:
        blockers.append("application_not_reviewable")
    return list(dict.fromkeys(blockers))


def hypotheses_tied(facts: CaseFacts) -> bool:
    ranked = sorted((p for _, p in facts.hypotheses), reverse=True)
    return len(ranked) >= 2 and ranked[0] - ranked[1] < TIE_MARGIN
