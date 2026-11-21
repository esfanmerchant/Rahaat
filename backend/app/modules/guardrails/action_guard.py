"""Action guard: may this tool call be proposed, and may it run now? Pure function, checked twice (PLAN 7.C, C11).

The agent proposes a call, the guard looks at it (stage `propose`); an officer approves it and the guard looks
again with fresh facts (stage `execute`). Every refusal carries reason codes and the caller stores the verdict
(`service.record` writes the audit row), so a refusal is never silent.

What the guard enforces:

| code | rule |
|---|---|
| unknown_tool | the tool is not in the registry |
| tool_not_allowed_for_role | the acting role may not use this tool (the auditor reads only; the agent never acts as a citizen) |
| case_state_invalid | the case or application is in a state where the tool cannot apply |
| free_text_to_citizen | a citizen-facing tool carries free text or a field outside its schema; templates only |
| amount_from_model | a payment tool carries an amount or a payee; the amount comes from the rules |
| payment_without_approved_decision | approve_and_pay without a decision and rules that support approval, on this application |
| reject_without_rule_failure | reject_with_reason without a failed hard rule |
| step_budget_exceeded | the run has used its budget |
| step_already_run | the step already ran (idempotency) |
| no_approval | an action tool at execute stage without an approval |
| self_approval | the approval did not come from a signed-in officer's own request |
| four_eyes_same_person | above the payment limit, the officer who already approved the case approves it again |
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

from app.modules.guardrails.verdict import GuardVerdict

MODEL_VERSION: Final = "guardrails-action-v1"
Stage = Literal["propose", "execute"]
ApprovalSource = Literal["none", "officer_request", "agent", "model"]


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    kind: Literal["read", "action"]
    roles: frozenset[str]
    citizen_facing: bool = False


_STAFF = frozenset({"officer"})
TOOLS: Final[dict[str, ToolPolicy]] = {
    "get_case": ToolPolicy("read", _STAFF),
    "get_handoff": ToolPolicy("read", _STAFF),
    "explain_decision": ToolPolicy("read", _STAFF),
    "check_rules": ToolPolicy("read", _STAFF),
    "find_duplicates": ToolPolicy("read", _STAFF),
    "search_policy": ToolPolicy("read", _STAFF),
    "request_proof": ToolPolicy("action", _STAFF, citizen_facing=True),
    "send_template_message": ToolPolicy("action", _STAFF, citizen_facing=True),
    "approve_and_pay": ToolPolicy("action", _STAFF, citizen_facing=True),
    "reject_with_reason": ToolPolicy("action", _STAFF, citizen_facing=True),
    "escalate": ToolPolicy("action", _STAFF),
}
READ_TOOLS: Final = tuple(n for n, p in TOOLS.items() if p.kind == "read")
ACTION_TOOLS: Final = tuple(n for n, p in TOOLS.items() if p.kind == "action")

# Fields a citizen-facing tool may carry. Anything else, or any key that looks like prose, is refused.
ALLOWED_FIELDS: Final[dict[str, frozenset[str]]] = {
    "request_proof": frozenset({"proof_kind"}),
    "send_template_message": frozenset({"template", "proof_kind"}),
    "approve_and_pay": frozenset(),
    "reject_with_reason": frozenset({"reason_code", "rule_id"}),
    "escalate": frozenset({"reason_code"}),
}
FREE_TEXT_KEYS: Final = frozenset({"text", "body", "message", "sms", "content", "note", "note_to_citizen", "reply", "html", "url", "link"})
PAYMENT_KEYS: Final = frozenset({"amount", "amount_pkr", "payee", "account", "wallet", "to", "iban", "phone", "payout_account"})
ALLOWED_TEMPLATES: Final = frozenset({"person_will_check", "proof_needed"})  # keyed, fixed wording, ends with a verify code
# Case actions each tool maps to, and the application states in which that case action is reviewable.
CASE_ACTION: Final[dict[str, str]] = {"request_proof": "request_proof", "approve_and_pay": "approve", "reject_with_reason": "reject",
                                      "escalate": "escalate"}  # fmt: skip
REVIEWABLE_APPLICATION: Final = frozenset({"submitted", "in_review", "needs_proof"})
OFFICER_ROLES: Final = frozenset({"officer"})


@dataclass(frozen=True, slots=True)
class ActionContext:
    stage: Stage
    tool: str
    inputs: Mapping[str, object] = field(default_factory=dict)
    acting_role: str = ""
    # case and application, read fresh at this stage
    case_kind: str = ""
    case_status: str = ""
    application_status: str | None = None
    allowed_case_actions: tuple[str, ...] = ()
    # facts that support or do not support an action, computed from the decision trace and the rules
    approval_supported: bool = False
    reject_supported: bool = False
    decision_matches_application: bool = False
    # the run
    steps_used: int = 0
    step_budget: int = 12
    step_status: str | None = None  # the stored step at execute stage
    # the approval (execute stage)
    approval_source: ApprovalSource = "none"
    approver_role: str | None = None
    approver_user_id: str | None = None
    # four eyes
    amount_pkr: int | None = None
    four_eyes_limit_pkr: int | None = None
    prior_case_approvers: tuple[str, ...] = ()


def _inputs_codes(ctx: ActionContext, policy: ToolPolicy) -> list[str]:
    codes: list[str] = []
    keys = {str(k).lower() for k in ctx.inputs}
    if policy.kind == "action" and keys & PAYMENT_KEYS:
        codes.append("amount_from_model")
    if policy.citizen_facing:
        allowed = ALLOWED_FIELDS.get(ctx.tool, frozenset())
        if keys & FREE_TEXT_KEYS or (keys - allowed - PAYMENT_KEYS):
            codes.append("free_text_to_citizen")
        template = ctx.inputs.get("template")
        if ctx.tool == "send_template_message" and template not in ALLOWED_TEMPLATES:
            codes.append("free_text_to_citizen")
    return codes


def _state_codes(ctx: ActionContext) -> list[str]:
    needed = CASE_ACTION.get(ctx.tool)
    codes: list[str] = []
    if ctx.case_kind != "application_review" and ctx.tool in CASE_ACTION and ctx.tool != "escalate":
        codes.append("case_state_invalid")
    elif needed is not None and needed not in ctx.allowed_case_actions:
        codes.append("case_state_invalid")
    elif ctx.tool == "send_template_message" and ctx.case_status in ("resolved", "closed"):
        codes.append("case_state_invalid")
    if (ctx.tool in ("request_proof", "approve_and_pay", "reject_with_reason") and ctx.application_status is not None
            and ctx.application_status not in REVIEWABLE_APPLICATION):  # fmt: skip
        codes.append("case_state_invalid")
    return codes


def check_action(ctx: ActionContext) -> GuardVerdict:
    """Allow or block one tool call at one stage. Blocking is the default for anything not understood."""
    policy = TOOLS.get(ctx.tool)
    if policy is None:
        return _verdict(ctx, ["unknown_tool"])
    codes: list[str] = []
    if ctx.acting_role not in policy.roles:
        codes.append("tool_not_allowed_for_role")
    codes += _inputs_codes(ctx, policy)
    if ctx.steps_used >= ctx.step_budget and ctx.stage == "propose":
        codes.append("step_budget_exceeded")
    if ctx.stage == "execute" and ctx.step_status in ("done", "failed", "blocked", "rejected"):
        codes.append("step_already_run")
    if policy.kind == "action":
        codes += _state_codes(ctx)
        if ctx.tool == "approve_and_pay" and not (ctx.approval_supported and ctx.decision_matches_application):
            codes.append("payment_without_approved_decision")
        if ctx.tool == "reject_with_reason" and not ctx.reject_supported:
            codes.append("reject_without_rule_failure")
        if ctx.stage == "execute":
            codes += _approval_codes(ctx)
    return _verdict(ctx, codes)


def _approval_codes(ctx: ActionContext) -> list[str]:
    if ctx.approval_source == "none":
        return ["no_approval"]
    codes: list[str] = []
    if ctx.approval_source != "officer_request" or not ctx.approver_user_id or ctx.approver_role not in OFFICER_ROLES:
        codes.append("self_approval")  # model, agent, or anybody who is not a signed-in officer asking for this step
    over_limit = ctx.amount_pkr is not None and ctx.four_eyes_limit_pkr is not None and ctx.amount_pkr > ctx.four_eyes_limit_pkr
    if ctx.tool == "approve_and_pay" and over_limit and ctx.approver_user_id and ctx.approver_user_id in ctx.prior_case_approvers:
        codes.append("four_eyes_same_person")
    return codes


def _verdict(ctx: ActionContext, codes: list[str]) -> GuardVerdict:
    unique = list(dict.fromkeys(codes))
    return GuardVerdict(guard="action", surface="action", verdict="block" if unique else "allow", codes=unique, model_version=MODEL_VERSION)
