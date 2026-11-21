"""Response shapes of the anomaly API. Staff views only: detection details are never shown to citizens."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.modules.anomaly.detectors import DetectorName, Status


class DetectorStatus(BaseModel):
    detector: DetectorName
    title: str
    status: Status
    flags: int = Field(description="Findings in the last run")
    abstained_reason: str | None = Field(default=None, description="Why the detector did not judge (not enough data), as a code")
    data_points: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class ScanSummary(BaseModel):
    run_id: uuid.UUID
    ran_at: str
    trigger: str = Field(description="manual | job | event")
    applications_scanned: int
    cases_opened: int
    cases_refreshed: int
    suppressed: int = Field(description="Findings a person already reviewed in full")
    detectors: list[DetectorStatus]


class FlagOut(BaseModel):
    case_id: uuid.UUID
    case_status: str
    detector: DetectorName
    title: str
    pattern_key: str
    confidence: float | None = Field(description="A heuristic score of the pattern, not a calibrated probability")
    priority: int
    evidence: dict[str, Any] = Field(description="Chips: numbers and short labels, never raw identifiers")
    evidence_count: int = Field(description="How many applications are behind the pattern")
    evidence_ids: list[str] = Field(description="Application ids, capped")
    cheapest_check: str | None
    resolution: str | None
    created_at: str


class AnomaliesOut(BaseModel):
    last_scan: ScanSummary | None = None
    flags: list[FlagOut]
    counts: dict[str, int] = Field(description="Active flags per detector")
    note: str


class ScanQueuedOut(BaseModel):
    job_id: uuid.UUID
    status: str
    already_queued: bool
