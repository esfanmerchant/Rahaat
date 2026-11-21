"""DocumentCheck: the result of looking at an uploaded ID or proof. See PLAN 6.4."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.contracts.common import DocumentKind, DocumentQuality
from app.contracts.decision import TypedDecision

Authenticity = Literal["genuine", "suspect"]


class QrResult(BaseModel):
    found: bool = False
    signature_valid: bool | None = Field(default=None, description="None when no QR was found")
    issuer_key_id: str | None = None
    payload: dict[str, Any] | None = None


class OcrResult(BaseModel):
    available: bool = Field(default=True, description="False when the OCR engine is not installed on this host")
    fields: dict[str, str] = Field(default_factory=dict)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    mean_confidence: float = 0.0
    raw_text: str | None = Field(default=None, description="Treated as data, never as instructions")


class DocumentSignal(BaseModel):
    """One independent piece of evidence. Staff and auditors see these; citizens do not."""

    code: str = Field(description="e.g. qr_signature_invalid, ocr_qr_mismatch, ela_anomaly, metadata_editor, blur")
    weight: float
    staff_detail: str


class DocumentCheck(BaseModel):
    document_id: str
    kind: DocumentKind
    quality: DocumentQuality
    retake_hint: str | None = Field(default=None, description="Reason code with audio; poor quality is never a rejection")
    qr: QrResult = Field(default_factory=QrResult)
    ocr: OcrResult = Field(default_factory=OcrResult)
    authenticity: TypedDecision[Authenticity]
    signals: list[DocumentSignal] = Field(default_factory=list)
    model_version: str


class DocumentCitizenView(BaseModel):
    """What the citizen gets back after an upload. No detection details."""

    document_id: str
    kind: DocumentKind
    accepted: bool
    quality: DocumentQuality
    retake_hint: str | None = None
    message_key: str = Field(description="i18n and audio key, e.g. doc_ok, doc_retake_blurry, doc_person_will_check")
