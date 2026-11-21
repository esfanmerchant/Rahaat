"""Evaluation of the local planner: agreement with the golden labels, the abstain rate, and that nothing runs without approval.

    uv run python -m app.modules.agent.evaluate

Numbers go into docs/EVAL_REPORT.md. See golden.py for what the labels are (and are not).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.modules.agent import redteam
from app.modules.agent.gate import check
from app.modules.agent.golden import golden_cases
from app.modules.agent.planner import plan_local
from app.modules.guardrails.action_guard import ACTION_TOOLS


def evaluate() -> dict[str, Any]:
    cases = golden_cases()
    rows: list[dict[str, Any]] = []
    for name, facts, expect in cases:
        plan = plan_local(facts)
        got = plan.action.tool if plan.action else "abstain"
        rows.append({"case": name, "expected": expect, "got": got, "match": got == expect, "reasons": plan.decision.reasons})
    n = len(rows)
    expected_actions = [r for r in rows if r["expected"] != "abstain"]
    expected_abstain = [r for r in rows if r["expected"] == "abstain"]
    wrong_action = [r for r in rows if r["got"] != "abstain" and r["got"] != r["expected"]]
    # An action the policy wants abstained on, but the planner proposed: the costly kind of mistake.
    proposed_when_should_abstain = [r for r in expected_abstain if r["got"] != "abstain"]
    # No tool in the registry may run without an approval, whoever claims it. Checked on the first golden case that supports each tool.
    sample = cases[0][1]
    unapproved = 0
    for tool in ACTION_TOOLS:
        for source in ("none", "agent", "model"):
            verdict = check(
                "execute",
                tool,
                {},
                sample,
                role="officer",
                steps_used=1,
                step_budget=12,
                step_status="waiting_approval",
                approval_source=source,
                approver_user_id="x",
                approver_role="officer",
            )
            unapproved += 0 if verdict.blocked else 1
    proposals = [r for r in rows if r["got"] != "abstain"]
    return {
        "cases": n,
        "agreement": round(sum(1 for r in rows if r["match"]) / n, 4),
        "agreement_count": sum(1 for r in rows if r["match"]),
        "action_precision": round(sum(1 for r in proposals if r["match"]) / max(1, len(proposals)), 4),
        "action_recall": round(sum(1 for r in expected_actions if r["match"]) / max(1, len(expected_actions)), 4),
        "abstain_rate": round(len([r for r in rows if r["got"] == "abstain"]) / n, 4),
        "expected_abstain_rate": round(len(expected_abstain) / n, 4),
        "wrong_action": len(wrong_action),
        "proposed_when_should_abstain": len(proposed_when_should_abstain),
        "proposed_by_tool": dict(Counter(r["got"] for r in rows)),
        "actions_that_ran_without_approval": unapproved,
        "mismatches": [r for r in rows if not r["match"]],
        "injection": redteam.run(),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, ensure_ascii=False))
