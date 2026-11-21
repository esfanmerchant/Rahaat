from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Strict
from app.modules.appeals.rules import AppealOutcome, ComplaintCategory, ComplaintOutcome


class AppealCreate(Strict):
    application_id: UUID
    reason: str = Field(min_length=5, max_length=500, description="Why the person disagrees, in their own words (a few sentences)")


class AppealDecide(Strict):
    outcome: AppealOutcome = Field(description="`upheld`: the first answer stays. `overturned`: the application is approved and paid.")
    reason: str = Field(min_length=5, max_length=1000, description="Required; stored in the audit log and the case")


class ComplaintCreate(Strict):
    category: ComplaintCategory
    details: str | None = Field(default=None, max_length=500, description="Optional: what happened, in a few sentences")


class ComplaintResolve(Strict):
    outcome: ComplaintOutcome = Field(description="`resolved`: action was taken. `dismissed`: nothing could be changed.")
    reason: str = Field(min_length=5, max_length=1000)


class KeyedText(BaseModel):
    key: str
    en: str
    ur: str


class AppealOut(BaseModel):
    """What the citizen (or their helper) sees."""

    id: UUID
    application_id: UUID
    tracking_code: str | None = None
    status: Literal["open", "upheld", "overturned", "withdrawn"]
    status_key: Literal["being_checked", "first_answer_stays", "approved_after_appeal", "withdrawn"]
    message: KeyedText = Field(description="Keyed text in English and Urdu; the app also plays the matching audio")
    reason: str | None = None
    created_at: str
    due_at: str | None = None
    resolved_at: str | None = None


class AppealList(BaseModel):
    items: list[AppealOut]
    next_cursor: str | None = None


class AppealStaffOut(BaseModel):
    id: UUID
    application_id: UUID
    case_id: UUID | None
    tracking_code: str | None = Field(default=None, description="Hidden (null) while the person's consent does not allow reading the application")
    status: Literal["open", "upheld", "overturned", "withdrawn"]
    created_at: str
    due_at: str | None = None
    resolved_at: str | None = None
    age_days: int


class AppealStaffList(BaseModel):
    items: list[AppealStaffOut]
    next_cursor: str | None = None


class AppealStaffDetail(AppealStaffOut):
    reason: str | None = Field(description="The citizen's reason")
    outcome: str | None = Field(default=None, description="The deciding officer's reason, once decided")
    decision_id: UUID | None = None
    original_outcome: str | None = None
    original_reasons: list[str] = []
    can_decide: bool = Field(description="False when the caller took part in the first decision: a different officer must decide")
    cannot_decide_reason: str | None = None


class ComplaintOut(BaseModel):
    id: UUID
    category: ComplaintCategory
    status: Literal["received", "being_checked", "resolved"]
    outcome: Literal["resolved", "closed"] | None = None
    message: KeyedText
    created_at: str
    resolved_at: str | None = None


class ComplaintList(BaseModel):
    items: list[ComplaintOut]
    next_cursor: str | None = None


class ComplaintStaffOut(BaseModel):
    id: UUID = Field(description="The case id: also usable on GET /v1/cases/{id}")
    category: ComplaintCategory
    case_kind: Literal["complaint", "scam_review"]
    status: str
    priority: int
    details: str | None = Field(default=None, description="Null while the person's consent does not allow reading it")
    created_at: str
    resolved_at: str | None = None
    resolution: str | None = None


class ComplaintStaffList(BaseModel):
    items: list[ComplaintStaffOut]
    next_cursor: str | None = None
