from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.contracts.api import PersonOut
from app.core.deps import get_db
from app.modules.people import service
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1", tags=["people"])

_track = acting_person("people:read-own", "track", description="A citizen's own record, or a helper's delegated person")


@router.get("/me/person", response_model=PersonOut, summary="My person record (or the person a helper acts for)")
def my_person(ctx: PersonContext = Depends(_track), db: Session = Depends(get_db)) -> PersonOut:
    return service.person_out(db, service.get_person(db, ctx))
