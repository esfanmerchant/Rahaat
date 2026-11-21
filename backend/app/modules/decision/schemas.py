"""Response shapes of the decision API (`/v1/decisions`)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Page
from app.contracts.decision import DecisionTrace, DecisionUserView


class DecisionView(BaseModel):
    """One decision: what the citizen was told, and the full trace (masked for auditors)."""

    user_view: DecisionUserView
    trace: DecisionTrace
    case_id: UUID | None = None
    replay_available: bool = Field(description="The pinned model version is loaded, so POST .../replay can recompute it exactly")


class DecisionSummary(BaseModel):
    """A row of the decision list. No names, identifiers or snapshot."""

    id: UUID
    application_id: UUID
    case_id: UUID | None = None
    created_at: str
    decided_at: str
    route: str = Field(description="auto | ask_more | human")
    outcome: str = Field(description="approved | rejected | needs_proof | needs_human")
    rule_version_id: UUID
    rule_version_no: int | None = None
    model_version: str
    engine_version: str
    p_ok: float | None = None
    guards: list[str] = Field(default_factory=list)
    main_reason: str | None = None
    expected_cost: float | None = Field(default=None, description="Expected cost of the action taken, in cost units")
    latency_ms: int | None = None
    ask_proof: str | None = None


class DecisionList(Page):
    items: list[DecisionSummary]
