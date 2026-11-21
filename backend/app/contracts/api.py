"""Request and response shapes of the spine API (PLAN section 2 flow).

Track A implements these endpoints; the frontend tracks code against them from day one. Until an endpoint
is real, `app/modules/zz_stubs` serves an example of the same shape in dev and test only.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.application import ApplicationFormV1
from app.contracts.common import (
    ApplicationStatus,
    CaseAction,
    CaseKind,
    CaseStatus,
    ConsentScope,
    DocumentKind,
    Page,
    Strict,
)
from app.contracts.decision import DecisionTrace, DecisionUserView, HandoffPackage
from app.contracts.documents import DocumentCheck, DocumentCitizenView

# --- people and programs -------------------------------------------------------------------------------


class PersonOut(BaseModel):
    id: UUID
    full_name: str
    full_name_ur: str | None = None
    district: str | None = None
    lang: str = "ur"
    national_id_masked: str | None = Field(default=None, description="Only the last three characters are shown")
    phone_masked: str | None = None


class RuleVersionBrief(BaseModel):
    id: UUID
    version_no: int
    description_en: str | None = None
    description_ur: str | None = None
    required_docs: list[str] = Field(default_factory=list)
    payment_pkr: int | None = None


class ProgramOut(BaseModel):
    id: UUID
    slug: str
    name: str
    name_ur: str | None = None
    active: bool = True
    rule_version: RuleVersionBrief | None = None


# --- consent -------------------------------------------------------------------------------------------


class ConsentCreate(Strict):
    person_id: UUID | None = Field(default=None, description="Omit for yourself; helpers name the person they act for")
    purpose: str = Field(default="relief_application", max_length=64)
    field_scopes: list[ConsentScope] = Field(min_length=1)
    expires_in_days: int = Field(default=180, ge=1, le=730)


class ConsentNarrow(Strict):
    field_scopes: list[ConsentScope] = Field(min_length=1)


class ConsentOut(BaseModel):
    id: UUID
    person_id: UUID
    grantee_type: str
    grantee_id: UUID
    grantee_name: str
    purpose: str
    field_scopes: list[str]
    status: str
    version: int
    granted_at: str
    expires_at: str | None = None
    withdrawn_at: str | None = None


# --- applications --------------------------------------------------------------------------------------


class ApplicationCreate(Strict):
    program_id: UUID
    client_op_id: str = Field(min_length=8, max_length=64, description="Client-generated id; the same id creates once")
    form: ApplicationFormV1 | None = None


class ApplicationPatch(Strict):
    base_version: int = Field(ge=1, description="The version this edit was made against (optimistic lock)")
    form_patch: dict[str, Any] = Field(description="Field name to FieldValue; unknown names are rejected")


class TimelineItem(BaseModel):
    at: str
    status: str
    label_key: str = Field(description="i18n and audio key")


class ApplicationSummary(BaseModel):
    id: UUID
    person_id: UUID
    program_id: UUID
    program_name: str
    status: ApplicationStatus
    tracking_code: str | None = None
    tracking_symbols: list[str] = Field(default_factory=list, description="Three pictogram names for people who cannot read")
    version: int
    updated_at: str


class ApplicationOut(ApplicationSummary):
    form: ApplicationFormV1
    missing_fields: list[str] = Field(default_factory=list)
    documents: list[DocumentCitizenView] = Field(default_factory=list)
    decision: DecisionUserView | None = None
    timeline: list[TimelineItem] = Field(default_factory=list)


class ApplicationList(Page):
    items: list[ApplicationSummary]


class SubmitOut(BaseModel):
    application: ApplicationOut
    decision: DecisionUserView | None = Field(default=None, description="None while documents are still being checked")


class DocumentOut(BaseModel):
    document: DocumentCitizenView
    application_version: int


# --- cases (officer) -----------------------------------------------------------------------------------


class CaseSummary(BaseModel):
    id: UUID
    kind: CaseKind
    status: CaseStatus
    priority: int
    confidence: float | None = None
    opened_reason: str
    subject_name: str | None = None
    application_id: UUID | None = None
    assigned_to: UUID | None = None
    sla_due_at: str | None = None
    age_minutes: int
    created_at: str


class CaseNoteOut(BaseModel):
    id: UUID
    author_kind: str
    author_name: str | None = None
    body: str
    created_at: str


class CaseEventOut(BaseModel):
    event: str
    from_status: str | None = None
    to_status: str | None = None
    actor_name: str | None = None
    at: str


class CaseDetail(CaseSummary):
    handoff: HandoffPackage | None = None
    form: ApplicationFormV1 | None = None
    document_checks: list[DocumentCheck] = Field(default_factory=list)
    decision: DecisionTrace | None = None
    notes: list[CaseNoteOut] = Field(default_factory=list)
    events: list[CaseEventOut] = Field(default_factory=list)
    allowed_actions: list[CaseAction] = Field(default_factory=list)


class CaseList(Page):
    items: list[CaseSummary]


class CaseActionIn(Strict):
    action: CaseAction
    reason: str = Field(min_length=5, max_length=1000, description="Required for every action; stored in the audit log")
    proof_kind: DocumentKind | None = None


class CaseNoteIn(Strict):
    body: str = Field(min_length=1, max_length=4000)


# --- payments, approvals, notifications ----------------------------------------------------------------


class PaymentOut(BaseModel):
    id: UUID
    application_id: UUID
    amount_pkr: int
    status: str
    rail_ref: str | None = None
    approval_id: UUID | None = None
    created_at: str


class ApprovalOut(BaseModel):
    id: UUID
    kind: str
    subject_type: str
    subject_id: UUID
    status: str
    requested_by: UUID | None = None
    approver_id: UUID | None = None
    reason: str | None = None
    created_at: str


class ApprovalDecideIn(Strict):
    approve: bool
    reason: str = Field(min_length=5, max_length=1000)


class NotificationOut(BaseModel):
    id: UUID
    channel: str
    template: str
    lang: str
    body: str
    status: str
    verify_code: str | None = Field(default=None, description="Anyone can check this code in the scam checker")
    created_at: str


class NotificationList(Page):
    items: list[NotificationOut]
