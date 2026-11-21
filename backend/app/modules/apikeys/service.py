"""Admins create, list, rotate and revoke their department's API keys. Every change is audited.

A key that can read personal data (`cases:read`) starts with no scopes and a pending approval; it works only
after a second admin approves it. Admins do not read personal records themselves (DECISIONS 6), so one admin
alone must not be able to mint a key that does.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import apikeys as keys
from app.core import audit
from app.core.apikeys import API_SCOPES
from app.core.config import get_settings
from app.core.deps import Principal
from app.core.errors import Conflict, Forbidden, NotFound
from app.db import models
from app.modules.apikeys import rules
from app.modules.apikeys.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyDecide, ApiKeyOut, ApiKeyRevoke, ApiKeyRotate, ScopeOut

APPROVAL_KIND = "api_key"
MAX_LISTED = 200


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value else None


def routes_by_scope(registry: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Which endpoints admit each scope, from the policy registry (`describe_routes`)."""
    found: dict[str, list[str]] = {name: [] for name in API_SCOPES}
    for entry in registry:
        for scope in entry.get("api_scopes") or []:
            found.setdefault(scope, []).append(f"{entry['method']} {entry['path']}")
    return found


def scopes_out(registry: Sequence[Mapping[str, Any]]) -> list[ScopeOut]:
    endpoints = routes_by_scope(registry)
    return [ScopeOut(name=s.name, description=s.description, personal_data=s.personal_data,
                     needs_second_admin=rules.needs_second_admin([s.name]), endpoints=endpoints.get(s.name, []))
            for s in API_SCOPES.values()]  # fmt: skip


def _pending(db: Session, key_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, models.Approval]:
    if not key_ids:
        return {}
    rows = db.scalars(select(models.Approval).where(models.Approval.kind == APPROVAL_KIND, models.Approval.subject_type == "api_key",
                                                    models.Approval.subject_id.in_(key_ids), models.Approval.status == "pending"))  # fmt: skip
    return {a.subject_id: a for a in rows}


def _out(key: models.ApiKey, approval: models.Approval | None, now: datetime) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id, name=key.name, prefix=key.prefix,
        status=rules.key_status(revoked_at=key.revoked_at, expires_at=key.expires_at, pending=approval is not None, now=now),
        scopes=list(key.scopes or []), requested_scopes=list((approval.data or {}).get("scopes", [])) if approval else None,
        approval_id=approval.id if approval else None, rate_limit_per_minute=key.rate_limit_per_min,
        expires_at=_iso(key.expires_at), revoked_at=_iso(key.revoked_at), last_used_at=_iso(key.last_used_at),
        created_at=_iso(key.created_at) or "", created_by=key.created_by,
    )  # fmt: skip


def _load(db: Session, principal: Principal, key_id: uuid.UUID, *, lock: bool = False) -> models.ApiKey:
    query = select(models.ApiKey).where(models.ApiKey.id == key_id, models.ApiKey.tenant_id == principal.tenant_id)
    key = db.scalar(query.with_for_update() if lock else query)
    if key is None:  # another department's key is invisible under RLS, so it is simply not found
        raise NotFound("No such API key.", code="api_key_not_found")
    return key


def _audit(db: Session, principal: Principal, action: str, key: models.ApiKey, *, reason: str | None = None,
           details: dict[str, Any] | None = None) -> None:  # fmt: skip
    audit.write(db, tenant_id=principal.tenant_id, action=action, actor_id=principal.user_id, actor_role=principal.role,
                object_type="api_key", object_id=key.id, reason=reason,
                details={"prefix": key.prefix, "name": key.name, **(details or {})})  # fmt: skip


def _new_key(db: Session, principal: Principal, *, name: str, scopes: list[str], rate: int, expires_at: datetime,
             now: datetime) -> tuple[models.ApiKey, str]:  # fmt: skip
    raw, prefix, digest = keys.generate()
    key = models.ApiKey(id=uuid.uuid4(), tenant_id=principal.tenant_id, name=name, prefix=prefix, key_hash=digest, scopes=scopes,
                        rate_limit_per_min=rate, expires_at=expires_at, created_by=principal.user_id, created_at=now)  # fmt: skip
    db.add(key)
    db.flush()
    return key, raw


def list_keys(db: Session, principal: Principal, *, include_inactive: bool = False) -> list[ApiKeyOut]:
    now = datetime.now(UTC)
    query = select(models.ApiKey).where(models.ApiKey.tenant_id == principal.tenant_id)
    if not include_inactive:
        query = query.where(models.ApiKey.revoked_at.is_(None))
    rows = list(db.scalars(query.order_by(models.ApiKey.created_at.desc(), models.ApiKey.id).limit(MAX_LISTED)).all())
    pending = _pending(db, [k.id for k in rows])
    out = [_out(k, pending.get(k.id), now) for k in rows]
    return out if include_inactive else [k for k in out if k.status != "expired"]


def get_key(db: Session, principal: Principal, key_id: uuid.UUID) -> ApiKeyOut:
    key = _load(db, principal, key_id)
    return _out(key, _pending(db, [key.id]).get(key.id), datetime.now(UTC))


def create_key(db: Session, principal: Principal, body: ApiKeyCreate, registry: Sequence[Mapping[str, Any]]) -> ApiKeyCreated:
    now = datetime.now(UTC)
    scopes = rules.check_scopes(body.scopes, routes_by_scope(registry))
    gated = rules.needs_second_admin(scopes)
    rate = body.rate_limit_per_minute or get_settings().rate_limits().api_key_default_per_minute
    name = body.name.strip()
    key, raw = _new_key(db, principal, name=name, scopes=[] if gated else scopes, rate=rate,
                        expires_at=now + timedelta(days=body.expires_in_days), now=now)  # fmt: skip
    approval = None
    if gated:
        approval = models.Approval(id=uuid.uuid4(), tenant_id=principal.tenant_id, kind=APPROVAL_KIND, subject_type="api_key",
                                   subject_id=key.id, status="pending", requested_by=principal.user_id, data={"scopes": scopes},
                                   created_at=now)  # fmt: skip
        db.add(approval)
        db.flush()
    _audit(db, principal, "apikey.created", key, details={
        "scopes": scopes, "rate_limit_per_minute": rate, "expires_at": _iso(key.expires_at), "needs_second_admin": gated,
    })  # fmt: skip
    db.commit()
    return ApiKeyCreated(**_out(key, approval, now).model_dump(), key=raw)


def rotate_key(db: Session, principal: Principal, key_id: uuid.UUID, body: ApiKeyRotate) -> ApiKeyCreated:
    """A new secret with the same name, scopes, limit and end date. The old key is revoked in the same transaction.

    There is never more than one live key per approval, and rotation never moves the end date, so rotating cannot
    multiply or prolong a key that a second admin approved.
    """
    now = datetime.now(UTC)
    old = _load(db, principal, key_id, lock=True)
    status = rules.key_status(revoked_at=old.revoked_at, expires_at=old.expires_at, pending=bool(_pending(db, [old.id])), now=now)
    if status != "active":
        raise Conflict(f"Only an active key can be rotated; this one is {status.replace('_', ' ')}.", code=f"api_key_{status}")
    scopes = list(old.scopes or [])
    new, raw = _new_key(db, principal, name=old.name, scopes=scopes, rate=old.rate_limit_per_min,
                        expires_at=rules.rotated_expiry(expires_at=old.expires_at, now=now, days=body.expires_in_days), now=now)  # fmt: skip
    old.revoked_at = now
    _audit(db, principal, "apikey.rotated", old, reason=body.reason, details={"replaced_by": str(new.id), "new_prefix": new.prefix})
    _audit(db, principal, "apikey.created", new, reason=body.reason, details={
        "rotated_from": str(old.id), "scopes": scopes, "rate_limit_per_minute": new.rate_limit_per_min,
        "expires_at": _iso(new.expires_at), "needs_second_admin": False,
        "approval_carried_from": str(old.id) if rules.needs_second_admin(scopes) else None,
    })  # fmt: skip
    db.commit()
    return ApiKeyCreated(**_out(new, None, now).model_dump(), key=raw)


def revoke_key(db: Session, principal: Principal, key_id: uuid.UUID, body: ApiKeyRevoke) -> ApiKeyOut:
    """Stops the key on its very next request. Revoking twice is harmless."""
    now = datetime.now(UTC)
    key = _load(db, principal, key_id, lock=True)
    pending = _pending(db, [key.id]).get(key.id)
    if key.revoked_at is None:
        key.revoked_at = now
        if pending is not None:  # a key nobody approved yet will never be approved now
            pending.status, pending.decided_at, pending.reason = "expired", now, "key revoked"
            pending = None
        _audit(db, principal, "apikey.revoked", key, reason=body.reason)
        db.commit()
    return _out(key, pending, now)


def decide_key(db: Session, principal: Principal, key_id: uuid.UUID, body: ApiKeyDecide) -> ApiKeyOut:
    """The second admin's decision on a key that can read personal data."""
    now = datetime.now(UTC)
    key = _load(db, principal, key_id, lock=True)
    approval = db.scalar(select(models.Approval).where(models.Approval.kind == APPROVAL_KIND, models.Approval.subject_type == "api_key",
                                                       models.Approval.subject_id == key.id, models.Approval.status == "pending")
                         .with_for_update())  # fmt: skip
    if approval is None:
        raise Conflict("This key is not waiting for approval.", code="no_pending_approval")
    if approval.requested_by == principal.user_id:
        audit.write_independent(tenant_id=principal.tenant_id, action="access.denied", actor_id=principal.user_id,
                                actor_role=principal.role, object_type="api_key", object_id=key.id, result="denied",
                                reason="second_admin_required", details={"approval_id": str(approval.id)})  # fmt: skip
        raise Forbidden("A different admin must approve this key.", code="second_admin_required")
    if key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise Conflict("This key is no longer active.", code="api_key_inactive")
    approval.approver_id, approval.decided_at, approval.reason = principal.user_id, now, body.reason
    if body.approve:
        approval.status = "approved"
        key.scopes = list((approval.data or {}).get("scopes", []))
        _audit(db, principal, "apikey.approved", key, reason=body.reason, details={"scopes": key.scopes, "approval_id": str(approval.id)})
    else:
        approval.status = "rejected"
        key.revoked_at = now
        _audit(db, principal, "apikey.rejected", key, reason=body.reason, details={"approval_id": str(approval.id)})
    db.commit()
    return _out(key, None, now)
