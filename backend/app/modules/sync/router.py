"""Offline sync: the device sends what it queued without signal; each op is applied at most once."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.modules.people.context import PersonContext, acting_person
from app.modules.sync import service
from app.modules.sync.schemas import SyncIn, SyncOut

router = APIRouter(prefix="/v1", tags=["sync"])

_sync = acting_person("sync:apply", "apply", description="A citizen's own queued changes, or a helper's for the family they switched to")


@router.post("/sync", response_model=SyncOut, summary="Apply changes queued offline, in order; the same op is never applied twice")
def sync(
    body: SyncIn,
    ctx: PersonContext = Depends(_sync),
    db: Session = Depends(get_db),
    x_acting_for: str | None = Header(default=None, alias="X-Acting-For", include_in_schema=False),
    x_helper_ticket: str | None = Header(default=None, alias="X-Helper-Ticket", max_length=128, include_in_schema=False),
) -> SyncOut:
    return service.apply_batch(db, ctx, body, acting_for=x_acting_for, ticket=x_helper_ticket)
