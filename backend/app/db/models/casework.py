"""Programs, applications, documents and the generic case system used for every human handoff."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, Index, Integer, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, UpdatedMixin, fk, json_dict, ts


class Program(Base, IdMixin, TenantMixin, CreatedMixin):
    """A public service run by a tenant. New services are added as data, not code."""

    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_program_tenant_slug"),)
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    name_ur: Mapped[str | None] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32), default="relief_payment")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = json_dict()


class Application(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "client_op_id", name="uq_application_client_op"),
        Index("ix_applications_tenant_status", "tenant_id", "status"),
        Index("uq_applications_tracking_code", "tenant_id", "tracking_code", unique=True,
              postgresql_where=text("tracking_code IS NOT NULL")),
    )
    program_id: Mapped[uuid.UUID] = fk("programs.id")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    # draft | submitted | needs_proof | in_review | approved | rejected | paid | on_hold_consent | withdrawn
    status: Mapped[str] = mapped_column(String(24), default="draft")
    form: Mapped[dict[str, Any]] = json_dict()  # ApplicationFormV1 (contracts)
    form_version: Mapped[str] = mapped_column(String(8), default="v1")
    version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic lock for offline sync
    client_op_id: Mapped[str | None] = mapped_column(String(64))  # idempotency for creates made offline
    submitted_via: Mapped[str] = mapped_column(String(16), default="web")  # web | helper | ussd | api
    tracking_code: Mapped[str | None] = mapped_column(String(24), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    submitted_at: Mapped[datetime | None] = ts()


class Document(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "documents"
    application_id: Mapped[uuid.UUID | None] = fk("applications.id", nullable=True, ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(32))  # rahat_id | income_proof | other
    storage_key: Mapped[str] = mapped_column(String(128))  # random name; never the uploaded filename
    sha256: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded | checked | retake | suspect
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class DocumentCheck(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "document_checks"
    document_id: Mapped[uuid.UUID] = fk("documents.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    quality: Mapped[str] = mapped_column(String(16))  # ok | blurry | glare | cropped | not_a_card
    authenticity: Mapped[str | None] = mapped_column(String(16))  # genuine | suspect | None when abstained
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    result: Mapped[dict[str, Any]] = json_dict()  # full DocumentCheck (contracts), signals included
    model_version: Mapped[str] = mapped_column(String(64), default="docs-ai-0")


class Case(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    """One unit of human work. Every "I am not sure" becomes a case with a handoff package."""

    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_queue", "tenant_id", "status", "priority"),)
    # application_review | duplicate_review | document_review | complaint | appeal | correction | scam_review
    kind: Mapped[str] = mapped_column(String(32))
    # open | assigned | in_review | waiting_proof | escalated | resolved | closed
    status: Mapped[str] = mapped_column(String(16), default="open")
    priority: Mapped[int] = mapped_column(Integer, default=50)  # 0 is most urgent
    confidence: Mapped[float | None] = mapped_column(Float)
    subject_person_id: Mapped[uuid.UUID | None] = fk("persons.id", nullable=True, ondelete="SET NULL")
    application_id: Mapped[uuid.UUID | None] = fk("applications.id", nullable=True, ondelete="SET NULL")
    decision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    opened_reason: Mapped[str] = mapped_column(String(64), default="low_confidence")
    handoff: Mapped[dict[str, Any]] = json_dict()  # HandoffPackage (contracts)
    sla_due_at: Mapped[datetime | None] = ts()
    resolved_at: Mapped[datetime | None] = ts()
    resolution: Mapped[str | None] = mapped_column(String(32))  # approved | rejected | proof_requested | ...
    resolution_reason: Mapped[str | None] = mapped_column(Text)


class CaseNote(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "case_notes"
    case_id: Mapped[uuid.UUID] = fk("cases.id", ondelete="CASCADE")
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    author_kind: Mapped[str] = mapped_column(String(16), default="user")  # user | ai | system
    body: Mapped[str] = mapped_column(Text)


class CaseEvent(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "case_events"
    case_id: Mapped[uuid.UUID] = fk("cases.id", ondelete="CASCADE")
    event: Mapped[str] = mapped_column(String(32))  # created | assigned | status_changed | escalated | reopened
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any]] = json_dict()


class Appeal(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "appeals"
    application_id: Mapped[uuid.UUID] = fk("applications.id", ondelete="CASCADE")
    decision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | upheld | overturned | withdrawn
    due_at: Mapped[datetime | None] = ts()
    outcome: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = ts()
