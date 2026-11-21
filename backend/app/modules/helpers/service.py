"""Helper delegations and safe switching between families on one shared phone (PLAN 7.A, A12).

Citizen side: grant a helper (found by their mock phone) a delegation with scopes, an expiry and a family
PIN; list and revoke delegations. Revocation is immediate: the database (`app_can_read_person`) and the
person context both require a live delegation on every request, and a switch ticket is bound to the
delegation it was issued under.

Helper side: the list of families, and `switch`, which checks the family PIN with attempt limits and
returns a short-lived ticket bound to this session and that person (see `tickets.py`).

The helper's account is looked up by a keyed hash of the phone number in the system context, the same
narrow pattern as sign-in. A citizen learns only whether that number belongs to an active community helper
of this department; "not a helper" and "no account" give the same answer.
"""

from __future__ import annotations

import base64
import json
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, case, select, text
from sqlalchemy.orm import Session

from app.contracts.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core import audit, metrics
from app.core.crypto import blind_index, decrypt_platform
from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound, TooManyRequests, Unprocessable
from app.core.logging import get_logger
from app.core.mockdata import mask_identifier, normalise_mock_phone
from app.core.security import check_pin_strength, hash_secret, verify_secret
from app.db import models
from app.modules.applications.timeline import symbols_for
from app.modules.consent.access_log import VIEW_ACTION, record_view
from app.modules.consent.rules import active_consent, people_with_active_consent
from app.modules.helpers import tickets
from app.modules.helpers.schemas import (
    DelegationCreate,
    DelegationOut,
    FamiliesOut,
    FamilyApplication,
    FamilyOut,
    SwitchIn,
    SwitchOut,
)
from app.modules.people.context import DELEGATION_SCOPES, PersonContext, live_delegations

log = get_logger("rahat.helpers")

SCOPE_ORDER: Final = ("track", "apply", "upload")
ENDED_VISIBLE_FOR: Final = timedelta(days=30)  # a revoked or expired family stays on the list this long, without its name
FAMILY_LIST_VIEW_EVERY: Final = timedelta(hours=1)  # one "seen in the family list" row per family per hour
GRANTS_PER_HOUR: Final = 10  # helper look-ups by phone, per person (in process, like the sign-in throttle)
_grant_attempts: dict[str, deque[float]] = defaultdict(deque)
_DELEGATION_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('delegation:' || :person_id || ':' || :helper_id, 0))")
# One switch attempt at a time per helper, so wrong PINs sent in parallel are all counted before the next is checked.
_SWITCH_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('helper-switch:' || :helper_id, 0))")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def delegation_status(delegation: models.HelperDelegation, now: datetime) -> str:
    if delegation.revoked_at is not None:
        return "revoked"
    if delegation.expires_at <= now:
        return "expired"
    return "live"


def ordered_scopes(scopes: list[str]) -> list[str]:
    wanted = set(scopes)
    return [s for s in SCOPE_ORDER if s in wanted]


# --- helper accounts (narrow system lookups) -------------------------------------------------------------


def _find_helper(tenant_id: UUID, phone: str) -> tuple[UUID, str] | None:
    """The active community helper of this department who uses this mock phone, if any."""
    with system_session() as sdb:
        row = sdb.execute(
            select(models.User.id, models.User.display_name)
            .join(models.Membership, models.Membership.user_id == models.User.id)
            .where(
                models.User.phone_hash == blind_index(phone), models.User.status == "active",
                models.Membership.tenant_id == tenant_id, models.Membership.role == "helper", models.Membership.status == "active",
            )
            .limit(1)
        ).first()  # fmt: skip
        return (row.id, row.display_name) if row is not None else None


def helper_cards(user_ids: set[UUID]) -> dict[UUID, tuple[str, str | None]]:
    """Display name and masked phone of the helpers a person chose. Only these ids are read."""
    if not user_ids:
        return {}
    with system_session() as sdb:
        rows = sdb.execute(select(models.User.id, models.User.display_name, models.User.phone_enc).where(models.User.id.in_(user_ids))).all()
    cards: dict[UUID, tuple[str, str | None]] = {}
    for row in rows:
        masked = None
        if row.phone_enc:
            try:
                masked = mask_identifier(decrypt_platform(row.phone_enc))
            except Exception:  # noqa: BLE001
                log.warning("could not decrypt a helper phone for masking")
        cards[row.id] = (row.display_name, masked)
    return cards


# --- citizen side ----------------------------------------------------------------------------------------


def _out(delegation: models.HelperDelegation, card: tuple[str, str | None] | None, now: datetime) -> DelegationOut:
    name, phone = card or ("Community helper", None)
    return DelegationOut(
        id=delegation.id, helper_name=name, helper_phone_masked=phone, scopes=ordered_scopes(list(delegation.scopes or [])),
        status=delegation_status(delegation, now), pin_set=bool(delegation.pin_hash), granted_at=_iso(delegation.created_at) or "",
        expires_at=_iso(delegation.expires_at) or "", revoked_at=_iso(delegation.revoked_at),
    )  # fmt: skip


def _require_self(ctx: PersonContext) -> None:
    if ctx.via_helper:
        raise Forbidden("Only the person can choose who helps them.", code="citizen_only")


def list_delegations(db: Session, ctx: PersonContext) -> list[DelegationOut]:
    _require_self(ctx)
    rows = db.scalars(
        select(models.HelperDelegation)
        .where(models.HelperDelegation.tenant_id == ctx.tenant_id, models.HelperDelegation.person_id == ctx.person_id)
        .order_by(models.HelperDelegation.created_at.desc(), models.HelperDelegation.id)
    ).all()
    cards = helper_cards({d.helper_user_id for d in rows})
    now = datetime.now(UTC)
    return [_out(d, cards.get(d.helper_user_id), now) for d in rows]


def _throttle_grant(ctx: PersonContext) -> None:
    """At most a few helper look-ups per person per hour, so phone numbers cannot be tried in bulk."""
    now = time.monotonic()
    hits = _grant_attempts[str(ctx.person_id)]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= GRANTS_PER_HOUR:
        retry = int(3600 - (now - hits[0])) + 1
        raise TooManyRequests("Too many tries. Try again later.", code="too_many_helper_lookups", headers={"Retry-After": str(retry)})
    hits.append(now)
    if len(_grant_attempts) > 10_000:
        _grant_attempts.clear()


def grant(db: Session, ctx: PersonContext, body: DelegationCreate) -> DelegationOut:
    """Let one helper act for me. 404 `helper_not_found`, 409 `delegation_exists`, 422 for a weak PIN, 429 when
    too many numbers were tried."""
    _require_self(ctx)
    phone = normalise_mock_phone(body.helper_phone)
    if phone is None:
        raise Unprocessable("Use the mock phone format 0999-NNNNNNN.", code="mock_phone_format")
    check_pin_strength(body.pin)
    _throttle_grant(ctx)
    found = _find_helper(ctx.tenant_id, phone)
    if found is None:
        audit.write_independent(tenant_id=ctx.tenant_id, action="helper.lookup_failed", actor_id=ctx.user_id, actor_role=ctx.principal.role,
                                object_type="person", object_id=ctx.person_id, result="denied", reason="helper_not_found",
                                details={"phone_ref": blind_index(phone, scope="helper-lookup")[:16]})  # fmt: skip
        raise NotFound("No community helper in this department uses that number.", code="helper_not_found")
    helper_id, helper_name = found
    if helper_id == ctx.user_id:
        raise Unprocessable("You cannot choose yourself as your helper.", code="cannot_delegate_to_self")
    db.execute(_DELEGATION_LOCK, {"person_id": str(ctx.person_id), "helper_id": str(helper_id)})
    existing = live_delegations(db, tenant_id=ctx.tenant_id, helper_user_id=helper_id, person_id=ctx.person_id)
    if existing:
        raise Conflict("This helper can already help you. Take it back first to change it.", code="delegation_exists",
                       extra={"delegation_id": str(existing[0].id)})  # fmt: skip
    now = datetime.now(UTC)
    scopes = ordered_scopes(list(body.scopes))
    delegation = models.HelperDelegation(
        tenant_id=ctx.tenant_id, helper_user_id=helper_id, person_id=ctx.person_id, scopes=scopes,
        pin_hash=hash_secret(body.pin), expires_at=now + timedelta(days=body.expires_in_days), created_at=now,
    )  # fmt: skip
    db.add(delegation)
    db.flush()
    audit.write(
        db, tenant_id=ctx.tenant_id, action="helper.delegation_granted", object_type="helper_delegation", object_id=delegation.id,
        details={"helper_user_id": str(helper_id), "person_id": str(ctx.person_id), "scopes": scopes,
                 "expires_at": _iso(delegation.expires_at)},  # fmt: skip
        **ctx.audit_fields(),
    )  # fmt: skip
    db.commit()
    return _out(delegation, (helper_name, mask_identifier(phone)), now)


def revoke(db: Session, ctx: PersonContext, delegation_id: UUID) -> DelegationOut:
    """Stop a helper at once. Their switch ticket stops working on the very next request."""
    _require_self(ctx)
    delegation = db.scalars(
        select(models.HelperDelegation)
        .where(models.HelperDelegation.id == delegation_id, models.HelperDelegation.tenant_id == ctx.tenant_id,
               models.HelperDelegation.person_id == ctx.person_id)  # fmt: skip
        .with_for_update()
    ).first()
    if delegation is None:
        raise NotFound("That helper permission does not exist.")
    now = datetime.now(UTC)
    if delegation.revoked_at is None:
        delegation.revoked_at = now
        audit.write(
            db, tenant_id=ctx.tenant_id, action="helper.delegation_revoked", object_type="helper_delegation", object_id=delegation.id,
            details={"helper_user_id": str(delegation.helper_user_id), "person_id": str(ctx.person_id)}, **ctx.audit_fields(),
        )  # fmt: skip
        db.commit()
    cards = helper_cards({delegation.helper_user_id})
    return _out(delegation, cards.get(delegation.helper_user_id), now)


# --- helper side: families ---------------------------------------------------------------------------------


def _encode_cursor(at: datetime, person_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{at.astimezone(UTC).isoformat()}|{person_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode()).decode()
        at, _, ident = raw.partition("|")
        parsed = datetime.fromisoformat(at)
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), UUID(ident)
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise Unprocessable("The page cursor is not valid. Start from the first page.", code="invalid_cursor") from exc


def _latest_application(db: Session, tenant_id: UUID, person_id: UUID) -> models.Application | None:
    return db.scalars(
        select(models.Application)
        .where(models.Application.tenant_id == tenant_id, models.Application.person_id == person_id)
        .order_by(models.Application.created_at.desc(), models.Application.id.desc())
        .limit(1)
    ).first()


def _latest_applications(db: Session, tenant_id: UUID, person_ids: list[UUID]) -> dict[UUID, models.Application]:
    """`_latest_application` for a whole page of families, in one query."""
    if not person_ids:
        return {}
    rows = db.scalars(
        select(models.Application)
        .where(models.Application.tenant_id == tenant_id, models.Application.person_id.in_(person_ids))
        .order_by(models.Application.person_id, models.Application.created_at.desc(), models.Application.id.desc())
        .distinct(models.Application.person_id)
    ).all()
    return {row.person_id: row for row in rows}


def _family_application(application: models.Application | None) -> FamilyApplication | None:
    if application is None:
        return None
    return FamilyApplication(
        id=application.id, status=application.status, tracking_code=application.tracking_code,
        tracking_symbols=symbols_for(application.tracking_code), updated_at=_iso(application.updated_at) or "",
    )  # fmt: skip


def _recently_listed(db: Session, principal: Principal, now: datetime) -> set[str]:
    rows = db.execute(
        select(models.AuditLog.object_id, models.AuditLog.details).where(
            models.AuditLog.tenant_id == principal.tenant_id, models.AuditLog.actor_id == str(principal.user_id),
            models.AuditLog.action == VIEW_ACTION, models.AuditLog.ts > now - FAMILY_LIST_VIEW_EVERY,
        )
    ).all()  # fmt: skip
    seen: set[str] = set()
    for object_id, details in rows:
        try:
            if json.loads(details or "{}").get("what") == "family_list" and object_id:
                seen.add(object_id)
        except ValueError:
            continue
    return seen


def families(db: Session, principal: Principal, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE) -> FamiliesOut:
    """The helper's families: name and application status while the delegation is live and consent is active."""
    now = datetime.now(UTC)
    limit = max(1, min(limit or DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE))
    delegation = models.HelperDelegation
    live_first = case((and_(delegation.revoked_at.is_(None), delegation.expires_at > now), 0), else_=1)
    # One row per family (a live delegation first, the longest left), however often it was granted and revoked.
    rows = db.scalars(
        select(delegation)
        .where(delegation.tenant_id == principal.tenant_id, delegation.helper_user_id == principal.user_id)
        .order_by(delegation.person_id, live_first, delegation.expires_at.desc(), delegation.created_at.desc())
        .distinct(delegation.person_id)
    ).all()
    chosen = []
    for pick in rows:
        status = delegation_status(pick, now)
        ended_at = pick.revoked_at or pick.expires_at
        if status != "live" and ended_at < now - ENDED_VISIBLE_FOR:
            continue
        chosen.append((pick.created_at, pick.person_id, pick, status))
    chosen.sort(key=lambda item: (item[0], item[1]))
    if cursor:
        at, ident = _decode_cursor(cursor)
        chosen = [c for c in chosen if (c[0], c[1]) > (at, ident)]
    page, more = chosen[:limit], len(chosen) > limit

    record = tickets.latest_switch(db, tenant_id=principal.tenant_id, session_id=principal.session_id)
    current = record.person_id if record is not None and record.active and record.expires_at and record.expires_at > now else None
    seen = _recently_listed(db, principal, now)
    # Three queries for the whole page, not three per family: each one is a network round trip to the database.
    live_ids = [person_id for _, person_id, _, status in page if status == "live"]
    consented = people_with_active_consent(db, tenant_id=principal.tenant_id, person_ids=live_ids)
    # RLS lets a live delegation read the person; without the department consent the helper is shown nothing more.
    readable = [person_id for person_id in live_ids if person_id in consented]
    people = (
        {p.id: p for p in db.scalars(select(models.Person).where(models.Person.tenant_id == principal.tenant_id,
                                                                 models.Person.id.in_(readable))).all()}  # fmt: skip
        if readable else {}
    )
    latest = _latest_applications(db, principal.tenant_id, list(people))
    items: list[FamilyOut] = []
    shown: list[UUID] = []
    for _, person_id, chosen_delegation, status in page:
        consent = person_id in consented
        person = people.get(person_id)
        application = latest.get(person_id) if person is not None else None
        if person is not None:
            shown.append(person_id)
        items.append(FamilyOut(
            person_id=person_id, delegation_id=chosen_delegation.id, delegation_status=status,
            display_name=person.full_name if person else None, display_name_ur=person.full_name_ur if person else None,
            district=person.district if person else None, scopes=ordered_scopes(list(chosen_delegation.scopes or [])),
            expires_at=_iso(chosen_delegation.expires_at) or "", consent_active=consent, application=_family_application(application),
            current=current == person_id,
        ))  # fmt: skip
    for person_id in shown:
        if str(person_id) not in seen:
            record_view(db, principal, person_id, what="family_list", purpose="helper_assist", flush=False)
    db.commit()  # sends the pending view rows in one batch
    live_count = sum(1 for c in chosen if c[3] == "live") if not cursor else sum(1 for i in items if i.delegation_status == "live")
    return FamiliesOut(
        items=items, next_cursor=_encode_cursor(page[-1][0], page[-1][1]) if more and page else None, live_count=live_count,
        current_person_id=current, current_ticket_expires_at=_iso(record.expires_at) if current and record else None,
    )  # fmt: skip


# --- helper side: switching ----------------------------------------------------------------------------------


def _failure_times(db: Session, principal: Principal, *, person_id: UUID | None, since: datetime) -> list[datetime]:
    query = select(models.AuditLog.ts).where(
        models.AuditLog.tenant_id == principal.tenant_id, models.AuditLog.actor_id == str(principal.user_id),
        models.AuditLog.action == tickets.SWITCH_DENIED, models.AuditLog.reason.in_(tickets.COUNTED_FAILURES),
        models.AuditLog.ts > since,
    )  # fmt: skip
    if person_id is not None:
        query = query.where(models.AuditLog.object_id == str(person_id))
    return list(db.scalars(query).all())


def _last_switch(db: Session, principal: Principal, person_id: UUID) -> datetime | None:
    return db.scalar(
        select(models.AuditLog.ts)
        .where(models.AuditLog.tenant_id == principal.tenant_id, models.AuditLog.actor_id == str(principal.user_id),
               models.AuditLog.action == tickets.SWITCHED, models.AuditLog.acting_for_person_id == person_id)  # fmt: skip
        .order_by(models.AuditLog.seq.desc())
        .limit(1)
    )


def _refuse(db: Session, principal: Principal, person_id: UUID, code: str, details: dict[str, Any] | None = None) -> None:
    """Record a refused switch and commit it now, in this request's own transaction (nothing else was written).

    Committed before the error is raised, so the row survives the failed request. It is not a separate
    best-effort write: if it cannot be recorded the request fails with it, so no wrong PIN goes uncounted.
    """
    metrics.ACCESS_DENIED.labels("helper_switch").inc()
    audit.write(
        db, tenant_id=principal.tenant_id, action=tickets.SWITCH_DENIED, actor_id=principal.user_id, actor_role=principal.role,
        acting_for_person_id=person_id, object_type="person", object_id=person_id, result="denied", reason=code,
        details=details or {},
    )  # fmt: skip
    db.commit()


def _locked(db: Session, principal: Principal, person_id: UUID, remaining: timedelta) -> TooManyRequests:
    seconds = max(1, int(remaining.total_seconds()) + 1)
    _refuse(db, principal, person_id, "pin_locked", {"retry_after": seconds})
    return TooManyRequests("Too many wrong PINs. Wait a little and try again.", code="pin_locked",
                           headers={"Retry-After": str(seconds)}, extra={"retry_after": seconds})  # fmt: skip


def switch(db: Session, principal: Principal, body: SwitchIn) -> SwitchOut:
    """Check the family PIN and give this session a ticket for that one family.

    403 `no_delegation`, `pin_not_set`, `pin_incorrect` (with `attempts_left`) or `pin_blocked` (too many wrong
    PINs since the last good one: the family must set a new PIN); 429 `pin_locked`. One hash verification runs
    on every path that checks a PIN, so a family without a delegation takes as long as a wrong PIN.
    """
    if principal.session_id is None:
        raise Forbidden("Switching families needs a signed-in helper.", code="session_required")
    db.execute(_SWITCH_LOCK, {"helper_id": str(principal.user_id)})  # held until this request's transaction ends
    now = datetime.now(UTC)
    person_id = body.person_id
    window_start = now - tickets.PIN_WINDOW
    remaining = tickets.lock_remaining(_failure_times(db, principal, person_id=None, since=window_start), now=now,
                                       limit=tickets.PIN_MAX_PER_HELPER)  # fmt: skip
    if remaining is not None:
        raise _locked(db, principal, person_id, remaining)
    delegations = live_delegations(db, tenant_id=principal.tenant_id, helper_user_id=principal.user_id, person_id=person_id)
    delegation = max(delegations, key=lambda d: (d.expires_at, d.created_at)) if delegations else None
    last_success = _last_switch(db, principal, person_id)
    family_failures = _failure_times(db, principal, person_id=person_id, since=window_start)
    remaining = tickets.lock_remaining(family_failures, now=now, limit=tickets.PIN_MAX_PER_FAMILY, since=last_success)
    if remaining is not None:
        raise _locked(db, principal, person_id, remaining)
    if delegation is not None:
        # Over any length of time: after this many wrong PINs since the last good switch (or since the family set
        # this PIN), the PIN is spent. A slow guesser gets ten tries, not ten thousand.
        since = max(t for t in (last_success, delegation.created_at) if t is not None)
        if len(_failure_times(db, principal, person_id=person_id, since=since)) >= tickets.PIN_BLOCK_AFTER:
            _refuse(db, principal, person_id, "pin_blocked")
            raise Forbidden("Too many wrong PINs for this family. Ask the family to set a new PIN.", code="pin_blocked")

    pin_ok = verify_secret(delegation.pin_hash if delegation is not None else None, body.pin)  # always one verification
    if delegation is None:
        _refuse(db, principal, person_id, "no_delegation")
        raise Forbidden("You cannot help this family. Ask them to choose you as their helper.", code="no_delegation")
    if not delegation.pin_hash:
        _refuse(db, principal, person_id, "pin_not_set")
        raise Forbidden("This family has not set a PIN yet. Ask them to set one.", code="pin_not_set")
    if not pin_ok:
        _refuse(db, principal, person_id, "wrong_pin")
        left = tickets.attempts_left([*family_failures, now], now=now, limit=tickets.PIN_MAX_PER_FAMILY, since=last_success)
        raise Forbidden("That PIN is not right.", code="pin_incorrect", extra={"attempts_left": left})

    raw, hashed = tickets.new_ticket()
    expires_at = now + tickets.TICKET_TTL
    consent = active_consent(db, tenant_id=principal.tenant_id, person_id=person_id) is not None
    person = db.get(models.Person, person_id) if consent else None  # after withdrawal: no name, but the helper can help re-grant
    scopes = ordered_scopes([s for s in (delegation.scopes or []) if s in DELEGATION_SCOPES])
    audit.write(
        db, tenant_id=principal.tenant_id, action=tickets.SWITCHED, actor_id=principal.user_id, actor_role=principal.role,
        acting_for_person_id=person_id, object_type=tickets.SESSION_OBJECT, object_id=principal.session_id,
        details={"ticket_hash": hashed, "expires_at": expires_at.isoformat(), "delegation_id": str(delegation.id), "scopes": scopes},
    )  # fmt: skip
    db.commit()
    return SwitchOut(person_id=person_id, display_name=person.full_name if person else None, scopes=scopes, ticket=raw,
                     expires_at=_iso(expires_at) or "", expires_in=int(tickets.TICKET_TTL.total_seconds()))  # fmt: skip


def end_switch(db: Session, principal: Principal) -> bool:
    """Hand the phone back: the current ticket stops working. Returns False when there was nothing to end."""
    record = tickets.latest_switch(db, tenant_id=principal.tenant_id, session_id=principal.session_id)
    if record is None or not record.active:
        return False
    audit.write(db, tenant_id=principal.tenant_id, action=tickets.SWITCH_ENDED, actor_id=principal.user_id, actor_role=principal.role,
                acting_for_person_id=record.person_id, object_type=tickets.SESSION_OBJECT, object_id=principal.session_id)  # fmt: skip
    db.commit()
    return True
