"""Request and response shapes of the rule-version API (`/v1/rules`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Page, Strict
from app.contracts.engine import DecisionInput, DecisionResult


class RuleSetOut(BaseModel):
    id: UUID
    program_id: UUID
    program_slug: str | None = None
    name: str
    active_version_id: UUID | None = None
    active_version_no: int | None = None


class ValidationIssue(BaseModel):
    path: str
    code: str
    message: str


class RuleVersionOut(BaseModel):
    id: UUID
    rule_set_id: UUID
    version_no: int
    status: str = Field(description="draft | pending_approval | published | retired")
    is_active: bool
    dsl: dict[str, Any]
    description_en: str | None = None
    description_ur: str | None = None
    content_hash: str | None = None
    parent_version_id: UUID | None = None
    created_by: UUID | None = None
    approved_by: UUID | None = None
    pending_approval_id: UUID | None = None
    published_at: str | None = None
    created_at: str
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class RuleVersionList(Page):
    items: list[RuleVersionOut]


class DraftCreate(Strict):
    parent_version_id: UUID = Field(description="The version this draft starts from")
    dsl: dict[str, Any] | None = Field(default=None, description="Omit to copy the parent's rules unchanged")
    description_en: str | None = Field(default=None, max_length=2000)
    description_ur: str | None = Field(default=None, max_length=2000)


class DraftUpdate(Strict):
    dsl: dict[str, Any] | None = None
    description_en: str | None = Field(default=None, max_length=2000)
    description_ur: str | None = Field(default=None, max_length=2000)


class DslIn(Strict):
    dsl: dict[str, Any]


class ValidationOut(BaseModel):
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class ReasonIn(Strict):
    reason: str = Field(min_length=5, max_length=1000, description="Stored in the audit log")


class DryRunIn(Strict):
    input: DecisionInput


class DryRunOut(BaseModel):
    rule_version_id: UUID
    result: DecisionResult
    note: str = "Dry run: nothing was stored, sent or paid."


class DiffChange(BaseModel):
    path: str
    kind: str = Field(description="added | removed | changed | reordered")
    old: Any | None = None
    new: Any | None = None


class DiffOut(BaseModel):
    version_id: UUID
    against_version_id: UUID | None
    changes: list[DiffChange]
