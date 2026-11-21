from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.contracts.api import ConsentCreate, ConsentNarrow, ConsentOut
from app.core.deps import get_db
from app.modules.consent import service
from app.modules.people.context import PersonContext, acting_person

router = APIRouter(prefix="/v1/consents", tags=["consent"])

_read = acting_person("consent:read-own", "track", description="See who holds my data")
_manage = acting_person("consent:manage-own", "apply", description="Give, narrow or take back consent")


@router.get("", response_model=list[ConsentOut], summary="Who has my data, for what, until when")
def list_consents(ctx: PersonContext = Depends(_read), db: Session = Depends(get_db)) -> list[ConsentOut]:
    return service.list_consents(db, ctx)


@router.post("", response_model=ConsentOut, status_code=201, summary="Share my data with this department for a purpose")
def grant_consent(body: ConsentCreate, response: Response, ctx: PersonContext = Depends(_manage),
                  db: Session = Depends(get_db)) -> ConsentOut:  # fmt: skip
    out, created = service.grant(db, ctx, body)
    if not created:
        response.status_code = 200
    return out


@router.patch("/{consent_id}", response_model=ConsentOut, summary="Share less: remove field scopes from a consent")
def narrow_consent(consent_id: UUID, body: ConsentNarrow, ctx: PersonContext = Depends(_manage),
                   db: Session = Depends(get_db)) -> ConsentOut:  # fmt: skip
    return service.narrow(db, ctx, consent_id, body)


@router.post("/{consent_id}/withdraw", response_model=ConsentOut, summary="Take my data back; stops access on the next request")
def withdraw_consent(consent_id: UUID, ctx: PersonContext = Depends(_manage), db: Session = Depends(get_db)) -> ConsentOut:
    return service.withdraw(db, ctx, consent_id)
