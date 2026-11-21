"""People, their identifiers, duplicates, helper delegations and consent."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, Float, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedMixin, IdMixin, TenantMixin, UpdatedMixin, fk, json_dict, json_list, ts


class Person(Base, IdMixin, TenantMixin, CreatedMixin, UpdatedMixin):
    """A department's record of one person. Identifiers are encrypted; lookups use blind indexes."""

    __tablename__ = "persons"
    __table_args__ = (Index("ix_persons_tenant_name_key", "tenant_id", "name_key"),)
    user_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)  # set when the person has their own login
    full_name: Mapped[str] = mapped_column(String(200))
    full_name_ur: Mapped[str | None] = mapped_column(String(200))
    name_key: Mapped[str | None] = mapped_column(String(120))  # phonetic key used for blocking in dedupe
    dob: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[str | None] = mapped_column(String(16))
    district: Mapped[str | None] = mapped_column(String(64))
    lang: Mapped[str] = mapped_column(String(8), default="ur")
    phone_enc: Mapped[str | None] = mapped_column(Text)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    national_id_enc: Mapped[str | None] = mapped_column(Text)
    national_id_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | merged | deleted
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    data: Mapped[dict[str, Any]] = json_dict()
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class PersonIdentifier(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "person_identifiers"
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    kind: Mapped[str] = mapped_column(String(32))  # national_id | phone | payout_account | device
    value_enc: Mapped[str] = mapped_column(Text)
    value_hash: Mapped[str] = mapped_column(String(64), index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(32), default="declared")  # declared | qr_signed | registry


class NameVariant(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "name_variants"
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    variant: Mapped[str] = mapped_column(String(200))
    script: Mapped[str] = mapped_column(String(16), default="latin")  # latin | arabic
    name_key: Mapped[str | None] = mapped_column(String(120), index=True)
    source: Mapped[str] = mapped_column(String(32), default="declared")


class HouseholdLink(Base, IdMixin, TenantMixin, CreatedMixin):
    __tablename__ = "household_links"
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    household_key: Mapped[str] = mapped_column(String(64), index=True)
    relation: Mapped[str] = mapped_column(String(32), default="member")
    data: Mapped[dict[str, Any]] = json_dict()


class DuplicateCandidate(Base, IdMixin, TenantMixin, CreatedMixin):
    """A possible duplicate pair. Never merged on name alone; the middle band goes to a human."""

    __tablename__ = "duplicate_candidates"
    person_a_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    person_b_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(16))  # same | possible | distinct
    evidence: Mapped[dict[str, Any]] = json_dict()
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | linked | rejected | reversed
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = ts()


class HelperDelegation(Base, IdMixin, TenantMixin, CreatedMixin):
    """A person's permission for one helper to act for them. Per person, scoped, expiring, revocable."""

    __tablename__ = "helper_delegations"
    __table_args__ = (Index("ix_delegation_helper_person", "helper_user_id", "person_id"),)
    helper_user_id: Mapped[uuid.UUID] = fk("users.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    scopes: Mapped[list[Any]] = json_list()  # ["apply", "track", "upload"]
    pin_hash: Mapped[str | None] = mapped_column(Text)  # the person's PIN for switching on a shared phone
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = ts()


class Consent(Base, IdMixin, TenantMixin, CreatedMixin):
    """Who may use a person's data, for what, which fields, and until when."""

    __tablename__ = "consents"
    __table_args__ = (
        Index("ix_consents_person_status", "person_id", "status"),
        # One active consent per person, grantee and purpose, even if two requests race.
        Index("uq_consents_active", "tenant_id", "person_id", "grantee_type", "grantee_id", "purpose", unique=True,
              postgresql_where=text("status = 'active'")),
    )
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    grantee_type: Mapped[str] = mapped_column(String(16))  # tenant | helper | api_key | partner
    grantee_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(64))  # relief_application | scam_report | research ...
    field_scopes: Mapped[list[Any]] = json_list()  # ["identity", "household", "income", "documents", "contact"]
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | withdrawn | expired
    version: Mapped[int] = mapped_column(Integer, default=1)
    granted_at: Mapped[datetime] = mapped_column()
    expires_at: Mapped[datetime | None] = ts()
    withdrawn_at: Mapped[datetime | None] = ts()
    data: Mapped[dict[str, Any]] = json_dict()


class ConsentEvent(Base, IdMixin, TenantMixin, CreatedMixin):
    """Append-only history of consent changes."""

    __tablename__ = "consent_events"
    consent_id: Mapped[uuid.UUID] = fk("consents.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    event: Mapped[str] = mapped_column(String(32))  # granted | narrowed | withdrawn | expired
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any]] = json_dict()


class CorrectionRequest(Base, IdMixin, TenantMixin, CreatedMixin):
    """A citizen asking for a wrong value to be fixed; reviewed by an officer as a case."""

    __tablename__ = "correction_requests"
    person_id: Mapped[uuid.UUID] = fk("persons.id", ondelete="CASCADE")
    field: Mapped[str] = mapped_column(String(64))
    old_value_hash: Mapped[str | None] = mapped_column(String(64))
    new_value_enc: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | accepted | rejected
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolved_at: Mapped[datetime | None] = ts()
