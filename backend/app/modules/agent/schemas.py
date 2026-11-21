"""Typed inputs and outputs of the agent tools, and the API models. Inputs forbid extra fields: a call with a field the
schema does not know (an amount, free text for a citizen) is invalid before the guard ever sees it."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import DocumentKind, Strict

ReadToolName = Literal["get_case", "get_handoff", "explain_decision", "check_rules", "find_duplicates", "search_policy"]
ActionToolName = Literal["request_proof", "send_template_message", "approve_and_pay", "reject_with_reason", "escalate"]
ToolName = ReadToolName | ActionToolName
EscalateCode = Literal["integrity_flag", "needs_senior_review", "conflicting_signals"]
RejectCode = Literal["hard_rule_failed"]
TemplateName = Literal["person_will_check", "proof_needed"]

# --- inputs ---------------------------------------------------------------------------------------------


class NoArgs(Strict):
    pass


class SearchPolicyIn(Strict):
    query: str = Field(min_length=3, max_length=200)


class RequestProofIn(Strict):
    proof_kind: DocumentKind


class SendTemplateIn(Strict):
    template: TemplateName
    proof_kind: DocumentKind | None = None


class ApproveAndPayIn(Strict):
    """No amount and no payee: the amount comes from the rule version and the payee from the application."""


class RejectIn(Strict):
    reason_code: RejectCode = "hard_rule_failed"
    rule_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class EscalateIn(Strict):
    reason_code: EscalateCode = "needs_senior_review"


INPUTS: dict[str, type[Strict]] = {
    "get_case": NoArgs, "get_handoff": NoArgs, "explain_decision": NoArgs, "check_rules": NoArgs, "find_duplicates": NoArgs,
    "search_policy": SearchPolicyIn, "request_proof": RequestProofIn, "send_template_message": SendTemplateIn,
    "approve_and_pay": ApproveAndPayIn, "reject_with_reason": RejectIn, "escalate": EscalateIn,
}  # fmt: skip

# --- outputs of the read tools --------------------------------------------------------------------------


class GetCaseOut(BaseModel):
    case_id: str
    kind: str
    status: str
    opened_reason: str
    application_status: str | None
    allowed_actions: list[str]
    note_count: int = Field(description="Notes are data and are not repeated here")


class GetHandoffOut(BaseModel):
    understanding: str
    rule_fired: str | None
    hypotheses: list[dict[str, Any]]
    uncertain_fields: list[dict[str, str]]
    resolving_proof: str | None
    suggested_question: str | None
    expected_costs: dict[str, float]


class ExplainDecisionOut(BaseModel):
    outcome: str | None
    route: str | None
    reasons: list[str]
    guards: list[str]
    p_ok: float | None
    thresholds: dict[str, float | None]
    rule_version_no: int | None


class CheckRulesOut(BaseModel):
    rules: list[dict[str, Any]]
    hard_failed: list[str]
    hard_unknown: list[str]
    approval_supported: bool
    approval_blockers: list[str]
    reject_supported: bool
    payment_pkr: int | None = Field(description="From the rule version; the only amount that can ever be paid")


class FindDuplicatesOut(BaseModel):
    worst_band: str | None
    candidates: list[dict[str, Any]]


class PolicyCitation(BaseModel):
    document_id: str
    doc_key: str
    title: str
    version: int
    section_id: str
    section: str
    chunk_id: str


class SearchPolicyOut(BaseModel):
    answered: bool
    reason: str
    sentences: list[dict[str, Any]] = Field(default_factory=list, description="Copied from the policy text; each has a citation index")
    citations: list[PolicyCitation] = Field(default_factory=list)


class ActionOut(BaseModel):
    case_status: str
    application_status: str | None = None
    payment_status: str | None = None
    payment_pkr: int | None = None
    pending_second_approver: bool = False
    notification_template: str | None = None


# --- API ------------------------------------------------------------------------------------------------


class AgentDecisionOut(BaseModel):
    choice: str | None
    confidence: float
    abstained: bool
    route: str
    reasons: list[str]
    model_version: str


class PlannerOut(BaseModel):
    type: str
    model_version: str
    fallback_reason: str | None = None


class ApprovalOut(BaseModel):
    action: Literal["approved", "rejected"]
    by_user_id: UUID
    at: str
    reason: str


class StepOut(BaseModel):
    id: UUID
    ordinal: int
    tool: str
    kind: Literal["read", "action"]
    status: str = Field(description="done | waiting_approval | rejected | failed | blocked")
    requires_approval: bool
    args: dict[str, Any]
    rationale: str | None = None
    output: dict[str, Any]
    approval: ApprovalOut | None = None
    block_codes: list[str] = Field(default_factory=list)
    created_at: str


class RunOut(BaseModel):
    id: UUID
    case_id: UUID
    status: str = Field(description="running | waiting_approval | done | failed | cancelled")
    outcome: str = Field(description="proposed | abstained | proposal_blocked | approved | rejected | failed")
    planner: PlannerOut
    decision: AgentDecisionOut
    rationale: str | None
    flags: list[str] = Field(description="Instruction-like text found in case text and treated as data; staff only")
    step_budget: int
    steps_used: int
    steps: list[StepOut]
    reused: bool = False
    created_at: str
    updated_at: str


class RunList(BaseModel):
    items: list[RunOut]


class StepDecisionIn(Strict):
    reason: str = Field(min_length=5, max_length=1000, description="Why the officer approves or rejects this proposal; stored in the audit log")
