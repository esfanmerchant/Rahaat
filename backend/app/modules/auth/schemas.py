from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Role, Strict


class LoginIn(Strict):
    identifier: str = Field(min_length=3, max_length=254, description="Staff: email. Citizen or helper: mock phone 0999-NNNNNNN.")
    secret: str = Field(min_length=1, max_length=128, description="Staff: password. Citizen or helper: PIN.")
    tenant_slug: str | None = Field(default=None, max_length=64, description="Pick a department when the account has several")


class SwitchIn(Strict):
    tenant_id: UUID
    role: Role | None = None


class UserOut(BaseModel):
    id: UUID
    display_name: str
    lang: str


class MembershipOut(BaseModel):
    tenant_id: UUID
    tenant_slug: str
    tenant_name: str
    role: Role


class ActiveOut(MembershipOut):
    person_id: UUID | None = None


class MeOut(BaseModel):
    user: UserOut
    active: ActiveOut
    memberships: list[MembershipOut]


class AuthOut(MeOut):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Seconds until the access token expires")


class SessionOut(BaseModel):
    id: UUID
    device_label: str | None = None
    tenant_id: UUID
    role: str
    created_at: str
    last_seen_at: str | None = None
    expires_at: str
    current: bool
