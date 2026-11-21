"""Shared vocabulary. Change these only with the lead's agreement (docs/REQUESTS.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["citizen", "helper", "officer", "admin", "auditor"]
Lang = Literal["en", "ur", "sd"]

# Three-way router, used by every AI component (PLAN 6.2).
Route = Literal["auto", "ask_more", "human"]

Provenance = Literal["tapped", "typed", "spoken", "ocr", "qr_signed", "registry"]
VERIFIED_PROVENANCE: frozenset[str] = frozenset({"qr_signed", "registry"})

ApplicationStatus = Literal[
    "draft", "submitted", "needs_proof", "in_review", "approved", "rejected", "paid", "on_hold_consent", "withdrawn"
]
DecisionOutcome = Literal["approved", "rejected", "needs_proof", "needs_human"]

CaseKind = Literal[
    "application_review", "duplicate_review", "document_review", "complaint", "appeal", "correction", "scam_review", "anomaly_review"
]
CaseStatus = Literal["open", "assigned", "in_review", "waiting_proof", "escalated", "resolved", "closed"]
CaseAction = Literal["approve", "reject", "request_proof", "escalate"]

DocumentKind = Literal["rahat_id", "income_proof", "other"]
DocumentQuality = Literal["ok", "blurry", "glare", "cropped", "not_a_card", "unchecked"]

ScamLabel = Literal[
    "relief_scam", "phishing_link", "advance_fee", "impersonation", "legit_program_message", "unknown"
]

IncomeBand = Literal["under_15k", "15k_30k", "30k_50k", "over_50k"]
INCOME_BAND_BOUNDS: dict[str, tuple[int, int | None]] = {
    "under_15k": (0, 15_000),
    "15k_30k": (15_000, 30_000),
    "30k_50k": (30_000, 50_000),
    "over_50k": (50_000, None),
}

ConsentScope = Literal["identity", "contact", "household", "income", "documents"]

# A tracking code is shown as three of these pictograms plus digits, so a person who cannot read can still
# recognise and say it. The frontend has one pictogram per name.
TRACKING_SYMBOLS: tuple[str, ...] = (
    "moon", "star", "fish", "tree", "house", "sun", "bird", "flower",
    "key", "boat", "lamp", "leaf", "cup", "drum", "kite", "bell",
)  # fmt: skip


def tracking_symbols(number: int) -> list[str]:
    """Three symbols derived from a tracking number (16 x 16 x 16 combinations)."""
    return [TRACKING_SYMBOLS[(number >> shift) & 0xF] for shift in (8, 4, 0)]


class Strict(BaseModel):
    """Base for request bodies: unknown fields are rejected, so nothing can be mass-assigned."""

    model_config = ConfigDict(extra="forbid")


class Page(BaseModel):
    next_cursor: str | None = None


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25
