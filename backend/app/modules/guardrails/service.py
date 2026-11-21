"""Storing verdicts and reporting the guard providers.

Every verdict is stored: the feature's own audit row (`voice.interpreted`, `rag.asked`) carries the summary
of all its verdicts, and any verdict other than `allow` also gets a `guardrail.verdict` row of its own, so
auditors can list every block, flag and mask in one query.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core import audit
from app.modules.guardrails.verdict import GuardVerdict


def record(
    db: Session,
    verdict: GuardVerdict,
    *,
    tenant_id: UUID,
    actor_type: str = "user",
    actor_id: UUID | str | None = None,
    actor_role: str | None = None,
    acting_for_person_id: UUID | None = None,
    object_type: str | None = None,
    object_id: UUID | str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Write a `guardrail.verdict` audit row for a verdict that is not `allow`. Never stores the raw text."""
    if verdict.verdict == "allow":
        return
    details: dict[str, Any] = {**verdict.summary(), **(context or {})}
    audit.write(
        db, tenant_id=tenant_id, action="guardrail.verdict", actor_type=actor_type, actor_id=actor_id, actor_role=actor_role,
        acting_for_person_id=acting_for_person_id, object_type=object_type, object_id=object_id,
        result="blocked" if verdict.blocked else verdict.verdict, reason=",".join(verdict.codes)[:200] or None,
        input_hash=verdict.text_hash, model_version=verdict.model_version, details=details,
    )  # fmt: skip


def providers() -> dict[str, str]:
    """For /v1/system/health. The guards are local rules and always available."""
    from app.modules.guardrails import input_guard, output_guard

    return {"guardrails_input": input_guard.MODEL_VERSION, "guardrails_output": output_guard.MODEL_VERSION}
