"""Hash-chained audit log: every user, AI and agent action, with who, what, when and why.

Each tenant has one chain. A row's hash covers its own content and the previous row's hash, so editing,
deleting or reordering any row breaks every hash after it. Appends are serialised per tenant with an
advisory lock. The app role cannot UPDATE or DELETE this table.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.context import current_request_id
from app.core.db import system_session
from app.core.logging import get_logger
from app.db import models

log = get_logger("rahat.audit")

GENESIS_HASH = "0" * 64
PLATFORM_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")  # chain for events that belong to no tenant

_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('audit:' || :tenant_id, 0))")


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no extra whitespace. Used wherever something is hashed."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hash_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _row_hash(row: models.AuditLog) -> str:
    material = {
        "tenant_id": str(row.tenant_id),
        "seq": row.seq,
        "ts": row.ts.astimezone(UTC).isoformat(timespec="microseconds"),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "actor_role": row.actor_role,
        "acting_for_person_id": str(row.acting_for_person_id) if row.acting_for_person_id else None,
        "action": row.action,
        "object_type": row.object_type,
        "object_id": row.object_id,
        "result": row.result,
        "reason": row.reason,
        "input_hash": row.input_hash,
        "model_version": row.model_version,
        "rule_version_id": str(row.rule_version_id) if row.rule_version_id else None,
        "request_id": row.request_id,
        "details": row.details,
        "prev_hash": row.prev_hash,
    }
    return hashlib.sha256(canonical_json(material).encode()).hexdigest()


def write(
    db: Session,
    *,
    tenant_id: UUID,
    action: str,
    actor_type: str = "user",
    actor_id: UUID | str | None = None,
    actor_role: str | None = None,
    acting_for_person_id: UUID | None = None,
    object_type: str | None = None,
    object_id: UUID | str | None = None,
    result: str = "ok",
    reason: str | None = None,
    input_hash: str | None = None,
    model_version: str | None = None,
    rule_version_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> models.AuditLog:
    """Append one row to the tenant's chain inside the caller's transaction.

    The row is committed or rolled back together with the change it describes. Never put raw personal
    data in `details`; store ids and hashes.
    """
    if actor_role == "api_client" and actor_type == "user":
        actor_type = "api_key"  # services pass the principal's id; a key is never recorded as a person
    db.execute(_LOCK, {"tenant_id": str(tenant_id)})
    last = db.execute(
        select(models.AuditLog.seq, models.AuditLog.hash)
        .where(models.AuditLog.tenant_id == tenant_id)
        .order_by(models.AuditLog.seq.desc())
        .limit(1)
    ).first()
    row = models.AuditLog(
        tenant_id=tenant_id,
        seq=(last.seq + 1) if last else 1,
        ts=datetime.now(UTC),
        actor_type=actor_type,
        actor_id=str(actor_id) if actor_id else None,
        actor_role=actor_role,
        acting_for_person_id=acting_for_person_id,
        action=action,
        object_type=object_type,
        object_id=str(object_id) if object_id else None,
        result=result,
        reason=reason,
        input_hash=input_hash,
        model_version=model_version,
        rule_version_id=rule_version_id,
        request_id=current_request_id(),
        details=canonical_json(details or {}),
        prev_hash=last.hash if last else GENESIS_HASH,
        hash="",
    )
    row.hash = _row_hash(row)
    db.add(row)
    db.flush()
    return row


def write_independent(**fields: Any) -> None:
    """Append a row in its own committed transaction.

    Used for denied attempts: the request fails and rolls back, but the record of the attempt stays.
    A failure to write is logged and never hides the original error.
    """
    try:
        with system_session() as db:
            # If the caller's own transaction holds this tenant's audit lock, give up instead of waiting forever.
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            write(db, **fields)
    except Exception:  # noqa: BLE001
        log.exception("could not write independent audit row for action %s", fields.get("action"))


@dataclass(frozen=True, slots=True)
class ChainReport:
    ok: bool
    checked: int
    head_seq: int
    head_hash: str
    first_broken_seq: int | None = None
    problem: str | None = None


def verify_chain(db: Session, tenant_id: UUID, *, batch: int = 2000) -> ChainReport:
    """Walk the tenant's chain from the start and recompute every hash."""
    expected_prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    head_hash = GENESIS_HASH
    after = 0
    while True:
        rows = db.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.tenant_id == tenant_id, models.AuditLog.seq > after)
            .order_by(models.AuditLog.seq)
            .limit(batch)
        ).all()
        if not rows:
            break
        for row in rows:
            if row.seq != expected_seq:
                return ChainReport(False, checked, expected_seq - 1, head_hash, expected_seq, "a row is missing")
            if row.prev_hash != expected_prev:
                return ChainReport(False, checked, expected_seq - 1, head_hash, row.seq, "link to the previous row is broken")
            if _row_hash(row) != row.hash:
                return ChainReport(False, checked, expected_seq - 1, head_hash, row.seq, "row content was changed")
            expected_prev = head_hash = row.hash
            expected_seq += 1
            checked += 1
        after = rows[-1].seq
    return ChainReport(True, checked, expected_seq - 1, head_hash)
