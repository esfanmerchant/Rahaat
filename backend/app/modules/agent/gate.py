"""Glue between the facts of a case and the action guard (guardrails/action_guard.py): one place builds the context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.modules.agent.facts import CaseFacts, approval_blockers, reject_blockers
from app.modules.guardrails.action_guard import ActionContext, ApprovalSource, Stage, check_action
from app.modules.guardrails.verdict import GuardVerdict


def context(
    stage: Stage, tool: str, args: Mapping[str, Any], facts: CaseFacts, *, role: str, steps_used: int, step_budget: int,
    step_status: str | None = None, approval_source: ApprovalSource = "none", approver_user_id: str | None = None,
    approver_role: str | None = None, four_eyes_limit_pkr: int | None = None, prior_case_approvers: tuple[str, ...] = (),
) -> ActionContext:  # fmt: skip
    return ActionContext(
        stage=stage, tool=tool, inputs=dict(args), acting_role=role, case_kind=facts.case_kind, case_status=facts.case_status,
        application_status=facts.application_status, allowed_case_actions=facts.allowed_actions,
        approval_supported=not approval_blockers(facts), reject_supported=not reject_blockers(facts),
        decision_matches_application=facts.decision_application_id is not None and facts.decision_application_id == facts.application_id,
        steps_used=steps_used, step_budget=step_budget, step_status=step_status, approval_source=approval_source,
        approver_role=approver_role, approver_user_id=approver_user_id, amount_pkr=facts.payment_pkr,
        four_eyes_limit_pkr=four_eyes_limit_pkr, prior_case_approvers=prior_case_approvers,
    )  # fmt: skip


def check(*args: Any, **kwargs: Any) -> GuardVerdict:
    return check_action(context(*args, **kwargs))
