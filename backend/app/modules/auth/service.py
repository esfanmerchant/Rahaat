"""Sign-in, token refresh with reuse detection, tenant switching and sign-out.

Sign-in and refresh happen before there is an authenticated caller, so they use the system database
context for narrow lookups by a keyed hash. Everything else runs in the caller's own context.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import audit, metrics
from app.core.config import get_settings
from app.core.crypto import blind_index
from app.core.db import system_session
from app.core.deps import Principal
from app.core.errors import Forbidden, NotFound, TooManyRequests, Unauthorized
from app.core.mockdata import normalise_mock_phone
from app.core.security import hash_token, issue_access_token, new_refresh_token, verify_secret
from app.db import models
from app.modules.auth.schemas import ActiveOut, AuthOut, MembershipOut, MeOut, SessionOut, UserOut

_GENERIC_FAILURE = "The sign-in details are not right."

# Per-process throttles. They assume a single API process, which is how the prototype is deployed.
_ip_hits: dict[str, deque[float]] = defaultdict(deque)
_ghost_failures: dict[str, tuple[int, float]] = {}  # failures for identifiers that match no account


@dataclass(frozen=True, slots=True)
class Issued:
    out: AuthOut
    refresh_token: str


def _throttle_ip(ip: str) -> None:
    if not ip:
        return
    now = time.monotonic()
    hits = _ip_hits[ip]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= get_settings().login_ip_attempts_per_minute:
        metrics.AUTH_EVENTS.labels("ip_throttled").inc()
        raise TooManyRequests("Too many sign-in attempts. Wait a minute and try again.", headers={"Retry-After": "60"})
    hits.append(now)


def _ghost_locked(key: str) -> int:
    """Unknown identifiers lock out exactly like real accounts, so lockout does not reveal who exists."""
    count, until = _ghost_failures.get(key, (0, 0.0))
    remaining = int(until - time.monotonic())
    return remaining if remaining > 0 else 0


def _ghost_fail(key: str) -> None:
    settings = get_settings()
    count, until = _ghost_failures.get(key, (0, 0.0))
    count += 1
    if count >= settings.login_max_failures:
        _ghost_failures[key] = (0, time.monotonic() + settings.login_lock_minutes * 60)
    else:
        _ghost_failures[key] = (count, until)
    if len(_ghost_failures) > 10_000:
        _ghost_failures.clear()


def _find_user(db: Session, identifier: str) -> models.User | None:
    ident = identifier.strip()
    if "@" in ident:
        return db.scalar(select(models.User).where(func.lower(models.User.email) == ident.lower()))
    phone = normalise_mock_phone(ident)
    if phone is None:
        return None
    return db.scalar(select(models.User).where(models.User.phone_hash == blind_index(phone)))


def _memberships(db: Session, user_id: UUID) -> list[tuple[models.Membership, models.Tenant]]:
    rows = db.execute(
        select(models.Membership, models.Tenant)
        .join(models.Tenant, models.Tenant.id == models.Membership.tenant_id)
        .where(
            models.Membership.user_id == user_id,
            models.Membership.status == "active",
            models.Tenant.status == "active",
        )
        .order_by(models.Membership.created_at, models.Tenant.slug, models.Membership.id)
    ).all()
    return [(m, t) for m, t in rows]


def _membership_out(m: models.Membership, t: models.Tenant) -> MembershipOut:
    return MembershipOut(tenant_id=t.id, tenant_slug=t.slug, tenant_name=t.name, role=m.role)  # type: ignore[arg-type]


def _me(user: models.User, active: tuple[models.Membership, models.Tenant], rows: list[tuple[models.Membership, models.Tenant]]) -> MeOut:
    m, t = active
    return MeOut(
        user=UserOut(id=user.id, display_name=user.display_name, lang=user.lang),
        active=ActiveOut(tenant_id=t.id, tenant_slug=t.slug, tenant_name=t.name, role=m.role, person_id=m.person_id),  # type: ignore[arg-type]
        memberships=[_membership_out(mm, tt) for mm, tt in rows],
    )


def _issue(user: models.User, session: models.AuthSession, active: tuple[models.Membership, models.Tenant],
           rows: list[tuple[models.Membership, models.Tenant]], refresh_token: str) -> Issued:  # fmt: skip
    token, ttl = issue_access_token(
        user_id=user.id, session_id=session.id, tenant_id=session.tenant_id, role=session.role, person_id=session.person_id
    )
    me = _me(user, active, rows)
    return Issued(AuthOut(access_token=token, expires_in=ttl, **me.model_dump()), refresh_token)


def login(*, identifier: str, secret: str, tenant_slug: str | None, device_label: str | None, ip: str) -> Issued:
    settings = get_settings()
    _throttle_ip(ip)
    ident_key = blind_index(identifier, scope="login-identifier")
    now = datetime.now(UTC)

    with system_session() as db:
        user = _find_user(db, identifier)
        # Always verify once, even for a missing account, so both cases take the same time.
        secret_ok = verify_secret(user.password_hash if user else None, secret)

        locked_seconds = _ghost_locked(ident_key)
        if user and user.locked_until and user.locked_until > now:
            locked_seconds = int((user.locked_until - now).total_seconds())
        if locked_seconds > 0:
            metrics.AUTH_EVENTS.labels("locked").inc()
            raise TooManyRequests(
                "Too many wrong attempts. Try again later.", code="account_locked", headers={"Retry-After": str(locked_seconds)}
            )

        rows = _memberships(db, user.id) if user and secret_ok and user.status == "active" else []
        active = None
        if rows:
            wanted = [r for r in rows if r[1].slug == tenant_slug] if tenant_slug else rows
            active = wanted[0] if wanted else None

        if user is None or not secret_ok or user.status != "active" or active is None:
            if user is None:
                _ghost_fail(ident_key)
            elif not secret_ok:
                user.failed_logins += 1
                if user.failed_logins >= settings.login_max_failures:
                    user.failed_logins = 0
                    user.locked_until = now + timedelta(minutes=settings.login_lock_minutes)
                    db.add(models.SecurityEvent(tenant_id=audit.PLATFORM_TENANT_ID, kind="lockout", severity="medium",
                                                actor_user_id=user.id, details={"minutes": settings.login_lock_minutes}))  # fmt: skip
            audit.write(db, tenant_id=audit.PLATFORM_TENANT_ID, action="auth.login_failed", actor_type="system",
                        actor_id=user.id if user else None, result="denied", details={"identifier_hash": ident_key})  # fmt: skip
            db.commit()  # keep the counters and the audit row even though the request fails
            metrics.AUTH_EVENTS.labels("login_failed").inc()
            raise Unauthorized(_GENERIC_FAILURE, code="invalid_credentials")

        membership, tenant = active
        user.failed_logins = 0
        user.locked_until = None
        user.last_login_at = now
        raw, hashed = new_refresh_token()
        session = models.AuthSession(
            user_id=user.id, family_id=uuid.uuid4(), tenant_id=tenant.id, role=membership.role,
            person_id=membership.person_id, refresh_hash=hashed, device_label=(device_label or "")[:160] or None,
            ip_hash=blind_index(ip, scope="ip") if ip else None, last_seen_at=now,
            expires_at=now + timedelta(seconds=settings.refresh_ttl_seconds),
        )  # fmt: skip
        db.add(session)
        db.flush()
        audit.write(db, tenant_id=tenant.id, action="auth.login", actor_id=user.id, actor_role=membership.role,
                    object_type="session", object_id=session.id)  # fmt: skip
        metrics.AUTH_EVENTS.labels("login").inc()
        return _issue(user, session, active, rows, raw)


def refresh(raw_token: str | None) -> Issued:
    if not raw_token:
        raise Unauthorized("Sign in to continue.", code="no_session")
    hashed = hash_token(raw_token)
    now = datetime.now(UTC)
    settings = get_settings()

    with system_session() as db:
        session = db.scalar(select(models.AuthSession).where(models.AuthSession.refresh_hash == hashed).with_for_update())
        if session is None:
            stale = db.scalar(select(models.AuthSession).where(models.AuthSession.prev_refresh_hash == hashed))
            if stale is not None:
                # A token that was already rotated came back: someone else holds a copy. End the whole family.
                db.execute(
                    update(models.AuthSession)
                    .where(models.AuthSession.family_id == stale.family_id, models.AuthSession.revoked_at.is_(None))
                    .values(revoked_at=now, revoked_reason="refresh_reuse")
                )
                db.add(models.SecurityEvent(tenant_id=stale.tenant_id, kind="refresh_reuse", severity="high",
                                            actor_user_id=stale.user_id, details={"family_id": str(stale.family_id)}))  # fmt: skip
                audit.write(db, tenant_id=stale.tenant_id, action="auth.refresh_reuse_detected", actor_type="system",
                            actor_id=stale.user_id, object_type="session_family", object_id=stale.family_id, result="denied")  # fmt: skip
                db.commit()
                metrics.AUTH_EVENTS.labels("refresh_reuse").inc()
            raise Unauthorized("Sign in to continue.", code="no_session")

        user = db.get(models.User, session.user_id)
        rows = _memberships(db, session.user_id) if user and user.status == "active" else []
        active = next((r for r in rows if r[0].tenant_id == session.tenant_id and r[0].role == session.role), None)
        if session.revoked_at is not None or session.expires_at <= now or user is None or active is None:
            raise Unauthorized("Sign in to continue.", code="no_session")

        raw, new_hash = new_refresh_token()
        session.prev_refresh_hash = session.refresh_hash
        session.refresh_hash = new_hash
        session.last_seen_at = now
        session.expires_at = now + timedelta(seconds=settings.refresh_ttl_seconds)
        metrics.AUTH_EVENTS.labels("refresh").inc()
        return _issue(user, session, active, rows, raw)


def switch(principal: Principal, *, tenant_id: UUID, role: str | None) -> Issued:
    """Move the current session to another of the user's memberships. Old access tokens stop working."""
    with system_session() as db:
        session = db.get(models.AuthSession, principal.session_id, with_for_update=True)
        user = db.get(models.User, principal.user_id)
        if session is None or user is None or session.user_id != principal.user_id:
            raise Unauthorized("Sign in to continue.", code="session_ended")
        rows = _memberships(db, principal.user_id)
        active = next((r for r in rows if r[0].tenant_id == tenant_id and (role is None or r[0].role == role)), None)
        if active is None:
            raise Forbidden("You are not a member of that department.", code="not_a_member")
        membership, tenant = active
        raw, new_hash = new_refresh_token()
        session.tenant_id, session.role, session.person_id = tenant.id, membership.role, membership.person_id
        session.prev_refresh_hash, session.refresh_hash = session.refresh_hash, new_hash
        session.last_seen_at = datetime.now(UTC)
        audit.write(db, tenant_id=tenant.id, action="auth.switch_tenant", actor_id=user.id, actor_role=membership.role,
                    object_type="session", object_id=session.id, details={"from_tenant": str(principal.tenant_id)})  # fmt: skip
        return _issue(user, session, active, rows, raw)


def logout(raw_token: str | None) -> None:
    if not raw_token:
        return
    with system_session() as db:
        session = db.scalar(select(models.AuthSession).where(models.AuthSession.refresh_hash == hash_token(raw_token)))
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            session.revoked_reason = "logout"
            audit.write(db, tenant_id=session.tenant_id, action="auth.logout", actor_id=session.user_id,
                        actor_role=session.role, object_type="session", object_id=session.id)  # fmt: skip


def me(db: Session, principal: Principal) -> MeOut:
    user = db.get(models.User, principal.user_id)
    rows = _memberships(db, principal.user_id)
    active = next((r for r in rows if r[0].tenant_id == principal.tenant_id and r[0].role == principal.role), None)
    if user is None or active is None:
        raise Unauthorized("Sign in to continue.", code="session_ended")
    return _me(user, active, rows)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def list_sessions(db: Session, principal: Principal) -> list[SessionOut]:
    now = datetime.now(UTC)
    rows = db.scalars(
        select(models.AuthSession)
        .where(models.AuthSession.user_id == principal.user_id, models.AuthSession.revoked_at.is_(None),
               models.AuthSession.expires_at > now)  # fmt: skip
        .order_by(models.AuthSession.created_at.desc())
    ).all()
    return [
        SessionOut(id=s.id, device_label=s.device_label, tenant_id=s.tenant_id, role=s.role, created_at=_iso(s.created_at) or "",
                   last_seen_at=_iso(s.last_seen_at), expires_at=_iso(s.expires_at) or "", current=s.id == principal.session_id)  # fmt: skip
        for s in rows
    ]


def revoke_session(db: Session, principal: Principal, session_id: UUID) -> None:
    session = db.get(models.AuthSession, session_id)
    if session is None or session.user_id != principal.user_id:
        raise NotFound("That session does not exist.")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        session.revoked_reason = "revoked_by_user"
        audit.write(db, tenant_id=principal.tenant_id, action="auth.session_revoked", actor_id=principal.user_id,
                    actor_role=principal.role, object_type="session", object_id=session.id)  # fmt: skip
    db.commit()


def revoke_all(db: Session, principal: Principal) -> int:
    now = datetime.now(UTC)
    result = db.execute(
        update(models.AuthSession)
        .where(models.AuthSession.user_id == principal.user_id, models.AuthSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason="revoke_all")
    )
    audit.write(db, tenant_id=principal.tenant_id, action="auth.sessions_revoked_all", actor_id=principal.user_id,
                actor_role=principal.role, details={"count": result.rowcount})  # fmt: skip
    db.commit()
    return int(result.rowcount or 0)
