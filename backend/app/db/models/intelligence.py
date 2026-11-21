"""Scam intelligence, knowledge base, memory, agent runs, evals and the model registry."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, UpdatedMixin, fk, json_dict, json_list, ts

EMBEDDING_DIM = 384


class ScamReport(Base, IdMixin, TenantMixin, CreatedMixin):
    """A message someone checked. The text is stored redacted; location is coarse (district)."""

    __tablename__ = "scam_reports"
    __table_args__ = (Index("ix_scam_reports_map", "tenant_id", "district", "label", "created_at"),)
    reporter_person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(16), default="text")  # text | voice | screenshot | sms_forward
    text_redacted: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64), index=True)
    sender: Mapped[str | None] = mapped_column(String(64))
    urls: Mapped[list[Any]] = json_list()
    # relief_scam | phishing_link | advance_fee | impersonation | legit_program_message | unknown
    label: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    route: Mapped[str] = mapped_column(String(16))
    classification: Mapped[dict[str, Any]] = json_dict()
    district: Mapped[str | None] = mapped_column(String(64))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    confirmed_label: Mapped[str | None] = mapped_column(String(32))  # set by an officer; feeds the mistakes ledger
    disputed: Mapped[bool] = mapped_column(default=False)  # "this is real, ask a person"


class ScamCluster(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "scam_clusters"
    label: Mapped[str] = mapped_column(String(32))
    signature: Mapped[str] = mapped_column(String(128), index=True)
    sample_text: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime | None] = ts()
    last_seen: Mapped[datetime | None] = ts()
    data: Mapped[dict[str, Any]] = json_dict()


class PublicWarning(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "public_warnings"
    title: Mapped[str] = mapped_column(String(200))
    body_en: Mapped[str] = mapped_column(Text)
    body_ur: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(String(64))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="published")
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    published_at: Mapped[datetime | None] = ts()


class TakedownRequest(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "takedown_requests"
    target_kind: Mapped[str] = mapped_column(String(16))  # url | sender
    target_value: Mapped[str] = mapped_column(Text)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="reported")  # reported | acknowledged | removed | refused
    outcome: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class KbDocument(Base, IdMixin, TenantMixin, CreatedMixin):
    """An approved, versioned source for RAG. Nothing unapproved enters the corpus."""

    __tablename__ = "kb_documents"
    title: Mapped[str] = mapped_column(String(200))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="approved")  # draft | approved | retired
    content_hash: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class KbChunk(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "kb_chunks"
    document_id: Mapped[uuid.UUID] = fk("kb_documents.id", ondelete="CASCADE")
    section: Mapped[str | None] = mapped_column(String(120))
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    meta: Mapped[dict[str, Any]] = json_dict()


class MemoryItem(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    """Per-person preferences and progress. Keyed by person, never by helper; purged on withdrawal."""

    __tablename__ = "memory_items"
    __table_args__ = (UniqueConstraint("tenant_id", "person_id", "kind", "key", name="uq_memory_item"),)
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(32))  # preference | progress | note
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = json_dict()


class AgentRun(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "agent_runs"
    goal: Mapped[str] = mapped_column(String(64))
    # running | waiting_approval | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="running")
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    acting_role: Mapped[str | None] = mapped_column(String(16))
    step_budget: Mapped[int] = mapped_column(Integer, default=12)
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = json_dict()


class AgentStep(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "agent_steps"
    run_id: Mapped[uuid.UUID] = fk("agent_runs.id", ondelete="CASCADE")
    ordinal: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(48))
    input: Mapped[dict[str, Any]] = json_dict()
    output: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(20), default="done")  # done | failed | blocked | waiting_approval
    approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class EvalRun(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "eval_runs"
    kind: Mapped[str] = mapped_column(String(32), index=True)  # decision | scam | documents | names | red_team | rag
    model_version: Mapped[str | None] = mapped_column(String(64))
    rule_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="done")
    metrics: Mapped[dict[str, Any]] = json_dict()
    artifacts: Mapped[dict[str, Any]] = json_dict()  # curve points, confusion matrix, reliability bins


class TwinRun(Base, IdMixin, TenantMixin, CreatedMixin):
    """Digital Twin: a draft rule version replayed over past cases. No side effects."""

    __tablename__ = "twin_runs"
    draft_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(16), default="done")
    summary: Mapped[dict[str, Any]] = json_dict()
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class ModelRegistry(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_model_version"),)
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    data_hash: Mapped[str | None] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = json_dict()
    metrics: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(16), default="active")  # shadow | canary | active | retired
    card: Mapped[str | None] = mapped_column(Text)


class FeedbackLabel(Base, IdMixin, TenantMixin, CreatedMixin):
    """An officer override turned into a label. Reviewed before it can train anything."""

    __tablename__ = "feedback_labels"
    decision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    subject_type: Mapped[str] = mapped_column(String(32), default="decision")
    labeler_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    label: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="officer_override")
    reviewed: Mapped[bool] = mapped_column(default=False)
