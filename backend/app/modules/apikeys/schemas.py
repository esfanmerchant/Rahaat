from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Strict
from app.modules.apikeys.rules import MAX_LIFETIME_DAYS, MAX_RATE_PER_MINUTE


class ApiKeyCreate(Strict):
    name: str = Field(min_length=3, max_length=120, description="Who or what uses the key, for example 'NGO case sync'")
    scopes: list[str] = Field(min_length=1, max_length=10, description="See GET /v1/admin/api-keys/scopes")
    expires_in_days: int = Field(default=90, ge=1, le=MAX_LIFETIME_DAYS, description="Every key expires; at most a year")
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=MAX_RATE_PER_MINUTE,
                                              description="Requests a minute for this key; the platform default when omitted")  # fmt: skip


class ApiKeyRotate(Strict):
    expires_in_days: int | None = Field(default=None, ge=1, le=MAX_LIFETIME_DAYS, description="Default: the old key's lifetime")
    grace_minutes: int = Field(default=0, ge=0, le=1440, description="Minutes the old key keeps working; 0 stops it at once")
    reason: str | None = Field(default=None, max_length=300)


class ApiKeyRevoke(Strict):
    reason: str | None = Field(default=None, max_length=300)


class ApiKeyDecide(Strict):
    approve: bool
    reason: str = Field(min_length=5, max_length=1000)


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str = Field(description="Public part of the key, to tell keys apart. The secret is never stored.")
    status: Literal["active", "pending_approval", "revoked", "expired"]
    scopes: list[str] = Field(description="What the key can do now. Empty while it waits for a second admin.")
    requested_scopes: list[str] | None = Field(default=None, description="Scopes waiting for a second admin's approval")
    approval_id: UUID | None = None
    rate_limit_per_minute: int
    expires_at: str | None
    revoked_at: str | None = None
    last_used_at: str | None = None
    created_at: str
    created_by: UUID | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str = Field(description="Shown once. Store it now: only a hash is kept, so it cannot be shown again.")


class ScopeOut(BaseModel):
    name: str
    description: str
    personal_data: bool
    needs_second_admin: bool
    endpoints: list[str]
