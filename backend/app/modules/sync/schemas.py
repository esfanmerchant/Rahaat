"""Shapes of `POST /v1/sync` (PLAN 6.9)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Strict

MAX_OPS_PER_BATCH = 50
_ID_PATTERN = r"^[A-Za-z0-9._:-]+$"

OpKind = Literal["create_application", "patch_application", "submit_application"]
OpStatus = Literal["applied", "duplicate", "conflict", "rejected"]


class SyncOpIn(Strict):
    op_id: str = Field(min_length=8, max_length=64, pattern=_ID_PATTERN, description="Made on the device; the same op is applied once")
    kind: OpKind
    entity_id: UUID | None = Field(default=None, description="The application. For a create, the id the device chose for it")
    base_version: int | None = Field(default=None, ge=1, description="patch_application: the version the edit was made against")
    patch: dict[str, Any] = Field(
        default_factory=dict,
        description="create_application: {program_id, form?}. patch_application: field name to FieldValue, like form_patch",
    )
    created_at: datetime | None = Field(default=None, description="When the device queued the op (kept for the record)")
    person_id: UUID | None = Field(default=None, description="Optional; must be the person of this request")


class SyncIn(Strict):
    device_id: str = Field(min_length=8, max_length=64, pattern=_ID_PATTERN)
    ops: list[SyncOpIn] = Field(min_length=1, max_length=MAX_OPS_PER_BATCH, description="Applied in this order")


class FieldConflictOut(BaseModel):
    field: str
    server_value: Any = Field(description="What the server holds (a FieldValue), kept")
    your_value: Any = Field(description="What the device sent, not applied")
    reason: str = Field(description="changed_since_your_version | field_locked")


class SyncOpResult(BaseModel):
    op_id: str
    status: OpStatus
    original_status: str | None = Field(default=None, description="For a duplicate: what happened the first time")
    entity_id: UUID | None = None
    version: int | None = None
    application_status: str | None = None
    tracking_code: str | None = None
    applied_fields: list[str] = Field(default_factory=list)
    unchanged_fields: list[str] = Field(default_factory=list)
    conflicts: list[FieldConflictOut] = Field(default_factory=list)
    reason: str | None = Field(default=None, description="For a rejection: the error code (consent_required, not_editable, ...)")
    detail: str | None = None
    retryable: bool = Field(default=False, description="True when the op was not recorded and can be sent again later as it is")
    extra: dict[str, Any] = Field(default_factory=dict)


class SyncOut(BaseModel):
    device_id: str
    person_id: UUID
    results: list[SyncOpResult]
    server_time: str
