"""Declarative base and column mixins.

Every default is set in Python (ids, timestamps), so inserts never need RETURNING. That matters under
Row Level Security: a RETURNING clause is checked against SELECT policies, and a freshly inserted
person row is not yet readable by the consent function in the same statement.

JSON columns are not mutation-tracked: assign a new value instead of changing one in place.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    __mapper_args__ = {"eager_defaults": False}
    # Every datetime column is timestamptz; every dict/list column is JSONB.
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, datetime: DateTime(timezone=True)}


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TenantMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class UpdatedMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


def ts(*, nullable: bool = True) -> Mapped[datetime | None]:
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def json_dict() -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, default=dict, server_default="{}")


def json_list() -> Mapped[list[Any]]:
    return mapped_column(JSONB, default=list, server_default="[]")


def fk(target: str, *, nullable: bool = False, index: bool = True, ondelete: str | None = None) -> Mapped[Any]:
    return mapped_column(Uuid, ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)
