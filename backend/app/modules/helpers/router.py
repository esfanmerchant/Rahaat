"""Community helpers: a citizen chooses a helper; the helper switches between families with each family's PIN.

    GET  /v1/me/helpers                     citizen: who may help me
    POST /v1/me/helpers                     citizen: let a helper (by mock phone) help me, with scopes, expiry, PIN
    POST /v1/me/helpers/{id}/revoke         citizen: stop that helper at once
    GET  /v1/helper/families                helper: my families, their application status, live or not
    POST /v1/helper/switch                  helper: family PIN -> switch ticket for this session and that person
    POST /v1/helper/switch/end              helper: hand the phone back; the ticket stops working
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.deps import Principal, get_db
from app.core.policy import Policy
from app.modules.helpers import service
from app.modules.helpers.schemas import DelegationCreate, DelegationOut, FamiliesOut, SwitchIn, SwitchOut
from app.modules.people.context import PersonContext, resolve_person

router = APIRouter(prefix="/v1", tags=["helpers"])

_citizen = Policy("helpers:manage-own", ["citizen"], description="A citizen chooses who may help them, and stops them")
_helper = Policy("helper:families", ["helper"], description="A community helper's own families and switching between them")


def _me(principal: Principal = Depends(_citizen), db: Session = Depends(get_db)) -> PersonContext:
    return resolve_person(db, principal, None, "apply")


@router.get("/me/helpers", response_model=list[DelegationOut], summary="Who may help me, with what, until when")
def list_my_helpers(ctx: PersonContext = Depends(_me), db: Session = Depends(get_db)) -> list[DelegationOut]:
    return service.list_delegations(db, ctx)


@router.post("/me/helpers", response_model=DelegationOut, status_code=201, summary="Let a community helper act for me")
def grant_helper(body: DelegationCreate, ctx: PersonContext = Depends(_me), db: Session = Depends(get_db)) -> DelegationOut:
    return service.grant(db, ctx, body)


@router.post("/me/helpers/{delegation_id}/revoke", response_model=DelegationOut, summary="Stop a helper at once")
def revoke_helper(delegation_id: UUID, ctx: PersonContext = Depends(_me), db: Session = Depends(get_db)) -> DelegationOut:
    return service.revoke(db, ctx, delegation_id)


@router.get("/helper/families", response_model=FamiliesOut, summary="My families: application status and whether I may still help")
def my_families(
    principal: Principal = Depends(_helper),
    db: Session = Depends(get_db),
    cursor: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
) -> FamiliesOut:
    return service.families(db, principal, cursor=cursor, limit=limit or DEFAULT_PAGE_SIZE)


@router.post("/helper/switch", response_model=SwitchOut, summary="Switch to a family with its PIN (attempts are limited)")
def switch_family(body: SwitchIn, principal: Principal = Depends(_helper), db: Session = Depends(get_db)) -> SwitchOut:
    return service.switch(db, principal, body)


@router.post("/helper/switch/end", status_code=204, summary="Hand the phone back: the current switch ticket stops working")
def end_switch(principal: Principal = Depends(_helper), db: Session = Depends(get_db)) -> Response:
    service.end_switch(db, principal)
    return Response(status_code=204)
