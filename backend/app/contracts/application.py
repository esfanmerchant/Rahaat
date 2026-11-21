"""ApplicationFormV1: the structured output every input path fills (voice, icons, OCR, registry).

Each field carries its own confidence and where it came from. Unknown stays unknown: `value` is None and
nothing is guessed. See PLAN 6.3.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.contracts.common import VERIFIED_PROVENANCE, IncomeBand, Lang, Provenance

T = TypeVar("T")


class FieldValue(BaseModel, Generic[T]):
    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: Provenance = "tapped"
    verified: bool = Field(default=False, description="Only a signed QR or the registry can make a field verified")

    @model_validator(mode="after")
    def _verified_needs_trusted_source(self) -> FieldValue[T]:
        if self.verified and self.provenance not in VERIFIED_PROVENANCE:
            raise ValueError("only qr_signed or registry values can be marked verified")
        if self.value is None:
            self.confidence = 0.0
        return self


class ApplicationFormV1(BaseModel):
    """Every field is optional while the form is a draft. Submission checks what the rules need."""

    form_version: str = "v1"
    full_name: FieldValue[str] = Field(default_factory=FieldValue[str])
    national_id: FieldValue[str] = Field(default_factory=FieldValue[str], description="Mock ID, 00000-NNNNNNN-C")
    dob: FieldValue[str] = Field(default_factory=FieldValue[str], description="ISO date")
    gender: FieldValue[str] = Field(default_factory=FieldValue[str])
    district: FieldValue[str] = Field(default_factory=FieldValue[str])
    phone: FieldValue[str] = Field(default_factory=FieldValue[str], description="Mock phone, 0999-NNNNNNN")
    household_size: FieldValue[int] = Field(default_factory=FieldValue[int])
    income_band: FieldValue[IncomeBand] = Field(default_factory=FieldValue[IncomeBand])
    is_widow: FieldValue[bool] = Field(default_factory=FieldValue[bool])
    has_disability: FieldValue[bool] = Field(default_factory=FieldValue[bool])
    receives_other_aid: FieldValue[bool] = Field(default_factory=FieldValue[bool])
    payout_account: FieldValue[str] = Field(default_factory=FieldValue[str], description="Mock wallet or account")
    language: Lang = "ur"

    def missing(self, required: list[str]) -> list[str]:
        """Names of required fields that are still unknown, so we ask only for what is needed."""
        return [name for name in required if getattr(self, name).value is None]


FORM_FIELDS: tuple[str, ...] = tuple(
    name for name in ApplicationFormV1.model_fields if name not in ("form_version", "language")
)


def apply_patch(form: ApplicationFormV1, patch: dict[str, Any]) -> ApplicationFormV1:
    """Merge field updates into a form and validate the result. Unknown field names are rejected."""
    unknown = set(patch) - set(FORM_FIELDS) - {"language"}
    if unknown:
        raise ValueError(f"unknown form fields: {sorted(unknown)}")
    merged = form.model_dump()
    merged.update(patch)
    return ApplicationFormV1.model_validate(merged)
