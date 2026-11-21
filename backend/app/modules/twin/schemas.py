"""Request and response shapes of the Digital Twin API (`/v1/twin`)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Page, Strict
from app.contracts.decision import CostMatrix
from app.modules.rules.schemas import DiffChange


class TwinRunIn(Strict):
    draft_version_id: UUID = Field(description="The rule version to try (usually a draft)")
    base_version_id: UUID | None = Field(default=None, description="Compare against this version; defaults to the active one")
    include_live: bool = Field(default=True, description="Replay the department's stored decisions")
    include_synthetic: bool = Field(default=True, description="Replay the labelled synthetic cases")


class ReasonIn(Strict):
    reason: str = Field(min_length=5, max_length=1000, description="Stored in the audit log")


class SliceRow(BaseModel):
    value: str
    n: int
    approve_rate_before: float
    approve_rate_after: float
    approve_change: float
    human_rate_before: float
    human_rate_after: float
    human_change: float
    noise: float = Field(description="Two standard errors of a slice this size changing at the overall rate")
    flagged: bool


class MistakeCounts(BaseModel):
    false_approvals: int
    false_rejections: int
    not_automatic_although_ok: int


class LabelledOut(BaseModel):
    realised_cost_before: float
    realised_cost_after: float
    realised_cost_change: float
    before: MistakeCounts
    after: MistakeCounts
    eligible_before: int
    eligible_after: int


class DatasetSummaryOut(BaseModel):
    n: int
    changed: int
    outcomes_before: dict[str, int]
    outcomes_after: dict[str, int]
    change: dict[str, int] = Field(description="After minus before, per outcome")
    transitions: dict[str, dict[str, int]] = Field(description="transitions[before][after] = number of cases")
    expected_cost_before: float
    expected_cost_after: float
    expected_cost_change: float
    expected_cost_change_per_case: float
    payout_before_pkr: int
    payout_after_pkr: int
    slices: dict[str, list[SliceRow]]
    flagged_slices: list[str]
    labelled: LabelledOut | None = Field(default=None, description="Synthetic cases only: realised cost and mistakes against the truth")
    skipped: int = Field(default=0, description="Stored decisions whose snapshot could not be read")
    base_differs_from_stored: int | None = Field(default=None, description="Live only: decisions the base version would now decide differently")


class CaseSide(BaseModel):
    outcome: str
    route: str
    p_ok: float
    expected_cost: float
    reasons: list[str]


class ChangedCaseOut(BaseModel):
    ref: str = Field(description="A synthetic case id, or a stored decision id (no names)")
    dataset: str
    slices: dict[str, str | None]
    before: CaseSide
    after: CaseSide


class TwinRunOut(BaseModel):
    id: UUID
    created_at: str
    status: str = Field(description="done | publishing | discarded")
    draft_version_id: UUID
    draft_version_no: int
    draft_status: str
    base_version_id: UUID | None
    base_version_no: int | None
    model_version: str
    costs: CostMatrix
    rule_changes: list[DiffChange]
    live: DatasetSummaryOut | None
    synthetic: DatasetSummaryOut | None
    sample: list[ChangedCaseOut]
    flagged_slices: list[str]
    side_effects: str = "None. Nothing was sent, paid, opened or decided; this run wrote only its own twin_runs row."
    decided_reason: str | None = None


class TwinRunSummary(BaseModel):
    id: UUID
    created_at: str
    status: str
    draft_version_id: UUID
    base_version_id: UUID | None
    changed_live: int | None = None
    changed_synthetic: int | None = None
    flagged_slices: list[str] = Field(default_factory=list)


class TwinRunList(Page):
    items: list[TwinRunSummary]
