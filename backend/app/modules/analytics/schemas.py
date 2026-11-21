"""Response shapes of the impact report."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Assumption(BaseModel):
    name: str
    value: float
    unit: str
    used_for: str
    label: str = "assumed"


class HandoffOut(BaseModel):
    decisions: int
    by_route: dict[str, int]
    rate: dict[str, float | None]
    handoff_rate: float | None = Field(description="Share of decisions sent to a person")
    not_automatic_rate: float | None = Field(description="Share not decided automatically (asked for proof or sent to a person)")
    silent_guesses: int = Field(description="Automatic decisions that break the invariant; must be 0")


class DurationOut(BaseModel):
    n: int
    median_seconds: float | None
    p90_seconds: float | None


class TimeToDecisionOut(BaseModel):
    automatic: DurationOut = Field(description="Submission to decision, from the application's and the decision's timestamps")
    automatic_engine_latency_ms_p50: float | None
    human_case: DurationOut = Field(description="Case opened to resolved, application-linked cases")
    human_review_hands_on: DurationOut = Field(description="Officer's first look to action (review_seconds)")
    human_case_by_kind: dict[str, DurationOut]


class FraudOut(BaseModel):
    forged_cards_flagged: int = Field(description="Decisions where the document check raised the suspect-document guard")
    identity_mismatches: int
    duplicates_caught: int = Field(description="Decisions held by a duplicate guard")
    duplicate_candidates: int = Field(description="Person pairs the matcher put in the same or possible band")
    duplicates_linked_by_a_person: int
    scams_flagged: int = Field(description="Checked messages the scam classifier labelled as a scam type (flagged, not proven)")
    scams_confirmed_by_a_person: int
    anomaly_cases: dict[str, int]
    payments_stopped: int = Field(description="Payments cancelled or reversed")
    payments_stopped_pkr: int
    held_for_a_person_by_a_guard: int


class PaymentsOut(BaseModel):
    count: int
    amount_pkr: int
    by_status: dict[str, dict[str, int]]
    settled_pkr: int
    average_pkr: float | None


class CostOut(BaseModel):
    decisions: int
    per_claim_units: float | None
    all_to_a_person_per_claim_units: float | None
    units_saved_per_claim: float | None
    per_claim_pkr_assumed: float | None


class TimeSavedOut(BaseModel):
    automatic_decisions: int
    minutes_per_manual_review_used: float
    hands_on_source: str
    hands_on_hours_saved: float
    waiting_hours_avoided: float | None
    label: str


class ReplayOut(BaseModel):
    synthetic: bool = True
    label: str
    cases: int | None = None
    accuracy_of_automatic: float | None = None
    false_approvals: int | None = None
    false_rejections: int | None = None
    unnecessary_handoffs: int | None = None
    abstention_rate: float | None = None
    cost_per_case: float | None = None
    all_human_cost_per_case: float | None = None
    ece: float | None = None
    stored_run: bool | None = None


class ImpactOut(BaseModel):
    generated_at: str
    window_days: int
    department: str
    handoff: HandoffOut
    time_to_decision: TimeToDecisionOut
    fraud_stopped: FraudOut
    cost_per_claim: CostOut
    payments: PaymentsOut
    time_saved: TimeSavedOut
    replay: ReplayOut
    assumptions: list[Assumption]
    measured_from: dict[str, Any] = Field(description="Row counts behind each block, so a reader can see how much data there is")
    notes: list[str]
