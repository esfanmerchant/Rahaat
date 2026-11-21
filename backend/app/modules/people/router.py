from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.contracts.api import PersonOut
from app.core.context import current_client_ip
from app.core.deps import get_db
from app.core.policy import Public
from app.modules.consent.access_log import record_view
from app.modules.consent.rules import require_consent_for_helper_read
from app.modules.people import registration, service
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1", tags=["people"])

_register_start = Public("self-registration happens before the person has an account")
_register_complete = Public("proves control of the phone with the one-time code")
_track = acting_person("people:read-own", "track", description="A citizen's own record, or a helper's delegated person")


@router.get("/me/person", response_model=PersonOut, summary="My person record (or the person a helper acts for)")
def my_person(ctx: PersonContext = Depends(_track), db: Session = Depends(get_db)) -> PersonOut:
    require_consent_for_helper_read(db, ctx, action="person.read")
    out = service.person_out(db, service.get_person(db, ctx))
    if ctx.via_helper:  # a helper's read shows in the person's access log
        record_view(db, ctx.principal, ctx.person_id, what="person_record")
        db.commit()
    return out


@router.post("/people/register/start", response_model=registration.RegisterStartOut, status_code=202,
             summary="Register: send a one-time code to a mock phone (same answer whether or not it is registered)")  # fmt: skip
def register_start(body: registration.RegisterStartIn, _: None = Depends(_register_start)) -> registration.RegisterStartOut:
    return registration.start(body, ip=current_client_ip())


@router.post("/people/register/complete", response_model=registration.RegisterCompleteOut, status_code=201,
             summary="Register: confirm the code, set a PIN, then sign in")  # fmt: skip
def register_complete(body: registration.RegisterCompleteIn, _: None = Depends(_register_complete)) -> registration.RegisterCompleteOut:
    return registration.complete(body, ip=current_client_ip())
