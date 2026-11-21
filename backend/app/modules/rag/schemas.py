"""Request and response shapes of the rules assistant and the knowledge-base endpoints."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.contracts.common import Strict
from app.contracts.decision import TypedDecision
from app.core.config import PROTOTYPE_LABEL


class AskIn(Strict):
    question: str = Field(min_length=1, max_length=500, description="Treated as data, never as instructions")
    lang: Literal["en", "ur"] | None = Field(default=None, description="Answer language; Urdu script is always answered in Urdu")
    tenant_slug: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9-]+$",
                                    description="Anonymous callers only: which department's rules (default: the first)")  # fmt: skip


class Citation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    doc_key: str
    title: str
    version: int
    section_id: str
    section: str
    lang: str


class AnswerSentenceOut(BaseModel):
    text: str = Field(description="Copied word for word from the cited section")
    citation: int = Field(description="Index into `citations`")


class SpokenText(BaseModel):
    key: str = Field(description="Message key; the app has a recording for it")
    text: str
    lang: str


class AskOut(BaseModel):
    decision: TypedDecision[str] = Field(description="choice 'answer', or abstained with route 'human' (ask a person)")
    answered: bool
    lang: str
    sentences: list[AnswerSentenceOut]
    citations: list[Citation]
    notice: SpokenText | None = Field(description="Shown with answers about eligibility or payment: only an officer decides")
    refusal: SpokenText | None = Field(description="'I am not sure. Please ask a person.' when nothing reliable was found")
    reason: str
    retrieval: dict[str, float]
    prototype_label: str = PROTOTYPE_LABEL


class KbSectionOut(BaseModel):
    chunk_id: UUID
    section_id: str
    section: str
    sentences: int


class KbDocumentOut(BaseModel):
    id: UUID
    doc_key: str
    title: str
    lang: str
    version: int
    status: str
    content_hash: str
    sections: list[KbSectionOut]


class KbIngestOut(BaseModel):
    added: list[str]
    unchanged: int
    retired: list[str]
    refused: list[str]
