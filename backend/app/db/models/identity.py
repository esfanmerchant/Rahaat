"""Platform identity: plans, tenants, users, sessions, memberships.

`users`, `sessions` and `plans` are global (a user can belong to several tenants). Every other table in
the system carries `tenant_id`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, UpdatedMixin, fk, json_dict, ts


class Plan(Base, IdMixin, CreatedMixin):
    __tablename__ = "plans"
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    price_pkr: Mapped[int] = mapped_column(Integer, default=0)
    limits: Mapped[dict[str, Any]] = json_dict()  # {"api_calls": 1000, "ocr": 200, "sms": 500, "ai_calls": 2000}


class Tenant(Base, IdMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "tenants"
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    name_ur: Mapped[str | None] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(32), default="department")  # department | ngo | partner | platform
    region: Mapped[str] = mapped_column(String(32), default="PK-SD")  # data-residency tag
    status: Mapped[str] = mapped_column(String(16), default="active")
    plan_id: Mapped[uuid.UUID | None] = fk("plans.id", nullable=True)
    config: Mapped[dict[str, Any]] = json_dict()  # payment_four_eyes_limit_pkr, languages, feature flags
    cost_matrix: Mapped[dict[str, Any]] = json_dict()  # PLAN 6.1
    wrapped_dek: Mapped[str] = mapped_column(Text)  # tenant data key, wrapped by the master key


class User(Base, IdMixin, CreatedMixin, UpdatedMixin):
    __tablename__ = "users"
    email: Mapped[str | None] = mapped_column(String(254), unique=True)  # staff sign in with email
    phone_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # citizens sign in with a mock phone
    phone_enc: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(160))
    lang: Mapped[str] = mapped_column(String(8), default="en")
    password_hash: Mapped[str] = mapped_column(Text)  # argon2id; a PIN for citizens
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="active")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = ts()
    last_login_at: Mapped[datetime | None] = ts()


class AuthSession(Base, IdMixin, CreatedMixin):
    """One signed-in device. The refresh token rotates on every use; reuse of an old one revokes the family."""

    __tablename__ = "sessions"
    user_id: Mapped[uuid.UUID] = fk("users.id", ondelete="CASCADE")
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    tenant_id: Mapped[uuid.UUID] = fk("tenants.id")
    role: Mapped[str] = mapped_column(String(16))
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prev_refresh_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    device_label: Mapped[str | None] = mapped_column(String(160))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    last_seen_at: Mapped[datetime | None] = ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = ts()
    revoked_reason: Mapped[str | None] = mapped_column(String(40))


class Membership(Base, IdMixin, TenantMixin, CreatedMixin):
    """A user's role in a tenant. Citizens and helpers have memberships too, so every token names one tenant."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "role", name="uq_membership_user_tenant_role"),)
    user_id: Mapped[uuid.UUID] = fk("users.id", ondelete="CASCADE")
    role: Mapped[str] = mapped_column(String(16))  # citizen | helper | officer | admin | auditor
    status: Mapped[str] = mapped_column(String(16), default="active")
    person_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # the citizen's own person record in this tenant
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
