"""Request and response shapes of the evaluation API (`/v1/evals`, `/v1/cost-matrix`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Page, Strict
from app.contracts.decision import CostMatrix


class CostMatrixIn(Strict):
    """Costs in units (1 unit is about Rs 120). The thresholds follow from these; none is set by hand."""

    wrong_approve: float = Field(default=100.0, gt=0, le=100_000, description="A payment to someone not eligible or not genuine")
    wrong_reject: float = Field(default=30.0, gt=0, le=100_000, description="An eligible family denied")
    human_review: float = Field(default=3.0, gt=0, le=10_000, description="One officer review")
    ask_proof: float = Field(default=1.0, ge=0, le=10_000, description="One more step for the citizen")
    delay_per_day: float = Field(default=0.2, ge=0, le=10_000, description="Each day of waiting")

    def matrix(self) -> CostMatrix:
        return CostMatrix(**self.model_dump())


class CostMatrixSave(CostMatrixIn):
    reason: str = Field(min_length=5, max_length=1000, description="Stored in the audit log")


class ThresholdsOut(BaseModel):
    approve: float
    reject: float
    queue_days: float = 1.0
    approve_formula: str | None = None
    reject_formula: str | None = None


class CostMatrixOut(BaseModel):
    costs: CostMatrix
    thresholds: ThresholdsOut
    eval_run_id: UUID | None = Field(default=None, description="The analysis stored for this matrix, when one was made")


class OperatingPointOut(BaseModel):
    n: int
    approved: int
    rejected: int
    needs_proof: int
    needs_human: int
    auto_rate: float
    false_approvals: int
    false_approve_rate: float
    false_approve_share_of_approvals: float
    false_rejections: int
    false_reject_rate: float
    unnecessary_handoffs: int = Field(description="Eligible and genuine cases sent to a person")
    unnecessary_handoff_rate: float
    unnecessary_proof_requests: int = Field(description="Eligible and genuine cases asked for one more proof")
    unnecessary_proof_request_rate: float
    not_automatic_although_ok: int
    not_automatic_although_ok_rate: float
    cost_per_case: float
    all_human_cost_per_case: float
    saving_per_case: float
    silent_guesses: int
    cost_of_false_approvals: float
    cost_of_false_rejections: float
    cost_of_unnecessary_handoffs: float


class ConfusionOut(BaseModel):
    rows: list[str] = Field(description="Truth: eligible_and_genuine | not_eligible | not_genuine")
    columns: list[str] = Field(description="Outcome: approved | rejected | needs_proof | needs_human")
    counts: dict[str, dict[str, int]]


class CostCurvePoint(BaseModel):
    threshold: float
    cost_per_case: float
    approvals: int
    false_approvals: int


class BestThresholdOut(BaseModel):
    threshold: float
    cost_per_case: float


class RocPoint(BaseModel):
    threshold: float
    tpr: float
    fpr: float


class PrPoint(BaseModel):
    threshold: float
    precision: float
    recall: float


class ReliabilityBin(BaseModel):
    bin: int
    low: float
    high: float
    count: int
    mean_predicted: float | None = None
    observed_rate: float | None = None


class ReliabilityOut(BaseModel):
    bins: list[ReliabilityBin]
    ece: float
    brier: float
    auc: float | None = None
    n: int


class DatasetOut(BaseModel):
    name: str
    seed: int
    persons: int
    cases: int
    families: int
    eligible_and_genuine: int
    not_genuine: int
    held_out: bool
    note: str


class DecisionAnalysisOut(BaseModel):
    """Everything the cost page shows: thresholds, the operating point, curves and calibration."""

    run_id: UUID | None = Field(default=None, description="Set when this analysis is a stored eval run")
    stored: bool
    created_at: str | None = None
    rule_version_id: UUID | None = None
    rule_version_no: int | None = None
    model_version: str
    costs: CostMatrix
    thresholds: ThresholdsOut
    operating_point: OperatingPointOut
    confusion: ConfusionOut
    cost_curve: list[CostCurvePoint]
    best_threshold: BestThresholdOut
    roc: list[RocPoint] = Field(description="p_ok as the approve signal, over cases the rules let it approve")
    roc_auc: float | None = None
    pr: list[PrPoint]
    average_precision: float | None = None
    approvable_cases: int
    reliability: ReliabilityOut
    explanation: str = Field(description="Why the chosen operating point wins, from the numbers")
    dataset: DatasetOut
    elapsed_ms: int | None = None


class EvalRunSummary(BaseModel):
    id: UUID
    kind: str
    created_at: str
    model_version: str | None = None
    rule_version_id: UUID | None = None
    metrics: dict[str, Any]


class EvalRunList(Page):
    items: list[EvalRunSummary]


class RunIn(Strict):
    note: str | None = Field(default=None, max_length=500)
