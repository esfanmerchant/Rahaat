"""Citizen self-registration with a one-time code sent through the notifications outbox.

    POST /v1/people/register/start     {tenant_slug, phone, lang}       -> 202 {registration_id, expires_in}
    POST /v1/people/register/complete  {tenant_slug, registration_id, code, full_name, pin, ...} -> 201

No enumeration: `start` answers the same way, with the same amount of work (one code hash, one message,
one audit row), whether or not the number already has an account. A number that is already registered
gets a "you already have an account, sign in instead" message and a decoy registration id that can never
complete. `complete` always runs one hash verification and gives one generic error for a wrong code, an
expired code, a used code or a decoy.

Registration happens before there is an authenticated caller, so it uses the system database context for
narrow lookups by keyed hash, exactly like sign-in. The code is stored only as an argon2 hash, lives for
ten minutes and allows five attempts.
"""

from __future__ import annotations

import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.common import Strict
from app.core import audit, metrics
from app.core.crypto import blind_index, decrypt_field, encrypt_field, encrypt_platform
from app.core.db import system_session
from app.core.errors import NotFound, TooManyRequests, Unauthorized, Unprocessable
from app.core.logging import get_logger
from app.core.mockdata import normalise_mock_phone
from app.core.security import check_pin_strength, hash_secret, verify_secret
from app.db import models
from app.modules.applications import hooks

log = get_logger("rahat.registration")

CODE_TTL: Final = timedelta(minutes=10)
MAX_ATTEMPTS: Final = 5
MAX_STARTS_PER_PHONE: Final = 3  # per CODE_TTL window; more are answered the same way but send nothing
IP_ATTEMPTS_PER_MINUTE: Final = 20
_GENERIC_CODE_ERROR = "The code is not right or has expired. Ask for a new code."

_ip_hits: dict[str, deque[float]] = defaultdict(deque)  # per process, like the sign-in throttle
_phone_starts: dict[str, deque[float]] = defaultdict(deque)


class RegisterStartIn(Strict):
    tenant_slug: str = Field(min_length=2, max_length=64)
    phone: str = Field(min_length=10, max_length=16, description="Mock phone, 0999-NNNNNNN")
    lang: Literal["ur", "en"] = "ur"


class RegisterStartOut(BaseModel):
    registration_id: UUID
    expires_in: int
    message_key: str = Field(default="register_code_sent", description="Same for every number, registered or not")


class RegisterCompleteIn(Strict):
    tenant_slug: str = Field(min_length=2, max_length=64)
    registration_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    full_name: str = Field(min_length=2, max_length=200)
    full_name_ur: str | None = Field(default=None, max_length=200)
    pin: str = Field(min_length=4, max_length=6)
    dob: date | None = None
    gender: Literal["female", "male", "other"] | None = None
    district: str | None = Field(default=None, max_length=64)


class RegisterCompleteOut(BaseModel):
    registered: bool = True
    person_id: UUID
    message_key: str = "register_done_sign_in"


def _throttle(bucket: dict[str, deque[float]], key: str, limit: int, window: float) -> bool:
    """True when the key is over its limit. Records the hit otherwise."""
    if not key:
        return False
    now = time.monotonic()
    hits = bucket[key]
    while hits and now - hits[0] > window:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    if len(bucket) > 10_000:
        bucket.clear()
    return False


def _throttle_ip(ip: str) -> None:
    if _throttle(_ip_hits, ip, IP_ATTEMPTS_PER_MINUTE, 60.0):
        metrics.AUTH_EVENTS.labels("register_throttled").inc()
        raise TooManyRequests("Too many tries. Wait a minute and try again.", headers={"Retry-After": "60"})


def _tenant(db: Session, slug: str) -> models.Tenant:
    tenant = db.scalar(select(models.Tenant).where(models.Tenant.slug == slug, models.Tenant.status == "active"))
    if tenant is None:
        raise NotFound("That department is not taking registrations.", code="tenant_not_found")
    return tenant


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _notify(db: Session, *, tenant_id: UUID, person_id: UUID | None, template: str, payload: dict[str, Any], lang: str) -> None:
    notify = hooks.optional(hooks.NOTIFY)
    if notify is None:
        log.warning("notifications module not available; registration message %s not sent", template)
        return
    try:
        with db.begin_nested():
            notify(db, tenant_id=tenant_id, person_id=person_id, template=template, payload=payload, lang=lang, channels=("sms",))
    except Exception:  # noqa: BLE001
        log.exception("could not queue registration message %s", template)


def start(body: RegisterStartIn, *, ip: str) -> RegisterStartOut:
    _throttle_ip(ip)
    phone = normalise_mock_phone(body.phone)
    if phone is None:
        raise Unprocessable("Use the mock phone format 0999-NNNNNNN.", code="mock_phone_format")
    code = _new_code()
    code_hash = hash_secret(code)  # computed on both paths so they take the same time
    over_limit = _throttle(_phone_starts, blind_index(phone, scope="register-start"), MAX_STARTS_PER_PHONE, CODE_TTL.total_seconds())
    now = datetime.now(UTC)

    with system_session() as db:
        tenant = _tenant(db, body.tenant_slug)
        scope = str(tenant.id)
        user = db.scalar(select(models.User).where(models.User.phone_hash == blind_index(phone)))
        if user is not None:
            # Already registered. Say the same thing, send a sign-in reminder instead of a code.
            registration_id = uuid.uuid4()
            existing = db.scalar(select(models.Person.id).where(models.Person.tenant_id == tenant.id, models.Person.user_id == user.id))
            template, payload, person_id = "registration_exists", {}, existing
        else:
            pending = db.scalar(
                select(models.Person).where(
                    models.Person.tenant_id == tenant.id, models.Person.phone_hash == blind_index(phone, scope=scope),
                    models.Person.status == "pending",
                )
            )  # fmt: skip
            if pending is None:
                pending = models.Person(
                    tenant_id=tenant.id, full_name="", status="pending", lang=body.lang,
                    phone_enc=encrypt_field(tenant.wrapped_dek, phone), phone_hash=blind_index(phone, scope=scope),
                )  # fmt: skip
                db.add(pending)
            pending.data = {"registration": {"code_hash": code_hash, "expires_at": (now + CODE_TTL).isoformat(), "attempts": 0}}
            db.flush()
            registration_id = pending.id
            template, payload, person_id = "registration_code", {"code": code, "expires_minutes": int(CODE_TTL.total_seconds() // 60)}, pending.id
        if not over_limit:
            _notify(db, tenant_id=tenant.id, person_id=person_id, template=template, payload=payload, lang=body.lang)
        audit.write(db, tenant_id=tenant.id, action="person.registration_started", actor_type="system", object_type="registration",
                    details={"phone_ref": blind_index(phone, scope="registration")[:16], "sent": not over_limit})  # fmt: skip
    metrics.AUTH_EVENTS.labels("register_start").inc()
    return RegisterStartOut(registration_id=registration_id, expires_in=int(CODE_TTL.total_seconds()))


def complete(body: RegisterCompleteIn, *, ip: str) -> RegisterCompleteOut:
    _throttle_ip(ip)
    check_pin_strength(body.pin)
    now = datetime.now(UTC)
    with system_session() as db:
        tenant = _tenant(db, body.tenant_slug)
        person = db.scalars(
            select(models.Person)
            .where(models.Person.id == body.registration_id, models.Person.tenant_id == tenant.id, models.Person.status == "pending")
            .with_for_update()
        ).first()
        reg: dict[str, Any] = dict((person.data or {}).get("registration") or {}) if person else {}
        usable = bool(reg) and int(reg.get("attempts", 0)) < MAX_ATTEMPTS and datetime.fromisoformat(reg["expires_at"]) > now
        code_ok = verify_secret(reg.get("code_hash") if usable else None, body.code)  # always one verification
        if person is None or not usable or not code_ok:
            if person is not None and reg:
                reg["attempts"] = int(reg.get("attempts", 0)) + 1
                person.data = {**(person.data or {}), "registration": reg}
                db.commit()  # keep the attempt count although the request fails
            metrics.AUTH_EVENTS.labels("register_failed").inc()
            raise Unauthorized(_GENERIC_CODE_ERROR, code="invalid_code")

        phone = decrypt_field(tenant.wrapped_dek, person.phone_enc or "")
        if db.scalar(select(models.User.id).where(models.User.phone_hash == blind_index(phone))) is not None:
            raise Unauthorized(_GENERIC_CODE_ERROR, code="invalid_code")  # registered meanwhile; the code is spent
        user = models.User(phone_hash=blind_index(phone), phone_enc=encrypt_platform(phone), display_name=body.full_name,
                           lang=person.lang or "ur", password_hash=hash_secret(body.pin))  # fmt: skip
        db.add(user)
        db.flush()
        person.user_id = user.id
        person.full_name = body.full_name
        person.full_name_ur = body.full_name_ur
        person.dob = body.dob
        person.gender = body.gender
        person.district = body.district
        person.status = "active"
        person.created_by = user.id
        person.data = {}
        db.add(models.Membership(tenant_id=tenant.id, user_id=user.id, role="citizen", person_id=person.id))
        audit.write(db, tenant_id=tenant.id, action="person.registered", actor_id=user.id, actor_role="citizen", object_type="person",
                    object_id=person.id, details={"channel": "self", "via": "one_time_code"})  # fmt: skip
        person_id = person.id
    metrics.AUTH_EVENTS.labels("register_complete").inc()
    return RegisterCompleteOut(person_id=person_id)
