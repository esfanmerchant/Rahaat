"""Digital Twin API (`/v1/twin`): try a rule version on past and labelled cases before it goes live.

    POST /v1/twin/runs                       run a draft against the active version (or another); sandboxed
    GET  /v1/twin/runs                       runs, newest first
    GET  /v1/twin/runs/{id}                  one run: changes, directions, costs, fairness slices, a sample
    POST /v1/twin/runs/{id}/request-publish  hand the draft to the four-eyes flow (a second admin publishes it)
    POST /v1/twin/runs/{id}/discard          record that the draft does not go ahead
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.twin import service
from app.modules.twin.schemas import ReasonIn, TwinRunIn, TwinRunList, TwinRunOut

router = APIRouter(prefix="/v1/twin", tags=["digital twin"])
_run = Policy("twin:run", ["admin"], description="Run a rule version in the Digital Twin and publish or discard it")
_read = Policy("twin:read", ["admin", "auditor"], description="Read Digital Twin runs")


@router.post("/runs", response_model=TwinRunOut, status_code=201, summary="Run a draft over past and labelled cases; nothing is sent or paid")
def run(body: TwinRunIn, principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> TwinRunOut:
    out = service.run(db, principal, body)
    db.commit()
    return out


@router.get("/runs", response_model=TwinRunList, summary="Digital Twin runs, newest first")
def list_runs(
    principal: Principal = Depends(_read),
    db: Session = Depends(get_db),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = Query(None, max_length=120),
) -> TwinRunList:
    return service.list_runs(db, principal, limit=limit, cursor=cursor)


@router.get("/runs/{run_id}", response_model=TwinRunOut, summary="One Digital Twin run")
def get_run(run_id: UUID, principal: Principal = Depends(_read), db: Session = Depends(get_db)) -> TwinRunOut:
    return service.get(db, principal, run_id)


@router.post("/runs/{run_id}/request-publish", response_model=TwinRunOut, summary="Send the draft for a second admin to publish")
def request_publish(run_id: UUID, body: ReasonIn, principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> TwinRunOut:
    out = service.request_publish(db, principal, run_id, body.reason)
    db.commit()
    return out


@router.post("/runs/{run_id}/discard", response_model=TwinRunOut, summary="Record that the draft does not go ahead")
def discard(run_id: UUID, body: ReasonIn, principal: Principal = Depends(_run), db: Session = Depends(get_db)) -> TwinRunOut:
    out = service.discard(db, principal, run_id, body.reason)
    db.commit()
    return out
