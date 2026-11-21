"""Duplicates API (`/v1/duplicates`): officers see possible duplicates and link, separate or unlink them.

    GET  /v1/duplicates                  pairs found by dedupe, newest first (filter by status)
    GET  /v1/duplicates/{id}             one pair, with what agreed and what did not
    POST /v1/duplicates/{id}/link        one person (reason required, audited, reversible)
    POST /v1/duplicates/{id}/distinct    two people (reason required, audited)
    POST /v1/duplicates/{id}/unlink      reverse a link (reason required, audited)
    POST /v1/matching/compare            compare two mock records without storing anything (Challenge Lab)

Both people must be readable under their consent; otherwise the officer gets 403 and the attempt is logged.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Strict
from app.core.deps import Principal, get_db
from app.core.mockdata import mock_id_shape_ok, normalise_mock_phone
from app.core.policy import Policy
from app.modules.matching import service
from app.modules.matching.compare import PersonRecord, compare

router = APIRouter(tags=["duplicates"])
_review = Policy("duplicates:review", ["officer"], description="See and decide possible duplicate people")
_compare = Policy("matching:compare", ["officer", "admin", "auditor"], description="Compare two mock records; nothing is stored")

Status = Literal["open", "linked", "rejected", "reversed", "all"]


class ReasonIn(Strict):
    reason: str = Field(min_length=5, max_length=1000, description="Stored in the audit log")


class RecordIn(Strict):
    """A person as typed. Mock formats only: IDs 00000-NNNNNNN-C (a wrong check digit is allowed here, to show
    typos), phones 0999-NNNNNNN."""

    full_name: str | None = Field(default=None, max_length=200)
    full_name_ur: str | None = Field(default=None, max_length=200)
    dob: str | None = Field(default=None, max_length=20)
    gender: str | None = Field(default=None, max_length=16)
    district: str | None = Field(default=None, max_length=64)
    national_id: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("national_id")
    @classmethod
    def _mock_id(cls, value: str | None) -> str | None:
        if value and not mock_id_shape_ok(value.strip()):
            raise ValueError("Use the mock ID format 00000-NNNNNNN-C.")
        return value.strip() if value else None

    @field_validator("phone")
    @classmethod
    def _mock_phone(cls, value: str | None) -> str | None:
        if value and normalise_mock_phone(value) is None:
            raise ValueError("Use the mock phone format 0999-NNNNNNN.")
        return normalise_mock_phone(value) if value else None

    def record(self, ref: str) -> PersonRecord:
        return PersonRecord(ref=ref, names=tuple(n for n in (self.full_name, self.full_name_ur) if n), dob=self.dob, gender=self.gender,
                            district=self.district, national_id=self.national_id, phone=self.phone)  # fmt: skip


class CompareIn(Strict):
    a: RecordIn
    b: RecordIn


class CompareOut(BaseModel):
    band: str = Field(description="same | possible | distinct")
    score: float
    name_score: float
    fields: dict[str, str]
    weights: dict[str, float]
    corroborated: bool
    conflicts: list[str]
    reasons: list[str]
    blocked_together: bool = Field(description="Whether blocking would even compare these two records")
    note: str = "Nothing was stored. Same needs an agreeing identifier and nothing contradicting; a name alone is never enough."


@router.get("/v1/duplicates", summary="Possible and linked duplicates, newest first")
def list_duplicates(
    principal: Principal = Depends(_review),
    db: Session = Depends(get_db),
    status: Status = Query("open"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=120),
) -> dict[str, Any]:
    return service.list_candidates(db, principal, status=status, limit=limit, before=cursor)


@router.get("/v1/duplicates/{candidate_id}", summary="One pair and what agreed")
def get_duplicate(candidate_id: UUID, principal: Principal = Depends(_review), db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.get_candidate(db, principal, candidate_id)


def _decide(decision: str) -> Any:
    def endpoint(candidate_id: UUID, body: ReasonIn, principal: Principal = Depends(_review), db: Session = Depends(get_db)) -> dict[str, Any]:
        out = service.decide_pair(db, principal, candidate_id, decision=decision, reason=body.reason)
        db.commit()
        return out

    endpoint.__name__ = f"{decision}_duplicate"
    return endpoint


router.post("/v1/duplicates/{candidate_id}/link", summary="The same person: link the two records (reversible)")(_decide("link"))
router.post("/v1/duplicates/{candidate_id}/distinct", summary="Two different people")(_decide("distinct"))
router.post("/v1/duplicates/{candidate_id}/unlink", summary="Reverse a link")(_decide("unlink"))


@router.post("/v1/matching/compare", response_model=CompareOut, summary="Compare two mock records; nothing is stored")
def compare_records(body: CompareIn, principal: Principal = Depends(_compare)) -> CompareOut:
    from app.modules.matching.compare import blocking_keys

    a, b = body.a.record("a"), body.b.record("b")
    result = compare(a, b)
    return CompareOut(band=result.band, score=result.score, name_score=result.name.score, fields=dict(result.fields),
                      weights={k: round(v, 3) for k, v in result.weights.items()}, corroborated=result.corroborated,
                      conflicts=list(result.conflicts), reasons=list(result.reasons),
                      blocked_together=bool(blocking_keys(a) & blocking_keys(b)))  # fmt: skip
