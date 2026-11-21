"""Append-only records: the hash-chained audit log, its anchors, and security events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, json_dict


class AuditLog(Base, IdMixin, TenantMixin):
    """Who did what, when and why. Each row's hash covers the previous row's hash (one chain per tenant).

    The app role may only INSERT and SELECT here. `details` is stored as canonical JSON text so the exact
    bytes that were hashed can be checked later.
    """

    __tablename__ = "audit_log"
    __table_args__ = (UniqueConstraint("tenant_id", "seq", name="uq_audit_tenant_seq"),)
    seq: Mapped[int] = mapped_column(BigInteger)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | ai | agent | system | api_key
    actor_id: Mapped[str | None] = mapped_column(String(64), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(16))
    acting_for_person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64), index=True)
    object_type: Mapped[str | None] = mapped_column(String(48))
    object_id: Mapped[str | None] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(16), default="ok")  # ok | denied | failed
    reason: Mapped[str | None] = mapped_column(Text)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    rule_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[str] = mapped_column(Text, default="{}")
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditAnchor(Base, IdMixin, TenantMixin, CreatedMixin):
    """The chain head, written on a schedule. A later rewrite of history would not match an anchor."""

    __tablename__ = "audit_anchors"
    seq: Mapped[int] = mapped_column(BigInteger)
    head_hash: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(Text)


class SecurityEvent(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "security_events"
    kind: Mapped[str] = mapped_column(String(48), index=True)  # refresh_reuse | lockout | ssrf_blocked | upload_rejected
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = json_dict()
