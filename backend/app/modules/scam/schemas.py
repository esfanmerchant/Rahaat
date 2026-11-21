"""Request and response shapes of the scam checker, the Scam Map and public warnings."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.common import Page, Route, ScamLabel, Strict

Channel = Literal["text", "sms_forward", "voice", "screenshot"]
Certainty = Literal["likely_scam", "might_be_scam", "not_sure", "looks_real", "confirmed_real"]


class ScamCheckIn(Strict):
    text: str = Field(min_length=1, max_length=2000, description="The message as received. It is analysed as data and stored redacted.")
    sender: str | None = Field(default=None, max_length=64, description="The sender name or number shown on the phone, if known")
    channel: Channel = "text"
    district: str | None = Field(default=None, max_length=64, description="A district name; anything else is dropped")


class ReasonOut(BaseModel):
    code: str
    text: str


class UrlOut(BaseModel):
    url: str = Field(description="Defanged, never a live link: hxxps://example[.]com")
    host: str
    risk: Literal["high", "medium", "low"]
    flags: list[str]
    flag_texts: list[str] = Field(description="The flags in plain words, in the caller's language")


class VerifiedOut(BaseModel):
    genuine: bool
    department: str | None = None
    sent_at: str | None = None
    template: str | None = None


class SignalWeightOut(BaseModel):
    signal: str
    weight: float = Field(description="Log-odds this signal adds to the chosen class over `compared_with`")


class StaffDetailOut(BaseModel):
    """For officers, admins and auditors only."""

    probabilities: dict[str, float]
    confidence: float
    abstained: bool
    model_version: str
    p_scam: float
    p_scam_text: float | None
    text_probabilities: dict[str, float]
    text_model_weight: float | None = Field(description="Log-odds the text model adds to the chosen class over `compared_with`")
    compared_with: str | None
    signals: list[SignalWeightOut]
    fired: list[str]
    abstain_reason: str | None
    route_costs: dict[str, float]
    thresholds: dict[str, float]
    script: str
    sender_kind: str
    sender: str | None
    decision_reasons: list[str]


class ReviewOut(BaseModel):
    status: Literal["none", "waiting", "done"]
    confirmed_label: str | None = None
    case_id: uuid.UUID | None = None


class ScamCheckOut(BaseModel):
    report_id: uuid.UUID
    label: ScamLabel | None = Field(description="None when the checker is not sure")
    label_text: str
    certainty: Certainty
    route: Route
    lang: Literal["ur", "en"]
    headline: str
    reasons: list[ReasonOut] = Field(max_length=3)
    what_to_do: str
    urls: list[UrlOut]
    verified: VerifiedOut | None = None
    audio_keys: list[str]
    can_dispute: bool
    review: ReviewOut
    checked_at: str
    detail: StaffDetailOut | None = Field(default=None, description="Staff only")


class DisputeIn(Strict):
    note: str | None = Field(default=None, max_length=500, description="Optional: why the person thinks the message is real")


class DisputeOut(BaseModel):
    report_id: uuid.UUID
    disputed: bool
    case_id: uuid.UUID
    message: str


class LabelIn(Strict):
    label: ScamLabel
    reason: str = Field(min_length=5, max_length=500)


class ScamReportOut(BaseModel):
    id: uuid.UUID
    created_at: str
    channel: str
    label: str
    certainty: str | None
    route: str
    confidence: float
    district: str | None
    sender: str | None
    text_redacted: str
    urls: list[UrlOut]
    cluster_id: uuid.UUID | None
    disputed: bool
    confirmed_label: str | None
    model_version: str | None


class ScamReportList(Page):
    items: list[ScamReportOut]


class MyReportOut(BaseModel):
    id: uuid.UUID
    checked_at: str
    label: str | None
    certainty: str
    disputed: bool
    review: ReviewOut


class MyReportList(Page):
    items: list[MyReportOut]


class MapCell(BaseModel):
    district: str
    label: str
    day: str
    count: int


class DistrictLabelCount(BaseModel):
    district: str
    label: str
    count: int


class DistrictCount(BaseModel):
    district: str
    count: int


class MapOut(BaseModel):
    days: int
    k: int
    first_day: str
    last_day: str
    timezone: str = "Asia/Karachi"
    labels: list[str]
    cells: list[MapCell]
    districts: list[DistrictLabelCount]
    district_totals: list[DistrictCount]
    hidden: dict[str, int] = Field(description="How many groups of each kind were hidden for having fewer than k reports")
    note: str


class TrendPoint(BaseModel):
    day: str
    count: int | None = Field(description="None when 1 to k-1 reports are hidden")


class TrendSeries(BaseModel):
    label: str
    points: list[TrendPoint]


class TrendsOut(BaseModel):
    days: int
    k: int
    series: list[TrendSeries]
    total: list[TrendPoint]
    note: str


class CampaignOut(BaseModel):
    id: uuid.UUID
    label: str
    signature: str
    size: int = Field(description="Reports in this campaign, all time")
    size_in_window: int
    sample_text: str = Field(description="Redacted")
    first_seen: str | None
    last_seen: str | None
    districts: list[DistrictCount]
    trend: list[TrendPoint]
    hosts: list[str] = Field(description="Defanged link hosts seen in this campaign")
    senders: int = Field(description="How many different senders, never who")


class CampaignList(BaseModel):
    days: int
    k: int
    items: list[CampaignOut]
    hidden: int
    note: str


class WarningIn(Strict):
    title: str = Field(min_length=5, max_length=200)
    body_en: str = Field(min_length=10, max_length=1000)
    body_ur: str | None = Field(default=None, min_length=5, max_length=1000)
    district: str | None = Field(default=None, max_length=64)
    cluster_id: uuid.UUID | None = None


class WarningOut(BaseModel):
    id: uuid.UUID
    title: str
    body_en: str
    body_ur: str | None
    district: str | None
    cluster_id: uuid.UUID | None
    status: str
    published_at: str | None


class WarningList(Page):
    items: list[WarningOut]
