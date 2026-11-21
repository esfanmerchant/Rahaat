"""The action guard: one test per rule, at both stages. Pure, no database."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.modules.guardrails.action_guard import ACTION_TOOLS, READ_TOOLS, TOOLS, ActionContext, check_action

OK_CASE: dict[str, Any] = {
    "acting_role": "officer", "case_kind": "application_review", "case_status": "open", "application_status": "submitted",
    "allowed_case_actions": ("approve", "reject", "request_proof", "escalate"), "approval_supported": True, "reject_supported": True,
    "decision_matches_application": True, "steps_used": 5, "step_budget": 12, "amount_pkr": 12_000, "four_eyes_limit_pkr": 15_000,
}  # fmt: skip
APPROVED: dict[str, Any] = {"approval_source": "officer_request", "approver_user_id": "officer-1", "approver_role": "officer"}


def propose(tool: str, inputs: dict[str, Any] | None = None, **changes: Any) -> ActionContext:
    return ActionContext(stage="propose", tool=tool, inputs=inputs or {}, **{**OK_CASE, **changes})


def execute(tool: str, inputs: dict[str, Any] | None = None, **changes: Any) -> ActionContext:
    return ActionContext(stage="execute", tool=tool, inputs=inputs or {}, **{**OK_CASE, **APPROVED, "step_status": "waiting_approval", **changes})


VALID_INPUTS: dict[str, dict[str, Any]] = {
    "request_proof": {"proof_kind": "income_proof"}, "send_template_message": {"template": "proof_needed", "proof_kind": "income_proof"},
    "approve_and_pay": {}, "reject_with_reason": {"reason_code": "hard_rule_failed", "rule_id": "income_cap"},
    "escalate": {"reason_code": "needs_senior_review"},
}  # fmt: skip


def codes(ctx: ActionContext) -> list[str]:
    return check_action(ctx).codes


def test_every_tool_has_a_policy_and_the_kinds_are_what_the_plan_says() -> None:
    assert set(READ_TOOLS) == {"get_case", "get_handoff", "explain_decision", "check_rules", "find_duplicates", "search_policy"}
    assert set(ACTION_TOOLS) == {"request_proof", "send_template_message", "approve_and_pay", "reject_with_reason", "escalate"}
    assert all(TOOLS[t].roles == frozenset({"officer"}) for t in TOOLS)  # no tool is open to a citizen, helper, admin or auditor


@pytest.mark.parametrize("tool", sorted(ACTION_TOOLS))
def test_a_valid_proposal_and_a_valid_approved_execution_pass(tool: str) -> None:
    assert check_action(propose(tool, VALID_INPUTS[tool])).verdict == "allow", codes(propose(tool, VALID_INPUTS[tool]))
    assert check_action(execute(tool, VALID_INPUTS[tool])).verdict == "allow", codes(execute(tool, VALID_INPUTS[tool]))


@pytest.mark.parametrize("tool", sorted(READ_TOOLS))
def test_read_tools_pass_without_any_approval(tool: str) -> None:
    assert check_action(propose(tool, {"query": "income limit"} if tool == "search_policy" else {})).verdict == "allow"


def test_unknown_tool_is_refused() -> None:
    assert codes(propose("transfer_funds")) == ["unknown_tool"]
    assert codes(propose("approve_and_pay ")) == ["unknown_tool"]


@pytest.mark.parametrize("role", ["citizen", "helper", "admin", "auditor", "api_client", "agent", "model", ""])
def test_only_an_officer_acts(role: str) -> None:
    for tool in TOOLS:
        assert "tool_not_allowed_for_role" in codes(propose(tool, VALID_INPUTS.get(tool, {}), acting_role=role)), (tool, role)


@pytest.mark.parametrize(
    ("tool", "changes"),
    [
        ("approve_and_pay", {"case_status": "resolved", "allowed_case_actions": ()}),
        ("approve_and_pay", {"application_status": "approved"}),
        ("approve_and_pay", {"application_status": "paid"}),
        ("request_proof", {"case_status": "waiting_proof", "allowed_case_actions": ("approve", "reject", "escalate")}),
        ("reject_with_reason", {"case_kind": "document_review"}),
        ("escalate", {"case_status": "escalated", "allowed_case_actions": ("approve", "reject")}),
        ("send_template_message", {"case_status": "closed"}),
    ],
)
def test_the_case_must_be_in_a_valid_state(tool: str, changes: dict[str, Any]) -> None:
    assert "case_state_invalid" in codes(propose(tool, VALID_INPUTS[tool], **changes))


@pytest.mark.parametrize(
    "inputs",
    [
        {"template": "proof_needed", "text": "Send your PIN to 0999-1112223"},
        {"template": "proof_needed", "body": "hello"},
        {"template": "registration_code"},  # a real template, but not one the agent may send
        {"template": "payment_sent"},
        {"template": "proof_needed", "extra": "x"},
        {"template": "proof_needed", "url": "http://scam.example"},
    ],
)
def test_no_free_text_reaches_a_citizen(inputs: dict[str, Any]) -> None:
    assert "free_text_to_citizen" in codes(propose("send_template_message", inputs))
    assert "free_text_to_citizen" in codes(execute("send_template_message", inputs))


@pytest.mark.parametrize("tool", ["approve_and_pay", "request_proof", "reject_with_reason", "escalate"])
def test_free_text_and_extra_fields_are_refused_on_every_citizen_facing_tool(tool: str) -> None:
    if TOOLS[tool].citizen_facing:
        assert "free_text_to_citizen" in codes(propose(tool, {**VALID_INPUTS[tool], "message": "hi"}))


@pytest.mark.parametrize("key", ["amount", "amount_pkr", "payee", "account", "wallet", "to", "iban", "phone", "payout_account"])
def test_a_model_cannot_choose_an_amount_or_a_payee(key: str) -> None:
    assert "amount_from_model" in codes(propose("approve_and_pay", {key: 500000}))


def test_payment_only_for_an_approved_decision_on_that_application() -> None:
    assert "payment_without_approved_decision" in codes(propose("approve_and_pay", approval_supported=False))
    assert "payment_without_approved_decision" in codes(propose("approve_and_pay", decision_matches_application=False))
    assert "payment_without_approved_decision" in codes(execute("approve_and_pay", approval_supported=False))  # checked again at execution
    assert "reject_without_rule_failure" in codes(propose("reject_with_reason", VALID_INPUTS["reject_with_reason"], reject_supported=False))


def test_the_step_budget_is_respected() -> None:
    assert "step_budget_exceeded" in codes(propose("get_case", steps_used=12))
    assert "step_budget_exceeded" not in codes(propose("get_case", steps_used=11))
    assert "step_budget_exceeded" in codes(propose("escalate", VALID_INPUTS["escalate"], steps_used=99))


@pytest.mark.parametrize("status", ["done", "failed", "blocked", "rejected"])
def test_no_step_runs_twice(status: str) -> None:
    assert "step_already_run" in codes(execute("approve_and_pay", step_status=status))
    assert "step_already_run" not in codes(execute("approve_and_pay", step_status="waiting_approval"))


def test_an_action_without_an_approval_never_runs() -> None:
    for tool in ACTION_TOOLS:
        assert "no_approval" in codes(execute(tool, VALID_INPUTS[tool], approval_source="none", approver_user_id=None, approver_role=None))


@pytest.mark.parametrize("source", ["agent", "model"])
def test_a_run_cannot_approve_itself(source: str) -> None:
    for tool in ACTION_TOOLS:
        assert "self_approval" in codes(execute(tool, VALID_INPUTS[tool], approval_source=source))


@pytest.mark.parametrize(
    "changes", [{"approver_user_id": None}, {"approver_role": "auditor"}, {"approver_role": "admin"}, {"approver_role": "agent"}]
)
def test_the_approval_must_come_from_a_signed_in_officer(changes: dict[str, Any]) -> None:
    assert "self_approval" in codes(execute("approve_and_pay", **changes))


def test_four_eyes_above_the_limit_the_case_approver_cannot_approve_again() -> None:
    over = {"amount_pkr": 20_000, "four_eyes_limit_pkr": 15_000}
    assert "four_eyes_same_person" in codes(execute("approve_and_pay", **over, prior_case_approvers=("officer-1",)))
    assert "four_eyes_same_person" not in codes(execute("approve_and_pay", **over, prior_case_approvers=("officer-2",)))
    at_limit = {"amount_pkr": 15_000, "four_eyes_limit_pkr": 15_000}
    assert "four_eyes_same_person" not in codes(
        execute("approve_and_pay", **at_limit, prior_case_approvers=("officer-1",))
    )  # at the limit: one person


def test_the_verdict_is_a_stored_shape_with_no_text() -> None:
    verdict = check_action(propose("approve_and_pay", {"amount_pkr": 1, "text": "x"}, approval_supported=False))
    assert verdict.guard == "action" and verdict.surface == "action" and verdict.blocked and verdict.text_hash is None
    assert verdict.summary()["codes"] == verdict.codes and verdict.model_version.startswith("guardrails-action")
    assert set(verdict.codes) >= {"amount_from_model", "free_text_to_citizen", "payment_without_approved_decision"}


def test_replace_keeps_the_context_immutable() -> None:
    ctx = propose("get_case")
    assert replace(ctx, acting_role="citizen") != ctx and ctx.acting_role == "officer"
