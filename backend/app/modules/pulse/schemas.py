"""Response shapes of the public pulse. Counts, sums and synthetic rows only."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PaymentsOut(BaseModel):
    sent: int
    sent_amount_pkr: int
    settled: int
    settled_amount_pkr: int


class ScamOut(BaseModel):
    reports: int
    blocked: int


class LiveOut(BaseModel):
    applications_by_status: dict[str, int]
    decisions_by_route: dict[str, int] = Field(description="auto (approved), ask_more, human and reject (hard-rule rejection)")
    payments: PaymentsOut
    scam: ScamOut
    audit_chain_length: int
    departments: int


class ThresholdsOut(BaseModel):
    reject: float
    approve: float
    confidence_floor: float


class HeadlineOut(BaseModel):
    cases: int
    approved: int
    rejected: int
    asked_for_proof: int
    sent_to_person: int
    wrong_approvals: int
    wrong_rejections: int
    silent_guesses: int
    thresholds: ThresholdsOut


class ReplayCase(BaseModel):
    route: str = Field(description="auto | ask_more | human; an auto case with outcome rejected is a hard-rule rejection")
    outcome: str
    p_ok: float
    correct: bool = Field(description="An automatic outcome matched the label. Deferrals to proof or a person are never counted wrong.")
    reason_code: str
    kind: str = Field(description="Synthetic case kind: a fraud type, eligible_and_genuine, not_eligible or not_genuine")


class ReplayOut(BaseModel):
    available: bool
    replay_source: str
    rule_version_no: int | None
    model_version: str | None
    cases_scored: int
    cases: list[ReplayCase]
    headline: HeadlineOut | None


class PulseOut(BaseModel):
    generated_at: str
    cache_seconds: int
    notice: str
    live: LiveOut
    replay: ReplayOut
    elapsed_ms: int
