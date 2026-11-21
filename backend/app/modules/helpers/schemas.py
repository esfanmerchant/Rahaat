"""Request and response shapes for helper delegations, the family list and switching."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Page, Strict

DelegationScope = Literal["track", "apply", "upload"]
DelegationStatus = Literal["live", "expired", "revoked"]


class DelegationCreate(Strict):
    helper_phone: str = Field(min_length=10, max_length=16, description="The helper's mock phone, 0999-NNNNNNN")
    scopes: list[DelegationScope] = Field(min_length=1, description="track: see status; apply: fill and send; upload: add photos")
    expires_in_days: int = Field(default=90, ge=1, le=365)
    pin: str = Field(min_length=4, max_length=6, description="Family PIN the helper must enter on the shared phone")


class DelegationOut(BaseModel):
    id: UUID
    helper_name: str
    helper_phone_masked: str | None = None
    scopes: list[str]
    status: DelegationStatus
    pin_set: bool
    granted_at: str
    expires_at: str
    revoked_at: str | None = None


class FamilyApplication(BaseModel):
    id: UUID
    status: str
    tracking_code: str | None = None
    tracking_symbols: list[str] = Field(default_factory=list)
    updated_at: str


class FamilyOut(BaseModel):
    person_id: UUID
    delegation_id: UUID
    delegation_status: DelegationStatus
    display_name: str | None = Field(default=None, description="Only while the delegation is live")
    display_name_ur: str | None = None
    district: str | None = None
    scopes: list[str]
    expires_at: str
    consent_active: bool = Field(description="False when the family took back its consent from the department")
    application: FamilyApplication | None = Field(default=None, description="The newest application, while consent is active")
    current: bool = Field(description="True for the family this session has switched to")


class FamiliesOut(Page):
    items: list[FamilyOut]
    live_count: int
    current_person_id: UUID | None = None
    current_ticket_expires_at: str | None = None


class SwitchIn(Strict):
    person_id: UUID
    pin: str = Field(min_length=4, max_length=6, pattern=r"^\d{4,6}$")


class SwitchOut(BaseModel):
    person_id: UUID
    display_name: str | None = None
    scopes: list[str]
    ticket: str = Field(description="Send as X-Helper-Ticket with X-Acting-For on every request for this family")
    expires_at: str
    expires_in: int
