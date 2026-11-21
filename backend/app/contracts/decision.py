"""Decision contracts: the typed decision every AI component returns, cost matrix, trace, handoff, explanation.

See PLAN 6.1 (cost math), 6.2 (TypedDecision), 6.5 (handoff package).
"""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.contracts.common import DecisionOutcome, Route

T = TypeVar("T")


class TypedDecision(BaseModel, Generic[T]):
    """Our Jev-equivalent: classify, score, and route. A component that is unsure abstains; it never guesses."""

    choice: T | None = Field(description="None when the component abstained")
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0, description="Calibrated probability of the chosen class")
    route: Route
    reasons: list[str] = Field(default_factory=list, description="Reason codes, never free text")
    model_version: str
    abstained: bool = False

    @model_validator(mode="after")
    def _abstain_is_consistent(self) -> TypedDecision[T]:
        if self.abstained and self.route == "auto":
            raise ValueError("an abstained decision cannot be routed 'auto'")
        if self.choice is None and not self.abstained:
            raise ValueError("a decision without a choice must be marked abstained")
        return self


class CostMatrix(BaseModel):
    """Per-tenant costs in units (1 unit is about Rs 120). Admin-editable; thresholds derive from it."""

    wrong_approve: float = Field(default=100.0, gt=0)
    wrong_reject: float = Field(default=30.0, gt=0)
    human_review: float = Field(default=3.0, gt=0)
    ask_proof: float = Field(default=1.0, ge=0)
    delay_per_day: float = Field(default=0.2, ge=0)

    def human_cost(self, queue_days: float = 1.0) -> float:
        return self.human_review + self.delay_per_day * queue_days

    def approve_threshold(self, queue_days: float = 1.0) -> float:
        """Approve alone only when p_ok is at least this."""
        return max(0.0, 1.0 - self.human_cost(queue_days) / self.wrong_approve)

    def reject_threshold(self, queue_days: float = 1.0) -> float:
        """Reject alone only on a verified hard-rule failure and p_ineligible at least this."""
        return max(0.0, 1.0 - self.human_cost(queue_days) / self.wrong_reject)


RuleResult = Literal["pass", "fail", "unknown"]


class RuleTraceItem(BaseModel):
    rule_id: str
    hard: bool
    result: RuleResult
    values_used: dict[str, Any] = Field(default_factory=dict)
    verified_inputs: bool = Field(default=False, description="True when every value came from a signed QR or the registry")
    label_en: str | None = None
    label_ur: str | None = None


class UncertainField(BaseModel):
    field: str
    value: Any | None = None
    confidence: float
    why: str = Field(description="Reason code, e.g. ocr_low_confidence, declared_not_verified, missing")


class Hypothesis(BaseModel):
    label: str
    probability: float


class HandoffPackage(BaseModel):
    """What a human needs to pick the case up without starting again."""

    question: str = Field(description="What the system was asked to decide")
    understanding: str = Field(description="What the system believes so far, in plain words")
    uncertain_fields: list[UncertainField] = Field(default_factory=list)
    rule_fired: str | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list, description="Top two, with probabilities")
    resolving_proof: str | None = Field(default=None, description="The single proof that would lower expected cost the most")
    suggested_question: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict, description="OCR text, transcript, document ids")
    expected_costs: dict[str, float] = Field(default_factory=dict)
    guards: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """The citizen's view: one to three short sentences from templates, keyed by reason code."""

    reason_codes: list[str]
    lang: str
    sentences: list[str] = Field(max_length=3)
    next_step: str | None = None
    ask_a_person: bool = True
    audio_keys: list[str] = Field(default_factory=list, description="Pre-generated audio files to play, in order")
    pictogram: str | None = None


class DecisionUserView(BaseModel):
    """What the citizen sees. No scores, no thresholds, no detection details."""

    decision_id: str
    outcome: DecisionOutcome
    route: Route
    explanation: Explanation
    rule_version_no: int
    decided_at: str


class DecisionTrace(BaseModel):
    """The auditor's view: everything needed to check and to replay the decision."""

    decision_id: str
    application_id: str
    route: Route
    outcome: DecisionOutcome
    rule_version_id: str
    rule_version_no: int
    model_version: str
    engine_version: str
    input_hash: str
    result_hash: str | None = None
    input_snapshot: dict[str, Any] = Field(description="Identifiers hashed or masked according to the viewer's access")
    rule_trace: list[RuleTraceItem]
    probabilities: dict[str, float]
    p_ok: float | None
    cost_matrix: CostMatrix
    expected_costs: dict[str, float]
    thresholds: dict[str, float]
    reasons: list[str]
    guards: list[str]
    guardrails: dict[str, Any] = Field(default_factory=dict)
    handoff: HandoffPackage | None = None
    human_reviews: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: int | None = None
    request_id: str | None = None
    decided_at: str


class ReplayResult(BaseModel):
    decision_id: str
    match: bool
    stored_result_hash: str | None
    replayed_result_hash: str
    differences: list[str] = Field(default_factory=list)
