"""Payments, notifications, webhooks, API keys, usage, jobs and offline sync."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, UpdatedMixin, fk, json_dict, json_list, ts


class Payment(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    """A mock payment. It exists only for an approved decision; the idempotency key makes it single."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_payment_idempotency"),)
    application_id: Mapped[uuid.UUID] = fk("applications.id", ondelete="CASCADE")
    decision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    amount_pkr: Mapped[int] = mapped_column(Integer)
    # pending_approval | approved | submitted | settled | failed | reversed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending_approval")
    idempotency_key: Mapped[str] = mapped_column(String(80))
    rail_ref: Mapped[str | None] = mapped_column(String(80))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    failure_reason: Mapped[str | None] = mapped_column(Text)


class ReconciliationItem(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "reconciliation_items"
    payment_id: Mapped[uuid.UUID] = fk("payments.id", ondelete="CASCADE")
    run_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # matched | missing_on_rail | amount_mismatch | duplicate | reversed
    expected_pkr: Mapped[int] = mapped_column(Integer)
    settled_pkr: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)


class Notification(Base, IdMixin, TenantMixin, CreatedMixin):
    """Outbox row. Mock providers deliver it; every official message carries a verify code."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_tenant_status", "tenant_id", "status"),)
    person_id: Mapped[uuid.UUID | None] = fk("persons.id", nullable=True, ondelete="CASCADE")
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    channel: Mapped[str] = mapped_column(String(16))  # in_app | sms | whatsapp | email
    template: Mapped[str] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(8), default="ur")
    payload: Mapped[dict[str, Any]] = json_dict()
    body: Mapped[str] = mapped_column(Text)
    body_hash: Mapped[str | None] = mapped_column(String(64))
    verify_code: Mapped[str | None] = mapped_column(String(16), index=True)
    destination_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | sent | failed | read
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = ts()


class Webhook(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "webhooks"
    url: Mapped[str] = mapped_column(Text)
    secret_enc: Mapped[str] = mapped_column(Text)
    events: Mapped[list[Any]] = json_list()
    active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class WebhookDelivery(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "webhook_deliveries"
    webhook_id: Mapped[uuid.UUID] = fk("webhooks.id", ondelete="CASCADE")
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | delivered | failed | dead
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = ts()
    delivered_at: Mapped[datetime | None] = ts()


class ApiKey(Base, IdMixin, TenantMixin, CreatedMixin):
    """Shown once at creation. Only the prefix and a hash are stored."""

    __tablename__ = "api_keys"
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16), unique=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[Any]] = json_list()
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=60)
    expires_at: Mapped[datetime | None] = ts()
    revoked_at: Mapped[datetime | None] = ts()
    last_used_at: Mapped[datetime | None] = ts()
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class UsageCounter(Base, IdMixin, TenantMixin, UpdatedMixin):
    __tablename__ = "usage_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "metric", "period", name="uq_usage_counter"),)
    metric: Mapped[str] = mapped_column(String(32))  # api_calls | ocr | sms | ai_calls
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    count: Mapped[int] = mapped_column(BigInteger, default=0)


class Job(Base, IdMixin, TenantMixin, CreatedMixin):
    """Postgres-backed queue. Workers claim rows with SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "priority", "run_at"),)
    kind: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed | dead | cancelled
    priority: Mapped[int] = mapped_column(Integer, default=50)  # interactive work uses a lower number
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    run_at: Mapped[datetime | None] = ts()
    locked_at: Mapped[datetime | None] = ts()
    locked_by: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # lets consent withdrawal cancel it
    finished_at: Mapped[datetime | None] = ts()


class SyncOp(Base, IdMixin, TenantMixin, CreatedMixin):
    """One operation queued on a device while offline. (device_id, op_id) is applied at most once."""

    __tablename__ = "sync_ops"
    __table_args__ = (UniqueConstraint("tenant_id", "device_id", "op_id", name="uq_sync_op"),)
    device_id: Mapped[str] = mapped_column(String(64))
    op_id: Mapped[str] = mapped_column(String(64))
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    kind: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(16))  # applied | duplicate | conflict | rejected
    result: Mapped[dict[str, Any]] = json_dict()
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class UssdSession(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "ussd_sessions"
    session_key: Mapped[str] = mapped_column(String(64), index=True)
    msisdn_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(48), default="menu")
    data: Mapped[dict[str, Any]] = json_dict()
