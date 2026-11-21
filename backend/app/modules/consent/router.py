"""The consent centre: who has my data, who looked at it, correct it, export it, ask for it to be erased.

A citizen acts for themself; a helper acts for a family with a live delegation and a switch ticket.
Erasure is the person's own request only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.contracts.api import ConsentCreate, ConsentNarrow, ConsentOut
from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.errors import NotFound
from app.core.policy import Policy
from app.db import models
from app.modules.consent import access_log, export, requests, service
from app.modules.consent.rules import require_consent_for_helper_read
from app.modules.people.context import PersonContext, acting_person, resolve_person

router = APIRouter(prefix="/v1", tags=["consent"])

_read = acting_person("consent:read-own", "track", description="See who holds my data and who looked at it")
_manage = acting_person("consent:manage-own", "apply", description="Give, narrow or take back consent; ask for a correction")
_export = acting_person("consent:export-own", "track", description="Download everything the department holds about me")
_erase = Policy("consent:erase-own", ["citizen"], description="Ask for my data to be erased (the person only; an officer decides)")


def _me(principal: Principal = Depends(_erase), db: Session = Depends(get_db)) -> PersonContext:
    return resolve_person(db, principal, None, "apply")


@router.get("/consents", response_model=list[ConsentOut], summary="Who has my data, for what, until when")
def list_consents(ctx: PersonContext = Depends(_read), db: Session = Depends(get_db)) -> list[ConsentOut]:
    return service.list_consents(db, ctx)


@router.post("/consents", response_model=ConsentOut, status_code=201, summary="Share my data with this department for a purpose")
def grant_consent(body: ConsentCreate, response: Response, ctx: PersonContext = Depends(_manage),
                  db: Session = Depends(get_db)) -> ConsentOut:  # fmt: skip
    out, created = service.grant(db, ctx, body)
    if not created:
        response.status_code = 200
    return out


@router.patch("/consents/{consent_id}", response_model=ConsentOut, summary="Share less: remove field scopes from a consent")
def narrow_consent(consent_id: UUID, body: ConsentNarrow, ctx: PersonContext = Depends(_manage),
                   db: Session = Depends(get_db)) -> ConsentOut:  # fmt: skip
    return service.narrow(db, ctx, consent_id, body)


@router.post("/consents/{consent_id}/withdraw", response_model=ConsentOut, summary="Take my data back; stops access on the next request")
def withdraw_consent(consent_id: UUID, ctx: PersonContext = Depends(_manage), db: Session = Depends(get_db)) -> ConsentOut:
    return service.withdraw(db, ctx, consent_id)


@router.get("/me/access-log", response_model=access_log.AccessLogPage,
            summary="Who looked at my data: reads by staff, helpers and partner systems, and refused attempts")  # fmt: skip
def my_access_log(
    ctx: PersonContext = Depends(_read),
    db: Session = Depends(get_db),
    cursor: int | None = Query(default=None, ge=1, description="Entries older than this one (the seq of the last entry seen)"),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> access_log.AccessLogPage:
    require_consent_for_helper_read(db, ctx, action="access_log.read")
    person = db.get(models.Person, ctx.person_id)
    if person is None:
        raise NotFound("We could not find your record.")
    page = access_log.access_log(db, tenant_id=ctx.tenant_id, person_id=ctx.person_id, own_user_id=person.user_id, cursor=cursor,
                                 limit=limit)  # fmt: skip
    if ctx.via_helper:
        access_log.record_view(db, ctx.principal, ctx.person_id, what="access_log")
        db.commit()
    return page


@router.get("/me/data-requests", response_model=list[requests.DataRequestOut], summary="My correction and erasure requests")
def my_data_requests(ctx: PersonContext = Depends(_read), db: Session = Depends(get_db)) -> list[requests.DataRequestOut]:
    return requests.list_requests(db, ctx)


@router.post("/me/corrections", response_model=requests.DataRequestOut, status_code=201,
             summary="Ask for a wrong value to be corrected (an officer decides)")  # fmt: skip
def request_correction(body: requests.CorrectionIn, ctx: PersonContext = Depends(_manage),
                       db: Session = Depends(get_db)) -> requests.DataRequestOut:  # fmt: skip
    return requests.request_correction(db, ctx, body)


@router.post("/me/erasure-request", response_model=requests.DataRequestOut, status_code=201,
             summary="Ask for my data to be erased (nothing is deleted until an officer approves)")  # fmt: skip
def request_erasure(body: requests.ErasureIn, ctx: PersonContext = Depends(_me), db: Session = Depends(get_db)) -> requests.DataRequestOut:
    return requests.request_erasure(db, ctx, body)


@router.get("/me/export", summary="Download everything we hold about me (JSON)",
            responses={200: {"content": {"application/json": {}}, "description": "The export file"}})  # fmt: skip
def export_my_data(ctx: PersonContext = Depends(_export), db: Session = Depends(get_db)) -> JSONResponse:
    require_consent_for_helper_read(db, ctx, action="person.export")
    data = export.export(db, ctx)
    name = f"rahat-my-data-{datetime.now(UTC):%Y%m%d}.json"
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})
