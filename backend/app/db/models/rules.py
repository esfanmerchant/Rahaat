"""Rule versions, policy documents, decisions and the human reviews and approvals around them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, fk, json_dict, json_list, ts


class RuleSet(Base, IdMixin, TenantMixin, CreatedMixin):
    """The rules of one program. `active_version_id` is read inside each decision's transaction."""

    __tablename__ = "rule_sets"
    program_id: Mapped[uuid.UUID] = fk("programs.id", ondelete="CASCADE")
    name: Mapped[str] = mapped_column(String(120))
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("rule_versions.id", use_alter=True, name="fk_rule_sets_active_version"), nullable=True
    )


class RuleVersion(Base, IdMixin, TenantMixin, CreatedMixin):
    """Immutable once published. A rollback is a new version that copies an old one."""

    __tablename__ = "rule_versions"
    __table_args__ = (UniqueConstraint("rule_set_id", "version_no", name="uq_rule_version_no"),)
    rule_set_id: Mapped[uuid.UUID] = fk("rule_sets.id", ondelete="CASCADE")
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | pending_approval | published | retired
    dsl: Mapped[dict[str, Any]] = json_dict()  # PLAN 6.8
    description_en: Mapped[str | None] = mapped_column(Text)
    description_ur: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime | None] = ts()
    content_hash: Mapped[str | None] = mapped_column(String(64))
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    high_impact: Mapped[bool] = mapped_column(default=True)  # needs a second approver to publish
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    published_at: Mapped[datetime | None] = ts()


class PolicyDocument(Base, IdMixin, TenantMixin, CreatedMixin):
    """Versioned policy text. Explanations cite the text that was valid when the decision was made."""

    __tablename__ = "policy_documents"
    program_id: Mapped[uuid.UUID | None] = fk("programs.id", nullable=True, ondelete="CASCADE")
    title: Mapped[str] = mapped_column(String(200))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    body: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[datetime | None] = ts()
    status: Mapped[str] = mapped_column(String(16), default="published")
    content_hash: Mapped[str | None] = mapped_column(String(64))


class Decision(Base, IdMixin, TenantMixin, CreatedMixin):
    """One AI decision with everything needed to explain it and to replay it bit for bit."""

    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_tenant_created", "tenant_id", "created_at"),)
    application_id: Mapped[uuid.UUID] = fk("applications.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rule_version_id: Mapped[uuid.UUID] = fk("rule_versions.id")
    model_version: Mapped[str] = mapped_column(String(64))
    engine_version: Mapped[str] = mapped_column(String(32), default="decide-1")
    cost_matrix: Mapped[dict[str, Any]] = json_dict()
    input_snapshot: Mapped[dict[str, Any]] = json_dict()
    input_hash: Mapped[str] = mapped_column(String(64))
    rule_trace: Mapped[list[Any]] = json_list()
    probabilities: Mapped[dict[str, Any]] = json_dict()
    p_ok: Mapped[float | None] = mapped_column(Float)
    expected_costs: Mapped[dict[str, Any]] = json_dict()
    route: Mapped[str] = mapped_column(String(16))  # auto | ask_more | human
    outcome: Mapped[str] = mapped_column(String(24))  # approved | rejected | needs_proof | needs_human
    reasons: Mapped[list[Any]] = json_list()
    guards: Mapped[list[Any]] = json_list()
    handoff: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    explanation: Mapped[dict[str, Any]] = json_dict()
    guardrails: Mapped[dict[str, Any]] = json_dict()
    result_hash: Mapped[str | None] = mapped_column(String(64))  # replay must reproduce this
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(64))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class HumanReview(Base, IdMixin, TenantMixin, CreatedMixin):
    """An officer's action on a decision. Overrides become labelled feedback."""

    __tablename__ = "human_reviews"
    decision_id: Mapped[uuid.UUID | None] = fk("decisions.id", nullable=True, ondelete="CASCADE")
    case_id: Mapped[uuid.UUID] = fk("cases.id", ondelete="CASCADE")
    reviewer_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    action: Mapped[str] = mapped_column(String(24))  # approve | reject | request_proof | escalate
    reason: Mapped[str] = mapped_column(Text)
    review_seconds: Mapped[int | None] = mapped_column(Integer)
    overrode_ai: Mapped[bool] = mapped_column(default=False)
    second_approver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Approval(Base, IdMixin, TenantMixin, CreatedMixin):
    """Maker-checker gate: a payment above the limit, a rule publication, an admin grant, an agent step."""

    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_tenant_status", "tenant_id", "status"),)
    kind: Mapped[str] = mapped_column(String(32))  # payment | rule_publish | admin_grant | agent_step
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | approved | rejected | expired
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approver_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = json_dict()
    decided_at: Mapped[datetime | None] = ts()
