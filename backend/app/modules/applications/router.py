from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.contracts.api import ApplicationCreate, ApplicationList, ApplicationOut, ApplicationPatch, ProgramOut, SubmitOut
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import ALL_ROLES, Principal, get_db
from app.core.policy import Policy
from app.modules.applications import pipeline, service
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1", tags=["applications"])

_programs = Policy("programs:read", ALL_ROLES, description="Programs open in the caller's department")
_track = acting_person("applications:read-own", "track", description="A citizen's own applications, or a helper's delegated person's")
_apply = acting_person("applications:write-own", "apply", description="Start, answer and submit an application")


@router.get("/programs", response_model=list[ProgramOut], summary="Programs in this department, with the active rule version")
def list_programs(principal: Principal = Depends(_programs), db: Session = Depends(get_db)) -> list[ProgramOut]:
    return service.list_programs(db, principal)


@router.get("/applications", response_model=ApplicationList, summary="My applications, newest first")
def list_applications(
    ctx: PersonContext = Depends(_track),
    db: Session = Depends(get_db),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ApplicationList:
    return service.list_applications(db, ctx, cursor=cursor, limit=limit)


@router.post("/applications", response_model=ApplicationOut, status_code=201,
             summary="Start an application (the same client_op_id returns the same application)")  # fmt: skip
def create_application(body: ApplicationCreate, response: Response, ctx: PersonContext = Depends(_apply),
                       db: Session = Depends(get_db)) -> ApplicationOut:  # fmt: skip
    out, created = service.create_application(db, ctx, body)
    if not created:
        response.status_code = 200
    return out


@router.get("/applications/{application_id}", response_model=ApplicationOut, summary="One application with documents, decision and timeline")
def get_application(application_id: UUID, ctx: PersonContext = Depends(_track), db: Session = Depends(get_db)) -> ApplicationOut:
    return service.get_application(db, ctx, application_id)


@router.patch("/applications/{application_id}", response_model=ApplicationOut, summary="Save answers (optimistic lock on base_version)")
def patch_application(application_id: UUID, body: ApplicationPatch, ctx: PersonContext = Depends(_apply),
                      db: Session = Depends(get_db)) -> ApplicationOut:  # fmt: skip
    return service.patch_application(db, ctx, application_id, body)


@router.post("/applications/{application_id}/submit", response_model=SubmitOut,
             summary="Submit and get the decision (repeat submits return the first result)")  # fmt: skip
def submit_application(application_id: UUID, ctx: PersonContext = Depends(_apply), db: Session = Depends(get_db)) -> SubmitOut:
    return pipeline.submit(db, ctx, application_id)
