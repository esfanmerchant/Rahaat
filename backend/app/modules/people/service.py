"""Person records as the citizen (or their helper) sees them: identifiers decrypted only to be masked."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.contracts.api import PersonOut
from app.core.crypto import decrypt_field
from app.core.errors import NotFound
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier
from app.db import models
from app.modules.people.context import PersonContext

log = get_logger("rahat.people")


def _masked(tenant: models.Tenant | None, token: str | None) -> str | None:
    if not token or tenant is None:
        return None
    try:
        return mask_identifier(decrypt_field(tenant.wrapped_dek, token))
    except Exception:  # noqa: BLE001
        log.warning("could not decrypt an identifier for masking")
        return None


def get_person(db: Session, ctx: PersonContext) -> models.Person:
    person = db.get(models.Person, ctx.person_id)
    if person is None or person.tenant_id != ctx.tenant_id or person.status == "deleted":
        raise NotFound("We could not find your record.")
    return person


def person_out(db: Session, person: models.Person) -> PersonOut:
    tenant = db.get(models.Tenant, person.tenant_id)
    return PersonOut(
        id=person.id,
        full_name=person.full_name,
        full_name_ur=person.full_name_ur,
        district=person.district,
        lang=person.lang or "ur",
        national_id_masked=_masked(tenant, person.national_id_enc),
        phone_masked=_masked(tenant, person.phone_enc),
    )


def registered_national_id(db: Session, person: models.Person) -> str | None:
    """The person's own registered ID in clear, for the identity and registry calls. Never logged or returned."""
    tenant = db.get(models.Tenant, person.tenant_id)
    if tenant is None or not person.national_id_enc:
        return None
    try:
        return decrypt_field(tenant.wrapped_dek, person.national_id_enc)
    except Exception:  # noqa: BLE001
        log.warning("could not decrypt the registered ID of a person")
        return None


def person_by_id(db: Session, tenant_id: UUID, person_id: UUID) -> models.Person | None:
    person = db.get(models.Person, person_id)
    return person if person is not None and person.tenant_id == tenant_id else None
